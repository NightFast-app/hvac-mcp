"""Tests for hvac_pipe_size (Tool 6)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from hvac_mcp.tools.sizing import (
    DuctShape,
    DuctSizeInput,
    PipeApplication,
    PipeMaterial,
    PipeSizeInput,
    _equivalent_round_diameter,
    _huebscher_width,
    _load_pipe_tables,
    _nominal_to_inches,
    _velocity_fpm,
)


def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None
    return asyncio.run(tool.fn(**kw))


def _server():
    from mcp.server.fastmcp import FastMCP

    from hvac_mcp.tools import sizing

    mcp = FastMCP("test")
    sizing.register(mcp)
    return mcp


class TestHelpers:
    def test_nominal_to_inches(self) -> None:
        assert _nominal_to_inches('1/2"') == 0.5
        assert _nominal_to_inches('3/4"') == 0.75
        assert _nominal_to_inches('1"') == 1.0
        assert _nominal_to_inches('1-1/2"') == 1.5
        assert _nominal_to_inches('3"') == 3.0

    def test_tables_loaded(self) -> None:
        t = _load_pipe_tables()
        assert t["dwv_horizontal_branch"][0]["nominal"] == '1-1/4"'
        assert t["supply_by_wsfu_copper"][0]["nominal"] == '1/2"'


class TestInputValidation:
    def test_rejects_pex_dwv(self) -> None:
        with pytest.raises(ValidationError):
            PipeSizeInput(
                fixture_units=5,
                material=PipeMaterial.PEX,
                application=PipeApplication.DWV,
            )

    def test_rejects_pvc_supply(self) -> None:
        with pytest.raises(ValidationError):
            PipeSizeInput(
                fixture_units=5,
                material=PipeMaterial.PVC,
                application=PipeApplication.SUPPLY,
            )

    def test_rejects_cast_iron_supply(self) -> None:
        with pytest.raises(ValidationError):
            PipeSizeInput(
                fixture_units=5,
                material=PipeMaterial.CAST_IRON,
                application=PipeApplication.SUPPLY,
            )

    def test_rejects_negative_dfu(self) -> None:
        with pytest.raises(ValidationError):
            PipeSizeInput(
                fixture_units=-1,
                material=PipeMaterial.PVC,
                application=PipeApplication.DWV,
            )


class TestDWVSizing:
    def test_small_dfu_picks_one_and_a_quarter(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=1, material=PipeMaterial.PVC, application=PipeApplication.DWV
            ),
        )
        assert res["status"] == "matched"
        assert res["recommended_size_in"] == '1-1/4"'

    def test_six_dfu_picks_two_inch(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=6, material=PipeMaterial.PVC, application=PipeApplication.DWV
            ),
        )
        assert res["recommended_size_in"] == '2"'

    def test_twenty_dfu_picks_three_inch(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=20, material=PipeMaterial.PVC, application=PipeApplication.DWV
            ),
        )
        assert res["recommended_size_in"] == '3"'

    def test_wc_note_appears_at_low_dfu(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=3, material=PipeMaterial.PVC, application=PipeApplication.DWV
            ),
        )
        notes = " ".join(res["notes"]).lower()
        assert "water closet" in notes or "wc" in notes

    def test_out_of_range_dfu(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=1000, material=PipeMaterial.PVC, application=PipeApplication.DWV
            ),
        )
        assert res["status"] == "out_of_range"
        assert res["recommended_size_in"] is None


class TestSupplySizing:
    def test_copper_ten_wsfu_picks_three_quarter(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=10,
                material=PipeMaterial.COPPER,
                application=PipeApplication.SUPPLY,
            ),
        )
        assert res["recommended_size_in"] == '3/4"'

    def test_pex_bumps_size_up(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=10,
                material=PipeMaterial.PEX,
                application=PipeApplication.SUPPLY,
            ),
        )
        assert res["copper_equivalent_size_in"] == '3/4"'
        assert res["recommended_size_in"] == '1"'
        assert any("PEX" in n for n in res["notes"])

    def test_cpvc_matches_copper_size(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=20,
                material=PipeMaterial.CPVC,
                application=PipeApplication.SUPPLY,
            ),
        )
        assert res["recommended_size_in"] == '1"'

    def test_large_wsfu_out_of_range(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=500,
                material=PipeMaterial.COPPER,
                application=PipeApplication.SUPPLY,
            ),
        )
        assert res["status"] == "out_of_range"


class TestDisclaimer:
    def test_always_present(self) -> None:
        res = _call(
            _server(),
            "hvac_pipe_size",
            params=PipeSizeInput(
                fixture_units=5, material=PipeMaterial.PVC, application=PipeApplication.DWV
            ),
        )
        assert "AHJ" in res["disclaimer"]


class TestDuctMath:
    def test_known_diameter_400cfm_at_0_10(self) -> None:
        """400 CFM at 0.10 in.wc/100ft ≈ 9.4" on ASHRAE friction chart."""
        de = _equivalent_round_diameter(400, 0.10)
        assert 9.0 <= de <= 10.0

    def test_known_diameter_800cfm_at_0_08(self) -> None:
        # ASHRAE friction chart: 800 CFM at 0.08 in.wc/100ft → ~13.4"
        de = _equivalent_round_diameter(800, 0.08)
        assert 12.5 <= de <= 14.0

    def test_lower_friction_gives_larger_duct(self) -> None:
        small_f = _equivalent_round_diameter(500, 0.05)
        big_f = _equivalent_round_diameter(500, 0.15)
        assert small_f > big_f

    def test_velocity_computation(self) -> None:
        # 10" duct at 400 CFM → velocity ~733 fpm
        v = _velocity_fpm(400, 10.0)
        assert 700 <= v <= 760

    def test_huebscher_consistency(self) -> None:
        """Round-trip: compute width for a given h and De, then verify De via Huebscher."""
        de = 12.0
        w = _huebscher_width(8.0, de)
        de_back = 1.30 * (8.0 * w) ** 0.625 / (8.0 + w) ** 0.25
        assert abs(de_back - de) / de < 0.02


