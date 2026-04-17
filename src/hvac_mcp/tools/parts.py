"""Parts tools — capacitor cross-reference for now; later: contactor, filter
drier, TXV, and OEM→aftermarket part lookups.

The capacitor cross-ref is intentionally free-tier: every tech asks the same
"can I put a 40/5 where a 45/5 should go" question weekly. Driving adoption
matters more than paywalling it.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, model_validator

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CAP_PATH = _DATA_DIR / "capacitors.json"


class CapacitorType(StrEnum):
    RUN = "run"
    START = "start"
    DUAL_RUN = "dual_run"


class CapacitorApp(StrEnum):
    COMPRESSOR = "compressor"
    FAN = "fan"
    DUAL = "dual"  # one dual-run cap powering both compressor and condenser fan


class CapacitorSpec(BaseModel):
    """One capacitor's nameplate specs.

    For dual-run caps, `uf_main` is the compressor leg (HERM terminal) and
    `uf_fan` is the fan leg (FAN terminal). For run / start, leave `uf_fan`
    empty.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    cap_type: CapacitorType = Field(..., description="run | start | dual_run")
    uf_main: float = Field(
        ..., ge=0, le=1000, description="Microfarad rating. For dual caps, HERM leg."
    )
    uf_fan: float | None = Field(
        default=None, ge=0, le=200, description="Fan-leg µF for dual_run caps only."
    )
    voltage_v: int = Field(..., description="Voltage rating (370 or 440 typical).")
    application: CapacitorApp = Field(..., description="compressor | fan | dual")

    @model_validator(mode="after")
    def consistency(self) -> CapacitorSpec:
        if self.cap_type is CapacitorType.DUAL_RUN:
            if self.uf_fan is None or self.uf_fan <= 0:
                raise ValueError("dual_run capacitors require uf_fan > 0")
            if self.application is not CapacitorApp.DUAL:
                raise ValueError(
                    "dual_run caps must have application='dual'; use two single caps otherwise"
                )
        else:
            if self.uf_fan is not None:
                raise ValueError(
                    f"{self.cap_type.value} caps are single-leg — leave uf_fan empty"
                )
            if self.application is CapacitorApp.DUAL:
                raise ValueError(
                    "application='dual' requires cap_type='dual_run' (a true dual cap)"
                )
        return self

    def label(self) -> str:
        if self.cap_type is CapacitorType.DUAL_RUN:
            return f"{_num(self.uf_main)}/{_num(self.uf_fan or 0)} µF {self.voltage_v}V dual"
        return f"{_num(self.uf_main)} µF {self.voltage_v}V {self.cap_type.value}"


def _num(v: float) -> str:
    return f"{v:g}"


