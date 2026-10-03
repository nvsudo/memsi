#!/bin/sh
# Claude Code SessionStart hook: inject the memsi digest as context.
# Receives hook JSON on stdin (cwd, session_id, source). Derives project scope from cwd.
# Never blocks a session: on any failure prints a one-line note and exits 0.
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CWD="$(python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("cwd",""))
except Exception:
    print("")' 2>/dev/null || true)"
[ -n "$CWD" ] || CWD="$PWD"
SLUG="$(basename "$CWD" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-' | sed 's/-*$//;s/^-*//')"
SCOPE="project:${SLUG:-unknown}"
OUT="$("$HERE/uvw" run --directory "$HERE" memctl recall --scope "$SCOPE" --app claude-code --budget "${MEMSI_BUDGET:-1500}" 2>/dev/null)" || OUT=""
if [ -n "$OUT" ]; then
  printf '%s\n' "$OUT"
else
  echo "(memsi: memory store unreachable at session start; use memory_recall once it is back)"
fi
exit 0
