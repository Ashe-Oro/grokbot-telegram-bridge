#!/usr/bin/env bash
# Start the Grok Bot Telegram bridge in the background.
# Reads settings from the environment, or from .env next to this script.
# Refuses to start unless the webhook URL and key are set, unless --pairing-only is given.
# Launches supervise.sh, which restarts relay.py a few seconds after any exit.
set -eu
umask 077
cd "$(dirname "$0")"
if [ -f .env ]; then
  # Existing environment variables win over .env (same rule as relay.py).
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#export }"
    key="${line%%=*}"
    case "$key" in ''|\#*|*[!A-Za-z0-9_]*) continue ;; esac
    [ "$key" = "$line" ] && continue
    if [ -z "${!key:-}" ]; then
      val="${line#*=}"
      val="${val%\"}"; val="${val#\"}"; val="${val%\'}" ; val="${val#\'}"
      export "$key=$val"
    fi
  done < .env
fi
DATA_DIR="${GROKBOT_DATA_DIR:-$(pwd)}"
mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"
PID="$DATA_DIR/relay.pid"
LOG="$DATA_DIR/relay.log"
[ -n "${TELEGRAM_BOT_TOKEN:-}" ] || { echo "TELEGRAM_BOT_TOKEN not set"; exit 1; }
if [ -z "${GROKBOT_WEBHOOK_URL:-}" ] || [ -z "${GROKBOT_WEBHOOK_KEY:-}" ]; then
  if [ "${1:-}" != "--pairing-only" ]; then
    echo "GROKBOT_WEBHOOK_URL / GROKBOT_WEBHOOK_KEY not set. Use --pairing-only to run pairing without forwarding."; exit 1
  fi
fi
if [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then echo "already running (pid $(cat "$PID"))"; exit 0; fi
python3 relay.py --check || exit 1
setsid nohup ./supervise.sh >/dev/null 2>&1 < /dev/null &
echo $! > "$PID"
chmod 600 "$PID"
echo "started pid $(cat "$PID"); log: $LOG"
