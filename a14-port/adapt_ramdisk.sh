#!/usr/bin/env bash
# cezanne · 移植包 ramdisk 的 cezanne 适配
#
# 目标: 把 K40G 移植包的 GSI ramdisk 改成 cezanne 能用的版本
#
# ★ 关键差异 (2026-11-10 实测, 逐文件对比得出):
#
#   1. **fs 类型**: 移植包的 system/product/system_ext 是 EROFS,
#      而原厂 fstab 写的是 ext4 -> 必须改成 erofs, 否则挂载失败
#      ★ 新 super 里 vendor 仍是原厂 ext4 -> vendor 那行保持 ext4
#
#   2. **MT6893 专用文件**: ueventd.mt6893.rc / init.recovery.mt6893.rc
#      是 K40G (MT6893) 专属 -> 要用 cezanne (MT6885) 原厂版本替换
#
#   3. **高通残留**: init.tuna.rc 里有 omap/HSMMC 的 userdata 挂载路径
#      -> 在 MTK 上无效, 要换掉
#
#   4. **GSI 必需的 avb key**: 原厂 ramdisk 自带
#      avb/{q,r,s}-gsi.avbpubkey 和 verity_key,
#      移植包的 ramdisk 里**没有** -> 必须补上
#      (fstab 里的 avb_keys=... 引用的就是它们)
#
#   5. **fstab.mt6885**: 原厂有 (MT6885 = cezanne 的 SoC ID),
#      移植包只有 fstab.mt6893 -> 要换
#
# 用法:
#   bash adapt_ramdisk.sh <移植包boot.img> <原厂boot.img> <工作目录>
#
# 产物:
#   <工作目录>/ramdisk_cezanne.img   适配后的 ramdisk (可直接塞进 boot.img)
#   <工作目录>/rd_diff.txt           逐文件的改动报告

set -euo pipefail

