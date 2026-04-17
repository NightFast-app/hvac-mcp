"""Sizing tools: water/DWV pipe + duct. Pipe sizing uses IPC Table 710.1
(DWV horizontal branch) and a simplified Hunter's-curve lookup (supply)."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, model_validator

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PIPE_PATH = _DATA_DIR / "pipe_sizing.json"

_PIPE_DISCLAIMER = (
    "Informational sizing only. Developed length, slope, velocity, pressure loss, "
    "vent sizing, and local amendments are NOT evaluated here. Verify with AHJ."
)


class PipeMaterial(StrEnum):
    PVC = "PVC"
    CPVC = "CPVC"
    COPPER = "copper"
    PEX = "PEX"
    CAST_IRON = "cast_iron"


class PipeApplication(StrEnum):
    DWV = "DWV"
    SUPPLY = "supply"


class DuctShape(StrEnum):
    ROUND = "round"
    RECTANGULAR = "rectangular"


# Combinations a plumber should NOT use; rejecting at the input layer.
_INVALID_COMBOS: set[tuple[PipeApplication, PipeMaterial]] = {
    (PipeApplication.SUPPLY, PipeMaterial.CAST_IRON),
    (PipeApplication.SUPPLY, PipeMaterial.PVC),
    (PipeApplication.DWV, PipeMaterial.PEX),
    (PipeApplication.DWV, PipeMaterial.COPPER),  # legal but rare residential; leave allowed
}
# Remove copper-DWV from blocked set — some older systems use copper DWV.
_INVALID_COMBOS.discard((PipeApplication.DWV, PipeMaterial.COPPER))


class PipeSizeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    fixture_units: float = Field(
        ...,
        description="Drainage Fixture Units (DFU) for DWV or Water Supply Fixture Units (WSFU) for supply.",
        ge=0,
        le=2000,
    )
    material: PipeMaterial = Field(..., description="Pipe material.")
    application: PipeApplication = Field(..., description="DWV or supply.")

    @model_validator(mode="after")
    def reject_invalid_combos(self) -> PipeSizeInput:
        if (self.application, self.material) in _INVALID_COMBOS:
            raise ValueError(
                f"{self.material.value} is not an approved material for "
                f"{self.application.value} in residential work. "
                "Supply: copper, CPVC, or PEX. DWV: PVC or cast iron."
            )
        return self


_pipe_cache: dict | None = None


def _load_pipe_tables() -> dict:
    global _pipe_cache
    if _pipe_cache is None:
        _pipe_cache = json.loads(_PIPE_PATH.read_text())
    return _pipe_cache


def _nominal_to_inches(nominal: str) -> float:
    """Parse a nominal pipe label like '1-1/2\"' → 1.5 (decimal inches)."""
    s = nominal.replace('"', "").strip()
    if "-" in s:
        whole, frac = s.split("-", 1)
        num, denom = frac.split("/")
        return int(whole) + int(num) / int(denom)
    if "/" in s:
        num, denom = s.split("/")
        return int(num) / int(denom)
    return float(s)


class DuctSizeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    cfm: float = Field(..., description="Required airflow (CFM).", gt=0, le=10000)
    friction_rate: float = Field(
        default=0.08,
        description="Friction rate in inches water column per 100 ft (typical residential: 0.08, commercial: 0.10).",
        gt=0,
        le=0.5,
    )
    duct_shape: DuctShape = Field(
        default=DuctShape.ROUND,
        description="Target duct shape. If 'rectangular', response includes 3 joist-friendly (height, width) pairs.",
    )


_DUCT_DISCLAIMER = (
    "ASHRAE friction chart method for galvanized-steel duct at 0.075 lb/ft³ "
    "standard air. Does not account for fittings, flex-duct penalty, insulation "
    "or altitude. Full Manual D accounts for total effective length and "
    "available static pressure."
)

# Joist-friendly heights typical in residential retrofit work.
_RECT_HEIGHTS_IN = (6, 8, 10, 12, 14)


def _equivalent_round_diameter(cfm: float, friction: float) -> float:
    """ASHRAE friction chart equation solved for D (inches).

    Δp/L (in.wc/100ft) = 0.109136 · Q^1.9 / D^5.02
    so D = (0.109136 · Q^1.9 / Δp)^(1/5.02)
    """
    return (0.109136 * cfm**1.9 / friction) ** (1.0 / 5.02)


def _velocity_fpm(cfm: float, diameter_in: float) -> float:
    """V = Q / A. Area from diameter in square feet."""
    area_sqft = 3.141592653589793 * (diameter_in / 2.0) ** 2 / 144.0
    return cfm / area_sqft


def _huebscher_width(height_in: float, de_in: float) -> float:
    """Given a rectangular height and an equivalent round diameter, bisect
    for the width that satisfies De = 1.30 · (a·b)^0.625 / (a+b)^0.25."""

    def huebscher(h: float, w: float) -> float:
        return 1.30 * (h * w) ** 0.625 / (h + w) ** 0.25

    lo, hi = height_in, height_in * 40.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if huebscher(height_in, mid) < de_in:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _round_up_half_inch(value: float) -> float:
    """Size up to the nearest 0.5" — ducts ship in even/half sizes."""
    import math

    return math.ceil(value * 2.0) / 2.0


