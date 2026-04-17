"""Tests for hvac_capacitor_crossref (Tool 8, free tier)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from hvac_mcp.tools.parts import (
    CapacitorApp,
    CapacitorCrossrefInput,
    CapacitorSpec,
    CapacitorType,
    _within_pct,
)


def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None
    return asyncio.run(tool.fn(**kw))


def _server():
    from mcp.server.fastmcp import FastMCP

    from hvac_mcp.tools import parts

    mcp = FastMCP("test")
    parts.register(mcp)
    return mcp


# ─── Math helpers ───────────────────────────────────────────────────────────


class TestWithinPct:
    def test_exact(self) -> None:
        assert _within_pct(45, 45, 6) is True

    def test_small_delta_under_tol(self) -> None:
        # 45 vs 47 = 4.4% off
        assert _within_pct(47, 45, 6) is True

    def test_small_delta_over_tol(self) -> None:
        # 45 vs 50 = 11% off
        assert _within_pct(50, 45, 6) is False

    def test_zero_baseline(self) -> None:
        assert _within_pct(0, 0, 6) is True
        assert _within_pct(1, 0, 6) is False


# ─── Input validation ───────────────────────────────────────────────────────


class TestInputValidation:
    def test_dual_requires_fan_leg(self) -> None:
        with pytest.raises(ValidationError, match="uf_fan"):
            CapacitorSpec(
                cap_type=CapacitorType.DUAL_RUN,
                uf_main=45,
                voltage_v=440,
                application=CapacitorApp.DUAL,
            )

    def test_run_rejects_fan_leg(self) -> None:
        with pytest.raises(ValidationError, match="single-leg"):
            CapacitorSpec(
                cap_type=CapacitorType.RUN,
                uf_main=45,
                uf_fan=5,
                voltage_v=440,
                application=CapacitorApp.COMPRESSOR,
            )

    def test_run_with_dual_application_rejected(self) -> None:
        with pytest.raises(ValidationError, match="dual"):
            CapacitorSpec(
                cap_type=CapacitorType.RUN,
                uf_main=45,
                voltage_v=440,
                application=CapacitorApp.DUAL,
            )

    def test_dual_with_compressor_app_rejected(self) -> None:
        with pytest.raises(ValidationError, match="application"):
            CapacitorSpec(
                cap_type=CapacitorType.DUAL_RUN,
                uf_main=45,
                uf_fan=5,
                voltage_v=440,
                application=CapacitorApp.COMPRESSOR,
            )


# ─── Verdict evaluation ─────────────────────────────────────────────────────


class TestVerdict:
    def test_exact_match_ok(self) -> None:
        needed = CapacitorSpec(
            cap_type=CapacitorType.DUAL_RUN,
            uf_main=45,
            uf_fan=5,
            voltage_v=440,
            application=CapacitorApp.DUAL,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed, have=needed),
        )
        assert res["verdict"] == "ok"
        assert "Exact match" in " ".join(res["reasons"])

    def test_same_spec_higher_voltage_marginal(self) -> None:
        """40/5 440V subbing for 40/5 370V: voltage higher = safe but not exact."""
        needed = CapacitorSpec(
            cap_type=CapacitorType.DUAL_RUN,
            uf_main=40,
            uf_fan=5,
            voltage_v=370,
            application=CapacitorApp.DUAL,
        )
        have = CapacitorSpec(
            cap_type=CapacitorType.DUAL_RUN,
            uf_main=40,
            uf_fan=5,
            voltage_v=440,
            application=CapacitorApp.DUAL,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed, have=have),
        )
        assert res["verdict"] == "marginal"
        reasons = " ".join(res["reasons"])
        assert "over-voltage" in reasons.lower() or "higher" in reasons.lower()

    def test_voltage_too_low_no_go(self) -> None:
        needed = CapacitorSpec(
            cap_type=CapacitorType.RUN,
            uf_main=45,
            voltage_v=440,
            application=CapacitorApp.COMPRESSOR,
        )
        have = CapacitorSpec(
            cap_type=CapacitorType.RUN,
            uf_main=45,
            voltage_v=370,
            application=CapacitorApp.COMPRESSOR,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed, have=have),
        )
        assert res["verdict"] == "no_go"
        assert "Voltage too low" in " ".join(res["reasons"])

    def test_uf_way_off_no_go(self) -> None:
        needed = CapacitorSpec(
            cap_type=CapacitorType.RUN,
            uf_main=45,
            voltage_v=440,
            application=CapacitorApp.COMPRESSOR,
        )
        have = CapacitorSpec(
            cap_type=CapacitorType.RUN,
            uf_main=35,  # 22% low
            voltage_v=440,
            application=CapacitorApp.COMPRESSOR,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed, have=have),
        )
        assert res["verdict"] == "no_go"
        assert "out of tolerance" in " ".join(res["reasons"])

    def test_uf_within_6pct_marginal(self) -> None:
        needed = CapacitorSpec(
            cap_type=CapacitorType.RUN,
            uf_main=45,
            voltage_v=440,
            application=CapacitorApp.COMPRESSOR,
        )
        have = CapacitorSpec(
            cap_type=CapacitorType.RUN,
            uf_main=47,  # ~4.4% high, inside tolerance
            voltage_v=440,
            application=CapacitorApp.COMPRESSOR,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed, have=have),
        )
        assert res["verdict"] == "marginal"

    def test_type_mismatch_no_go(self) -> None:
        needed = CapacitorSpec(
            cap_type=CapacitorType.RUN,
            uf_main=45,
            voltage_v=440,
            application=CapacitorApp.COMPRESSOR,
        )
        have = CapacitorSpec(
            cap_type=CapacitorType.START,
            uf_main=45,
            voltage_v=440,
            application=CapacitorApp.COMPRESSOR,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed, have=have),
        )
        assert res["verdict"] == "no_go"
        assert "Type mismatch" in " ".join(res["reasons"])

    def test_fan_leg_out_of_tol_no_go(self) -> None:
        needed = CapacitorSpec(
            cap_type=CapacitorType.DUAL_RUN,
            uf_main=45,
            uf_fan=5,
            voltage_v=440,
            application=CapacitorApp.DUAL,
        )
        have = CapacitorSpec(
            cap_type=CapacitorType.DUAL_RUN,
            uf_main=45,
            uf_fan=7.5,  # 50% off
            voltage_v=440,
            application=CapacitorApp.DUAL,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed, have=have),
        )
        assert res["verdict"] == "no_go"


# ─── Suggestion output ──────────────────────────────────────────────────────


class TestSuggestions:
    def test_suggests_stocked_dual_sizes(self) -> None:
        needed = CapacitorSpec(
            cap_type=CapacitorType.DUAL_RUN,
            uf_main=45,
            uf_fan=5,
            voltage_v=370,
            application=CapacitorApp.DUAL,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed),
        )
        assert any("45/5" in s for s in res["suggestions"])
        # Should offer 440V equivalent too (upgrade path)
        assert any("440V" in s for s in res["suggestions"])
        assert res["disclaimer"]

    def test_disclaimer_always_present(self) -> None:
        needed = CapacitorSpec(
            cap_type=CapacitorType.RUN,
            uf_main=10,
            voltage_v=370,
            application=CapacitorApp.FAN,
        )
        res = _call(
            _server(),
            "hvac_capacitor_crossref",
            params=CapacitorCrossrefInput(needed=needed),
        )
        assert "AHJ" not in res["disclaimer"]  # this isn't a code tool
        assert "like-with-like" in res["disclaimer"]
