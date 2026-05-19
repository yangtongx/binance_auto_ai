#!/usr/bin/env bash
# Overwrite repo .env from deploy/server.env (no editor). Safe to re-run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/deploy/server.env"
DEST="$ROOT/.env"

if [[ ! -f "$SRC" ]]; then
  echo "missing $SRC — run: git pull" >&2
  exit 1
fi

cp -f "$SRC" "$DEST"
chmod 600 "$DEST" 2>/dev/null || true

echo "OK: $DEST <= deploy/server.env"

if [[ -s "$ROOT/secrets/binance_api_key" && -s "$ROOT/secrets/binance_api_secret" ]]; then
  echo "Binance keys: Docker secrets/ present — leave BINANCE_* empty in .env"
elif grep -qE '^BINANCE_API_KEY=.' "$DEST" 2>/dev/null; then
  echo "Binance keys: set in .env"
else
  echo "WARN: no secrets/ and no BINANCE_API_KEY in .env — add keys before live trading"
  echo "  echo -n 'YOUR_KEY' > secrets/binance_api_key"
  echo "  echo -n 'YOUR_SECRET' > secrets/binance_api_secret"
  echo "  chmod 600 secrets/binance_api_*"
fi

echo "Next: docker compose run --rm bot python -m futures_llm_bot.cli --smoke"
echo "      docker compose up -d --build"