SRC_BOOT="${1:?用法: adapt_ramdisk.sh <移植包boot.img> <原厂boot.img> <工作目录>}"
ORIG_BOOT="${2:?用法: adapt_ramdisk.sh <移植包boot.img> <原厂boot.img> <工作目录>}"
WORK="${3:?用法: adapt_ramdisk.sh <移植包boot.img> <原厂boot.img> <工作目录>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { echo -e "\033[1;36m[rd]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[FAIL]\033[0m $*" >&2; exit 1; }

mkdir -p "$WORK/src" "$WORK/stock"
cd "$WORK"

# ─────────────────────────────────────────────────────────────
# 1. 拆两个 ramdisk
# ─────────────────────────────────────────────────────────────
log "[1/5] 拆解两个 ramdisk"

# ★ 不要删掉 $WORK 整个目录 —— stock_rc (原厂 vendor 的 rc 文件) 是外部准备的,
#   删了就没法替换 MT6893 专用文件了。只清理 src/stock 两个子目录。
rm -rf "$WORK/src" "$WORK/stock"

dump() {
  # $1 = boot.img, $2 = 输出目录
  # ★ 必须保留目录结构! first_stage_ramdisk/fstab.emmc 不能展平成
  #   first_stage_ramdisk_fstab.emmc —— 展平后 cpio 重打包会丢掉层级,
  #   开机时 first_stage_mount 找不到 fstab。
  python3 - "$1" "$2" << 'PYEOF'
import os, sys
sys.path.insert(0, os.environ["RAMDISK_TOOLS_DIR"])
from ramdisk_tools import load_boot, cpio_mkbootfs

boot, dest = sys.argv[1], sys.argv[2]
os.makedirs(dest, exist_ok=True)
kern, rd, cmdline, name = load_boot(boot)
ents = cpio_mkbootfs(rd)

# ★ cpio 里同一个名字可能既是目录条目又是 0 字节条目
#   -> 先把**所有目录**建出来, 再写文件, 否则 makedirs 会 FileExistsError
names = []
for nm, sz, do in ents:
    # ★ 必须跳过 TRAILER!!! —— 它是 cpio 的结束标记, 不是真实文件。
    #   留着的话重打包时会混到中间, 导致解析器提前结束。
    if nm in (".", "..", "") or nm == "TRAILER!!!":
        continue
    names.append((nm, sz, do))

for nm, sz, do in names:
    rel = nm.lstrip("/").replace("/", os.sep)
    out = os.path.join(dest, rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)

n = 0
for nm, sz, do in names:
    rel = nm.lstrip("/").replace("/", os.sep)
    out = os.path.join(dest, rel)
    if os.path.isdir(out):
        continue           # 目录条目不写文件
    with open(out, "wb") as f:
        f.write(rd[do:do + sz])
    n += 1
print("%d" % n)
PYEOF
}

export RAMDISK_TOOLS_DIR="$SCRIPT_DIR"
N_SRC=$(dump "$SRC_BOOT" "$WORK/src" | tail -1)
N_STOCK=$(dump "$ORIG_BOOT" "$WORK/stock" | tail -1)
ok "移植包 ramdisk: $N_SRC 个条目"
ok "原厂 ramdisk  : $N_STOCK 个条目"

# ★ 根目录条目名是 "." —— 不能当文件名, 删掉
rm -f "$WORK/src/." "$WORK/stock/." 2>/dev/null || true

# ─────────────────────────────────────────────────────────────
# 2. 逐文件对比
# ─────────────────────────────────────────────────────────────
log "[2/5] 对比两个 ramdisk"
REPORT="$WORK/rd_diff.txt"
{
  echo "=== 只在移植包里 (MT6893 专用, 需替换或删除) ==="
  comm -23 <(cd "$WORK/src"   && find . -type f | sed 's|^\./||' | sort) \
           <(cd "$WORK/stock" && find . -type f | sed 's|^\./||' | sort) | sed 's/^/  /'
  echo
  echo "=== 只在原厂里 (GSI 必需, 需补进移植包) ==="
  comm -13 <(cd "$WORK/src"   && find . -type f | sed 's|^\./||' | sort) \
           <(cd "$WORK/stock" && find . -type f | sed 's|^\./||' | sort) | sed 's/^/  /'
  echo
  echo "=== 两边都有但内容不同 ==="
  while IFS= read -r f; do
    [ -f "$WORK/stock/$f" ] || continue
    cmp -s "$WORK/src/$f" "$WORK/stock/$f" || echo "  $f"
  done < <(cd "$WORK/src" && find . -type f | sed 's|^\./||')
} > "$REPORT"
cat "$REPORT" | sed 's/^/    /'

# ─────────────────────────────────────────────────────────────
# 3. 补 GSI 必需的 avb key / verity_key
# ─────────────────────────────────────────────────────────────
log "[3/5] 补 GSI 必需的 avb key / verity_key"
added=0
for f in avb/q-gsi.avbpubkey avb/r-gsi.avbpubkey avb/s-gsi.avbpubkey verity_key; do
  if [ -f "$WORK/stock/$f" ] && [ ! -f "$WORK/src/$f" ]; then
    mkdir -p "$(dirname "$WORK/src/$f")"
    cp "$WORK/stock/$f" "$WORK/src/$f"
    ok "补入 $f"
    added=$((added + 1))
  fi
done
[ "$added" -gt 0 ] || warn "avb key / verity_key 无需补 (或原厂里也没有)"

# ─────────────────────────────────────────────────────────────
# 4. 替换 MT6893 专用文件 -> cezanne 原厂版本
# ─────────────────────────────────────────────────────────────
log "[4/5] 替换 MT6893 专用文件"
replaced=0

# (4a) ★ 优先用**原厂 vendor 分区**里的 MT6885 版本
#      原厂 vendor 里有 73 个 .rc + fstab.mt6885 (含 ueventd.rc 7028 字节),
#      这些是 MT6885 专属的硬件配置 —— 比 boot.img 的 ramdisk 全得多。
STOCK_RC="${STOCK_RC:-$WORK/stock_rc}"
if [ -d "$STOCK_RC" ]; then
  # ★★★ 替换规则必须**严格**:
  #   只接受 "同基名 + mt6885 后缀" 的原厂文件, 或者
  #   "ueventd.mt6893.rc" 对应 "ueventd.rc" 这一种特例。
  #   ★ 绝不能拿 ueventd.rc 去替换 fstab/init.recovery —— 那会直接弄坏启动。
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    base="${f%%mt6893*}"          # 如 "first_stage_ramdisk/fstab." / "ueventd." / "init.recovery."
    cand=""
    # 特例1: ueventd.mt6893.rc -> ueventd.rc
    if [ "$f" = "ueventd.mt6893.rc" ] && [ -f "$STOCK_RC/ueventd.rc" ]; then
      cand="ueventd.rc"
    fi
    # 特例2: <base>mt6885<后缀> -> <base>mt6885<后缀>
    if [ -z "$cand" ]; then
      for g in $(cd "$STOCK_RC" && ls -1 2>/dev/null); do
        case "$g" in
          "${base}mt6885"*) cand="$g" ;;
        esac
      done
    fi
    if [ -n "$cand" ]; then
      cp "$STOCK_RC/$cand" "$WORK/src/$f"
      ok "$f  <-  原厂 vendor/$cand"
      replaced=$((replaced + 1))
    else
      warn "$f 在原厂 vendor 里没有对应版本, 保留移植包的"
    fi
  done < <(cd "$WORK/src" && find . -type f -name '*mt6893*' | sed 's|^\./||')
  ok "已从原厂 vendor 替换 $replaced 个 MT6893 专用文件"
else
  warn "没有 $STOCK_RC (原厂 vendor 的 rc 文件) —— MT6893 文件无法替换"
fi

# (4b) init.tuna.rc 里的高通 omap/HSMMC 挂载路径 -> 无效, 换掉
if [ -f "$WORK/src/init.tuna.rc" ] && grep -q "omap\|hsmc" "$WORK/src/init.tuna.rc" 2>/dev/null; then
  warn "init.tuna.rc 含高通 omap/HSMMC 残留 —— MTK 上无效"
  cp "$WORK/src/init.tuna.rc" "$WORK/src/init.tuna.rc.bak"
  grep -v "omap\|hsmc" "$WORK/src/init.tuna.rc.bak" > "$WORK/src/init.tuna.rc" || true
  ok "已剔除高通残留"
fi

# ─────────────────────────────────────────────────────────────
# 5. 修 fstab 的 fs 类型 (EROFS!)
# ─────────────────────────────────────────────────────────────
log "[5/5] 修 fstab 的文件系统类型"

# ★ 关键: 移植包的 system/product/system_ext 是 EROFS, vendor 是 ext4(原厂)
#   fstab 里对应的行必须改对, 否则 first_stage_mount 挂载失败 -> 卡开机
python3 - "$WORK/src" << 'PYEOF' || warn "fstab 修正失败"
import os, sys, glob
src = sys.argv[1]

# 每个分区实际的文件系统类型 (实测)
FS_TYPE = {
    "system": "erofs",
    "product": "erofs",
    "system_ext": "erofs",
    "vendor": "ext4",     # 原厂 ext4, 不改
    "odm": "erofs",
    "odm_dlkm": "erofs",
    "system_dlkm": "erofs",
    "vendor_dlkm": "ext4",
}

total = 0
for path in glob.glob(os.path.join(src, "**", "*fstab*"), recursive=True):
    if not os.path.isfile(path) or os.path.getsize(path) > 200000:
        continue
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        lines = f.readlines()
    out = []
    hit = 0
    for line in lines:
        parts = line.split()
        if len(parts) >= 3 and parts[0] in FS_TYPE:
            want = FS_TYPE[parts[0]]
            if parts[2] != want:
                line = line.replace(" %s " % parts[2], " %s " % want, 1)
                hit += 1
        out.append(line)
    if hit:
        with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.writelines(out)
        rel = os.path.relpath(path, src)
        print("  %s: 改了 %d 处" % (rel, hit))
        total += hit
print("  合计 %d 处" % total)
PYEOF

# 汇总校验
echo
echo "=== 修正后的 fstab 关键行 ==="
while IFS= read -r f; do
  echo "--- $f"
  grep -E "^system |^vendor |^product |^system_ext |^odm " "$WORK/src/$f" 2>/dev/null | sed 's/^/    /' || true
done < <(cd "$WORK/src" && find . -type f -name '*fstab*' | sed 's|^\./||')

exit 0

cat << EOF

==================================================
  完成
==================================================

产物目录: $WORK/src  (适配后的 ramdisk 文件)
改动报告: $REPORT

★ 下一步: 需要把这些文件重新打包成 cpio -> ramdisk.img -> 塞进 boot.img
   (make_boot.py 可以组装 boot.img, 但 cpio 重打包需要额外一步)

★ 完整刷机流程见 a14-port/现状与下一步.md

==================================================

EOF
