"""Premium tools: invoice/estimate generation + quote-from-diagnosis.
License-gated.

Every premium tool uses @premium. If a user hits a premium tool without a
license, they get a structured error pointing to the purchase URL — no
silent degradation.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from hvac_mcp.licensing import premium

# Defaults tuned for FL solo / small-shop operator. Override per call.
DEFAULT_LABOR_RATE_PER_HOUR = 120.0
DEFAULT_PARTS_MARKUP_PCT = 50.0
DEFAULT_TAX_RATE_PCT = 6.5  # Florida state + typical local surtax


class LineItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    description: str = Field(..., min_length=1, max_length=200)
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)


class InvoiceDraftInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    customer_name: str = Field(..., description="Customer full name.", min_length=1, max_length=200)
    customer_address: str | None = Field(default=None, max_length=300)
    job_description: str = Field(
        ..., description="Short summary of work performed.", min_length=1, max_length=500
    )
    line_items: list[LineItem] = Field(
        ..., description="Parts + labor line items.", min_length=1, max_length=50
    )
    tax_rate_pct: float = Field(
        default=DEFAULT_TAX_RATE_PCT,
        description="Sales tax rate in percent (FL default 6.5).",
        ge=0,
        le=20,
    )
    notes: str | None = Field(default=None, max_length=500)


# ─── Quote-from-diagnosis (new premium tool) ────────────────────────────────


class QuotePart(BaseModel):
    """A part line on the quote. Unit cost is what YOU pay at the supply
    house; we mark it up before the customer sees anything."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    description: str = Field(..., min_length=1, max_length=200)
    unit_cost: float = Field(..., ge=0, description="Your cost per unit (pre-markup).")
    quantity: float = Field(default=1.0, gt=0)
    markup_pct: float = Field(
        default=DEFAULT_PARTS_MARKUP_PCT,
        description="Markup on cost (%). Default 50%; typical shops run 40-100%.",
        ge=0,
        le=300,
    )


