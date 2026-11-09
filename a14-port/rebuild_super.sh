#!/usr/bin/env bash
# cezanne · 重组 super.img (A-only 布局)
#
# 目标:
#   用 **移植包里的 system/product/system_ext (通用用户空间)**
#   配 **cezanne 原厂的 vendor (硬件专属)**
#   组装成一个 cezanne 能刷的 A-only super.img
#
# 为什么必须这么做 (2026-11-10 实测):
#   · K40G 移植包的 vendor 是 MT6893 的 —— 相机/指纹/充电/马达全不对, 不能用
#   · cezanne 原厂 vendor 是 MT6889 专属调校好的 —— 必须保留
#   · system/product/system_ext 是 Android 用户空间 —— 与 SoC 无关, 可以用移植包的
#
# 已验证的布局 (lpdumps 输出):
#   cezanne 原厂 (A-only, metadata 10.0, 2 slot):
#     product  741912 sectors  readonly
#     vendor  2769416 sectors  readonly
#     system  9172896 sectors  readonly
#     First sector: 2048   Total: 9126805504 字节
#
#   K40G 移植包 (A/B 虚拟, metadata 10.2, 3 slot):
#     product_a / system_a / system_ext_a / vendor_a  (只有 _a 有数据)
#
# 用法:
#   bash rebuild_super.sh <移植包super.img> <原厂super.img> <工作目录>
#
# 例:
#   bash rebuild_super.sh \
#     "D:/123pan/Downloads/K40G_OS4.0.5.0_A17.zip"  # 或已解压的 super.img \
#     "D:/cezanne-work/firmware/.../images/super.img" \
#     "D:/cezanne-work/rebuild"

set -euo pipefail

SRC_SUPER="${1:?用法: rebuild_super.sh <移植包super.img> <原厂super.img> <工作目录>}"
ORIG_SUPER="${2:?用法: rebuild_super.sh <移植包super.img> <原厂super.img> <工作目录>}"
WORK="${3:?用法: rebuild_super.sh <移植包super.img> <原厂super.img> <工作目录>}"

TOOLS="${TOOLS:-D:/cezanne-work/lp_tools}"
LPMK="$TOOLS/lpmake.exe"
LPUNPK="$TOOLS/lpunpack.exe"
LPDUMP="$TOOLS/lpdumps.exe"
SIMG2IMG="$TOOLS/simg2img.exe"
IMG2SIMG="$TOOLS/img2simg.exe"

log()  { echo -e "\033[1;36m[super]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[FAIL]\033[0m $*" >&2; exit 1; }

for t in "$LPMK" "$LPUNPK" "$LPDUMP" "$SIMG2IMG" "$IMG2SIMG"; do
  [ -f "$t" ] || die "缺少工具: $t"
done

mkdir -p "$WORK"
cd "$WORK"

# ─────────────────────────────────────────────────────────────
# 1. 准备 raw super (lpunpack/lpmake 只认 raw)
#
# ★ 磁盘纪律: 绝不能同时保留两份 8.5GB 的 raw super —— D 盘会被撑爆。
#   策略: 需要时转换, 用完立刻删。
#   只保留最���的"原厂 vendor.img"(1.4GB), 其他的中间文件随用随删。
# ─────────────────────────────────────────────────────────────
log "[1/6] 准备 raw super"

is_sparse() {
  local magic
  magic=$(head -c 4 "$1" | od -An -tx1 | tr -d ' \n')
  [ "$magic" = "3aff26ed" ]
}

# 转成 raw (若已是 raw 则软链/复制)
to_raw() {
  # $1 = 输入, $2 = 输出
  local in="$1" out="$2"
  if is_sparse "$in"; then
    log "  $(basename "$in") 是 sparse -> 转 raw"
    "$SIMG2IMG" "$in" "$out" || die "simg2img 失败: $in"
  else
    log "  $(basename "$in") 已是 raw"
    cp "$in" "$out"
  fi
}

# ─────────────────────────────────────────────────────────────
# 2. 读原厂分区表 (A-only 布局的黄金标准)
# ─────────────────────────────────────────────────────────────
log "[2/6] 读取原厂分区表"
ORIG_RAW="$WORK/orig_super.img"
to_raw "$ORIG_SUPER" "$ORIG_RAW"
"$LPDUMP" -s 0 "$ORIG_RAW" > "$WORK/orig_layout.txt" 2>&1 || die "lpdumps 原厂失败"
grep -E "Name:|linear super|First sector|Metadata version" "$WORK/orig_layout.txt" | sed 's/^/    /'

# ─────────────────────────────────────────────────────────────
# 3. 拆原厂 (只取 vendor —— 唯一必须原厂的分区)
# ─────────────────────────────────────────────────────────────
log "[3/6] 拆原厂分区 (只取 vendor)"
mkdir -p "$WORK/orig_parts"
VENDOR="$WORK/orig_parts/vendor.img"
if [ ! -f "$VENDOR" ]; then
  ( cd "$WORK/orig_parts" && "$LPUNPK" -p vendor "$ORIG_RAW" . ) >/dev/null 2>&1 || \
    ( cd "$WORK/orig_parts" && "$LPUNPK" "$ORIG_RAW" . ) >/dev/null 2>&1 || true