def _round_up_to_even_inch(value: float) -> int:
    """Rectangular widths typically specified in whole inches, usually even."""
    import math

    return math.ceil(value)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="hvac_pipe_size",
        annotations={
            "title": "Plumbing Pipe Size (DWV or Supply)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def hvac_pipe_size(params: PipeSizeInput) -> dict[str, Any]:
        """Return minimum pipe size for fixture units + material + application.

        DWV: IPC Table 710.1 horizontal branch capacity ladder.
        Supply: simplified Hunter's-curve lookup (IPC 604). PEX recommendations
        step up one nominal size vs copper because effective ID is smaller.

        Returns:
            dict with recommended_size_in, code_reference, notes, disclaimer, status.
        """
        tables = _load_pipe_tables()
        notes: list[str] = []

        if params.application is PipeApplication.DWV:
            ladder = tables["dwv_horizontal_branch"]
            pick = next(
                (row for row in ladder if params.fixture_units <= row["max_dfu"]),
                None,
            )
            if pick is None:
                return {
                    "recommended_size_in": None,
                    "code_reference": "IPC Table 710.1",
                    "notes": [
                        f'{params.fixture_units} DFU exceeds the 6" horizontal '
                        f"branch capacity ({ladder[-1]['max_dfu']}). This is a design-"
                        "level load — bring in an engineer for stack sizing and "
                        "multi-branch analysis."
                    ],
                    "disclaimer": _PIPE_DISCLAIMER,
                    "status": "out_of_range",
                }
            if params.fixture_units >= 1 and params.fixture_units < 4:
                notes.append(
                    'Water closets require a minimum 3" drain regardless of DFU — '
                    "upsize if a WC is on this branch."
                )
            if params.fixture_units >= 4 and _nominal_to_inches(pick["nominal"]) < 3.0:
                notes.append('Any water closet on this branch forces 3" minimum (IPC 710.1).')
            return {
                "recommended_size_in": pick["nominal"],
                "max_dfu_for_size": pick["max_dfu"],
                "code_reference": "2021 IPC Table 710.1 (horizontal branch, standard slope)",
                "material": params.material.value,
                "notes": notes,
                "disclaimer": _PIPE_DISCLAIMER,
                "status": "matched",
            }

        # Supply
        ladder = tables["supply_by_wsfu_copper"]
        pick = next(
            (row for row in ladder if params.fixture_units <= row["max_wsfu"]),
            None,
        )
        if pick is None:
            return {
                "recommended_size_in": None,
                "code_reference": "IPC §604 and Hunter's curve",
                "notes": [
                    f'{params.fixture_units} WSFU exceeds the 2" simplified '
                    "lookup. Perform a full pressure-loss calc with developed "
                    "length, static pressure, and simultaneous demand."
                ],
                "disclaimer": _PIPE_DISCLAIMER,
                "status": "out_of_range",
            }
        copper_size = pick["nominal"]
        recommended = copper_size
        if params.material is PipeMaterial.PEX:
            recommended = tables["pex_size_bump"].get(copper_size, copper_size)
            notes.append(
                f"PEX effective ID is smaller than copper — stepping up from "
                f"{copper_size} (copper equivalent) to {recommended} (PEX)."
            )
        if params.fixture_units <= 10:
            notes.append(
                "For long runs (>50 ft developed length) consider upsizing to "
                "account for pressure drop."
            )
        return {
            "recommended_size_in": recommended,
            "copper_equivalent_size_in": copper_size,
            "max_wsfu_for_size": pick["max_wsfu"],
            "code_reference": "2021 IPC §604 / Hunter's curve (simplified)",
            "material": params.material.value,
            "notes": notes,
            "disclaimer": _PIPE_DISCLAIMER,
            "status": "matched",
        }

    @mcp.tool(
        name="hvac_duct_size",
        annotations={
            "title": "HVAC Duct Size (Friction Rate Method)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def hvac_duct_size(params: DuctSizeInput) -> dict[str, Any]:
        """Return duct size for a target CFM at a given friction rate.

        Friction-rate method per ASHRAE friction chart equation for galvanized
        steel duct, air at 0.075 lb/ft³ standard density. Returns the equivalent
        round diameter plus three joist-friendly rectangular (h, w) options.

        Returns:
            dict with equivalent_round_diameter_in (rounded up to nearest 0.5"),
            velocity_fpm, rectangular_options, warnings, source.
        """
        de_exact = _equivalent_round_diameter(params.cfm, params.friction_rate)
        de_rounded = _round_up_half_inch(de_exact)
        v = _velocity_fpm(params.cfm, de_rounded)

        rect_options: list[dict[str, Any]] = []
        for h in _RECT_HEIGHTS_IN:
            # Only recommend rectangular pairs where height < De (wider than tall
            # is the usable case for duct installed in joist bays).
            if h >= de_exact * 1.8:
                continue
            w_exact = _huebscher_width(float(h), de_exact)
            w_rounded = _round_up_to_even_inch(w_exact)
            aspect = w_rounded / h
            if aspect < 0.8 or aspect > 6.0:
                continue
            rect_options.append(
                {
                    "height_in": h,
                    "width_in": w_rounded,
                    "aspect_ratio": round(aspect, 2),
                }
            )
            if len(rect_options) >= 3:
                break

        warnings: list[str] = []
        if v > 1200.0:
            warnings.append(
                f"Velocity {round(v)} fpm is high for residential supply "
                "(target 600-900 fpm). Expect noise — consider upsizing or "
                "splitting runs."
            )
        if v < 400.0 and params.cfm > 100.0:
            warnings.append(
                f"Velocity {round(v)} fpm is low — air may not reach the "
                "farthest registers. Verify with total effective length calc."
            )
        if params.friction_rate > 0.12:
            warnings.append(
                f"Friction rate {params.friction_rate} in.wc/100ft is "
                "aggressive for residential. Verify available static pressure "
                "at the blower."
            )

        return {
            "cfm": params.cfm,
            "friction_rate_in_wc_per_100ft": params.friction_rate,
            "equivalent_round_diameter_in": de_rounded,
            "equivalent_round_diameter_in_exact": round(de_exact, 2),
            "velocity_fpm": round(v, 0),
            "rectangular_options": rect_options
            if params.duct_shape is DuctShape.RECTANGULAR or params.duct_shape is DuctShape.ROUND
            else [],
            "warnings": warnings,
            "source": (
                "ACCA Manual D friction-rate method / ASHRAE friction chart. "
                "Huebscher equation for round-to-rectangular equivalence."
            ),
            "disclaimer": _DUCT_DISCLAIMER,
            "status": "matched",
        }
