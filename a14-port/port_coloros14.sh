#!/usr/bin/env bash
# cezanne · ColorOS 14 (A14 档) 改包脚本
#
# 目标: 把 Mystic GSI 的 ColorOS 14 移植包改成能在 cezanne 上跑的样子
#
# 关键约束（本机实测得出）:
#   · 内核 4.14.186 → A14 最低要求正好 4.14 → **不需要新内核**
#   · /proc/filesystems 无 erofs → **打包必须 ext4**
#   · vendor SDK=31 / VNDK=31 / A-only / slot-count=0
#   · /system/apex 是**文件夹** → ro.apex.updatable=false
#   · 手机已有 vndk v28~v34 全部 apex → apex 补包大多可省
#
# 依赖（Linux/WSL）:
#   MIO Kitchen  ·  UKL  ·  TFSS(a14)  ·  init.gsi.rc  ·  apex 目录
#   路径: https://sourceforge.net/projects/origin-oem-ports/files/portingessential/
#
# 用法:
#   bash port_coloros14.sh <Mystic包.zip> <底包目录>
#   例: bash port_coloros14.sh Coloros-ossi-14-...zip ../stock

set -euo pipefail

PORT_ZIP="${1:?用法: bash port_coloros14.sh <ColorOS14包.zip> [底包目录]}"
STOCK_DIR="${2:-}"

WORK="${WORK:-./coloros14_work}"
TOOLS="${TOOLS:-$HOME/portingessential}"
OUT_DIR="${OUT_DIR:-./out_coloros14}"

SRC_BRAND="${SRC_BRAND:-ColorOS}"
SRC_MODEL="${SRC_MODEL:-OP5565}"     # 从包名解析
PORT_MODEL="${PORT_MODEL:-OP5565}"
PORT_BRAND="${PORT_BRAND:-ColorOS}"
ROM_VERSION="${ROM_VERSION:-1.0.0.0}"
ROM_NAME="${ROM_NAME:-coloros14_gsi}"
BUILD_FINGERPRINT="${BUILD_FINGERPRINT:-ColorOS/OP5565/OP5565:14/UQ1A.231003.003/1705978592:user/release-keys}"

