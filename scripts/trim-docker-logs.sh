#!/usr/bin/env bash
# 裁剪 binance-auto-ai 容器日志，仅保留近 2 小时（默认）。
# 用法：
#   bash scripts/trim-docker-logs.sh
#   LOG_KEEP_HOURS=3 bash scripts/trim-docker-logs.sh
# 定时（每 30 分钟）：
#   */30 * * * * cd /opt/binance_auto_ai && bash scripts/trim-docker-logs.sh >> /var/log/binance_auto_ai-trim.log 2>&1
#
# 说明：需能访问 Docker 日志文件（通常 root 或 docker 组）；会短暂 stop/start 容器以安全替换日志文件。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="${CONTAINER_NAME:-binance-auto-ai}"
HOURS="${LOG_KEEP_HOURS:-2}"
SERVICE="${COMPOSE_SERVICE:-bot}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found" >&2
  exit 1
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "container not found: $CONTAINER" >&2
  exit 1
fi

LOG_PATH="$(docker inspect --format='{{.LogPath}}' "$CONTAINER")"
if [[ -z "$LOG_PATH" || ! -f "$LOG_PATH" ]]; then
  echo "log file missing: $LOG_PATH" >&2
  exit 1
fi

BEFORE_BYTES="$(wc -c <"$LOG_PATH" | tr -d ' ')"
TMP_FILTERED="$(mktemp)"
TMP_NEW="$(mktemp)"
trap 'rm -f "$TMP_FILTERED" "$TMP_NEW"' EXIT

python3 "$ROOT/scripts/trim_docker_logs.py" "$LOG_PATH" "$TMP_FILTERED" --hours "$HOURS"
AFTER_LINES="$(wc -l <"$TMP_FILTERED" | tr -d ' ')"

# 替换日志文件前短暂停容器，避免写入中被截断
cd "$ROOT"
echo "stopping $SERVICE ($CONTAINER) to rotate logs..."
docker compose stop "$SERVICE"

install_log() {
  if [[ -w "$LOG_PATH" ]]; then
    cp -f "$TMP_FILTERED" "$LOG_PATH"
  elif command -v sudo >/dev/null 2>&1; then
    sudo cp -f "$TMP_FILTERED" "$LOG_PATH"
  else
    echo "cannot write $LOG_PATH (try sudo or docker group)" >&2
    docker compose start "$SERVICE"
    exit 1
  fi
}

install_log
AFTER_BYTES="$(wc -c <"$LOG_PATH" | tr -d ' ')"

echo "starting $SERVICE..."
docker compose start "$SERVICE"

echo "OK: $CONTAINER log ${BEFORE_BYTES}B -> ${AFTER_BYTES}B (~${AFTER_LINES} lines, keep ${HOURS}h)"
