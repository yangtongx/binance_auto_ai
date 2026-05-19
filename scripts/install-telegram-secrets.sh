#!/usr/bin/env bash
# Write secrets/telegram_bot_token and secrets/telegram_chat_id on the server (no .env edit).
#
# Usage (pick one):
#   bash scripts/install-telegram-secrets.sh '8860025206:YOUR_TOKEN' 8539559221
#   TELEGRAM_BOT_TOKEN='...' TELEGRAM_CHAT_ID=8539559221 bash scripts/install-telegram-secrets.sh
#   bash scripts/install-telegram-secrets.sh   # reads deploy/telegram.credentials (2 lines)
#   bash scripts/install-telegram-secrets.sh -i   # interactive prompt
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS="$ROOT/secrets"
TOKEN=""
CHAT_ID=""

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \?//'
  exit "${1:-0}"
}

read_credentials_file() {
  local f="$ROOT/deploy/telegram.credentials"
  if [[ ! -f "$f" ]]; then
    return 1
  fi
  mapfile -t lines < <(grep -v '^[[:space:]]*#' "$f" | grep -v '^[[:space:]]*$' || true)
  if [[ "${#lines[@]}" -lt 2 ]]; then
    echo "need 2 lines in $f (token, chat_id)" >&2
    return 1
  fi
  TOKEN="${lines[0]//[[:space:]]/}"
  CHAT_ID="${lines[1]//[[:space:]]/}"
}

interactive() {
  echo "Paste bot token from @BotFather (input hidden), then chat_id."
  read -r -s -p "TELEGRAM_BOT_TOKEN: " TOKEN
  echo
  read -r -p "TELEGRAM_CHAT_ID [8539559221]: " CHAT_ID
  CHAT_ID="${CHAT_ID:-8539559221}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage 0
fi

if [[ "${1:-}" == "-i" ]]; then
  interactive
elif [[ -n "${1:-}" ]]; then
  TOKEN="$1"
  CHAT_ID="${2:-8539559221}"
elif [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  TOKEN="$TELEGRAM_BOT_TOKEN"
  CHAT_ID="$TELEGRAM_CHAT_ID"
else
  read_credentials_file || {
    echo "No args and no deploy/telegram.credentials." >&2
    echo "Run: bash scripts/install-telegram-secrets.sh -i" >&2
    echo " Or: bash scripts/install-telegram-secrets.sh 'TOKEN' CHAT_ID" >&2
    exit 1
  }
fi

if [[ "$TOKEN" == *PASTE* || "$TOKEN" == *REPLACE* ]]; then
  echo "Replace placeholder token with your real @BotFather token" >&2
  exit 1
fi
if [[ -z "$TOKEN" || -z "$CHAT_ID" ]]; then
  echo "token and chat_id required" >&2
  exit 1
fi

mkdir -p "$SECRETS"
printf '%s' "$TOKEN" >"$SECRETS/telegram_bot_token"
printf '%s' "$CHAT_ID" >"$SECRETS/telegram_chat_id"
chmod 600 "$SECRETS/telegram_bot_token" "$SECRETS/telegram_chat_id" 2>/dev/null || true

echo "OK: wrote secrets/telegram_bot_token and secrets/telegram_chat_id"
echo "Test: docker compose run --rm bot python -c \"
from futures_llm_bot.config import Settings
from futures_llm_bot.telegram_notify import send_telegram_message
s = Settings()
send_telegram_message(s, 'futures-llm-bot telegram OK (server)')
print('configured', bool(s.telegram_bot_token), bool(s.telegram_chat_id))
\""
echo "Then: docker compose up -d --build"
