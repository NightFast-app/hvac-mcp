"""Premium tools: invoice/estimate generation. License-gated.

This module demonstrates the @premium decorator pattern. Every premium tool
MUST use it — there is no silent degradation. If a user hits a premium tool
without a license, they get a structured error pointing to the purchase URL.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from hvac_mcp.licensing import premium


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
        default=6.5, description="Sales tax rate in percent (FL default 6.5).", ge=0, le=20
    )
    notes: str | None = Field(default=None, max_length=500)


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
