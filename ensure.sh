#!/usr/bin/env bash
# Idempotent health check: starts the bridge if it is not running.
# Safe to run from cron, a systemd timer, or a scheduled Grok Bot routine
# (for hosts where PID 1 isn't systemd and cron isn't installed).
umask 077
cd "$(dirname "$0")"
if [ -f .env ]; then
  # Existing environment variables win over .env (same rule as start.sh / relay.py).
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#export }"
    key="${line%%=*}"
    case "$key" in ''|\#*|*[!A-Za-z0-9_]*) continue ;; esac
    [ "$key" = "$line" ] && continue
    if [ -z "${!key:-}" ]; then
      val="${line#*=}"
      val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
      export "$key=$val"
    fi
  done < .env
fi
DATA_DIR="${GROKBOT_DATA_DIR:-$(pwd)}"
PID="$DATA_DIR/relay.pid"
if [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then
  echo "ok: running (pid $(cat "$PID"))"
  exit 0
fi
command -v ffmpeg >/dev/null || echo "warn: ffmpeg missing (voice notes and some media decode will fail); install it with your package manager"
ASR_PYTHON="${GROKBOT_ASR_PYTHON:-$(pwd)/.venv-asr/bin/python}"
[ -x "$ASR_PYTHON" ] || echo "warn: ASR venv missing at $ASR_PYTHON"
echo "relay not running; starting"
./start.sh
