#!/bin/sh
# Nightly export of the memsi store to a JSON file outside the project.
# Installed as a launchd user agent by scripts/install-launchd.sh. Safe to run by hand.
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${MEMSI_BACKUP_DIR:-$HOME/.memsi/backups}"
KEEP="${MEMSI_BACKUP_KEEP:-30}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y-%m-%d)"
OUT="$BACKUP_DIR/memsi-$STAMP.json"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] export -> $OUT"
"$HERE/uvw" run --directory "$HERE" memctl export "$OUT"
# prune: keep the newest $KEEP files
ls -1t "$BACKUP_DIR"/memsi-*.json 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  echo "prune $old"; rm -f "$old"
done
