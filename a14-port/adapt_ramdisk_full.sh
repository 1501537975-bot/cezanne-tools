#!/usr/bin/env bash
# cezanne · ramdisk 完整适配流程 (一步到位)
#
# 流程:
#   1. 从原厂 vendor 分区 (ext4) 提取 MT6885 专用的 .rc / fstab 文件
#   2. 解开移植包的 ramdisk, 做 5 项适配, 重打包成 cpio+gzip
#   3. 闭环验证 (打包 -> 读回 -> 检查关键文件与 fstab fs 类型)
#
# 用法:
#   bash adapt_ramdisk_full.sh <移植包boot.img> <原厂boot.img> <原厂vendor.img> <工作目录>

set -uo pipefail

SRC_BOOT="${1:?用法: adapt_ramdisk_full.sh <移植包boot.img> <原厂boot.img> <原厂vendor.img> <工作目录>}"
ORIG_BOOT="${2:?用法: adapt_ramdisk_full.sh <移植包boot.img> <原厂boot.img> <原厂vendor.img> <工作目录>}"
VENDOR_IMG="${3:?用法: adapt_ramdisk_full.sh <移植包boot.img> <原厂boot.img> <原厂vendor.img> <工作目录>}"
WORK="${4:?用法: adapt_ramdisk_full.sh <移植包boot.img> <原厂boot.img> <原厂vendor.img> <工作目录>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { echo -e "\033[1;36m[rd]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[FAIL]\033[0m $*" >&2; exit 1; }

[ -f "$SRC_BOOT" ]   || die "移植包 boot.img 不存在: $SRC_BOOT"
[ -f "$ORIG_BOOT" ]  || die "原厂 boot.img 不存在: $ORIG_BOOT"
[ -f "$VENDOR_IMG" ] || die "原厂 vendor.img 不存在: $VENDOR_IMG"

mkdir -p "$WORK"

# ── 1. 提取原厂 vendor 里的 MT6885 rc 文件 ──────────────────
log "[1/3] 从原厂 vendor 提取 MT6885 的 rc 文件"
STOCK_RC="$WORK/stock_rc"
mkdir -p "$STOCK_RC"
python3 "$SCRIPT_DIR/extract_mt6885_rc.py" "$VENDOR_IMG" "$STOCK_RC" \
  | tail -3
# vendor 根目录下的 .rc (ueventd.rc 等) 不在 etc/init 里, 单独补
python3 - "$VENDOR_IMG" "$STOCK_RC" << 'PYEOF' || warn "根目录 rc 提取失败"
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
from ext4 import Ext4
fs = Ext4(sys.argv[1])
dest = sys.argv[2]
for name, ino, isdir, size in fs.listdir(2):
    if name.endswith(".rc") and not isdir:
        with open(os.path.join(dest, name), "wb") as f:
            f.write(fs.read_file(ino))
PYEOF
ok "原厂 rc 文件: $(ls -1 "$STOCK_RC" | wc -l) 个"

# ── 2. 适配 + 重打包 ──────────────────────────────────────────
log "[2/3] 适配 ramdisk"
rm -rf "$WORK/src" "$WORK/stock"
STOCK_RC="$STOCK_RC" bash "$SCRIPT_DIR/adapt_ramdisk.sh" "$SRC_BOOT" "$ORIG_BOOT" "$WORK" \
  || die "ramdisk 适配失败"

log "     重打包 cpio"
python3 "$SCRIPT_DIR/repack_ramdisk.py" "$WORK/src" "$WORK/ramdisk.cpio" \
  --gzip "$WORK/ramdisk.img" || die "重打包失败"

# ── 3. 闭环验证 ──────────────────────────────────────────────
log "[3/3] 闭环验证"
python3 - "$WORK/ramdisk.img" << 'PYEOF' || die "闭环验证失败"
import gzip
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
from ramdisk_tools import cpio_mkbootfs

blob = gzip.decompress(open(sys.argv[1], "rb").read())
ents = cpio_mkbootfs(blob)
names = {n for n, _, _ in ents}
print("    读回 %d 个条目" % len(ents))

must = [
    "init",
    "avb/q-gsi.avbpubkey",
    "avb/r-gsi.avbpubkey",
    "avb/s-gsi.avbpubkey",
    "verity_key",
    "first_stage_ramdisk/fstab.emmc",
    "first_stage_ramdisk/fstab.mt6893",
    "ueventd.mt6893.rc",
    "init.recovery.mt6893.rc",
]
missing = [m for m in must if m not in names]
if missing:
    print("    [FAIL] 缺: %s" % missing)
    sys.exit(1)
for m in must:
    print("    [OK] %s" % m)

print()
print("    fstab 的 fs 类型:")
bad = 0
for n, sz, do in ents:
    if n.endswith("fstab.emmc") or n.endswith("fstab.mt6893") or n.endswith("recovery.fstab"):
        for line in blob[do:do + sz].decode("utf-8", "replace").splitlines():
            m = re.match(r"^(system|vendor|product|system_ext)\s+\S+\s+(\S+)", line)
            if m:
                part, fs = m.group(1), m.group(2)
                want = "ext4" if part == "vendor" else "erofs"
                flag = "OK" if fs == want else "!! 应为 %s" % want
                if fs != want:
                    bad += 1
                print("      %-12s %-8s %s" % (part, fs, flag))
if bad:
    print("    [FAIL] %d 处 fs 类型不对" % bad)
    sys.exit(1)
print()
print("    [OK] 全部校验通过")
PYEOF

ok "完成"
echo
echo "产物: $WORK/ramdisk.img"
