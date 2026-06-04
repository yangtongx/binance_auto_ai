#!/usr/bin/env bash
# 修复 .env 中 RANK_BY 与 RANK_WEIGHTS 数量不一致（从 deploy/server.env 同步这两行）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/deploy/server.env"
DEST="$ROOT/.env"

if [[ ! -f "$SRC" ]]; then
  echo "missing $SRC — run: git pull" >&2
  exit 1
fi

if [[ ! -f "$DEST" ]]; then
  cp -f "$SRC" "$DEST"
  chmod 600 "$DEST" 2>/dev/null || true
  echo "OK: created $DEST from deploy/server.env"
  exit 0
fi

rank_by="$(grep -E '^SYMBOL_CANDIDATES_RANK_BY=' "$SRC" | tail -1)"
rank_w="$(grep -E '^SYMBOL_CANDIDATES_RANK_WEIGHTS=' "$SRC" | tail -1)"
if [[ -z "$rank_by" || -z "$rank_w" ]]; then
  echo "missing RANK_BY/WEIGHTS in $SRC" >&2
  exit 1
fi

tmp="$(mktemp)"
awk -v rb="$rank_by" -v rw="$rank_w" '
  /^SYMBOL_CANDIDATES_RANK_BY=/ { print rb; next }
  /^SYMBOL_CANDIDATES_RANK_WEIGHTS=/ { print rw; next }
  { print }
' "$DEST" >"$tmp"
if ! grep -qE '^SYMBOL_CANDIDATES_RANK_BY=' "$tmp"; then
  echo "$rank_by" >>"$tmp"
fi
if ! grep -qE '^SYMBOL_CANDIDATES_RANK_WEIGHTS=' "$tmp"; then
  echo "$rank_w" >>"$tmp"
fi
mv -f "$tmp" "$DEST"
chmod 600 "$DEST" 2>/dev/null || true

echo "OK: synced rank env in $DEST"
echo "  $rank_by"
echo "  $rank_w"
echo "Next: docker compose up -d --build   # 拉过 6054318+ 代码后重建镜像"
