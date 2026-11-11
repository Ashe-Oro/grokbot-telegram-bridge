#!/usr/bin/env bash
# Stop the bridge started by start.sh (the supervisor and its relay child).
cd "$(dirname "$0")"
DATA_DIR="${GROKBOT_DATA_DIR:-}"
if [ -z "$DATA_DIR" ] && [ -f .env ]; then
  DATA_DIR="$(sed -n 's/^\(export \)\{0,1\}GROKBOT_DATA_DIR=//p' .env | tail -n1 | tr -d "\"'")"
fi
PIDFILE="${DATA_DIR:-$(pwd)}/relay.pid"
if [ -f "$PIDFILE" ] && pid="$(cat "$PIDFILE")" && kill -0 "$pid" 2>/dev/null; then
  kill -TERM -- "-$pid" 2>/dev/null || kill "$pid"
  # Give the supervisor a moment to reap the relay; then stop any leftover child
  # of this supervisor only (do not pkill other relay processes on the machine).
  for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.2
  done
  pkill -P "$pid" -f 'python3 -u relay.py' 2>/dev/null || true
  echo "stopped"
else
  echo "not running"
fi
rm -f "$PIDFILE"
