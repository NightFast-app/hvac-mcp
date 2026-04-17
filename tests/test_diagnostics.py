"""Tests for hvac_diagnostic_symptom_tree."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from hvac_mcp.tools.diagnostics import (
    FaultCodeInput,
    SymptomTreeInput,
    SystemType,
    _load_fault_codes,
    _load_tree,
)


def _call_tool(mcp, name: str, **kwargs):
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None
    return asyncio.run(tool.fn(**kwargs))


def _server():
    from mcp.server.fastmcp import FastMCP

    from hvac_mcp.tools import diagnostics

    mcp = FastMCP("test")
    diagnostics.register(mcp)
    return mcp


class TestInput:
    def test_rejects_short_symptom(self) -> None:
        with pytest.raises(ValidationError):
            SymptomTreeInput(system_type=SystemType.SPLIT_AC, symptom="x")

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            SymptomTreeInput(system_type=SystemType.SPLIT_AC, symptom="no cool", foo=1)


class TestYAMLStructure:
    """YAML must be well-formed and satisfy the schema every tool run depends on."""

    def test_loads(self) -> None:
        tree = _load_tree()
        assert "systems" in tree
        assert "split_ac" in tree["systems"]

    def test_every_cause_has_required_fields(self) -> None:
        tree = _load_tree()
        for sys_name, sys in tree["systems"].items():
            for sym in sys.get("symptoms", []):
                assert sym.get("name"), f"{sys_name}: symptom missing name"
                assert sym.get("keywords"), f"{sys_name}/{sym.get('name')}: no keywords"
                for c in sym.get("causes", []):
                    assert c.get("cause"), "missing cause text"
                    assert 0.0 <= c.get("probability", -1) <= 1.0, "bad probability"
                    assert c.get("test"), "missing test procedure"
                    assert c.get("fix"), "missing fix"

    def test_no_cool_includes_float_switch(self) -> None:
        """Regression: lesson 2026-04-17 — float switch must appear in any no-cool tree."""
        tree = _load_tree()
        symptoms = tree["systems"]["split_ac"]["symptoms"]
        no_cool = next(s for s in symptoms if "no cool" in s["keywords"])
        causes_text = " ".join(c["cause"].lower() for c in no_cool["causes"])
        assert "float" in causes_text or "condensate" in causes_text


class TestMatching:
    def test_exact_keyword_match(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_diagnostic_symptom_tree",
            params=SymptomTreeInput(system_type=SystemType.SPLIT_AC, symptom="no cool"),
        )
        assert res["status"] == "matched"
        assert res["matched_symptom"] == "No cooling — indoor blower running, warm air"
        assert len(res["probable_causes"]) > 0
        # Ranked by probability desc
        probs = [c["probability"] for c in res["probable_causes"]]
        assert probs == sorted(probs, reverse=True)

    def test_phrase_match(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_diagnostic_symptom_tree",
            params=SymptomTreeInput(
                system_type=SystemType.SPLIT_AC, symptom="AC is blowing warm air in the house"
            ),
        )
        assert res["status"] == "matched"

    def test_ice_keyword(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_diagnostic_symptom_tree",
            params=SymptomTreeInput(
                system_type=SystemType.SPLIT_AC, symptom="ice on suction line, frozen up"
            ),
        )
        assert res["status"] == "matched"
        assert "Ice" in res["matched_symptom"]

    def test_furnace_ignition(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_diagnostic_symptom_tree",
            params=SymptomTreeInput(system_type=SystemType.FURNACE, symptom="won't ignite"),
        )
        assert res["status"] == "matched"

    def test_no_match_returns_suggestions(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_diagnostic_symptom_tree",
            params=SymptomTreeInput(
                system_type=SystemType.SPLIT_AC, symptom="purple smoke coming out"
            ),
        )
        assert res["status"] == "no_match"
        assert res["probable_causes"] == []
        assert len(res["suggestions"]) > 0

    def test_max_causes_honored(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_diagnostic_symptom_tree",
            params=SymptomTreeInput(
                system_type=SystemType.SPLIT_AC, symptom="no cool", max_causes=2
            ),
        )
        assert len(res["probable_causes"]) == 2

    def test_float_switch_is_top_cause_for_no_cool(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_diagnostic_symptom_tree",
            params=SymptomTreeInput(system_type=SystemType.SPLIT_AC, symptom="no cool"),
        )
        top_causes_text = " ".join(c["cause"].lower() for c in res["probable_causes"][:3])
        assert "float" in top_causes_text or "condensate" in top_causes_text


class TestFaultCodesData:
    def test_every_code_has_required_fields(self) -> None:
        data = _load_fault_codes()
        for brand, entry in data["brands"].items():
            assert entry.get("codes"), f"{brand} has no codes"
            for code, c in entry["codes"].items():
                assert c.get("meaning"), f"{brand}/{code}: missing meaning"
                assert c.get("causes"), f"{brand}/{code}: missing causes"
                assert c.get("fix"), f"{brand}/{code}: missing fix"
                assert c.get("source"), f"{brand}/{code}: missing source"


class TestFaultCodeInput:
    def test_rejects_empty_code(self) -> None:
        with pytest.raises(ValidationError):
            FaultCodeInput(brand="carrier", code="")

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            FaultCodeInput(brand="carrier", code="13", foo=1)


class TestFaultCodeLookup:
    def test_exact_match(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_fault_code_lookup",
            params=FaultCodeInput(brand="carrier", code="13"),
        )
        assert res["status"] == "matched"
        assert res["brand"] == "carrier"
        assert "thermostat" in res["meaning"].lower()
        assert res["causes"]
        assert res["disclaimer"]

    def test_alias_match_bryant_to_carrier(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_fault_code_lookup",
            params=FaultCodeInput(brand="Bryant", code="13"),
        )
        assert res["status"] == "matched"
        assert res["brand"] == "carrier"

    def test_alias_match_ruud_to_rheem(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_fault_code_lookup",
            params=FaultCodeInput(brand="Ruud", code="57"),
        )
        assert res["status"] == "matched"
        assert res["brand"] == "rheem"

    def test_case_insensitive_code(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_fault_code_lookup",
            params=FaultCodeInput(brand="mitsubishi", code="e5"),
        )
        assert res["status"] == "matched"
        assert res["code"] == "E5"

    def test_whitespace_tolerant_code(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_fault_code_lookup",
            params=FaultCodeInput(brand="daikin", code="  u4  "),
        )
        assert res["status"] == "matched"
        assert res["code"] == "U4"

    def test_unknown_code_returns_suggestions(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_fault_code_lookup",
            params=FaultCodeInput(brand="carrier", code="999"),
        )
        assert res["status"] == "unknown_code"
        assert "13" in res["suggestions"]

    def test_unknown_brand_returns_brand_list(self) -> None:
        res = _call_tool(
            _server(),
            "hvac_fault_code_lookup",
            params=FaultCodeInput(brand="nonexistent-brand", code="E1"),
        )
        assert res["status"] == "unknown_brand"
        assert "carrier" in res["suggestions"]
        assert "trane" in res["suggestions"]
