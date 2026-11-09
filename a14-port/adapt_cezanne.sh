#!/usr/bin/env bash
# cezanne · 从 MTK 移植包适配出可刷的 boot.img
#
# 背景 (2026-11-09 实测结论):
#   K40G 移植包 (MT6893) 自带完整 MIO Kitchen 工具链和 GSI ramdisk,
#   但 **设备树在 dtbo.img 分区里, 不在 boot.img 里**。
#   → boot.img 里只需要换 **内核 + ramdisk**, 头部沿用 cezanne 原厂。
#   → dtbo.img **必须用 cezanne 原厂** (MT6889 ≠ MT6893, 硬件全不同)。
#
# 本脚本做三件事:
#   1. 从移植包 boot.img 里拆出 kernel 与 ramdisk
#   2. 用 cezanne 原厂 boot.img 的头部重新组装 boot.img
#   3. 打印需要人工确认的清单 (哪些文件是 MT6893 专用的, 必须换掉)
#
# 用法:
#   bash adapt_cezanne.sh <移植包boot.img> <cezanne原厂boot.img> <输出目录>
#
# 例:
#   bash adapt_cezanne.sh \
#     "/d/123pan/Downloads/K40G_Android16_OS3.0.311.0-Fiagelia-26.9.19/no-root/boot.img" \
#     "../firmware/.../images/boot.img" \
#     "./out_boot"

set -euo pipefail

SRC_BOOT="${1:?用法: adapt_cezanne.sh <移植包boot.img> <原厂boot.img> <输出目录>}"
ORIG_BOOT="${2:?用法: adapt_cezanne.sh <移植包boot.img> <原厂boot.img> <输出目录>}"
OUT_DIR="${3:?用法: adapt_cezanne.sh <移植包boot.img> <原厂boot.img> <输出目录>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { echo -e "\033[1;36m[adapt]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[FAIL]\033[0m $*" >&2; exit 1; }

[ -f "$SRC_BOOT" ]  || die "找不到移植包 boot.img: $SRC_BOOT"
[ -f "$ORIG_BOOT" ] || die "找不到原厂 boot.img: $ORIG_BOOT"
mkdir -p "$OUT_DIR"

command -v python3 >/dev/null 2>&1 || die "需要 python3"

# ─────────────────────────────────────────────────────────────
# 1. 拆分移植包 boot.img
# ─────────────────────────────────────────────────────────────
log "[1/4] 拆分移植包 boot.img"
# 只取摘要, 完整输出重定向到文件 (避免输出过长)
python3 "$SCRIPT_DIR/ramdisk_tools.py" "$SRC_BOOT" --export "$OUT_DIR/rd_src" \
  > "$OUT_DIR/ramdisk_report.txt" 2>&1 || { cat "$OUT_DIR/ramdisk_report.txt"; die "解析移植包 boot.img 失败"; }
grep -E "内核:|ramdisk 条目" "$OUT_DIR/ramdisk_report.txt" | sed 's/^/    /' || true

# 拆出内核与 ramdisk 原始字节
python3 - "$SRC_BOOT" "$OUT_DIR" << 'PYEOF'
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
from ramdisk_tools import load_boot, gunzip_all

boot, outdir = sys.argv[1], sys.argv[2]
with open(boot, "rb") as f:
    data = f.read()
(k_size, _ka, r_size, _ra, s_size, _sa, _ta, page, hdr) = struct.unpack_from("<9I", data, 8)
off = 8 + 36
if hdr >= 1: off += 4
off += 16 + 512 + 32 + 1024
pa = lambda x: (x + page - 1) // page * page
k_off = pa(off); r_off = k_off + pa(k_size)

# 内核段: 原样保存 (可能是 gzip 的 Image.gz)
kern_raw = data[k_off:k_off + k_size]
open(os.path.join(outdir, "kernel.img"), "wb").write(kern_raw)

# ramdisk 段: 原样保存
rd_raw = data[r_off:r_off + r_size]
open(os.path.join(outdir, "ramdisk.img"), "wb").write(rd_raw)

print("  kernel.img  : %d 字节" % len(kern_raw))
print("  ramdisk.img : %d 字节" % len(rd_raw))
PYEOF

# 内核可能是 gzip, 打包时内核和 ramdisk 都要保持原样(不能解压再压, 会改变格式)
# 但 Makefile 那边我们是 Image.gz -> 保持 gzip
ok "已拆分 kernel.img / ramdisk.img"

# ─────────────────────────────────────────────────────────────
# 2. 组装 cezanne boot.img
# ─────────────────────────────────────────────────────────────
log "[2/4] 组装 cezanne boot.img (头部沿用原厂)"
python3 "$SCRIPT_DIR/make_boot.py" \
  --orig  "$ORIG_BOOT" \
  --kernel "$OUT_DIR/kernel.img" \
  --ramdisk "$OUT_DIR/ramdisk.img" \
  --out   "$OUT_DIR/boot_cezanne.img" \
  || die "组装失败"

ok "生成 $OUT_DIR/boot_cezanne.img"

# ─────────────────────────────────────────────────────────────
# 3. 校验
# ─────────────────────────────────────────────────────────────
log "[3/4] 校验产物"
python3 "$SCRIPT_DIR/ramdisk_tools.py" "$OUT_DIR/boot_cezanne.img" \
  > "$OUT_DIR/verify_report.txt" 2>&1 || { cat "$OUT_DIR/verify_report.txt"; die "生成的 boot.img 无法解析"; }
grep -E "cmdline|内核:|ramdisk 条目" "$OUT_DIR/verify_report.txt" | sed 's/^/    /' || true
ok "boot.img 可解析"

# ─────────────────────────────────────────────────────────────
# 4. 人工确认清单
# ─────────────────────────────────────────────────────────────
cat << EOF

==================================================
  ★ 刷入前必须人工确认的清单
==================================================

【绝对不能用的】来自移植包 (MT6893) 的文件:
  ✗ dtbo.img      设备树 —— MT6893 ≠ MT6889, 屏幕/指纹/充电/相机全废
  ✗ vendor (在 super.img 里)  —— 硬件专属, 相机/马达调校全不对
  ✗ cust.img      运营商配置
  ✗ vbmeta*.img   若原厂能启动, 保留原厂 vbmeta 并 --disable-verity

【必须保留 cezanne 原厂的】:
  ✓ dtbo.img      (96272 字节, model=CEZANNE, compatible=mediatek,MT6889)
  ✓ super.img     里的 vendor / product / odm / system_ext
  ✓ boot.img      里原厂的头部参数 (cmdline / page_size / header_version)

【ramdisk 里 MT6893 专用、需换成原厂的】:
  ⚠ ueventd.mt6893.rc        → 用 cezanne 原厂版本
  ⚠ init.recovery.mt6893.rc → 用 cezanne 原厂版本
  ⚠ init.tuna.rc            → 里面有 omap/HSMMC 路径 (高通残留), MTK 上无效
  ⚠ first_stage_ramdisk/fstab.mt6893 → 换成 fstab.mt68xx / fstab.emmc

【内核选择】:
  · 移植包的 4.14 Oblivion 内核 vermagic = -Oblivion-V4.0-DEV-ColorOS
    → 与原厂 .ko 不匹配, **加载不了原厂 vendor 的 10 个 .ko**
    → 除非同时用移植包自带的 vendor (但那是 MT6893 的, 不能用)
  · 所以本脚本产出的 boot.img 只在"配合移植包 vendor"时成立
  · **正解是用自编内核** (vermagic = 4.14.186-perf-00252-g2f26b5917fd6)

==================================================

EOF
