#!/usr/bin/env bash
# 在 Linux 宿主机安装首次部署所需系统依赖：git、curl、Docker Engine、Compose 插件、python3。
# Python 业务依赖（ccxt、pydantic 等）在 Docker 镜像内 pip 安装，宿主机 python3 仅用于辅助脚本。
#
# 支持：OpenCloudOS / CentOS / Rocky / Alma / RHEL / Fedora（dnf）、Ubuntu / Debian（apt）。
# OpenCloudOS 不能用 get.docker.com，走系统源 moby/docker 包。
#
# 用法（需 root）：
#   sudo bash scripts/install-prerequisites.sh
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "请使用 root 运行: sudo bash scripts/install-prerequisites.sh" >&2
  exit 1
fi

OS_ID=""
OS_ID_LIKE=""
OS_VERSION_ID=""

if [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  OS_ID="${ID:-}"
  OS_ID_LIKE="${ID_LIKE:-}"
  OS_VERSION_ID="${VERSION_ID:-}"
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

echo "==> 系统: ${OS_ID:-unknown} ${OS_VERSION_ID} (pkg=$PKG_MGR)"

_is_rhel_like() {
  local id="${OS_ID,,}"
  case "$id" in
    opencloudos|anolis|centos|rocky|almalinux|rhel|ol|fedora|tencentos|alinux|alios) return 0 ;;
  esac
  if [[ "${OS_ID_LIKE,,}" == *rhel* || "${OS_ID_LIKE,,}" == *fedora* ]]; then
    return 0
  fi
  [[ "$PKG_MGR" == "dnf" || "$PKG_MGR" == "yum" ]]
}

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

_dnf_or_yum() {
  if [[ "$PKG_MGR" == "dnf" ]]; then
    dnf "$@"
  else
    yum "$@"
  fi
}

install_docker_dnf() {
  echo "==> 使用系统源安装 Docker（OpenCloudOS/RHEL 系：moby/docker 包）"
  # OpenCloudOS 文档：dnf install docker / moby；需 docker > 20.10.9
  if ! _dnf_or_yum install -y docker docker-compose-plugin; then
    echo "    重试: moby + docker-compose-plugin"
    _dnf_or_yum install -y moby docker-compose-plugin || _dnf_or_yum install -y docker moby
  fi
  # 部分源只有独立 docker-compose 命令
  if ! docker compose version >/dev/null 2>&1; then
    _dnf_or_yum install -y docker-compose-plugin 2>/dev/null || \
      _dnf_or_yum install -y docker-compose 2>/dev/null || true
  fi
}

install_docker_ce_centos_repo() {
  echo "==> 回退：Docker CE 官方 CentOS 源"
  _dnf_or_yum install -y dnf-plugins-core yum-utils 2>/dev/null || true
  local repo=/etc/yum.repos.d/docker-ce.repo
  if [[ ! -f "$repo" ]]; then
    _dnf_or_yum config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
  fi
  # OpenCloudOS 9 等与 CentOS 9 兼容；旧版可设 DOCKER_CE_RELEASEVER=8
  local rv="${DOCKER_CE_RELEASEVER:-}"
  if [[ -z "$rv" ]]; then
    rv="${OS_VERSION_ID%%.*}"
    [[ -z "$rv" || "$rv" -lt 8 ]] && rv=9
  fi
  if [[ -f "$repo" ]] && grep -q '\$releasever' "$repo" 2>/dev/null; then
    sed -i "s/\$releasever/${rv}/g" "$repo" || true
  fi
  _dnf_or_yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

install_docker_apt() {
  echo "==> 安装 Docker Engine（get.docker.com）"
  curl -fsSL https://get.docker.com | sh
}

start_docker_daemon() {
  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable docker
    systemctl start docker
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "==> Docker 已安装且 daemon 可用"
    return 0
  fi

  local id="${OS_ID,,}"
  if [[ "$id" == "opencloudos" ]] || _is_rhel_like; then
    if ! install_docker_dnf; then
      install_docker_ce_centos_repo
    fi
  elif [[ "$PKG_MGR" == "apt" ]]; then
    install_docker_apt
  else
    echo "ERROR: 未识别的发行版 ${OS_ID}，请手动安装 Docker 后重试 deploy.sh" >&2
    exit 1
  fi

  start_docker_daemon

  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker 已安装但 daemon 未运行，请检查: systemctl status docker" >&2
    exit 1
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
  echo "ERROR: 未检测到 docker compose。RHEL 系可试: dnf install -y docker-compose-plugin" >&2
  exit 1
}

install_base_packages
install_docker
verify_compose

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
