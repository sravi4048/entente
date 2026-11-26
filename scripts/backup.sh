#!/usr/bin/env bash
# Consistent backup of the live SQLite database.
#
# Uses SQLite's online backup API on the Fly machine, so the copy is a clean
# point-in-time snapshot even while the app is writing (a raw file copy can
# miss pages still in the WAL). Downloads it, deletes the temp copy on the
# server, and runs an integrity check locally.
#
#   scripts/backup.sh              # -> backups/entente-<UTC timestamp>.db
#   scripts/backup.sh ~/somewhere  # custom output directory
#
# Restore (stops games mid-phase; do it when nobody is playing):
#   fly ssh sftp shell -a entente-diplomacy   ->  put <file> /data/restore.db
#   fly ssh console -a entente-diplomacy -C "sh -c 'mv /data/restore.db /data/entente.db && rm -f /data/entente.db-wal /data/entente.db-shm'"
#   fly machine restart -a entente-diplomacy
set -euo pipefail

APP="${FLY_APP:-entente-diplomacy}"
FLY="${FLY:-$(command -v fly || command -v flyctl || echo "$HOME/.fly/bin/flyctl")}"
OUT_DIR="${1:-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REMOTE="/data/backup-$STAMP.db"
LOCAL="$OUT_DIR/entente-$STAMP.db"

mkdir -p "$OUT_DIR"
cleanup() { "$FLY" ssh console -a "$APP" -C "rm -f $REMOTE" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "Snapshotting /data/entente.db on $APP..."
"$FLY" ssh console -a "$APP" -C "python -c \"import sqlite3; s=sqlite3.connect('/data/entente.db'); d=sqlite3.connect('$REMOTE'); s.backup(d); d.close(); s.close()\"" >/dev/null

echo "Downloading..."
"$FLY" ssh sftp get "$REMOTE" "$LOCAL" -a "$APP" >/dev/null

python3 - "$LOCAL" <<'EOF'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
ok = db.execute("pragma integrity_check").fetchone()[0]
counts = {t: db.execute(f"select count(*) from {t}").fetchone()[0] for t in ("users", "games", "messages")}
if ok != "ok":
    sys.exit(f"Integrity check FAILED: {ok}")
print("Integrity: ok |", ", ".join(f"{k}: {v}" for k, v in counts.items()))
EOF
echo "Saved $LOCAL ($(du -h "$LOCAL" | cut -f1))"
