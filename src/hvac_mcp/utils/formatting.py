"""Shared response formatting helpers.

Every tool that supports multiple output formats should reuse these rather
than hand-rolling markdown/JSON construction per tool.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any


class ResponseFormat(StrEnum):
    MARKDOWN = "markdown"
    JSON = "json"


def as_json(data: Any) -> str:
    """Compact, deterministic JSON suitable for programmatic use."""
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def ahj_disclaimer() -> str:
    """The mandatory 'verify with AHJ' line. Every code/sizing tool output uses this."""
    return (
        "Informational only. Verify current adopted codes with the Authority "
        "Having Jurisdiction (AHJ) before relying on this output for permit or "
        "installation decisions."
    )


def refrigerant_source_note() -> str:
    """Citation line appended to every PT-based response."""
    return (
        "Source: bundled PT tables derived from manufacturer charts (Chemours, Honeywell, Daikin)."
    )