class TestDuctInput:
    def test_rejects_zero_cfm(self) -> None:
        with pytest.raises(ValidationError):
            DuctSizeInput(cfm=0)

    def test_rejects_excessive_friction(self) -> None:
        with pytest.raises(ValidationError):
            DuctSizeInput(cfm=400, friction_rate=1.0)

    def test_default_friction_rate(self) -> None:
        inp = DuctSizeInput(cfm=400)
        assert inp.friction_rate == 0.08


class TestDuctTool:
    def test_round_sized_result(self) -> None:
        res = _call(
            _server(),
            "hvac_duct_size",
            params=DuctSizeInput(cfm=400, friction_rate=0.10),
        )
        assert res["status"] == "matched"
        assert 9.0 <= res["equivalent_round_diameter_in"] <= 10.0
        assert res["velocity_fpm"] > 0

    def test_rectangular_options_returned(self) -> None:
        res = _call(
            _server(),
            "hvac_duct_size",
            params=DuctSizeInput(cfm=600, friction_rate=0.08, duct_shape=DuctShape.RECTANGULAR),
        )
        assert res["rectangular_options"]
        for opt in res["rectangular_options"]:
            assert opt["height_in"] in (6, 8, 10, 12, 14)
            assert opt["width_in"] > opt["height_in"] * 0.5

    def test_high_velocity_warning(self) -> None:
        # Very high CFM at high friction rate forces small duct, high velocity.
        res = _call(
            _server(),
            "hvac_duct_size",
            params=DuctSizeInput(cfm=2000, friction_rate=0.15),
        )
        assert any("velocity" in w.lower() for w in res["warnings"])

    def test_disclaimer_present(self) -> None:
        res = _call(
            _server(),
            "hvac_duct_size",
            params=DuctSizeInput(cfm=400),
        )
        assert "galvanized" in res["disclaimer"].lower()
