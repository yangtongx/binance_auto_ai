#!/usr/bin/env bash
# 在 Linux 宿主机安装首次部署所需系统依赖：git、curl、Docker Engine、Compose 插件、python3。
# Python 业务依赖（ccxt、pydantic 等）在 Docker 镜像内 pip 安装，宿主机 python3 仅用于辅助脚本。
#
# 用法（需 root）：
#   sudo bash scripts/install-prerequisites.sh
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请使用 root 运行: sudo bash scripts/install-prerequisites.sh" >&2
  exit 1
fi

PKG_MGR=""
if command -v apt-get >/dev/null 2>&1; then
  PKG_MGR=apt
elif command -v dnf >/dev/null 2>&1; then
  PKG_MGR=dnf
elif command -v yum >/dev/null 2>&1; then
  PKG_MGR=yum
else
  echo "ERROR: 不支持的发行版（需要 apt、dnf 或 yum）" >&2
  exit 1
fi

echo "==> 包管理器: $PKG_MGR"

install_base_packages() {
  echo "==> 安装基础工具: git curl ca-certificates python3"
  case "$PKG_MGR" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y git curl ca-certificates python3 python3-venv
      ;;
    dnf)
      dnf install -y git curl ca-certificates python3
      ;;
    yum)
      yum install -y git curl ca-certificates python3
      ;;
  esac
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "==> Docker 已安装且 daemon 可用"
    return 0
  fi

  echo "==> 安装 Docker Engine（官方 get.docker.com 脚本）"
  curl -fsSL https://get.docker.com | sh

  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker
    systemctl start docker
  fi
}

verify_compose() {
  if docker compose version >/dev/null 2>&1; then
    echo "==> Docker Compose 插件 OK: $(docker compose version)"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    echo "==> docker-compose 独立命令 OK: $(docker-compose --version)"
    return 0
  fi
  echo "ERROR: 未检测到 docker compose，请检查 Docker 安装" >&2
  exit 1
}

install_base_packages
install_docker
verify_compose

# 非 root 运维用户加入 docker 组（若存在且不是 root）
DEPLOY_USER="${SUDO_USER:-${DEPLOY_USER:-}}"
if [[ -n "$DEPLOY_USER" && "$DEPLOY_USER" != "root" ]]; then
  if getent group docker >/dev/null 2>&1; then
    usermod -aG docker "$DEPLOY_USER" 2>/dev/null || true
    echo "==> 已将用户 $DEPLOY_USER 加入 docker 组（重新登录后免 sudo docker）"
  fi
fi

echo ""
echo "OK: 系统依赖就绪"
echo "  git     $(git --version)"
echo "  python3 $(python3 --version 2>&1)"
echo "  docker  $(docker --version)"
echo "  compose $(docker compose version 2>/dev/null || docker-compose --version)"