log()  { echo -e "\033[1;36m[port]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
die()  { echo -e "\033[1;31m[FAIL]\033[0m $*" >&2; exit 1; }

log "==== ColorOS 14 移植 (A14 档) ===="
log "包: $PORT_ZIP"
log "工作目录: $WORK"

[ -f "$PORT_ZIP" ] || die "找不到包: $PORT_ZIP"

# ─────────────────────────────────────────────────────────────
# 0. 工具检查
# ─────────────────────────────────────────────────────────────
log "[0/9] 检查工具"
for t in "$TOOLS/UKL" "$TOOLS/MIO" "$TOOLS/TFSS/a14"; do
  [ -e "$t" ] || die "缺少工具: $t  (从 origin-oem-ports/portingessential 下载)"
done
[ -f "$TOOLS/init.gsi.rc" ] || die "缺少 init.gsi.rc"
ok "工具就绪"

mkdir -p "$WORK" "$OUT_DIR"
cd "$WORK"

# ─────────────────────────────────────────────────────────────
# 1. 解包 ColorOS 14 源包
# ─────────────────────────────────────────────────────────────
log "[1/9] 解包 ColorOS 14 源包"
rm -rf src && mkdir src
if command -v 7z >/dev/null 2>&1; then
  7z x -y "$PORT_ZIP" -osrc >/dev/null
else
  unzip -q "$PORT_ZIP" -d src
fi
ok "解压完成"
find src -maxdepth 2 -type f | head -20 | sed 's/^/    /'

# 找 system.img
SYS_IMG=$(find src -name "system.img" -o -name "system.*.img" | head -1)
[ -n "$SYS_IMG" ] || die "包里没有 system.img"
log "    system.img: $SYS_IMG"

# 检测原包是 ext4 还是 erofs
FS_TYPE=$(python3 - "$SYS_IMG" << 'PY'
import sys
p = sys.argv[1]
with open(p, 'rb') as f:
    head = f.read(4096)
# ext4 magic at 0x438 = 0xEF53
if len(head) > 0x43A and head[0x438:0x43A] == b'\x53\xef':
    print('ext4'); sys.exit()
# erofs magic at 0x1000
if len(head) > 0x1004 and head[0x1000:0x1004] == b'\xe2\xe1\xf0\xe3':
    print('erofs'); sys.exit()
print('unknown')
PY
)
log "    源包文件系统: $FS_TYPE"
[ "$FS_TYPE" != "erofs" ] || warn "源包是 erofs, 本机内核不支持 → 必须转 ext4"

# ─────────────────────────────────────────────────────────────
# 2. 解包 system.img
# ─────────────────────────────────────────────────────────────
log "[2/9] 解包 system.img"
rm -rf sysroot && mkdir sysroot
if [ "$FS_TYPE" = "erofs" ]; then
  command -v erofs-utils >/dev/null 2>&1 || command -v dump.erofs >/dev/null 2>&1 || \
    die "需要 erofs-utils (dump.erofs) 才能解 erofs"
  dump.erofs -o sysroot "$SYS_IMG" || die "erofs 解包失败"
else
  mkdir -p mnt
  sudo mount -o loop,rw "$SYS_IMG" mnt 2>/dev/null || \
    die "挂载失败 (需要 sudo 或 用 e2fsdroid/extract.erofs)"
  sudo cp -a mnt/. sysroot/ && sudo umount mnt && rmdir mnt
fi
ok "system 解包完成: $(du -sh sysroot | cut -f1)"

# ─────────────────────────────────────────────────────────────
# 3. 解包底包取 vendor (设备专属分区)
# ─────────────────────────────────────────────────────────────
log "[3/9] 准备 vendor"
if [ -n "$STOCK_DIR" ] && [ -d "$STOCK_DIR" ]; then
  ok "使用指定底包: $STOCK_DIR"
  cp -a "$STOCK_DIR" stock 2>/dev/null || true
else
  warn "未指定底包目录 → 将不替换 vendor"
  warn "  (ColorOS 卡二最常见原因就是 vendor 不匹配, 强烈建议提供底包)"
fi

# ─────────────────────────────────────────────────────────────
# 4. ★ 开机三件套 (TFSS/a14) —— 不做必卡一
# ─────────────────────────────────────────────────────────────
log "[4/9] 替换开机三件套 (init / libfs_mgr)"
TFSS="$TOOLS/TFSS/a14"
found=0
for f in bin/init lib64/libfs_mgr.so lib64/libfs_mgr.binder.so; do
  src=$(find "$TFSS" -path "*$f" | head -1)
  if [ -n "$src" ] && [ -f "$src" ]; then
    mkdir -p "sysroot/$(dirname "$f")"
    cp "$src" "sysroot/$f"
    echo "    替换 $f"
    found=$((found+1))
  fi
done
[ "$found" -ge 1 ] || die "TFSS/a14 里没找到 init / libfs_mgr"
ok "替换 $found 个文件"

# ─────────────────────────────────────────────────────────────
# 5. ★ SELinux mapping —— 不做会报错重启
# ─────────────────────────────────────────────────────────────
log "[5/9] 替换 SELinux mapping (用底包的)"
if [ -d "stock" ]; then
  for part in system product system_ext; do
    src=$(find "stock" -path "*/etc/selinux/mapping" -type d | head -1)
    if [ -n "$src" ]; then
      rm -rf "sysroot/$part/etc/selinux/mapping"
      mkdir -p "sysroot/$part/etc/selinux"
      cp -a "$src" "sysroot/$part/etc/selinux/mapping"
      echo "    $part/etc/selinux/mapping 已替换"
    fi
  done
  ok "mapping 替换完成"
else
  warn "没有底包, 跳过 mapping 替换 (卡二高危)"
fi

# ─────────────────────────────────────────────────────────────
# 6. ★ apex 处理
#    A14 规则: 除 com.android.vndk.v34.apex 外的全部
#    本机已有 v28~v34 → 大多可省, 但仍按包内实际内容核对
# ─────────────────────────────────────────────────────────────
log "[6/9] apex 处理"
APEX_SRC="$TOOLS/apex"
if [ -d "$APEX_SRC" ]; then
  mkdir -p sysroot/system_ext/apex
  # A14: 除 vndk.v34 外的全部
  cnt=0
  for a in "$APEX_SRC"/*.apex; do
    b=$(basename "$a")
    case "$b" in
      com.android.vndk.v34.apex) continue ;;   # A14 排除 v34
    esac
    cp "$a" sysroot/system_ext/apex/ && cnt=$((cnt+1))
  done
  ok "放入 $cnt 个 apex (A14: 排除 vndk.v34)"
  log "    注意: 手机已自带 v28~v34, 实际以包内需要为准"
else
  warn "没有 apex 目录 ($APEX_SRC), 跳过"
  warn "  本机已自带 vndk v28~v34, A14 大概率够用"
fi

# ─────────────────────────────────────────────────────────────
# 7. ★ vendor 修复 (passwd / group / overlay)
# ─────────────────────────────────────────────────────────────
log "[7/9] 修 vendor (passwd/group, 删 overlay)"
if [ -d "stock/vendor" ] || [ -d "stock/vendor_a" ]; then
  V=stock/vendor; [ -d "stock/vendor_a" ] && V=stock/vendor_a
  # 删除 overlay
  rm -rf "$V/overlay"
  ok "已删除 vendor/overlay"
  # passwd/group 用移植包的
  if [ -f sysroot/etc/passwd ]; then
    cp sysroot/etc/passwd "$V/etc/passwd" 2>/dev/null && ok "etc/passwd 已用移植包的"
  fi
  if [ -f sysroot/etc/group ]; then
    cp sysroot/etc/group "$V/etc/group" 2>/dev/null && ok "etc/group 已用移植包的"
  fi
else
  warn "没有底包 vendor, 跳过 (ColorOS 卡二主因)"
fi

# ─────────────────────────────────────────────────────────────
# 8. ★ build.prop 修改 + init.gsi.rc + permissive
# ─────────────────────────────────────────────────────────────
log "[8/9] 改 build.prop / init.gsi.rc / permissive"

BP=""
for p in sysroot/system/build.prop sysroot/build.prop; do
  [ -f "$p" ] && { BP="$p"; break; }
done
[ -n "$BP" ] || die "找不到 build.prop"

# 删除这一行 (存在才删)
if grep -q "^media.settings.xml=/vendor/etc/media_profiles_vendor.xml" "$BP"; then
  sed -i '/^media\.settings\.xml=\/vendor\/etc\/media_profiles_vendor\.xml/d' "$BP"
  ok "已删除 media.settings.xml"
fi

# 追加一组
cat >> "$BP" << EOF

# ---- cezanne ColorOS14 移植 ----
ro.cp_system_other_odex=0
ro.nnapi.extensions.deny_on_product=true
ro.crypto.metadata_init_delete_all_keys.enabled=false
persist.sys.disable_rescue=true
ro.control_privapp_permissions=disable
persist.sys.usb.config=mtp,adb
ro.adb.secure=0
ro.secure=0
ro.debuggable=1
persist.service.adb.enable=1
EOF
ok "build.prop 已追加"

# system/apex 是文件夹 -> ro.apex.updatable=false
if [ -d "sysroot/system/apex" ]; then
  echo "ro.apex.updatable=false" >> "$BP"
  ok "ro.apex.updatable=false (system/apex 是文件夹)"
elif [ -f "sysroot/system/apex" ]; then
  echo "ro.apex.updatable=true" >> "$BP"
  ok "ro.apex.updatable=true (system/apex 是文件)"
fi

# init.gsi.rc -> system_ext/etc/init  (★不做直接开不了机)
mkdir -p sysroot/system_ext/etc/init
cp "$TOOLS/init.gsi.rc" sysroot/system_ext/etc/init/init.gsi.rc
ok "init.gsi.rc 已放入 system_ext/etc/init/"

# permissive (强烈建议)
if [ -f sysroot/system/init/hw/init.rc ]; then
  if ! grep -q "init.svc.selinux_audit" sysroot/system/init/hw/init.rc; then
    sed -i '1i setprop init.svc.selinux_audit permissive' sysroot/system/init/hw/init.rc
    ok "已加 permissive"
  fi
else
  warn "找不到 system/init/hw/init.rc, 跳过 permissive"
fi

# ─────────────────────────────────────────────────────────────
# 9. ★ 打包 ext4 (本机无 erofs, 必须 ext4)
# ─────────────────────────────────────────────────────────────
log "[9/9] 打包 system.img (ext4)"
IMG_SIZE="8G"     # 按需调整, 太小装不下
rm -f sysroot.img
if command -v mkfs.ext4 >/dev/null 2>&1; then
  sudo mkfs.ext4 -q -F -s -b 4096 -L system -J size=64 "$IMG_SIZE" sysroot.img
  # 写入内容: 优先用 e2fsdroid (快), 失败则回退 mount 复制
  if command -v e2fsdroid >/dev/null 2>&1; then
    (cd sysroot && find . -mindepth 1 -maxdepth 1 -print0 | \
      e2fsdroid -a sysroot.img -S -f - 2>/dev/null) || true
  fi
  # 校验/补写: 用 mount 方式确保内容完整
  sudo mkdir -p mnt2
  if sudo mount -o loop sysroot.img mnt2 2>/dev/null; then
    sudo cp -a sysroot/. mnt2/
    sudo umount mnt2
  fi
  sudo rmdir mnt2 2>/dev/null || true
  ok "ext4 镜像生成: sysroot.img ($(du -h sysroot.img | cut -f1))"
else
  die "需要 e2fsprogs (mkfs.ext4)"
fi

# 稀疏转换 (fastboot 需要 sparse)
if command -v img2simg >/dev/null 2>&1; then
  img2simg sysroot.img system_sparse.img && mv system_sparse.img system.img
  ok "已转 sparse 格式"
else
  warn "没有 img2simg, 生成的可能是裸镜像 (刷入可能失败)"
fi

cp system.img "$OUT_DIR/system.img"
ok "输出: $OUT_DIR/system.img"

# ─────────────────────────────────────────────────────────────
cat << EOF

==================================================
  完成!
==================================================

产物: $OUT_DIR/system.img

刷入步骤 (fastboot):
  fastboot reboot fastboot
  fastboot --disable-verity --disable-verification flash vbmeta    vbmeta.img
  fastboot --disable-verity --disable-verification flash vbmeta_system vbmeta_system.img
  fastboot erase product
  fastboot erase system_ext
  fastboot erase system
  fastboot flash system $OUT_DIR/system.img
  fastboot erase userdata
  fastboot erase metadata
  fastboot reboot

验证:
  getprop sys.boot_completed      -> 1
  uname -r                        -> 4.14.186-...
  WiFi 能上网                     -> BPF 正常
  相机/指纹/充电动画              -> ColorOS 特有功能

如果卡二:
  1. logcat -b all | grep -iE "avc: denied|linker|cannot find"
  2. 优先怀疑 vendor 不匹配 → 用底包的 vendor 重打
  3. 优先怀疑 SELinux → 先 permissive 跑通再修 sepolicy

已知限制:
  · OPPO 私有服务 (AI/游戏空间/小布) 大概率不可用
  · 相机画质对不上 (Adreno 调校 vs 你的 Mali-G77)
  · FOD 屏下指纹不可用 (GSI 架构缺口)
EOF
