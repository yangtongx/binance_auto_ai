#!/bin/sh
# Load Docker Compose file secrets (root-only 0600) into env, then drop to user bot.
set -e

_load_one() {
  env_name="$1"
  secret_path="$2"
  eval "current=\${$env_name:-}"
  if [ -n "$current" ]; then
    return 0
  fi
  if [ -f "$secret_path" ] && [ -r "$secret_path" ]; then
    val=$(tr -d '\r\n' < "$secret_path")
    export "$env_name=$val"
  fi
}

if [ "$(id -u)" = "0" ]; then
  _load_one BINANCE_API_KEY /run/secrets/binance_api_key
  _load_one BINANCE_API_SECRET /run/secrets/binance_api_secret
  _load_one OPENAI_API_KEY /run/secrets/openai_api_key
  _load_one TELEGRAM_BOT_TOKEN /run/secrets/telegram_bot_token
  _load_one TELEGRAM_CHAT_ID /run/secrets/telegram_chat_id
  exec gosu bot:bot "$@"
fi

exec "$@"