class CapacitorCrossrefInput(BaseModel):
    """Inputs for `hvac_capacitor_crossref`.

    Always pass the `needed` spec (what the nameplate calls for).
    Optionally pass `have` (what you've got in the truck) to get a
    substitution verdict.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    needed: CapacitorSpec = Field(..., description="What the nameplate calls for.")
    have: CapacitorSpec | None = Field(
        default=None,
        description="Optional: what you've got on the truck to evaluate as a sub.",
    )


_cap_cache: dict | None = None


def _load_caps() -> dict:
    global _cap_cache
    if _cap_cache is None:
        _cap_cache = json.loads(_CAP_PATH.read_text())
    return _cap_cache


def _within_pct(a: float, b: float, pct: float) -> bool:
    """Is |a-b| within `pct` % of b?"""
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) * 100.0 <= pct


def _evaluate_sub(needed: CapacitorSpec, have: CapacitorSpec, tol: dict[str, float]) -> dict[str, Any]:
    """Return {verdict, reasons[]}. verdict ∈ {ok, marginal, no_go}."""
    reasons: list[str] = []
    if needed.cap_type is not have.cap_type:
        reasons.append(
            f"Type mismatch — you need a {needed.cap_type.value} cap; you have a {have.cap_type.value}. "
            "Never substitute between run/start/dual — the construction is different (polypropylene vs electrolytic; single vs dual leg)."
        )
        return {"verdict": "no_go", "reasons": reasons}

    if needed.application is not have.application:
        reasons.append(
            f"Application mismatch — needed for {needed.application.value}, yours is wired for {have.application.value}."
        )
        return {"verdict": "no_go", "reasons": reasons}

    # Voltage rule
    if have.voltage_v < needed.voltage_v:
        reasons.append(
            f"Voltage too low — need ≥{needed.voltage_v}V, have {have.voltage_v}V. 440V drops into 370V applications; never the other way."
        )
        return {"verdict": "no_go", "reasons": reasons}
    elif have.voltage_v > needed.voltage_v:
        reasons.append(
            f"Voltage higher than spec ({have.voltage_v}V ≥ {needed.voltage_v}V) — that's fine; over-voltage is always safe on caps."
        )

    # µF tolerance
    tol_key = "dual_run" if needed.cap_type is CapacitorType.DUAL_RUN else needed.cap_type.value
    tol_pct = tol.get(tol_key, 6.0)

    main_ok = _within_pct(have.uf_main, needed.uf_main, tol_pct)
    if not main_ok:
        diff = ((have.uf_main - needed.uf_main) / needed.uf_main) * 100
        reasons.append(
            f"Main µF out of tolerance: {have.uf_main} µF vs {needed.uf_main} µF needed ({diff:+.1f}%, spec ±{tol_pct:g}%). "
            "Running a mis-sized cap degrades motor efficiency and shortens compressor life."
        )

    fan_ok = True
    if needed.cap_type is CapacitorType.DUAL_RUN and needed.uf_fan is not None:
        have_fan = have.uf_fan or 0
        fan_ok = _within_pct(have_fan, needed.uf_fan, tol_pct)
        if not fan_ok:
            diff = ((have_fan - needed.uf_fan) / needed.uf_fan) * 100
            reasons.append(
                f"Fan µF out of tolerance: {have_fan} µF vs {needed.uf_fan} µF needed ({diff:+.1f}%, spec ±{tol_pct:g}%)."
            )

    if not main_ok or not fan_ok:
        return {"verdict": "no_go", "reasons": reasons}

    # If we got here, it's technically within tolerance. Call it marginal if
    # the substitution isn't an exact match (different uF or voltage).
    exact = (
        have.uf_main == needed.uf_main
        and (have.uf_fan or 0) == (needed.uf_fan or 0)
        and have.voltage_v == needed.voltage_v
    )
    verdict = "ok" if exact else "marginal"
    if verdict == "marginal":
        reasons.append(
            "Within tolerance but not an exact match — fine for a same-day repair while you wait on the right part, "
            "but replace with the exact spec on the follow-up if the customer calls back."
        )
    else:
        reasons.append("Exact match — drop it in.")
    return {"verdict": verdict, "reasons": reasons}


def _suggest_subs(needed: CapacitorSpec, data: dict, max_n: int = 5) -> list[str]:
    """Return up-to-N human-readable spec labels that would satisfy `needed`
    from standard stocked sizes. Empty if none.
    """
    voltages = [v for v in data.get("voltages", []) if v >= needed.voltage_v]
    if not voltages:
        return []
    primary_v = min(voltages)  # cheapest valid voltage
    suggestions: list[str] = []

    if needed.cap_type is CapacitorType.DUAL_RUN:
        for row in data.get("dual_run_sizes", []):
            if row["main"] == needed.uf_main and row["fan"] == (needed.uf_fan or 0):
                suggestions.append(f'{row["label"]} µF {primary_v}V dual')
        # Pad with nearest-neighbors if we didn't find an exact
        if not suggestions:
            for row in data.get("dual_run_sizes", []):
                if (
                    _within_pct(row["main"], needed.uf_main, 6)
                    and _within_pct(row["fan"], needed.uf_fan or 0, 6)
                ):
                    suggestions.append(f'{row["label"]} µF {primary_v}V dual')
    elif needed.cap_type is CapacitorType.RUN:
        for uf in data.get("run_sizes_uf", []):
            if uf == needed.uf_main:
                suggestions.append(f"{_num(uf)} µF {primary_v}V run")
        if not suggestions:
            for uf in data.get("run_sizes_uf", []):
                if _within_pct(uf, needed.uf_main, 6):
                    suggestions.append(f"{_num(uf)} µF {primary_v}V run")
    elif needed.cap_type is CapacitorType.START:
        for lo, hi in data.get("start_ranges_uf", []):
            if lo <= needed.uf_main <= hi:
                suggestions.append(f"{lo}-{hi} µF {primary_v}V start (PTCR or mechanical)")

    # Always include a 440V option if needed is 370V — techs often stock 440V only
    if primary_v == 370 and 440 in data.get("voltages", []):
        bumped = [s.replace("370V", "440V") for s in suggestions]
        suggestions.extend(bumped)

    # Dedup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= max_n:
            break
    return out


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="hvac_capacitor_crossref",
        annotations={
            "title": "Capacitor Substitution & Cross-Reference",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def hvac_capacitor_crossref(params: CapacitorCrossrefInput) -> dict[str, Any]:
        """Check if a capacitor in your truck can sub for what the nameplate calls for,
        and/or list standard stocked sizes that satisfy the spec.

        Rules baked in:
        - Voltage: replacement must meet or exceed spec (440V drops into 370V, never the other way)
        - µF tolerance: run/dual ±6%, start ±20% (industry standard)
        - Types don't cross (run != start != dual_run)
        - dual_run ↔ two-singles substitution is flagged as no_go (code + install reality)

        Returns: verdict (if `have` provided), list of standard suggestions,
        plus a "replace with exact spec on the follow-up" disclaimer.
        """
        data = _load_caps()
        tol: dict[str, float] = data.get("_meta", {}).get("tolerance_pct", {})

        result: dict[str, Any] = {
            "needed": params.needed.label(),
            "suggestions": _suggest_subs(params.needed, data),
            "disclaimer": (
                "Always replace like-with-like when stocked. This tool reflects standard "
                "industry rules but doesn't see the actual unit — check the control board, "
                "contactor sizing, and any OEM-specific cap notes before swapping."
            ),
            "source": "Genteq / Packard / Amrad replacement guides (bundled).",
        }
        if params.have is not None:
            eval_res = _evaluate_sub(params.needed, params.have, tol)
            result["have"] = params.have.label()
            result["verdict"] = eval_res["verdict"]
            result["reasons"] = eval_res["reasons"]

        return result
