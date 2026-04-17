"""Refrigerant tools: PT lookup and charge check.

Reference implementation that sets the pattern for every other tool:
  1. Pydantic input model with model_config (strip whitespace, forbid extras)
  2. @mcp.tool decorator with name + annotations
  3. Docstring with Args / Returns
  4. Matching test in tests/test_<module>.py
"""

from __future__ import annotations

import json
from bisect import bisect_left
from enum import StrEnum
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, model_validator

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PT_TABLE_PATH = _DATA_DIR / "pt_tables.json"


class Refrigerant(StrEnum):
    """Supported refrigerants. Add more by extending pt_tables.json."""

    R410A = "R-410A"
    R32 = "R-32"
    R454B = "R-454B"
    R22 = "R-22"
    R134A = "R-134a"


class MeteringDevice(StrEnum):
    TXV = "TXV"
    PISTON = "piston"


class PTLookupInput(BaseModel):
    """Input for PT-saturation lookup. Exactly one of pressure_psig / temp_f required."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    refrigerant: Refrigerant = Field(..., description="Refrigerant type (e.g., 'R-410A').")
    pressure_psig: float | None = Field(
        default=None,
        description="Gauge pressure in psig. Provide this OR temp_f, not both.",
        ge=-14.7,
        le=700.0,
    )
    temp_f: float | None = Field(
        default=None,
        description="Saturation temperature in °F. Provide this OR pressure_psig, not both.",
        ge=-60.0,
        le=200.0,
    )

    @model_validator(mode="after")
    def exactly_one_input(self) -> PTLookupInput:
        if (self.pressure_psig is None) == (self.temp_f is None):
            raise ValueError("Provide exactly one of pressure_psig or temp_f, not both or neither.")
        return self


class ChargeCheckInput(BaseModel):
    """Input for superheat/subcool charge diagnosis."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    refrigerant: Refrigerant = Field(..., description="Refrigerant type.")
    suction_pressure_psig: float = Field(..., description="Suction line pressure (psig).", ge=0)
    suction_line_temp_f: float = Field(..., description="Suction line temperature (°F).")
    liquid_pressure_psig: float = Field(..., description="Liquid line pressure (psig).", ge=0)
    liquid_line_temp_f: float = Field(..., description="Liquid line temperature (°F).")
    metering: MeteringDevice = Field(
        default=MeteringDevice.TXV,
        description="Metering device: TXV targets subcool, piston targets superheat.",
    )
    target_superheat_f: float | None = Field(
        default=None,
        description="Piston-only: target superheat from OEM charging chart. Defaults to 15°F if omitted.",
        ge=0.0,
        le=50.0,
    )


_pt_cache: dict | None = None


def _load_pt_tables() -> dict:
    """Load the bundled PT table once per process."""
    global _pt_cache
    if _pt_cache is None:
        _pt_cache = json.loads(_PT_TABLE_PATH.read_text())
    return _pt_cache


def _curves(
    refrigerant: Refrigerant,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], float]:
    """Return (bubble_pairs, dew_pairs, glide_f) sorted by temp_f.

    Each pair is (temp_f, pressure_psig). For near-azeotropic refrigerants
    bubble == dew.
    """
    tables = _load_pt_tables()
    entry = tables.get(refrigerant.value)
    if not entry:
        raise ValueError(f"No PT table data for {refrigerant.value}")
    glide = float(entry.get("glide_f", 0.0))
    if "pairs" in entry:
        pairs = sorted((p["temp_f"], p["pressure_psig"]) for p in entry["pairs"])
        return pairs, pairs, glide
    bubble = sorted((p["temp_f"], p["pressure_psig"]) for p in entry["pairs_bubble"])
    dew = sorted((p["temp_f"], p["pressure_psig"]) for p in entry["pairs_dew"])
    return bubble, dew, glide


def _interp(pairs: list[tuple[float, float]], x: float, *, key: int) -> float:
    """Linear-interpolate the non-`key` column given `x` at column `key` (0=temp, 1=press).

    Raises ValueError if x is outside the table range.
    """
    xs = [p[key] for p in pairs]
    other = 1 - key
    if x < xs[0] or x > xs[-1]:
        raise ValueError(
            f"Value {x} is outside the table range [{xs[0]}, {xs[-1]}]. "
            "Use a hand-calc chart or extend pt_tables.json."
        )
    idx = bisect_left(xs, x)
    if idx < len(xs) and xs[idx] == x:
        return pairs[idx][other]
    lo, hi = pairs[idx - 1], pairs[idx]
    frac = (x - lo[key]) / (hi[key] - lo[key])
    return lo[other] + frac * (hi[other] - lo[other])


