#!/usr/bin/env bash
# 示例：每 4 小时重训 TorchScript（cron / systemd）
#
# Crontab（UTC），例如在 0、4、8、12、16、20 点的第 5 分钟：
#   5 */4 * * * /path/to/futures_llm_bot/examples/cron_retrain_4h.sh >> /var/log/ml_retrain.log 2>&1
#
# 按需调整路径与环境；机器人读取 ML_MODEL_PATH — 先写临时文件再 mv 原子替换

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
# 机器人按 ML_HOT_RELOAD_INTERVAL_SEC 检查 ML_MODEL_PATH 的 mtime，变更时热加载
# （推荐原子 cp/mv）；主交易进程通常无需重启
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
