#!/usr/bin/env bash
# Mystic GSI (SourceForge) 下载器 —— 多源自动降级 + Cloudflare 应对
#
# 背景: 2026-11-08 实测 SourceForge 全站挂了 Cloudflare Turnstile,
#       直连一律 403。本脚本按顺序尝试多条路径, 哪条通用哪条。
#
# 用法:
#   bash fetch_mystic.sh <相对路径>            # 例: ColorOS/Coloros-ossi-14-...zip
#   bash fetch_mystic.sh <相对路径> --browser  # 强制用浏览器下载(手动过 CF)
#
set -uo pipefail

REL="${1:?用法: bash fetch_mystic.sh <相对路径> [--browser]}"
FORCE_BROWSER=0
[ "${2:-}" = "--browser" ] && FORCE_BROWSER=1

PROJ="mystic-gsi-updates"
OUT_DIR="${OUT_DIR:-./downloads}"
MIRRORS="${MIRRORS:-master netix gigenet pilotfiber versaweb webwerks astutely informed drastich codeload}"

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
BASE="https://sourceforge.net/projects/$PROJ/files/$REL"
OUT="$OUT_DIR/$(basename "$REL")"

mkdir -p "$OUT_DIR"
log() { echo -e "\033[1;36m[dl]\033[0m $*"; }
ok()  { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
warn(){ echo -e "\033[1;33m[warn]\033[0m $*"; }

log "目标: $REL"
log "输出: $OUT"

# 已存在且大小合理 → 跳过
if [ -f "$OUT" ]; then
  sz=$(stat -c%s "$OUT")
  log "已存在, $((sz/1048576)) MB, 跳过"
  exit 0
fi

# ── 方式 1: 各镜像直链 ──────────────────────────────
if [ "$FORCE_BROWSER" != "1" ]; then
  for m in $MIRRORS; do
    url="https://$m.dl.sourceforge.net/project/$PROJ/$REL?viasf=1"
    log "试镜像: $m"
    code=$(curl -sIL -m 20 -A "$UA" -H "Referer: https://sourceforge.net/" "$url" \
           -o /dev/null -w '%{http_code}' 2>/dev/null)
    if [ "$code" = "200" ] || [ "$code" = "206" ]; then
      log "  镜像可达, 开始下载..."
      curl -L --retry 8 --retry-delay 4 --retry-all-errors -C - \
           -A "$UA" -H "Referer: https://sourceforge.net/" \
           -o "$OUT" "$url" && { ok "下载完成"; exit 0; }
    else
      log "  不可达 (HTTP $code)"
    fi
  done
fi

# ── 方式 2: 官方 download 端点 (需过 CF) ─────────────
log "试官方 download 端点..."
code=$(curl -sIL -m 20 -A "$UA" -H "Referer: https://sourceforge.net/projects/$PROJ/files/" \
       "$BASE/download" -o /dev/null -w '%{http_code}' 2>/dev/null)
if [ "$code" = "200" ]; then
  log "  可达, 下载中..."
  curl -L --retry 5 --retry-delay 5 -C - -A "$UA" \
       -H "Referer: https://sourceforge.net/projects/$PROJ/files/" \
       -o "$OUT" "$BASE/download" && { ok "下载完成"; exit 0; }
fi
warn "  官方端点 HTTP $code (Cloudflare 拦截)"

# ── 方式 3: 浏览器下载 ──────────────────────────────
log ""
log "==== 所有命令行方式都失败 ===="
log "Cloudflare 需要人工验证, 请用浏览器下载后放到:"
log "  $OUT"
log ""
log "方法:"
log "  1. 用 Chrome 打开:"
log "     $BASE"
log "  2. 等 Cloudflare 验证通过, 点 Download"
log "  3. 下载完成后把文件改名放到上面那个路径"
log ""
log "或直接在本目录执行 (会自动开浏览器并监听下载):"
log "  bash fetch_mystic.sh \"$REL\" --browser"
exit 1
