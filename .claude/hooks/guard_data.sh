#!/usr/bin/env bash
# PreToolUse hook — protect safety-critical bundled data files.
# Blocks edits to src/hvac_mcp/data/*.json|yaml unless tasks/lessons.md
# was also touched in the current working tree (indicating the operator
# has documented the source / rationale for the data change).
#
# Reads CLAUDE_FILE_PATHS from the env (colon- or newline-separated).
# Exit 0 = allow, exit 2 = block with message on stderr.

set -euo pipefail

paths="${CLAUDE_FILE_PATHS:-}"
[ -z "$paths" ] && exit 0

# Check if any target path is under data/
data_touched=0
while IFS= read -r p; do
  case "$p" in
    */src/hvac_mcp/data/*.json|*/src/hvac_mcp/data/*.yaml|*/src/hvac_mcp/data/*.yml|\
    src/hvac_mcp/data/*.json|src/hvac_mcp/data/*.yaml|src/hvac_mcp/data/*.yml)
      data_touched=1
      ;;
  esac
done <<< "$(echo "$paths" | tr ':' '\n')"

[ "$data_touched" -eq 0 ] && exit 0

# Data file is being edited — require lessons.md in working tree dirty set.
cd "$(dirname "$0")/../.."
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if ! git status --porcelain 2>/dev/null | grep -qE 'tasks/lessons\.md'; then
    cat >&2 <<'MSG'
[guard_data] Blocked: editing src/hvac_mcp/data/* requires a matching
source citation or correction note in tasks/lessons.md in the same
working-tree change. Update tasks/lessons.md first, then retry.

Override: touch tasks/lessons.md if the data change is purely cosmetic.
MSG
    exit 2
  fi
fi
exit 0
