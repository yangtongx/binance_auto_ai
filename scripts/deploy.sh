#!/usr/bin/env bash
# 在 Linux 服务器上一键部署（可选安装 Docker 等依赖 → 拉代码 → 构建镜像 → 启动容器）。
#
# ── 全新云主机（无任何依赖）────────────────────────────────────────────
#   curl -fsSL https://gitee.com/yang-huidong/binance_auto_ai/raw/master/scripts/bootstrap-server.sh | sudo bash
#
# ── 已有 git，首次 clone 后 ────────────────────────────────────────────
#   git clone https://gitee.com/yang-huidong/binance_auto_ai.git /opt/binance_auto_ai
#   cd /opt/binance_auto_ai
#   sudo bash scripts/install-prerequisites.sh   # 装 Docker / git / python3
#   # 配置 secrets/ 后：
#   bash scripts/deploy.sh
#
# ── 日常更新 ───────────────────────────────────────────────────────────
#   cd /opt/binance_auto_ai && bash scripts/deploy.sh
#   bash scripts/deploy.sh master
#   bash scripts/deploy.sh --no-smoke
#
# 说明：ccxt、pydantic、requests 等 Python 包在 Docker 镜像构建时安装（见 Dockerfile），
#       宿主机只需 Docker；python3 用于 verify_binance_keys.py 等辅助脚本。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH=""
RUN_SMOKE=1
SKIP_INSTALL=0
REPO_URL="${REPO_URL:-https://gitee.com/yang-huidong/binance_auto_ai.git}"

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \?//'
  echo ""
  echo "Options:"
  echo "  --skip-install   跳过 Docker/系统依赖检查（bootstrap 已装过时）"
  echo "  --no-smoke       跳过容器内 smoke 测试"
  echo "  -h, --help       显示帮助"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --no-smoke) RUN_SMOKE=0; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
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

ensure_prerequisites() {
  if [[ "$SKIP_INSTALL" == "1" ]]; then
    return 0
  fi

  local need_install=0
  if ! command -v git >/dev/null 2>&1; then
    need_install=1
  fi
  if ! command -v docker >/dev/null 2>&1; then
    need_install=1
  elif ! docker info >/dev/null 2>&1; then
    need_install=1
  fi
  if [[ "$need_install" == "0" ]] && docker compose version >/dev/null 2>&1; then
    echo "==> 系统依赖 OK（git + docker + compose）"
    return 0
  fi
  if [[ "$need_install" == "0" ]] && command -v docker-compose >/dev/null 2>&1; then
    echo "==> 系统依赖 OK（git + docker + docker-compose）"
    return 0
  fi

  local installer="$ROOT/scripts/install-prerequisites.sh"
  if [[ ! -f "$installer" ]]; then
    echo "ERROR: 缺少 $installer，请先 git pull" >&2
    exit 1
  fi

  echo "==> 检测到缺少 Docker 或基础工具，安装系统依赖..."
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    bash "$installer"
  elif command -v sudo >/dev/null 2>&1; then
    sudo bash "$installer"
  else
    echo "ERROR: 需要 root 安装 Docker。请运行: sudo bash scripts/install-prerequisites.sh" >&2
    exit 1
  fi
}

if [[ ! -d "$ROOT/.git" ]]; then
  echo "ERROR: $ROOT 不是 git 仓库。" >&2
  echo "全新主机请运行: sudo bash scripts/bootstrap-server.sh" >&2
  echo "或: git clone $REPO_URL /opt/binance_auto_ai && cd /opt/binance_auto_ai && bash scripts/deploy.sh" >&2
  exit 1
fi

ensure_prerequisites

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
if chown -R 1000:1000 state 2>/dev/null; then
  :
elif [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  chown -R 1000:1000 state
else
  echo "NOTE: 无法 chown state/（非 root）；若容器报 state 权限错误，请 sudo chown -R 1000:1000 state"
fi
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
  echo "NOTE: Telegram secrets empty — 可运行: bash scripts/install-telegram-secrets.sh -i"
fi

COMPOSE="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  COMPOSE="docker-compose"
fi

echo "==> $COMPOSE up -d --build  （镜像内 pip 安装 Python 依赖，含 coinglass/requests）"
$COMPOSE up -d --build

echo "==> container status"
$COMPOSE ps

if [[ "$RUN_SMOKE" == "1" ]]; then
  echo "==> smoke test（容器内 Python）"
  $COMPOSE run --rm bot python -m binance_auto_ai.cli --smoke
fi

echo "==> recent logs"
$COMPOSE logs --tail 30 bot

echo ""
echo "OK: deployed branch=$BRANCH at $ROOT"
echo "  日志: cd $ROOT && $COMPOSE logs -f bot"
echo "  健康: curl -s http://127.0.0.1:8080/health"
echo "  验钥: python3 scripts/verify_binance_keys.py   # 宿主机辅助脚本（可选）"
