#!/usr/bin/env bash
# cezanne 移植项目 · 一键状态总览
# 用法: bash status.sh
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
A="$BASE/platform-tools/adb.exe"
FB="$BASE/platform-tools/fastboot.exe"

ok()   { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m $*"; }
bad()  { echo -e "\033[1;31m[FAIL]\033[0m $*"; }
sec()  { echo ""; echo -e "\033[1;36m═══ $* ═══\033[0m"; }

echo "=================================================="
echo "  cezanne 移植项目状态"
echo "=================================================="

sec "1. 手机"
if [ -x "$A" ] && "$A" devices 2>/dev/null | grep -q "device$"; then
  ok "已连接 (adb)"
  for p in ro.product.model ro.build.version.release ro.build.version.sdk \
           ro.kernel.version ro.vndk.version ro.boot.flash.locked sys.boot_completed; do
    v=$("$A" shell getprop "$p" 2>/dev/null | tr -d '\r')
    printf "    %-26s %s\n" "$p" "$v"
  done
  erofs=$("$A" shell "mount | grep -c erofs" 2>/dev/null | tr -d '\r')
  echo "    erofs 挂载数                 ${erofs:-0}"
  btf=$("$A" shell "ls /sys/kernel/btf/vmlinux 2>&1" 2>/dev/null | tr -d '\r')
  case "$btf" in
    *No\ such*) warn "无 BTF (当前内核不具备 A16/A17 的 CO-RE 附加能力)" ;;
    *) ok "有 BTF" ;;
  esac
else
  warn "手机未连接 (adb)"
fi

sec "2. 备份"
if [ -d "$BASE/backup" ]; then
  for f in boot_current.img vbmeta.img vbmeta_system.img vbmeta_vendor.img dtbo.img; do
    p="$BASE/backup/$f"
    if [ -f "$p" ]; then
      printf "    %-24s %8s MB\n" "$f" "$(( $(stat -c%s "$p") / 1048576 ))"
    else
      printf "    %-24s 缺失\n" "$f"
    fi
  done
else
  warn "无 backup 目录"
fi

sec "3. 底包"
TGT="$BASE/firmware/cezanne_images_V12.5.11.0.RJNCNXM_20220301.0000.00_11.0_cn_7336febc6d.tgz"
if [ -f "$TGT" ]; then
  sz=$(stat -c%s "$TGT")
  printf "    %s / 4541 MB (%s%%)\n" "$(( sz / 1048576 ))" "$(( sz * 100 / 4761915395 ))"
  if [ "$sz" -eq 4761915395 ]; then
    ok "大小正确 (MD5 应为 7336febc6d6684d5e2b09b0b98c18b2d)"
  fi
  D=$(ls -d "$BASE"/firmware/cezanne_images_*/ 2>/dev/null | head -1)
  [ -n "$D" ] && ok "已解压: $(ls "$D/images" 2>/dev/null | wc -l) 个镜像"
else
  warn "底包未下载"
fi

sec "4. 内核仓库"
if [ -d "$BASE/kernel-bpf" ]; then
  n=$(find "$BASE/kernel-bpf/patches" -name "*.patch" 2>/dev/null | wc -l)
  ok "kernel-bpf/ 存在, $n 个 patch"
  if [ -d "$BASE/kernel-bpf/.git" ]; then
    cd "$BASE/kernel-bpf"
    printf "    分支 %s, %s 个提交\n" "$(git branch --show-current 2>/dev/null)" "$(git rev-list --count HEAD 2>/dev/null)"
    git log --oneline -3 2>/dev/null | sed 's/^/      /'
    cd - >/dev/null
  fi
else
  warn "无 kernel-bpf/"
fi

sec "5. 移植工具 (portingessential)"
for d in "$BASE/../portingessential" "$HOME/portingessential" "$BASE/portingessential"; do
  if [ -d "$d" ]; then
    ok "找到: $d"
    ls "$d" 2>/dev/null | head -8 | sed 's/^/      /'
    break
  fi
done
[ -d "$BASE/../portingessential" ] || [ -d "$HOME/portingessential" ] || [ -d "$BASE/portingessential" ] || \
  warn "未安装 (UKL / MIO Kitchen / TFSS / apex / init.gsi.rc)"

sec "6. 路线判断"
echo "    A14 档 (ColorOS 14 / OneUI 6 / OriginOS 4):"
echo "      最低内核 4.14 -> 原厂 4.14.186 原生满足, 不需自编内核"
echo "      唯一需求: 目标包的 system.img 是 ext4 还是 erofs"
echo ""
echo "    A16/A17 档 (HyperOS 4):"
echo "      需 5.4 -> 必须真改内核 (fake uname + 4.16 socket filter)"
echo "      且 Ty_1224 用 4.14.357 -> vermagic 与原厂不同 -> 他重编了 vendor"
echo "      (MTK 私有源码不可得) -> 我们无法完全复刻"

echo ""
echo "=================================================="
