#!/usr/bin/env bash
# PostToolUse hook — for Python files that were just written/edited:
#   1. Auto-fix with ruff (non-blocking)
#   2. Run ONLY the tests belonging to the affected module (fast feedback)
#
# Non-blocking: reports issues to stderr but always exits 0 so the turn
# continues; operator sees fixable issues + failing tests in the terminal
# immediately.

set -eu

paths="${CLAUDE_FILE_PATHS:-}"
[ -z "$paths" ] && exit 0

cd "$(dirname "$0")/../.."

py_files=()
while IFS= read -r p; do
  case "$p" in
    *.py) [ -f "$p" ] && py_files+=("$p") ;;
  esac
done <<< "$(echo "$paths" | tr ':' '\n')"

[ "${#py_files[@]}" -eq 0 ] && exit 0

# 1. Ruff auto-fix + report any remaining
uv run --no-project --with-editable . --with ruff ruff check --fix "${py_files[@]}" 2>&1 | tail -20 || true

# 2. Work out which test files correspond to the changed src files and
#    run just those. Source layout convention:
#      src/hvac_mcp/<module>.py              -> tests/test_<module>.py
#      src/hvac_mcp/tools/<name>.py          -> tests/test_<name>.py
#      src/hvac_mcp/utils/<name>.py          -> tests/test_<name>.py (if it exists)
#    Edits inside the tests/ tree run that test file directly.
targeted_tests=()
for p in "${py_files[@]}"; do
  rel="${p#./}"
  case "$rel" in
    tests/test_*.py)
      [ -f "$rel" ] && targeted_tests+=("$rel") ;;
    src/hvac_mcp/*.py|src/hvac_mcp/tools/*.py|src/hvac_mcp/utils/*.py)
      base=$(basename "$rel" .py)
      # A few special cases where the test file name differs from the module:
      #   storage.py + webhook.py + licensing.py all live in tests/test_storage_and_webhook.py
      case "$base" in
        storage|webhook|licensing) candidate="tests/test_storage_and_webhook.py" ;;
        __init__|server) candidate="tests/test_server_boots.py" ;;
        diagnostics) candidate="tests/test_diagnostics.py" ;;
        *) candidate="tests/test_${base}.py" ;;
      esac
      [ -f "$candidate" ] && targeted_tests+=("$candidate") ;;
  esac
done

# Deduplicate + bail if nothing to run
if [ "${#targeted_tests[@]}" -eq 0 ]; then
  exit 0
fi
unique_tests=$(printf '%s\n' "${targeted_tests[@]}" | sort -u)

# Run with -q for compact output; capture only the summary tail so we don't
# flood the terminal. Failures still surface (pytest prints FAILED lines
# above the summary).
echo "[auto_ruff] running affected tests: $(echo "$unique_tests" | tr '\n' ' ')" >&2
# shellcheck disable=SC2086
uv run --no-project --with-editable . \
  --with pytest --with pytest-asyncio --with pyyaml --with stripe \
  pytest -q $unique_tests 2>&1 | tail -15 || true

exit 0
