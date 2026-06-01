#!/usr/bin/env bash
# 全新 Linux 云主机从零部署（安装 Docker 等 → clone 仓库 → 启动 bot）。
#
# 用法（OpenCloudOS / Ubuntu / CentOS 等，需 root）：
#   curl -fsSL https://gitee.com/yang-huidong/binance_auto_ai/raw/master/scripts/bootstrap-server.sh | sudo bash
#
# 或已下载仓库后：
#   sudo bash scripts/bootstrap-server.sh
#
# 环境变量（可选）：
#   REPO_URL=https://gitee.com/yang-huidong/binance_auto_ai.git
#   DEPLOY_ROOT=/opt/binance_auto_ai
#   BRANCH=master
set -euo pipefail

REPO_URL="${REPO_URL:-https://gitee.com/yang-huidong/binance_auto_ai.git}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/binance_auto_ai}"
BRANCH="${BRANCH:-master}"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请使用 root 运行: sudo bash scripts/bootstrap-server.sh" >&2
  exit 1
fi

# 若通过 curl | bash 执行，先装 git 以便 clone
if ! command -v git >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y git curl ca-certificates
  elif command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y git curl ca-certificates
  elif command -v yum >/dev/null 2>&1; then
    yum install -y git curl ca-certificates
  fi
fi

if [[ ! -d "$DEPLOY_ROOT/.git" ]]; then
  echo "==> git clone $REPO_URL -> $DEPLOY_ROOT"
  mkdir -p "$(dirname "$DEPLOY_ROOT")"
  git clone "$REPO_URL" "$DEPLOY_ROOT"
fi

echo "==> install system prerequisites"
bash "$DEPLOY_ROOT/scripts/install-prerequisites.sh"

echo "==> deploy application"
bash "$DEPLOY_ROOT/scripts/deploy.sh" --skip-install "$BRANCH"

echo ""
echo "==> 下一步（密钥，按需）"
echo "  echo -n 'BINANCE_KEY'    > $DEPLOY_ROOT/secrets/binance_api_key"
echo "  echo -n 'BINANCE_SECRET' > $DEPLOY_ROOT/secrets/binance_api_secret"
echo "  echo -n 'CG_KEY'         > $DEPLOY_ROOT/secrets/coinglass_api_key   # 可选"
echo "  cd $DEPLOY_ROOT && bash scripts/install-telegram-secrets.sh -i       # 可选"
echo "  chmod 600 $DEPLOY_ROOT/secrets/*"
echo "  cd $DEPLOY_ROOT && bash scripts/deploy.sh"
