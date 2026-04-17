---
name: verify
description: Run the full HVAC-MCP verification gate from CLAUDE.md — ruff check, ruff format check, pytest, and server boot. Use before marking any tasks/todo.md item done, or after any change to src/ or tests/.
---

# Verify — full CLAUDE.md verification gate

Run these commands from the project root in order. Stop on first failure and report which gate failed and the first failing test/file. On success, print a one-line summary per gate.

## Gate 1 — Lint
```bash
uv run --no-project --with-editable . --with ruff ruff check src/ tests/
uv run --no-project --with-editable . --with ruff ruff format --check src/ tests/
```

## Gate 2 — Tests
```bash
uv run --no-project --with-editable . --with pytest --with pytest-asyncio --with pyyaml pytest -q
```

## Gate 3 — Server boots
```bash
uv run python -m hvac_mcp.server --help
```

## Gate 4 — Tool registration smoke test
```bash
uv run --no-project --with-editable . --with pytest --with pytest-asyncio --with pyyaml python -c "
from hvac_mcp.server import register_all_tools, mcp
register_all_tools()
tools = list(mcp._tool_manager.list_tools())
print(f'registered {len(tools)} tools:')
for t in tools: print(f'  - {t.name}')
"
```

## Reporting format
```
Gate 1 (lint):    PASS / FAIL — <first error>
Gate 2 (tests):   PASS / FAIL — <first failing test>
Gate 3 (boot):    PASS / FAIL
Gate 4 (tools):   PASS — N tools registered
```

## Do NOT
- Skip gates even if "small change."
- Mark a todo item done unless all four gates pass.
- Run `pip install` — always `uv run`.
