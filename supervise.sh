#!/usr/bin/env bash
# Keeps relay.py running: restarts it a few seconds after any crash or exit.
cd "$(dirname "$0")"
if [ -z "${GROKBOT_DATA_DIR:-}" ] && [ -f .env ]; then
  GROKBOT_DATA_DIR="$(sed -n 's/^\(export \)\{0,1\}GROKBOT_DATA_DIR=//p' .env | tail -n1 | tr -d "\"'")"
fi
DATA_DIR="${GROKBOT_DATA_DIR:-$(pwd)}"
mkdir -p "$DATA_DIR"
LOG="$DATA_DIR/relay.log"
trap 'kill "$child" 2>/dev/null; exit 0' TERM INT
while true; do
  python3 -u relay.py >> "$LOG" 2>&1 &
  child=$!
  wait "$child"
  echo "$(date '+%F %T') supervisor: relay exited (code $?); restarting in 5s" >> "$LOG"
  sleep 5
done
