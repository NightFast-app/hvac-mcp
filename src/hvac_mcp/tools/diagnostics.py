"""Diagnostic tools — symptom decision tree and OEM fault-code lookup."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SYMPTOMS_PATH = _DATA_DIR / "symptoms.yaml"
_FAULT_CODES_PATH = _DATA_DIR / "fault_codes.json"


class SystemType(StrEnum):
    SPLIT_AC = "split_ac"
    HEAT_PUMP = "heat_pump"
    FURNACE = "furnace"
    MINI_SPLIT = "mini_split"
    PACKAGE_UNIT = "package_unit"


class SymptomTreeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    system_type: SystemType = Field(..., description="System type being diagnosed.")
    symptom: str = Field(
        ...,
        description="Customer-facing symptom (e.g., 'no cool', 'ice on lineset').",
        min_length=2,
        max_length=200,
    )
    max_causes: int = Field(
        default=5, ge=1, le=10, description="Max number of ranked causes to return."
    )


_tree_cache: dict | None = None


def _load_tree() -> dict:
    global _tree_cache
    if _tree_cache is None:
        _tree_cache = yaml.safe_load(_SYMPTOMS_PATH.read_text()) or {}
    return _tree_cache


def _score(symptom_text: str, keywords: list[str]) -> int:
    """Count how many keywords appear as substrings in the user symptom."""
    lowered = symptom_text.lower()
    return sum(1 for k in keywords if k.lower() in lowered)


def _find_best_match(system_type: SystemType, symptom_text: str) -> dict | None:
    """Return the highest-scoring symptom entry for the given system_type, or None."""
    tree = _load_tree()
    system = tree.get("systems", {}).get(system_type.value)
    if not system:
        return None
    best: tuple[int, dict] | None = None
    for entry in system.get("symptoms", []):
        score = _score(symptom_text, entry.get("keywords", []))
        if score > 0 and (best is None or score > best[0]):
            best = (score, entry)
    return best[1] if best else None


def _collect_suggestions(system_type: SystemType, limit: int = 5) -> list[str]:
    tree = _load_tree()
    system = tree.get("systems", {}).get(system_type.value, {})
    names = [s.get("name", "") for s in system.get("symptoms", [])]
    return [n for n in names if n][:limit]


_fault_cache: dict | None = None


def _load_fault_codes() -> dict:
    global _fault_cache
    if _fault_cache is None:
        _fault_cache = json.loads(_FAULT_CODES_PATH.read_text())
    return _fault_cache


def _resolve_brand(brand_input: str) -> str | None:
    """Map user brand string → canonical key in fault_codes.json. Case-insensitive,
    honors aliases (e.g., 'Bryant' → 'carrier', 'Ruud' → 'rheem')."""
    data = _load_fault_codes().get("brands", {})
    needle = brand_input.strip().lower()
    if needle in data:
        return needle
    for key, entry in data.items():
        aliases = [a.lower() for a in entry.get("aliases", [])]
        if needle in aliases:
            return key
    return None


def _normalize_code(code: str) -> str:
    """Normalize user-entered codes: strip, uppercase, collapse whitespace."""
    return " ".join(code.strip().upper().split())


class FaultCodeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    brand: str = Field(
        ...,
        description="Manufacturer (e.g., 'Carrier', 'Bryant', 'Trane', 'Goodman', 'Mitsubishi').",
        min_length=2,
        max_length=40,
    )
    code: str = Field(
        ...,
        description="Fault code as shown on the control (e.g., '13', 'E5', '3_flash', 'P4').",
        min_length=1,
        max_length=20,
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="hvac_diagnostic_symptom_tree",
        annotations={
            "title": "HVAC Symptom → Probable Cause Tree",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def hvac_diagnostic_symptom_tree(params: SymptomTreeInput) -> dict[str, Any]:
        """Return ranked probable causes for a reported HVAC symptom.

        Matches the input symptom string against a bundled keyword index, then
        returns causes sorted by heuristic probability with test procedure and
        typical fix for each. When no match is found, returns nearby symptom
        names as suggestions.

        Returns:
            dict with system_type, symptom, matched_symptom, probable_causes
            (list of {cause, probability, test, fix}), suggestions, source.
        """
        match = _find_best_match(params.system_type, params.symptom)
        base = {
            "system_type": params.system_type.value,
            "symptom": params.symptom,
            "source": (
                "Bundled symptoms.yaml — field-experience heuristics, "
                "not manufacturer-certified diagnostics. Always verify on-site."
            ),
        }
        if match is None:
            return {
                **base,
                "matched_symptom": None,
                "probable_causes": [],
                "suggestions": _collect_suggestions(params.system_type),
                "status": "no_match",
            }

        causes = sorted(
            match.get("causes", []),
            key=lambda c: c.get("probability", 0.0),
            reverse=True,
        )[: params.max_causes]
        return {
            **base,
            "matched_symptom": match.get("name"),
            "probable_causes": [
                {
                    "cause": c.get("cause", ""),
                    "probability": c.get("probability", 0.0),
                    "test": c.get("test", ""),
                    "fix": c.get("fix", ""),
                }
                for c in causes
            ],
            "status": "matched",
        }

    @mcp.tool(
        name="hvac_fault_code_lookup",
        annotations={
            "title": "OEM Fault Code Lookup",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def hvac_fault_code_lookup(params: FaultCodeInput) -> dict[str, Any]:
        """Look up an OEM fault/error code by brand.

        Handles brand aliases (Bryant/Payne → Carrier, Ruud → Rheem, American
        Standard → Trane, etc.) and normalizes the code (case-insensitive,
        whitespace-collapsed). On miss, returns the list of known codes for
        that brand (or known brands if the brand itself is unknown).

        Returns:
            dict with brand (canonical), code, meaning, causes, fix, source,
            status ('matched' | 'unknown_code' | 'unknown_brand'), and
            suggestions when status != 'matched'.
        """
        canonical = _resolve_brand(params.brand)
        brands_data = _load_fault_codes().get("brands", {})

        if canonical is None:
            return {
                "brand": params.brand,
                "code": params.code,
                "status": "unknown_brand",
                "suggestions": sorted(brands_data.keys()),
                "source": "Bundled fault_codes.json — confirm against OEM service manual.",
            }

        brand_entry = brands_data[canonical]
        norm = _normalize_code(params.code)
        # Case-insensitive code lookup against stored keys
        code_key = next(
            (k for k in brand_entry.get("codes", {}) if k.upper() == norm),
            None,
        )
        if code_key is None:
            return {
                "brand": canonical,
                "code": params.code,
                "status": "unknown_code",
                "suggestions": sorted(brand_entry.get("codes", {}).keys()),
                "source": (
                    f"Bundled fault_codes.json — no entry for '{params.code}' under {canonical}. "
                    "Confirm the code from the control board LED pattern or stat display, "
                    "then check the OEM service manual."
                ),
            }

        entry = brand_entry["codes"][code_key]
        return {
            "brand": canonical,
            "code": code_key,
            "meaning": entry.get("meaning", ""),
            "causes": entry.get("causes", []),
            "fix": entry.get("fix", ""),
            "source": entry.get("source", "Bundled fault_codes.json"),
            "status": "matched",
            "disclaimer": "Always verify against the actual OEM service manual for the specific model.",
        }
