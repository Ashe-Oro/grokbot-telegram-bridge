#!/usr/bin/env bash
# Sourced after cd to the project directory.
RELAY_CODE_DIR="$(pwd -P)"
relay_starttime() {
  local line rest
  IFS= read -r line < "/proc/$1/stat" 2>/dev/null || return 1
  rest="${line##*) }"
  local fields=( $rest )
  [ "${fields[0]:-}" != Z ] || return 1
  printf '%s\n' "${fields[19]:-}"
}
relay_is_running() {
  local file="$1" saved interpreter
  local args=()
  [ -f "$file" ] || return 1
  { IFS= read -r pid; IFS= read -r saved; } < "$file" || return 1
  [[ "$pid" =~ ^[1-9][0-9]*$ && "$saved" =~ ^[0-9]+$ ]] || return 1
  [ "$(relay_starttime "$pid")" = "$saved" ] || return 1
  [ "$(readlink "/proc/$pid/cwd")" = "$RELAY_CODE_DIR" ] || return 1
  mapfile -d '' -t args < "/proc/$pid/cmdline" || return 1
  interpreter="${args[0]:-}"
  [ "${interpreter##*/}" = bash ] || return 1
  case "${args[1]:-}" in
    "$RELAY_CODE_DIR/supervise.sh"|./supervise.sh) ;;
    *) return 1 ;;
  esac
  [ "$(relay_starttime "$pid")" = "$saved" ]
}
relay_start_lock() {
  mkdir -p "$DATA_DIR"
  exec 9> "$DATA_DIR/relay.start.lock"
  chmod 600 "$DATA_DIR/relay.start.lock"
  flock -x 9
}