class QuoteLabor(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    description: str = Field(..., min_length=1, max_length=200)
    hours: float = Field(..., gt=0, le=40)
    rate_per_hour: float = Field(
        default=DEFAULT_LABOR_RATE_PER_HOUR,
        description=f"$/hr billed to customer. Default ${DEFAULT_LABOR_RATE_PER_HOUR:.0f} (FL solo/small shop typical).",
        ge=0,
        le=500,
    )


class QuoteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    customer_name: str = Field(..., min_length=1, max_length=200)
    job_summary: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="One-line diagnosis / scope, e.g. 'Replace failed dual run capacitor 45/5 440V'.",
    )
    parts: list[QuotePart] = Field(default_factory=list, max_length=30)
    labor: list[QuoteLabor] = Field(default_factory=list, max_length=20)
    tax_rate_pct: float = Field(
        default=DEFAULT_TAX_RATE_PCT,
        description="Sales tax rate in percent (FL default 6.5). FL labor is generally non-taxable; this applies to parts only.",
        ge=0,
        le=20,
    )
    minimum_charge: float | None = Field(
        default=None,
        description="Optional service-call floor (e.g. 89). If subtotal is below this, round up to it.",
        ge=0,
        le=10000,
    )
    include_why_narrative: bool = Field(
        default=True,
        description="Include a short customer-facing explanation of markup / labor rate.",
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="hvac_invoice_draft",
        annotations={
            "title": "Draft an HVAC/Plumbing Invoice (Premium)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @premium
    async def hvac_invoice_draft(params: InvoiceDraftInput) -> dict:
        """Generate a formatted invoice ready to send.

        PREMIUM — requires HVAC_MCP_LICENSE_KEY set in the environment.

        Args:
            params: InvoiceDraftInput validated fields.

        Returns:
            dict with keys:
                invoice_markdown (str): formatted invoice
                subtotal (float)
                tax (float)
                total (float)
                line_count (int)
        """
        subtotal = sum(li.quantity * li.unit_price for li in params.line_items)
        tax = round(subtotal * (params.tax_rate_pct / 100.0), 2)
        total = round(subtotal + tax, 2)

        lines_md = "\n".join(
            f"| {li.description} | {li.quantity:g} | ${li.unit_price:,.2f} | ${li.quantity * li.unit_price:,.2f} |"
            for li in params.line_items
        )

        invoice_md = f"""# Invoice — {params.customer_name}

**Job:** {params.job_description}

| Item | Qty | Unit | Subtotal |
|---|---:|---:|---:|
{lines_md}

**Subtotal:** ${subtotal:,.2f}
**Tax ({params.tax_rate_pct:g}%):** ${tax:,.2f}
**Total Due:** ${total:,.2f}

{params.notes or ""}
"""

        return {
            "invoice_markdown": invoice_md,
            "subtotal": round(subtotal, 2),
            "tax": tax,
            "total": total,
            "line_count": len(params.line_items),
        }

    @mcp.tool(
        name="hvac_quote_from_diagnosis",
        annotations={
            "title": "Customer-Facing Quote from a Diagnosis (Premium)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    @premium
    async def hvac_quote_from_diagnosis(params: QuoteInput) -> dict[str, Any]:
        """Generate a customer-ready quote from a diagnosis + parts list.

        Applies parts markup (default 50%) and FL-default labor rate
        ($120/hr), FL sales tax on parts only (6.5% default — labor is
        non-taxable in FL). Enforces optional minimum_charge floor.

        PREMIUM — requires HVAC_MCP_LICENSE_KEY.

        Returns:
            dict with quote_markdown, quote_text (SMS-safe plain text),
            subtotals_parts/labor, tax, total, and an optional
            why_this_price narrative the tech can strip before sending.
        """
        # ─── Parts: apply per-line markup ────────────────────────────────
        parts_rows: list[dict[str, Any]] = []
        parts_subtotal = 0.0
        for p in params.parts:
            line_cost = p.unit_cost * p.quantity
            line_customer = line_cost * (1 + p.markup_pct / 100.0)
            parts_subtotal += line_customer
            parts_rows.append(
                {
                    "description": p.description,
                    "quantity": p.quantity,
                    "unit_customer_price": round(line_customer / p.quantity, 2),
                    "line_total": round(line_customer, 2),
                    "markup_pct": p.markup_pct,
                }
            )
        parts_subtotal = round(parts_subtotal, 2)

        # ─── Labor: hours * rate per line ────────────────────────────────
        labor_rows: list[dict[str, Any]] = []
        labor_subtotal = 0.0
        for lb in params.labor:
            line = lb.hours * lb.rate_per_hour
            labor_subtotal += line
            labor_rows.append(
                {
                    "description": lb.description,
                    "hours": lb.hours,
                    "rate_per_hour": lb.rate_per_hour,
                    "line_total": round(line, 2),
                }
            )
        labor_subtotal = round(labor_subtotal, 2)

        # ─── Minimum charge floor ────────────────────────────────────────
        pre_tax_subtotal = parts_subtotal + labor_subtotal
        minimum_applied = False
        minimum_delta = 0.0
        if params.minimum_charge is not None and pre_tax_subtotal < params.minimum_charge:
            minimum_delta = round(params.minimum_charge - pre_tax_subtotal, 2)
            labor_rows.append(
                {
                    "description": f"Minimum service call adjustment (floor ${params.minimum_charge:.2f})",
                    "hours": 0.0,
                    "rate_per_hour": 0.0,
                    "line_total": minimum_delta,
                }
            )
            labor_subtotal = round(labor_subtotal + minimum_delta, 2)
            pre_tax_subtotal = parts_subtotal + labor_subtotal
            minimum_applied = True

        # ─── Tax: parts only (FL labor is non-taxable) ──────────────────
        tax = round(parts_subtotal * (params.tax_rate_pct / 100.0), 2)
        total = round(pre_tax_subtotal + tax, 2)

        # ─── Markdown ────────────────────────────────────────────────────
        parts_md = (
            "| Part | Qty | Price | Total |\n|---|---:|---:|---:|\n"
            + "\n".join(
                f"| {r['description']} | {r['quantity']:g} | ${r['unit_customer_price']:,.2f} | ${r['line_total']:,.2f} |"
                for r in parts_rows
            )
            if parts_rows
            else "_No parts on this job._"
        )
        labor_md = (
            "| Work | Hours | Rate | Total |\n|---|---:|---:|---:|\n"
            + "\n".join(
                f"| {r['description']} | {r['hours']:g} | ${r['rate_per_hour']:,.2f}/hr | ${r['line_total']:,.2f} |"
                for r in labor_rows
            )
            if labor_rows
            else "_No labor line items._"
        )

        why = ""
        if params.include_why_narrative:
            why = (
                "\n\n---\n"
                "**How this is priced.** Parts are marked up over our cost "
                "to cover warranty, procurement, and truck stock. Labor "
                "covers the time on site plus the drive, the diagnosis, "
                "and standing behind the work. No hidden fees — if you want "
                "anything itemized differently, ask and I'll rework it."
            )

        quote_md = f"""# Quote — {params.customer_name}

**Scope:** {params.job_summary}

## Parts
{parts_md}

## Labor
{labor_md}

| | Amount |
|---|---:|
| Parts subtotal | ${parts_subtotal:,.2f} |
| Labor subtotal | ${labor_subtotal:,.2f} |
| Sales tax on parts ({params.tax_rate_pct:g}%) | ${tax:,.2f} |
| **Total** | **${total:,.2f}** |
{why}
"""

        quote_text = (
            f"Quote for {params.customer_name}:\n"
            f"Scope: {params.job_summary}\n"
            f"Parts: ${parts_subtotal:,.2f}\n"
            f"Labor: ${labor_subtotal:,.2f}\n"
            f"Tax on parts ({params.tax_rate_pct:g}%): ${tax:,.2f}\n"
            f"TOTAL: ${total:,.2f}\n"
            f"Reply YES to approve."
        )

        return {
            "quote_markdown": quote_md,
            "quote_text": quote_text,
            "parts": parts_rows,
            "labor": labor_rows,
            "subtotal_parts": parts_subtotal,
            "subtotal_labor": labor_subtotal,
            "tax": tax,
            "total": total,
            "minimum_charge_applied": minimum_applied,
            "minimum_charge_delta": minimum_delta if minimum_applied else 0.0,
            "source": "hvac_quote_from_diagnosis — FL defaults ($120/hr, 50% parts markup, 6.5% parts tax).",
        }