def sat_temp_from_pressure(refrigerant: Refrigerant, psig: float, *, curve: str = "dew") -> float:
    """Saturation temperature at a given pressure. `curve` is 'bubble' or 'dew'."""
    bubble, dew, _ = _curves(refrigerant)
    pairs = bubble if curve == "bubble" else dew
    return _interp(pairs, psig, key=1)


def sat_pressure_from_temp(refrigerant: Refrigerant, temp_f: float, *, curve: str = "dew") -> float:
    """Saturation pressure at a given temperature. `curve` is 'bubble' or 'dew'."""
    bubble, dew, _ = _curves(refrigerant)
    pairs = bubble if curve == "bubble" else dew
    return _interp(pairs, temp_f, key=0)


def register(mcp: FastMCP) -> None:
    """Register refrigerant tools onto the MCP server."""

    @mcp.tool(
        name="hvac_refrigerant_pt_lookup",
        annotations={
            "title": "Refrigerant PT Saturation Lookup",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def hvac_refrigerant_pt_lookup(params: PTLookupInput) -> dict:
        """Look up saturation pressure/temperature pair for a refrigerant.

        Provide either pressure_psig OR temp_f (not both). For zeotropic blends
        (R-454B) bubble and dew differ — use dew for superheat, bubble for subcool.

        Returns:
            dict with refrigerant, pressure_psig, temp_f (for azeotropes),
            bubble_temp_f/dew_temp_f or bubble_pressure_psig/dew_pressure_psig (for blends),
            glide_f, guidance, and source.
        """
        bubble_pairs, dew_pairs, glide = _curves(params.refrigerant)
        is_blend = bubble_pairs is not dew_pairs and glide > 0.1

        result: dict = {
            "refrigerant": params.refrigerant.value,
            "glide_f": round(glide, 2),
            "source": "Bundled PT tables (pt_tables.json) — cross-check with manufacturer chart.",
        }

        if params.pressure_psig is not None:
            p = params.pressure_psig
            dew_t = sat_temp_from_pressure(params.refrigerant, p, curve="dew")
            result["pressure_psig"] = p
            result["dew_temp_f"] = round(dew_t, 1)
            if is_blend:
                bubble_t = sat_temp_from_pressure(params.refrigerant, p, curve="bubble")
                result["bubble_temp_f"] = round(bubble_t, 1)
                result["guidance"] = (
                    f"Zeotropic blend ({glide}°F glide). Use dew temp "
                    f"({result['dew_temp_f']}°F) for superheat on the suction side; "
                    f"use bubble temp ({result['bubble_temp_f']}°F) for subcool on the liquid side."
                )
            else:
                result["temp_f"] = result["dew_temp_f"]
                result["guidance"] = (
                    "Near-azeotropic — bubble ≈ dew. Use this temp for both superheat and subcool calcs."
                )
        else:
            t = params.temp_f
            assert t is not None  # model_validator guarantees this
            dew_p = sat_pressure_from_temp(params.refrigerant, t, curve="dew")
            result["temp_f"] = t
            result["dew_pressure_psig"] = round(dew_p, 1)
            if is_blend:
                bubble_p = sat_pressure_from_temp(params.refrigerant, t, curve="bubble")
                result["bubble_pressure_psig"] = round(bubble_p, 1)
                result["guidance"] = (
                    f"Zeotropic blend ({glide}°F glide). Bubble pressure reads higher than dew "
                    f"at the same temp; manifold readings approximate dew on low side, bubble on high side."
                )
            else:
                result["pressure_psig"] = result["dew_pressure_psig"]
                result["guidance"] = "Near-azeotropic — single saturation pressure at this temp."

        return result

    @mcp.tool(
        name="hvac_refrigerant_charge_check",
        annotations={
            "title": "Refrigerant Charge Diagnosis (Superheat/Subcool)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def hvac_refrigerant_charge_check(params: ChargeCheckInput) -> dict:
        """Calculate superheat & subcool, then diagnose charge state.

        TXV systems target subcool 8-12°F. Piston systems target manufacturer
        superheat (typically 10-25°F based on indoor/outdoor conditions).
        Uses dew curve for superheat (vapor side) and bubble curve for subcool
        (liquid side) — matters for zeotropic blends like R-454B.
        """
        sat_suction = sat_temp_from_pressure(
            params.refrigerant, params.suction_pressure_psig, curve="dew"
        )
        sat_liquid = sat_temp_from_pressure(
            params.refrigerant, params.liquid_pressure_psig, curve="bubble"
        )
        superheat = round(params.suction_line_temp_f - sat_suction, 1)
        subcool = round(sat_liquid - params.liquid_line_temp_f, 1)

        result: dict = {
            "superheat_f": superheat,
            "subcool_f": subcool,
            "saturated_suction_temp_f": round(sat_suction, 1),
            "saturated_liquid_temp_f": round(sat_liquid, 1),
            "metering": params.metering.value,
            "source": (
                "Diagnosis rules: ACCA Quality Installation. "
                "Always confirm against OEM charging chart and indoor/outdoor conditions."
            ),
        }

        if superheat < 0 or subcool < 0:
            result["diagnosis"] = "insufficient_data"
            result["confidence"] = "low"
            result["recommendation"] = (
                "Readings are physically impossible (negative superheat or subcool). "
                "Check gauge calibration, sensor placement on correct line, and whether "
                "the system is actually running in steady state."
            )
            return result

        if params.metering is MeteringDevice.TXV:
            if 8.0 <= subcool <= 12.0:
                result["diagnosis"] = "in_spec"
                result["confidence"] = "high"
                result["recommendation"] = (
                    f"Subcool {subcool}°F is in the 8-12°F target window. Charge looks correct."
                )
            elif subcool < 6.0:
                result["diagnosis"] = "undercharged"
                result["confidence"] = "high"
                result["recommendation"] = (
                    f"Subcool {subcool}°F is below target. Add refrigerant in small increments "
                    "and recheck subcool after stabilizing."
                )
            elif subcool > 14.0:
                result["diagnosis"] = "overcharged"
                result["confidence"] = "high"
                result["recommendation"] = (
                    f"Subcool {subcool}°F is above target. Recover refrigerant in small increments "
                    "and recheck. Also verify condenser airflow and cleanliness before adjusting."
                )
            else:
                result["diagnosis"] = "marginal"
                result["confidence"] = "medium"
                result["recommendation"] = (
                    f"Subcool {subcool}°F is near the edge of the 8-12°F window. "
                    "Verify steady-state conditions and indoor load before adjusting charge."
                )
            # Restriction check — TXV with high superheat often means starved evaporator.
            if superheat > 20.0 and subcool >= 8.0:
                result["diagnosis"] = "restriction_suspected"
                result["confidence"] = "medium"
                result["recommendation"] = (
                    f"High superheat ({superheat}°F) with normal/high subcool ({subcool}°F) "
                    "suggests a restriction feeding the TXV — stuck/plugged filter drier, "
                    "failed TXV power head, lost sensing bulb contact, or low charge trapped "
                    "upstream. Inspect drier pressure drop and TXV bulb before adding refrigerant."
                )
        else:  # Piston
            target = params.target_superheat_f if params.target_superheat_f is not None else 15.0
            delta = superheat - target
            result["target_superheat_f"] = target
            if abs(delta) <= 3.0:
                result["diagnosis"] = "in_spec"
                result["confidence"] = "high"
                result["recommendation"] = (
                    f"Superheat {superheat}°F is within ±3°F of target {target}°F. "
                    "Verify target against OEM charging chart for actual indoor wet-bulb "
                    "and outdoor dry-bulb."
                )
            elif delta < -5.0:
                result["diagnosis"] = "overcharged"
                result["confidence"] = "high"
                result["recommendation"] = (
                    f"Superheat {superheat}°F is well below target {target}°F — liquid floodback risk. "
                    "Recover refrigerant in small increments."
                )
            elif delta > 5.0:
                result["diagnosis"] = "undercharged"
                result["confidence"] = "high"
                result["recommendation"] = (
                    f"Superheat {superheat}°F is well above target {target}°F. "
                    "Add refrigerant in small increments, but first rule out low indoor airflow "
                    "and restriction (dirty filter, blocked coil)."
                )
            else:
                result["diagnosis"] = "marginal"
                result["confidence"] = "medium"
                result["recommendation"] = (
                    f"Superheat {superheat}°F is 3-5°F off target {target}°F. "
                    "Verify target against OEM chart before adjusting."
                )

        return result