fi
[ -f "$VENDOR" ] || die "原厂 vendor 没拆出来 (期望 $VENDOR)"
ok "原厂 vendor: $(stat -c%s "$VENDOR") 字节"

# 原厂 product 也要 (它是"用户空间"的一部分, 但我们保持原厂以减少变量)
PROD_ORIG="$WORK/orig_parts/product.img"
[ -f "$PROD_ORIG" ] || {
  ( cd "$WORK/orig_parts" && "$LPUNPK" -p product "$ORIG_RAW" . ) >/dev/null 2>&1 || true
}

# ★ 原厂 raw 用完即可删 —— 8.5GB 留着太占地方
rm -f "$ORIG_RAW"
ok "已删除原厂 raw 中间文件 (省 8.5GB)"

# ─────────────────────────────────────────────────────────────
# 4. 拆移植包 (拿 system / product / system_ext)
# ─────────────────────────────────────────────────────────────
log "[4/6] 拆移植包分区 (取 system/product/system_ext)"
mkdir -p "$WORK/src_parts"
SRC_RAW="$WORK/src_super.img"
to_raw "$SRC_SUPER" "$SRC_RAW"

pick() {
  # $1 = 基础名 (system), 在 src_parts 里找 system_a.img / system.img
  local base="$1" f
  for f in "$WORK/src_parts/${base}_a.img" "$WORK/src_parts/${base}.img"; do
    [ -f "$f" ] && { echo "$f"; return 0; }
  done
  return 1
}

# 先按名字挑 (如果之前拆过)
SYS_SRC="$(pick system)"       || true
PROD_SRC="$(pick product)"     || true
SEXT_SRC="$(pick system_ext)"  || true

# 没有就现拆 (只拆需要的, 避免一次性占 6GB+)
unpack_if_needed() {
  local part="$1"
  [ -n "$(pick "$part")" ] && return 0
  log "  拆 $part ..."
  ( cd "$WORK/src_parts" && "$LPUNPK" -p "${part}_a" "$SRC_RAW" . ) >/dev/null 2>&1 || true
  [ -f "$WORK/src_parts/${part}_a.img" ] && return 0
  ( cd "$WORK/src_parts" && "$LPUNPK" -p "$part" "$SRC_RAW" . ) >/dev/null 2>&1 || true
  [ -f "$WORK/src_parts/${part}.img" ] && return 0
  return 1
}

unpack_if_needed system     || die "移植包里没有 system"
unpack_if_needed product    || warn "移植包里没有 product"
unpack_if_needed system_ext || warn "移植包里没有 system_ext"

SYS_SRC="$(pick system)"
PROD_SRC="$(pick product)"     || PROD_SRC="$PROD_ORIG"
SEXT_SRC="$(pick system_ext)"  || SEXT_SRC=""

[ -n "$SYS_SRC" ] || die "system 没拿到"
[ -n "$SEXT_SRC" ] && ok "system_ext: $(basename "$SEXT_SRC")" || warn "移植包无 system_ext"

# 移植包的分区是 EROFS, cezanne 原厂的是 ext4 —— 格式不同也没关系,
# 因为我们只是把 vendor 原样搬过去, 不改任何分区内容。

# 记录移植包里的分区大小 (sector) —— lpmake 需要
"$LPDUMP" -s 0 "$SRC_RAW" > "$WORK/src_layout.txt" 2>&1 || true
# ★ 移植包的 raw 用完即可删 —— 8.5GB 留着太占地方
rm -f "$SRC_RAW"
ok "已删除移植包 raw 中间文件 (省 8.5GB)"

# ─────────────────────────────────────────────────────────────
# 5. 组装 A-only 的新 super
# ─────────────────────────────────────────────────────────────
log "[5/6] lpmake 组装新的 A-only super"

# 原厂布局: product(RO) + vendor(RO) + system(RO), First sector 2048
# 我们要保留 product 和 vendor 的原厂版本, 只把 system 换成移植包的。
#
# ★ 关键: 移植包还带 system_ext (A14+ 需要), 而原厂没有。
#   -> 必须把 system_ext 也加进去, 并给 group 留够空间。

# 先看原厂的 group / 大小参数
SUPER_SIZE=$(grep -o "Size: [0-9]*" "$WORK/orig_layout.txt" | head -1 | awk '{print $2}')
SUPER_SIZE=${SUPER_SIZE:-9126805504}
GROUP_SIZE=$(grep -o "Maximum size: [0-9]*" "$WORK/orig_layout.txt" | tail -1 | awk '{print $3}')
GROUP_SIZE=${GROUP_SIZE:-9124708352}
log "  super 总大小 = $SUPER_SIZE"
log "  group main 最大 = $GROUP_SIZE"

