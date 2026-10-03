#!/bin/sh
# Install (or remove with --uninstall) the nightly export as a macOS launchd user agent.
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.memsi.export"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/.memsi/logs"
HOUR="${MEMSI_EXPORT_HOUR:-2}"
MINUTE="${MEMSI_EXPORT_MINUTE:-30}"
UID_="$(id -u)"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>$HERE/scripts/nightly-export.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$LOG_DIR/export.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/export.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string><key>HOME</key><string>$HOME</string></dict>
</dict>
</plist>
PLIST
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_" "$PLIST"
echo "installed $LABEL: runs daily at $(printf '%02d:%02d' "$HOUR" "$MINUTE"), log at $LOG_DIR/export.log"
launchctl print "gui/$UID_/$LABEL" 2>/dev/null | grep -E "state|program|run interval|last exit" | sed 's/^/  /' || true
