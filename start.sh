#!/usr/bin/env bash
# Start the Grok Bot Telegram bridge in the background.
# Reads settings from the environment, from .env next to this script, and from
# a 0600 secrets file (GROKBOT_SECRETS_FILE, default
# /workspace/.secrets/grokbot-telegram.env) so values survive a reboot that
# clears the process environment. Never echo those values.
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
# Load persisted secrets if present (survive a reboot that clears the process
# environment). Already-set, non-empty environment values win over the file
# (a fresh secret-request card is in the environment; the file is the reboot
# fallback). The file should be 0600 in a 0700 directory; never print it.
SECRETS_FILE="${GROKBOT_SECRETS_FILE:-/workspace/.secrets/grokbot-telegram.env}"
if [ -f "$SECRETS_FILE" ]; then
  _mode="$(stat -c '%a' "$SECRETS_FILE")"
  _owner="$(stat -c '%u' "$SECRETS_FILE")"
  if [ "$((0$_mode & 044))" -ne 0 ]; then
    echo "warning: secrets file is group- or other-readable; run chmod 600 on it"
  fi
  if [ "$((0$_mode & 022))" -ne 0 ]; then
    echo "warning: secrets file is group- or other-writable; run chmod 600 on it"
  fi
  if [ "$_owner" != "$(id -u)" ]; then
    echo "warning: secrets file is not owned by the current user"
  fi
  # Save non-empty current values, source the file, then restore them.
  _SECRETS_KEEP_NAMES="TELEGRAM_BOT_TOKEN GROKBOT_WEBHOOK_URL GROKBOT_WEBHOOK_KEY GROKBOT_MEMBER_LLM_API_KEY"
  for _n in $_SECRETS_KEEP_NAMES; do
    if [ -n "${!_n:-}" ]; then
      printf -v "_SECRETS_KEEP_${_n}" '%s' "${!_n}"
    else
      unset "_SECRETS_KEEP_${_n}" 2>/dev/null || true
    fi
  done
  set -a
  # shellcheck disable=SC1090
  . "$SECRETS_FILE"
  set +a
  for _n in $_SECRETS_KEEP_NAMES; do
    _k="_SECRETS_KEEP_${_n}"
    if [ -n "${!_k:-}" ]; then
      export "$_n=${!_k}"
    fi
    unset "$_k"
  done
  unset _n _k _mode _owner _SECRETS_KEEP_NAMES
fi
PID="$DATA_DIR/relay.pid"
LOG="$DATA_DIR/relay.log"
. ./pidutil.sh
relay_start_lock
if [ "${1:-}" = "--pairing-only" ] || [ "${GROKBOT_PAIRING_ONLY:-0}" = 1 ]; then
  export GROKBOT_PAIRING_ONLY=1
  : > "$DATA_DIR/pairing-only"
  chmod 600 "$DATA_DIR/pairing-only"
else
  export GROKBOT_PAIRING_ONLY=0
  rm -f "$DATA_DIR/pairing-only"
fi
[ -n "${TELEGRAM_BOT_TOKEN:-}" ] || { echo "TELEGRAM_BOT_TOKEN not set"; exit 1; }
if [ -z "${GROKBOT_WEBHOOK_URL:-}" ] || [ -z "${GROKBOT_WEBHOOK_KEY:-}" ]; then
  if [ "$GROKBOT_PAIRING_ONLY" != 1 ]; then
    echo "GROKBOT_WEBHOOK_URL / GROKBOT_WEBHOOK_KEY not set. Use --pairing-only to run pairing without forwarding."; exit 1
  fi
fi
if relay_is_running "$PID"; then echo "already running (pid $pid)"; exit 0; fi
python3 relay.py --check || exit 1
setsid nohup ./supervise.sh 9>&- >/dev/null 2>&1 < /dev/null &
pid=$!
for _ in {1..100}; do
  started="$(relay_starttime "$pid")" || started=""
  if [ -n "$started" ]; then
    printf '%s\n%s\n' "$pid" "$started" > "$PID"
    chmod 600 "$PID"
    if relay_is_running "$PID"; then
      echo "started pid $pid; log: $LOG"
      exit 0
    fi
  fi
  sleep 0.02
done
rm -f "$PID"
echo "supervisor failed to start"
exit 1