# 分区大小 (sector -> 字节, 512/扇区)
#
# ★ 关键: **用移植包自己的分区大小**, 不是原厂的!
#   移植包的 system 是 ColorOS A17 (更大), 原厂的 system 是 MIUI A12 (更小)。
#   用原厂大小装移植包的内容 -> lpmake 会截断, 开机炸。
sect_of() {
  # $1 = 布局文件, $2 = 分区名
  # lpdumps 输出格式:
  #     Name: system_a
  #     Group: ...
  #     Attributes: none
  #     Extents:
  #       0 .. 1917223 linear super 7163904      <-- 大小在这行 (第 5 行)
  grep -A5 "Name: $2\$" "$1" 2>/dev/null \
    | grep -oE "[0-9]+ linear super" | awk '{print $1}' | head -1
}

prod_sz="$(sect_of "$WORK/src_layout.txt" product_a)"
[ -z "$prod_sz" ] && prod_sz="$(sect_of "$WORK/orig_layout.txt" product)"
vend_sz="$(sect_of "$WORK/orig_layout.txt" vendor)"
sys_sz="$(sect_of "$WORK/src_layout.txt" system_a)"
[ -z "$sys_sz" ] && sys_sz="$(sect_of "$WORK/orig_layout.txt" system)"
sext_sz="$(sect_of "$WORK/src_layout.txt" system_ext_a)"

[ -n "$prod_sz" ] && [ -n "$vend_sz" ] && [ -n "$sys_sz" ] || die "解析不出分区大小"

log "  product = $prod_sz sectors (移植包)"
log "  vendor  = $vend_sz sectors (原厂)"
log "  system  = $sys_sz sectors (移植包)"
[ -n "$sext_sz" ] && log "  system_ext = $sext_sz sectors (移植包)"

# 组装参数: 用原厂的 product/vendor + 移植包的 system (+system_ext)
# group 名沿用原厂的 "main"
# ── lpmake 参数 (语法来自 lpmake --help):
#     -p <name>:<attributes>:<size>[:group]   属性只能是 none / readonly
#     -i <PARTITION>=<FILE>                    分区内容用 -i 单独传
#     -g <GROUP>:<SIZE>
#     -d <device-size>  -m <metadata-size>  -s <metadata-slots>  -n <super-name>
#     -S                                          直接输出 sparse (fastboot 用)
#
# ★ 不用 --group-name/--partition-name/--size/--image 这些形式 —— 那个版本不支持。
LPMK_ARGS=(
  --device-size "$SUPER_SIZE"
  --metadata-size 65536
  --metadata-slots 2
  --super-name super
  --group "main:$GROUP_SIZE"
  --partition "product:readonly:$((prod_sz * 512)):main"
  --image "product=$PROD_SRC"
  --partition "vendor:readonly:$((vend_sz * 512)):main"
  --image "vendor=$VENDOR"
  --partition "system:readonly:$((sys_sz * 512)):main"
  --image "system=$SYS_SRC"
)
if [ -n "$SEXT_SRC" ] && [ -n "$sext_sz" ]; then
  LPMK_ARGS+=(--partition "system_ext:readonly:$((sext_sz * 512)):main")
  LPMK_ARGS+=(--image "system_ext=$SEXT_SRC")
  ok "加入 system_ext ($sext_sz sectors)"
fi

log "  lpmake 参数:"
printf '    %s\n' "${LPMK_ARGS[@]}" | sed 's/^/    /'

OUT_SUPER="$WORK/super_new.img"
rm -f "$OUT_SUPER"
"$LPMK" "${LPMK_ARGS[@]}" --output "$OUT_SUPER" || die "lpmake 失败"

ok "生成 $OUT_SUPER ($(stat -c%s "$OUT_SUPER") 字节)"

# ─────────────────────────────────────────────────────────────
# 6. 转 sparse 并验证
# ─────────────────────────────────────────────────────────────
log "[6/6] 转 sparse + 验证"
FINAL="$WORK/super_cezanne.img"
rm -f "$FINAL"
"$IMG2SIMG" "$OUT_SUPER" "$FINAL" || die "img2simg 失败"
ok "最终产物: $FINAL ($(stat -c%s "$FINAL") 字节)"

echo
echo "=== 验证新 super ==="
"$LPDUMP" -s 0 "$OUT_SUPER" 2>&1 | head -40

cat << EOF

==================================================
  完成
==================================================

产物: $FINAL

刷入步骤 (fastboot, A-only):
  fastboot flash super $FINAL

★ 前提 (缺一不可):
  1. 内核必须带 EROFS 驱动 (移植包的 system 是 EROFS 格式!)
     -> 用 Actions 产出的自编内核 (版本串必须 4.14.186-perf-00252-g2f26b5917fd6)
  2. vendor 必须用 cezanne 原厂的 (本脚本已自动处理)
  3. dtbo.img 必须用 cezanne 原厂的 (MT6889 != MT6893)
  4. boot.img 的 ramdisk 里 ueventd.mt6893.rc / init.recovery.mt6893.rc
     要换成 cezanne 原厂版本

⚠️ 本脚本只是"重组 super", 不含内核/dtbo/ramdisk 的适配。
   完整流程见 a14-port/现状与下一步.md

==================================================

EOF
