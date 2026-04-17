---
name: add-tool
description: Scaffold a new HVAC MCP tool following the mandatory CLAUDE.md pattern — Pydantic input model with model_config, @mcp.tool with annotations, Args/Returns docstring, pytest file, todo.md checkbox, and server registration.
---

# add-tool — scaffold a new MCP tool

Use when adding a new entry to the tool catalog. Enforces lessons.md seed rule #3.

## Required artifacts (all four, no exceptions)

1. **Tool module**: `src/hvac_mcp/tools/<name>.py` — see template below.
2. **Test module**: `tests/test_<name>.py` — see template below.
3. **Server registration**: append `<name>.register(mcp)` in `register_all_tools()` at `src/hvac_mcp/server.py`.
4. **Todo checkbox**: the corresponding `### Tool N: hvac_<name>` in `tasks/todo.md` gets ticked only after /verify passes all gates.

## Tool module template

```python
"""<what this tool does, one sentence>."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field


class <Name>Input(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )
    # fields with Field(..., description=..., ge=..., le=...)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="hvac_<name>",
        annotations={
            "title": "<human-readable title>",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,   # True ONLY if tool hits external network
        },
    )
    async def hvac_<name>(params: <Name>Input) -> dict[str, Any]:
        """<one-line summary>.

        <paragraph explaining logic / edge cases / units>.

        Returns:
            dict with keys: <list them>.
        """
        ...
        return {"source": "<citation for any bundled data>", ...}
```

## Test module template

```python
"""Tests for hvac_<name>."""
from __future__ import annotations
import asyncio
import pytest
from pydantic import ValidationError
from hvac_mcp.tools.<name> import <Name>Input


def _call(mcp, name, **kw):
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None
    return asyncio.run(tool.fn(**kw))


def _server():
    from mcp.server.fastmcp import FastMCP
    from hvac_mcp.tools import <name>
    mcp = FastMCP("test")
    <name>.register(mcp)
    return mcp


class TestInput:
    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            <Name>Input(foo="bar")


class TestBehavior:
    def test_happy_path(self) -> None:
        res = _call(_server(), "hvac_<name>", params=<Name>Input(...))
        assert res["source"]
```

## Non-negotiables (from CLAUDE.md + lessons.md)

- `model_config = ConfigDict(extra="forbid")` — always.
- Use `StrEnum` (Python 3.11+), not `class Foo(str, Enum)`.
- No hyphen-minus `-` confusion: avoid en-dashes `–` in docstrings (RUF002).
- Premium tools MUST call `require_license(ctx)` on the first line.
- Bundled reference data goes in `src/hvac_mcp/data/` and is loaded lazily + cached.
- Every `source` field cites origin — no silent guessing.

## After scaffolding
Run the /verify skill. Only check the todo.md box if all gates pass.
