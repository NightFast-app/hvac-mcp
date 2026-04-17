"""Tests for refrigerant tools."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from hvac_mcp.tools.refrigerant import (
    ChargeCheckInput,
    MeteringDevice,
    PTLookupInput,
    Refrigerant,
    sat_pressure_from_temp,
    sat_temp_from_pressure,
)


class TestPTLookupInput:
    def test_accepts_pressure_only(self) -> None:
        inp = PTLookupInput(refrigerant=Refrigerant.R410A, pressure_psig=118.0)
        assert inp.pressure_psig == 118.0
        assert inp.temp_f is None

    def test_accepts_temp_only(self) -> None:
        inp = PTLookupInput(refrigerant=Refrigerant.R410A, temp_f=40.0)
        assert inp.temp_f == 40.0
        assert inp.pressure_psig is None

    def test_rejects_both(self) -> None:
        with pytest.raises(ValidationError):
            PTLookupInput(refrigerant=Refrigerant.R410A, pressure_psig=118.0, temp_f=40.0)

    def test_rejects_neither(self) -> None:
        with pytest.raises(ValidationError):
            PTLookupInput(refrigerant=Refrigerant.R410A)

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            PTLookupInput(refrigerant=Refrigerant.R410A, temp_f=40.0, foo="bar")


class TestInterpolation:
    def test_r410a_40f_exact(self) -> None:
        # Table row: 40°F -> 118.5 psig
        assert sat_pressure_from_temp(Refrigerant.R410A, 40.0) == pytest.approx(118.5, abs=0.1)

    def test_r410a_118_5_psig_exact(self) -> None:
        assert sat_temp_from_pressure(Refrigerant.R410A, 118.5) == pytest.approx(40.0, abs=0.1)

    def test_r410a_interpolated_midpoint(self) -> None:
        # 35°F lies halfway between 30 (94.9) and 40 (118.5) -> ~106.7
        assert sat_pressure_from_temp(Refrigerant.R410A, 35.0) == pytest.approx(106.7, abs=0.1)

    def test_r22_40f(self) -> None:
        assert sat_pressure_from_temp(Refrigerant.R22, 40.0) == pytest.approx(68.5, abs=0.1)

    def test_r454b_has_glide(self) -> None:
        bubble = sat_pressure_from_temp(Refrigerant.R454B, 40.0, curve="bubble")
        dew = sat_pressure_from_temp(Refrigerant.R454B, 40.0, curve="dew")
        assert bubble > dew
        assert bubble - dew == pytest.approx(3.5, abs=0.2)

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="outside the table range"):
            sat_temp_from_pressure(Refrigerant.R410A, 900.0)


def _call_tool(mcp, name: str, **kwargs):
    """Helper to invoke a registered FastMCP tool directly for unit testing."""
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None, f"Tool {name} not registered"
    return asyncio.run(tool.fn(**kwargs))


class TestPTLookupTool:
    def test_pressure_input_azeotrope(self) -> None:
        from mcp.server.fastmcp import FastMCP

        from hvac_mcp.tools import refrigerant

        mcp = FastMCP("test")
        refrigerant.register(mcp)
        res = _call_tool(
            mcp,
            "hvac_refrigerant_pt_lookup",
            params=PTLookupInput(refrigerant=Refrigerant.R410A, pressure_psig=118.5),
        )
        assert res["refrigerant"] == "R-410A"
        assert res["temp_f"] == pytest.approx(40.0, abs=0.1)
        assert "Near-azeotropic" in res["guidance"]

    def test_temp_input_blend_reports_both_curves(self) -> None:
        from mcp.server.fastmcp import FastMCP

        from hvac_mcp.tools import refrigerant

        mcp = FastMCP("test")
        refrigerant.register(mcp)
        res = _call_tool(
            mcp,
            "hvac_refrigerant_pt_lookup",
            params=PTLookupInput(refrigerant=Refrigerant.R454B, temp_f=40.0),
        )
        assert res["bubble_pressure_psig"] > res["dew_pressure_psig"]
        assert res["glide_f"] > 0
        assert "Zeotropic" in res["guidance"]


class TestChargeCheckTool:
    """End-to-end diagnosis tests. R-410A saturation at 118.5 psig ≈ 40°F, at 380 psig ≈ ~115°F."""

    @staticmethod
    def _server():
        from mcp.server.fastmcp import FastMCP

        from hvac_mcp.tools import refrigerant

        mcp = FastMCP("test")
        refrigerant.register(mcp)
        return mcp

    def test_txv_in_spec(self) -> None:
        # suction sat ~40°F, suction line 50°F -> SH 10; liquid sat ~115°F, liquid 105°F -> SC 10
        res = _call_tool(
            self._server(),
            "hvac_refrigerant_charge_check",
            params=ChargeCheckInput(
                refrigerant=Refrigerant.R410A,
                suction_pressure_psig=118.5,
                suction_line_temp_f=50.0,
                liquid_pressure_psig=380.0,
                liquid_line_temp_f=105.0,
                metering=MeteringDevice.TXV,
            ),
        )
        assert res["diagnosis"] == "in_spec"
        assert res["superheat_f"] == pytest.approx(10.0, abs=0.5)
        assert res["subcool_f"] == pytest.approx(10.0, abs=1.0)

    def test_txv_undercharged(self) -> None:
        res = _call_tool(
            self._server(),
            "hvac_refrigerant_charge_check",
            params=ChargeCheckInput(
                refrigerant=Refrigerant.R410A,
                suction_pressure_psig=118.5,
                suction_line_temp_f=55.0,
                liquid_pressure_psig=380.0,
                liquid_line_temp_f=113.0,  # subcool ~2
                metering=MeteringDevice.TXV,
            ),
        )
        assert res["diagnosis"] == "undercharged"

    def test_txv_overcharged(self) -> None:
        res = _call_tool(
            self._server(),
            "hvac_refrigerant_charge_check",
            params=ChargeCheckInput(
                refrigerant=Refrigerant.R410A,
                suction_pressure_psig=118.5,
                suction_line_temp_f=50.0,
                liquid_pressure_psig=380.0,
                liquid_line_temp_f=95.0,  # subcool ~20
                metering=MeteringDevice.TXV,
            ),
        )
        assert res["diagnosis"] == "overcharged"

    def test_txv_restriction_suspected(self) -> None:
        # Normal subcool but very high superheat -> TXV starved
        res = _call_tool(
            self._server(),
            "hvac_refrigerant_charge_check",
            params=ChargeCheckInput(
                refrigerant=Refrigerant.R410A,
                suction_pressure_psig=118.5,
                suction_line_temp_f=70.0,  # SH ~30
                liquid_pressure_psig=380.0,
                liquid_line_temp_f=105.0,  # SC ~10
                metering=MeteringDevice.TXV,
            ),
        )
        assert res["diagnosis"] == "restriction_suspected"

    def test_piston_in_spec_default_target(self) -> None:
        res = _call_tool(
            self._server(),
            "hvac_refrigerant_charge_check",
            params=ChargeCheckInput(
                refrigerant=Refrigerant.R410A,
                suction_pressure_psig=118.5,
                suction_line_temp_f=55.0,  # SH ~15 → matches default target
                liquid_pressure_psig=380.0,
                liquid_line_temp_f=105.0,
                metering=MeteringDevice.PISTON,
            ),
        )
        assert res["diagnosis"] == "in_spec"
        assert res["target_superheat_f"] == 15.0

    def test_piston_custom_target_undercharged(self) -> None:
        res = _call_tool(
            self._server(),
            "hvac_refrigerant_charge_check",
            params=ChargeCheckInput(
                refrigerant=Refrigerant.R410A,
                suction_pressure_psig=118.5,
                suction_line_temp_f=70.0,  # SH ~30
                liquid_pressure_psig=380.0,
                liquid_line_temp_f=105.0,
                metering=MeteringDevice.PISTON,
                target_superheat_f=10.0,
            ),
        )
        assert res["diagnosis"] == "undercharged"

    def test_impossible_reading(self) -> None:
        # Suction line temp below saturation -> negative superheat
        res = _call_tool(
            self._server(),
            "hvac_refrigerant_charge_check",
            params=ChargeCheckInput(
                refrigerant=Refrigerant.R410A,
                suction_pressure_psig=118.5,
                suction_line_temp_f=30.0,
                liquid_pressure_psig=380.0,
                liquid_line_temp_f=105.0,
            ),
        )
        assert res["diagnosis"] == "insufficient_data"
        assert res["confidence"] == "low"


class TestChargeCheckInput:
    def test_valid_txv_input(self) -> None:
        inp = ChargeCheckInput(
            refrigerant=Refrigerant.R410A,
            suction_pressure_psig=118.0,
            suction_line_temp_f=50.0,
            liquid_pressure_psig=380.0,
            liquid_line_temp_f=100.0,
            metering=MeteringDevice.TXV,
        )
        assert inp.metering == MeteringDevice.TXV

    def test_defaults_to_txv(self) -> None:
        inp = ChargeCheckInput(
            refrigerant=Refrigerant.R410A,
            suction_pressure_psig=118.0,
            suction_line_temp_f=50.0,
            liquid_pressure_psig=380.0,
            liquid_line_temp_f=100.0,
        )
        assert inp.metering == MeteringDevice.TXV
