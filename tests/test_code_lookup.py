"""Tests for hvac_code_lookup."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from hvac_mcp.tools.code_lookup import CodeLookupInput, _load


def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None
    return asyncio.run(tool.fn(**kw))


def _server():
    from mcp.server.fastmcp import FastMCP

    from hvac_mcp.tools import code_lookup

    mcp = FastMCP("test")
    code_lookup.register(mcp)
    return mcp


class TestInput:
    def test_rejects_short_topic(self) -> None:
        with pytest.raises(ValidationError):
            CodeLookupInput(topic="x")

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            CodeLookupInput(topic="dryer", foo=1)

    def test_default_jurisdiction_is_fl(self) -> None:
        inp = CodeLookupInput(topic="dryer duct")
        assert inp.jurisdiction == "FL"


class TestDataSchema:
    def test_every_entry_has_required_fields(self) -> None:
        data = _load()
        assert data.get("_meta", {}).get("disclaimer"), "meta disclaimer missing"
        for e in data["entries"]:
            for k in (
                "id",
                "code",
                "section",
                "edition",
                "jurisdiction",
                "topic",
                "keywords",
                "summary",
                "source",
            ):
                assert e.get(k), f"{e.get('id')}: missing {k}"

    def test_fl_entries_present(self) -> None:
        data = _load()
        assert any(e["jurisdiction"] == "FL" for e in data["entries"])


class TestLookup:
    def test_dryer_duct_finds_m1502(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="dryer duct", jurisdiction="national"),
        )
        assert res["status"] == "matched"
        sections = [c["section"] for c in res["citations"]]
        assert "M1502" in sections

    def test_condensate_finds_imc_307(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="condensate drain", jurisdiction="national"),
        )
        assert res["status"] == "matched"
        assert any("307" in c["section"] for c in res["citations"])

    def test_disclaimer_always_present(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="anything", jurisdiction="FL"),
        )
        assert "AHJ" in res["disclaimer"]

    def test_fl_jurisdiction_includes_national_and_fl(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="hurricane anchor condensate", jurisdiction="FL"),
        )
        juris = {c["jurisdiction"] for c in res["citations"]}
        assert "FL" in juris

    def test_national_jurisdiction_excludes_fl(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="hurricane anchor", jurisdiction="national"),
        )
        juris = {c["jurisdiction"] for c in res["citations"]}
        assert "FL" not in juris

    def test_no_match_returns_empty_citations(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="zzzzzzz unrelated zzzzzzz"),
        )
        assert res["status"] == "no_match"
        assert res["citations"] == []
        assert "AHJ" in res["disclaimer"]

    def test_hvhz_query_returns_fl_hvhz_entry(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="HVHZ miami-dade", jurisdiction="FL"),
        )
        assert res["status"] == "matched"
        assert any("HVHZ" in c["section"] or "301.15" in c["section"] for c in res["citations"])

    def test_ranking_by_relevance(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="dryer exhaust lint", jurisdiction="national"),
        )
        scores = [c["relevance_score"] for c in res["citations"]]
        assert scores == sorted(scores, reverse=True)
        # Top hit should be the dryer section
        assert res["citations"][0]["section"] == "M1502"

    def test_max_results_honored(self) -> None:
        res = _call(
            _server(),
            "hvac_code_lookup",
            params=CodeLookupInput(topic="duct vent drain", max_results=2),
        )
        assert len(res["citations"]) <= 2
