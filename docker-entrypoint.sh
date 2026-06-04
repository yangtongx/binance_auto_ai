#!/bin/sh
# 从 Docker Compose 密钥文件（root 只读 0600）加载环境变量，再降权为 bot 用户
set -e

_load_one() {
  env_name="$1"
  secret_path="$2"
  # env_file 常注入 COINGLASS_API_KEY=（空字符串）；仅当已有非空值时才跳过 secret
  eval "current=\${$env_name:-}"
  current=$(printf '%s' "$current" | tr -d '\r\n')
  if [ -n "$current" ]; then
    return 0
  fi
  if [ -f "$secret_path" ] && [ -r "$secret_path" ]; then
    val=$(tr -d '\r\n' < "$secret_path")
    if [ -n "$val" ]; then
      export "$env_name=$val"
    fi
  fi
}

_log_secret_hint() {
  name="$1"
  path="$2"
  if [ ! -f "$path" ]; then
    echo "WARN: Docker secret missing: $path ($name)" >&2
    return
  fi
  size=$(wc -c < "$path" | tr -d ' ')
  if [ "$size" -eq 0 ]; then
    echo "WARN: Docker secret empty (0 bytes): $path ($name) — write host secrets/$(basename "$path") then recreate container" >&2
  fi
}

if [ "$(id -u)" = "0" ]; then
  _load_one BINANCE_API_KEY /run/secrets/binance_api_key
  _load_one BINANCE_API_SECRET /run/secrets/binance_api_secret
  _load_one OPENAI_API_KEY /run/secrets/openai_api_key
  _load_one TELEGRAM_BOT_TOKEN /run/secrets/telegram_bot_token
  _load_one TELEGRAM_CHAT_ID /run/secrets/telegram_chat_id
  _load_one COINGLASS_API_KEY /run/secrets/coinglass_api_key
  _log_secret_hint COINGLASS_API_KEY /run/secrets/coinglass_api_key
  if [ -n "${COINGLASS_API_KEY:-}" ]; then
    echo "INFO: COINGLASS_API_KEY loaded from secret (${#COINGLASS_API_KEY} chars)" >&2
  fi
  # 宿主机 bind mount 的 ./state 常为 root 创建，需让 bot(1000) 可写
  if [ -d /app/state ]; then
    chown -R bot:bot /app/state 2>/dev/null || true
    chmod -R u+rwX /app/state 2>/dev/null || true
  fi
  exec gosu bot:bot "$@"
fi

exec "$@"
