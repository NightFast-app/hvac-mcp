"""IRC/IMC/IPC + FL-amendment code lookup tool.

Read-only — never fetches from the network. Data bundled in
`src/hvac_mcp/data/code_snippets.json`. Every response carries the
"verify with AHJ" disclaimer per CLAUDE.md rule 6.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CODE_PATH = _DATA_DIR / "code_snippets.json"

_DISCLAIMER = (
    "Informational summary only. Code text is paraphrased. "
    "Verify against the authoritative adopted code and any local amendments "
    "with your Authority Having Jurisdiction (AHJ) before relying on this "
    "output for permit, installation, or inspection decisions."
)


class CodeLookupInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    topic: str = Field(
        ...,
        description="Keyword or topic (e.g., 'water heater clearances', 'DWV venting', 'dryer duct').",
        min_length=2,
        max_length=200,
    )
    jurisdiction: str = Field(
        default="FL",
        description="Jurisdiction. 'national' returns only model-code entries; 'FL' returns FL amendments + national. Case-insensitive.",
        max_length=16,
    )
    max_results: int = Field(default=5, ge=1, le=15)


_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(_CODE_PATH.read_text())
    return _cache


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _score(entry: dict, tokens: list[str]) -> int:
    """Count token hits across topic, keywords, summary, code, and section.
    Keyword hits are weighted 2x (they're curated for matching)."""
    score = 0
    haystack_fields = [
        entry.get("topic", ""),
        entry.get("summary", ""),
        entry.get("code", ""),
        entry.get("section", ""),
    ]
    haystack = " ".join(haystack_fields).lower()
    keywords = " ".join(entry.get("keywords", [])).lower()
    for tok in tokens:
        if tok in keywords:
            score += 2
        if tok in haystack:
            score += 1
    return score


def _jurisdiction_filter(entries: list[dict], jurisdiction: str) -> list[dict]:
    """`national` → national only. Anything else (e.g. 'FL') → matching jurisdiction + national."""
    j = jurisdiction.strip().lower()
    if j in ("national", "icc", "model"):
        return [e for e in entries if e.get("jurisdiction", "").lower() == "national"]
    return [
        e
        for e in entries
        if e.get("jurisdiction", "").lower() in ("national", j)
        or e.get("jurisdiction", "").upper() == jurisdiction.upper()
    ]


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="hvac_code_lookup",
        annotations={
            "title": "HVAC / Plumbing Code Lookup",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def hvac_code_lookup(params: CodeLookupInput) -> dict[str, Any]:
        """Return relevant IRC/IMC/IPC citations + FL amendments for a topic.

        Never represents output as legal compliance advice. Always includes
        the AHJ-verification disclaimer.

        Returns:
            dict with topic, jurisdiction, citations (list of
            {code, section, edition, topic, summary, gotchas, source}),
            disclaimer, status.
        """
        data = _load()
        entries = _jurisdiction_filter(data.get("entries", []), params.jurisdiction)
        tokens = _tokenize(params.topic)
        if not tokens:
            return {
                "topic": params.topic,
                "jurisdiction": params.jurisdiction,
                "citations": [],
                "disclaimer": _DISCLAIMER,
                "status": "no_match",
            }

        scored = [(e, _score(e, tokens)) for e in entries]
        hits = sorted(
            (pair for pair in scored if pair[1] > 0),
            key=lambda p: p[1],
            reverse=True,
        )[: params.max_results]

        citations = [
            {
                "code": e.get("code"),
                "section": e.get("section"),
                "edition": e.get("edition"),
                "jurisdiction": e.get("jurisdiction"),
                "topic": e.get("topic"),
                "summary": e.get("summary"),
                "gotchas": e.get("gotchas", []),
                "source": e.get("source"),
                "relevance_score": score,
            }
            for e, score in hits
        ]

        return {
            "topic": params.topic,
            "jurisdiction": params.jurisdiction,
            "citations": citations,
            "disclaimer": _DISCLAIMER,
            "status": "matched" if citations else "no_match",
            "source_meta": data.get("_meta", {}).get("editions", {}),
        }
