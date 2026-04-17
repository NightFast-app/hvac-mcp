#!/usr/bin/env bash
# PreToolUse hook — protect the license store schema.
#
# Any edit to src/hvac_mcp/storage.py that touches schema code (CREATE TABLE,
# CREATE INDEX, ALTER, new column references) MUST be paired with a
# docs/migrations/*.md file in the same working tree change. This forces the
# operator to think about existing rows on the live Fly volume before
# breaking them.
#
# Reads CLAUDE_FILE_PATHS from the env (colon- or newline-separated).
# Exit 0 = allow, exit 2 = block with message on stderr.

set -euo pipefail

paths="${CLAUDE_FILE_PATHS:-}"
[ -z "$paths" ] && exit 0

# Only care about edits targeting storage.py. Handle both absolute paths
# (/Volumes/.../src/hvac_mcp/storage.py) and working-dir-relative paths
# (src/hvac_mcp/storage.py).
storage_touched=0
while IFS= read -r p; do
  case "$p" in
    */src/hvac_mcp/storage.py|src/hvac_mcp/storage.py) storage_touched=1 ;;
  esac
done <<< "$(echo "$paths" | tr ':' '\n')"

[ "$storage_touched" -eq 0 ] && exit 0

cd "$(dirname "$0")/../.."
# If not in a git repo, skip (dev environments / worktrees without .git)
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# Look at current diff + untracked to detect a paired migration file.
migration_present=0
if git status --porcelain 2>/dev/null | grep -qE 'docs/migrations/.+\.md$'; then
  migration_present=1
fi

if [ "$migration_present" -eq 0 ]; then
  cat >&2 <<'MSG'
[guard_storage] Blocked: editing src/hvac_mcp/storage.py requires a paired
migration note in docs/migrations/YYYY-MM-DD-<short-slug>.md in the same
working-tree change.

Why: the live production volume on Fly.io has real customer licenses in
/data/licenses.db. A schema change without a thought-through migration
path will break production. Even "just adding a column" needs to consider
whether existing rows need a default or backfill.

Create the migration note with:
  mkdir -p docs/migrations
  date=$(date +%Y-%m-%d)
  echo "# Migration: <what changed>" > docs/migrations/${date}-<slug>.md

The note should document: what columns/indexes changed, what the schema
looked like before, what the deploy-time migration step is (backfill,
alter, re-index), and what the rollback is if it goes sideways.
MSG
  exit 2
fi

exit 0
