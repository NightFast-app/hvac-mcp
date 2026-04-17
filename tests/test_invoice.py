"""Tests for premium tools: hvac_invoice_draft and hvac_quote_from_diagnosis.

Both are license-gated. Tests set HVAC_MCP_LICENSE_KEY to the dev-allow-list
key so the @premium decorator lets the call through.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from hvac_mcp.tools.invoice import (
    InvoiceDraftInput,
    LineItem,
    QuoteInput,
    QuoteLabor,
    QuotePart,
)


@pytest.fixture(autouse=True)
def _dev_license(monkeypatch):
    monkeypatch.setenv("HVAC_MCP_LICENSE_KEY", "DEV-LOCAL-KEY-DO-NOT-SHIP")


def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None
    return asyncio.run(tool.fn(**kw))


def _server():
    from mcp.server.fastmcp import FastMCP

    from hvac_mcp.tools import invoice

    mcp = FastMCP("test")
    invoice.register(mcp)
    return mcp


# ─── License gating ────────────────────────────────────────────────────────


class TestLicenseGate:
    def test_quote_blocked_without_license(self, monkeypatch) -> None:
        monkeypatch.delenv("HVAC_MCP_LICENSE_KEY", raising=False)
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="Replace cap",
                parts=[QuotePart(description="45/5 cap", unit_cost=25)],
            ),
        )
        assert res.get("error") == "license_required"

    def test_invoice_blocked_without_license(self, monkeypatch) -> None:
        monkeypatch.delenv("HVAC_MCP_LICENSE_KEY", raising=False)
        res = _call(
            _server(),
            "hvac_invoice_draft",
            params=InvoiceDraftInput(
                customer_name="Jane",
                job_description="test",
                line_items=[LineItem(description="a", quantity=1, unit_price=10)],
            ),
        )
        assert res.get("error") == "license_required"


# ─── QuoteInput validation ─────────────────────────────────────────────────


class TestQuoteInput:
    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            QuoteInput(customer_name="x", job_summary="y", foo=1)

    def test_job_summary_min_length(self) -> None:
        with pytest.raises(ValidationError):
            QuoteInput(customer_name="x", job_summary="y")

    def test_tax_rate_bounded(self) -> None:
        with pytest.raises(ValidationError):
            QuoteInput(customer_name="x", job_summary="abc", tax_rate_pct=25)

    def test_defaults(self) -> None:
        q = QuoteInput(customer_name="x", job_summary="abc")
        assert q.tax_rate_pct == 6.5
        assert q.minimum_charge is None
        assert q.include_why_narrative is True


# ─── Quote math ────────────────────────────────────────────────────────────


class TestQuoteMath:
    def test_parts_markup_default_50_pct(self) -> None:
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="Replace 45/5 440V cap",
                parts=[QuotePart(description="cap", unit_cost=20, quantity=1)],
            ),
        )
        # 20 cost * 1.5 = 30 customer price
        assert res["subtotal_parts"] == 30.0
        assert res["parts"][0]["line_total"] == 30.0
        assert res["parts"][0]["markup_pct"] == 50.0

    def test_explicit_markup_overrides(self) -> None:
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="test scope",
                parts=[QuotePart(description="thermostat", unit_cost=100, markup_pct=100)],
            ),
        )
        # 100 cost * 2 = 200 customer price
        assert res["subtotal_parts"] == 200.0

    def test_default_labor_rate_120(self) -> None:
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="test scope",
                labor=[QuoteLabor(description="diag + replace", hours=1.5)],
            ),
        )
        assert res["subtotal_labor"] == 180.0  # 1.5 * 120
        assert res["labor"][0]["rate_per_hour"] == 120.0

    def test_tax_applies_to_parts_only(self) -> None:
        """FL labor is non-taxable; tax should only hit parts subtotal."""
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="test scope",
                parts=[QuotePart(description="p", unit_cost=100)],  # $150 after markup
                labor=[QuoteLabor(description="l", hours=1)],  # $120
            ),
        )
        # parts subtotal $150, labor $120, tax = 150 * 0.065 = $9.75
        assert res["tax"] == pytest.approx(9.75, abs=0.01)
        assert res["total"] == pytest.approx(279.75, abs=0.01)

    def test_minimum_charge_floor(self) -> None:
        """Low-value job bumped up to the minimum."""
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="test scope",
                parts=[QuotePart(description="p", unit_cost=10)],  # $15 after markup
                labor=[QuoteLabor(description="l", hours=0.25)],  # $30
                minimum_charge=89,
            ),
        )
        # Pre-tax subtotal $45, bumped to $89 → delta $44 added as labor line
        assert res["minimum_charge_applied"] is True
        assert res["minimum_charge_delta"] == pytest.approx(44.0, abs=0.01)
        # Total = $89 pre-tax + $15 * 6.5% = $89 + $0.975 = $89.975
        assert res["total"] == pytest.approx(89.98, abs=0.02)

    def test_minimum_charge_skipped_when_above(self) -> None:
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="test scope",
                parts=[QuotePart(description="p", unit_cost=100)],
                labor=[QuoteLabor(description="l", hours=2)],
                minimum_charge=50,
            ),
        )
        assert res["minimum_charge_applied"] is False


# ─── Output format ─────────────────────────────────────────────────────────


class TestQuoteOutput:
    def test_markdown_contains_sections(self) -> None:
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane Smith",
                job_summary="Replace failed dual run capacitor",
                parts=[QuotePart(description="45/5 440V cap", unit_cost=25)],
                labor=[QuoteLabor(description="Diagnose + replace", hours=1.0)],
            ),
        )
        md = res["quote_markdown"]
        assert "# Quote — Jane Smith" in md
        assert "## Parts" in md
        assert "## Labor" in md
        assert "Total" in md
        assert "$" in md

    def test_sms_text_fits_in_one_message(self) -> None:
        """plain-text variant is suitable for SMS (no markdown)."""
        res = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="Short scope",
                parts=[QuotePart(description="x", unit_cost=10)],
            ),
        )
        text = res["quote_text"]
        assert "|" not in text  # no table pipes
        assert "#" not in text  # no markdown headers
        assert "Reply YES to approve" in text

    def test_narrative_toggle(self) -> None:
        with_narrative = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="test scope",
                parts=[QuotePart(description="p", unit_cost=10)],
                include_why_narrative=True,
            ),
        )
        without = _call(
            _server(),
            "hvac_quote_from_diagnosis",
            params=QuoteInput(
                customer_name="Jane",
                job_summary="test scope",
                parts=[QuotePart(description="p", unit_cost=10)],
                include_why_narrative=False,
            ),
        )
        assert "How this is priced" in with_narrative["quote_markdown"]
        assert "How this is priced" not in without["quote_markdown"]


# ─── Invoice draft (existing tool) — smoke test under license fixture ──────


class TestInvoiceDraft:
    def test_happy_path(self) -> None:
        res = _call(
            _server(),
            "hvac_invoice_draft",
            params=InvoiceDraftInput(
                customer_name="Jane",
                job_description="Replaced run cap",
                line_items=[
                    LineItem(description="45/5 cap", quantity=1, unit_price=60),
                    LineItem(description="Labor 1hr", quantity=1, unit_price=120),
                ],
            ),
        )
        assert res["subtotal"] == 180.0
        assert res["tax"] == pytest.approx(11.70, abs=0.01)
        assert res["total"] == pytest.approx(191.70, abs=0.01)
        assert "Invoice" in res["invoice_markdown"]
