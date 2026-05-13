#!/usr/bin/env bash
# Example: retrain TorchScript every 4 hours (cron / systemd).
#
# Crontab (UTC), e.g. at minute 5 past 0,4,8,12,16,20:
#   5 */4 * * * /path/to/futures_llm_bot/examples/cron_retrain_4h.sh >> /var/log/ml_retrain.log 2>&1
#
# Adjust paths and env; the bot reads ML_MODEL_PATH — write via temp then mv for atomic replace.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=/dev/null
[[ -f "${VENV:-$ROOT/.venv}/bin/activate" ]] && source "${VENV:-$ROOT/.venv}/bin/activate"

export SYMBOL="${SYMBOL:-BTC/USDT:USDT}"
export TIMEFRAME="${TIMEFRAME:-4h}"
export BARS="${BARS:-20000}"
export PAGE_SIZE="${PAGE_SIZE:-1500}"
export ARCH="${ARCH:-lstm}"
export WINDOW="${WINDOW:-48}"
export EPOCHS="${EPOCHS:-25}"
export # The bot checks ML_MODEL_PATH mtime every ML_HOT_RELOAD_INTERVAL_SEC and reloads when it
# changes (atomic cp/mv recommended). Main futures bot process usually does not need restart.
MODEL_OUT="${MODEL_OUT:-$ROOT/artifacts/ml_latest.pt}"
export TMP_OUT="${TMP_OUT:-${MODEL_OUT}.tmp.$$}"

pip install -q -e ".[ml-torch]"

python examples/train_ml_torch.py \
  --fetch --no-testnet \
  --symbol "$SYMBOL" \
  --timeframe "$TIMEFRAME" \
  --limit "$BARS" \
  --page-size "$PAGE_SIZE" \
  --arch "$ARCH" \
  --window "$WINDOW" \
  --epochs "$EPOCHS" \
  --out "$TMP_OUT"

mv -f "$TMP_OUT" "$MODEL_OUT"
echo "$(date -Iseconds) ok → $MODEL_OUT"
