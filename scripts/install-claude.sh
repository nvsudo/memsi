#!/bin/sh
# Connect memsi to Claude Code and Claude Desktop. Idempotent; safe to re-run.
#   - Claude Code: user-scope MCP server "memsi", SessionStart hook, skill symlink
#   - Claude Desktop: mcpServers.memsi in claude_desktop_config.json (restart Desktop afterwards)
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$HERE/scripts/session-start.sh"
SETTINGS="$HOME/.claude/settings.json"
DESKTOP="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

echo "memsi at $HERE"

# 1. Claude Code MCP server (user scope)
if command -v claude >/dev/null 2>&1; then
  claude mcp remove --scope user memsi >/dev/null 2>&1 || true
  claude mcp add --scope user --env MEMSI_APP=claude-code -- memsi "$HERE/uvw" run --directory "$HERE" memsi-mcp >/dev/null
  if grep -q '"memsi"' "$HOME/.claude.json" 2>/dev/null; then echo "  claude code: MCP server registered"; else echo "  claude code: WARNING registration did not persist (sandbox?)"; fi
else
  echo "  claude code: 'claude' CLI not found, skipping MCP registration"
fi

# 2. Skill symlink
mkdir -p "$HOME/.claude/skills"
ln -sfn "$HERE/skills/memory" "$HOME/.claude/skills/memory"
echo "  claude code: skill linked at ~/.claude/skills/memory"

# 3. SessionStart hook merged into ~/.claude/settings.json
mkdir -p "$HOME/.claude"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
tmp="$(mktemp)"
jq --arg cmd "$HOOK" '
  .hooks = (.hooks // {}) |
  .hooks.SessionStart = ((.hooks.SessionStart // []) | map(select(((.hooks // [])[0].command // "") != $cmd))) +
    [{"matcher":"startup|resume|clear|compact","hooks":[{"type":"command","command":$cmd,"timeout":20,"statusMessage":"Loading memory from memsi…"}]}]
' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
echo "  claude code: SessionStart hook set in ~/.claude/settings.json"

# 4. Claude Desktop MCP config
mkdir -p "$(dirname "$DESKTOP")"
python3 - "$DESKTOP" "$HERE" <<'PY'
import json, sys, pathlib
path, here = pathlib.Path(sys.argv[1]), sys.argv[2]
cfg = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else {}
cfg.setdefault("mcpServers", {})["memsi"] = {
    "command": f"{here}/uvw",
    "args": ["run", "--directory", here, "memsi-mcp"],
    "env": {"MEMSI_APP": "claude-desktop", "HOME": str(pathlib.Path.home())},
}
path.write_text(json.dumps(cfg, indent=2) + "\n")
print("  claude desktop: mcpServers.memsi written (restart Claude Desktop)")
PY
echo "done. New Claude Code sessions get the digest; Claude Desktop needs a restart."
