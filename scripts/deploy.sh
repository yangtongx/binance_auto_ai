#!/usr/bin/env bash
# 在 Linux 服务器上一键部署（拉代码、同步 .env、启动 Docker）。
#
# 首次（仓库尚不存在）：
#   git clone https://gitee.com/yang-huidong/binance_auto_ai.git /opt/binance_auto_ai
#   cd /opt/binance_auto_ai
#   # 写入 secrets/ 密钥后：
#   bash scripts/deploy.sh
#
# 日常更新：
#   cd /opt/binance_auto_ai && bash scripts/deploy.sh
#   cd /opt/binance_auto_ai && bash scripts/deploy.sh feat/coinglass-selection-exit
#   bash scripts/deploy.sh --no-smoke master
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH=""
RUN_SMOKE=1
REPO_URL="${REPO_URL:-https://gitee.com/yang-huidong/binance_auto_ai.git}"

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \?//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --no-smoke) RUN_SMOKE=0; shift ;;
    -*) echo "unknown option: $1" >&2; usage 1 ;;
    *)
      if [[ -z "$BRANCH" ]]; then
        BRANCH="$1"
      else
        echo "unexpected arg: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$BRANCH" ]]; then
  BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ -z "$BRANCH" || "$BRANCH" == "HEAD" ]]; then
    BRANCH=master
  fi
fi

if [[ ! -d "$ROOT/.git" ]]; then
  echo "ERROR: $ROOT is not a git repo." >&2
  echo "Clone first: git clone $REPO_URL /opt/binance_auto_ai" >&2
  exit 1
fi

echo "==> git fetch & checkout $BRANCH"
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "==> sync .env from deploy/server.env"
if [[ ! -f deploy/server.env ]]; then
  echo "missing deploy/server.env — run git pull or check branch" >&2
  exit 1
fi
cp -f deploy/server.env .env
chmod 600 .env 2>/dev/null || true

echo "==> ensure secrets/ and state/"
mkdir -p secrets state
for f in binance_api_key binance_api_secret openai_api_key telegram_bot_token telegram_chat_id coinglass_api_key; do
  if [[ ! -f "secrets/$f" ]]; then
    : >"secrets/$f"
  fi
done
chmod 700 secrets 2>/dev/null || true
chmod 600 secrets/* 2>/dev/null || true

if [[ ! -s secrets/binance_api_key || ! -s secrets/binance_api_secret ]]; then
  echo "WARN: secrets/binance_api_* empty — 实盘前请写入密钥（当前 DRY_RUN 可安全试跑）"
fi
if [[ ! -s secrets/coinglass_api_key ]]; then
  echo "NOTE: secrets/coinglass_api_key empty — CoinGlass 功能自动关闭"
fi
if [[ ! -s secrets/telegram_bot_token || ! -s secrets/telegram_chat_id ]]; then
  echo "NOTE: Telegram secrets empty — 通知关闭；可运行: bash scripts/install-telegram-secrets.sh -i"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found" >&2
  exit 1
fi

COMPOSE="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  COMPOSE="docker-compose"
fi

echo "==> $COMPOSE up -d --build"
$COMPOSE up -d --build

echo "==> container status"
$COMPOSE ps

if [[ "$RUN_SMOKE" == "1" ]]; then
  echo "==> smoke test"
  $COMPOSE run --rm bot python -m binance_auto_ai.cli --smoke
fi

echo "==> recent logs"
$COMPOSE logs --tail 30 bot

echo ""
echo "OK: deployed branch=$BRANCH at $ROOT"
echo "  日志: cd $ROOT && $COMPOSE logs -f bot"
echo "  面板: 本机 curl http://127.0.0.1:8080/health  （仅绑定 127.0.0.1）"
