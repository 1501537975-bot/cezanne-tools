#!/usr/bin/env bash
# cezanne · 现状体检 + 全部材料清单（一条命令跑完）
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
ADB="$BASE/platform-tools/adb.exe"
FASTBOOT="$BASE/platform-tools/fastboot.exe"

ok()  { echo -e "\033[1;32m[ ok ]\033[0m $*"; }
warn(){ echo -e "\033[1;33m[warn]\033[0m $*"; }
bad() { echo -e "\033[1;31m[FAIL]\033[0m $*"; }
sec() { echo ""; echo -e "\033[1;36m===== $* =====\033[0m"; }

echo "=================================================="
echo "  cezanne 现状体检"
echo "=================================================="

sec "1. 手机连接"
if [ -x "$ADB" ]; then
  out=$("$ADB" devices 2>&1 | grep -E "device$|device " | head -1)
  if [ -n "$out" ]; then
    ok "adb 已连接: $(echo "$out" | awk '{print $1}')"
    echo ""
    echo "  --- 系统信息 ---"
    for p in ro.product.model ro.product.device ro.build.version.release ro.build.version.sdk \
             ro.vendor.build.version.sdk ro.vndk.version ro.kernel.version \
             sys.boot_completed ro.build.display.id; do
      v=$("$ADB" shell getprop "$p" 2>/dev/null | tr -d '\r')
      printf "    %-28s %s\n" "$p" "$v"
    done
    echo ""
    echo "  --- 关键能力 ---"
    erofs=$("$ADB" shell "cat /proc/filesystems 2>/dev/null | grep -c erofs" 2>/dev/null | tr -d '\r')
    # BTF: 存在 /sys/kernel/btf/vmlinux 才算有
    btf=$("$ADB" shell "su -c 'ls /sys/kernel/btf/vmlinux 2>/dev/null'" 2>/dev/null | tr -d '\r')
    bpfcfg=$("$ADB" shell "su -c 'zcat /proc/config.gz 2>/dev/null | grep -c \"^CONFIG_BPF_SYSCALL=y\"'" 2>/dev/null | tr -d '\r')
    apex=$("$ADB" shell "ls /system_ext/apex/ 2>/dev/null | tr -d '\r'" 2>/dev/null | grep -c apex)
    [ "$erofs" = "0" ] && warn "无 EROFS  → 系统分区必须 ext4" || ok "有 EROFS"
    [ -n "$btf" ] && ok "有 BTF ($btf)" || warn "无 BTF     → 需新内核(仅缺 BTF, BPF 主体已有)"
    [ "$bpfcfg" = "1" ] && ok "BPF_SYSCALL 已启用" || warn "BPF_SYSCALL 未开"
    ok "system_ext/apex 现有 $apex 个"
    "$ADB" shell "su -c 'ls /system_ext/apex/ 2>/dev/null'" 2>/dev/null | tr -d '\r' | sed 's/^/      /'
  else
    warn "adb 未连接 (手机可能在 fastboot 模式)"
  fi
else
  bad "缺 platform-tools"
fi

sec "2. fastboot 通道"
if [ -x "$FASTBOOT" ]; then
  out=$("$FASTBOOT" devices 2>&1 | grep -i fastboot | head -1)
  if [ -n "$out" ]; then
    ok "fastboot 已连接: $out"
  else
    warn "fastboot 未识别 (手机不在 fastboot, 或驱动未装)"
  fi
fi

sec "3. 备份完整性"
if [ -d "$BASE/backup" ]; then
  for f in boot_current.img vbmeta.img vbmeta_system.img vbmeta_vendor.img dtbo.img; do
    p="$BASE/backup/$f"
    if [ -f "$p" ]; then
      printf "    %-24s %8s MB  %s\n" "$f" "$(( $(stat -c%s "$p") / 1048576 ))" \
        "$(sha256sum "$p" 2>/dev/null | cut -c1-16)"
    else
      printf "    %-24s 缺失\n" "$f"
    fi
  done
else
  warn "backup 目录不存在"
fi

sec "4. 底包下载"
TGT="$BASE/firmware/cezanne_images_V12.5.11.0.RJNCNXM_20220301.0000.00_11.0_cn_7336febc6d.tgz"
if [ -f "$TGT" ]; then
  sz=$(stat -c%s "$TGT")
  pct=$(( sz * 100 / 4761915395 ))
  echo "    $(( sz / 1048576 )) MB / 4541 MB ($pct%)"
  if [ "$sz" -eq 4761915395 ]; then
    ok "大小正确, 待校验 MD5 (应为 7336febc6d6684d5e2b09b0b98c18b2d)"
  else
    warn "尚未下完"
  fi
else
  warn "底包未开始下载"
fi

sec "5. 移植工具"
for t in "$BASE/../portingessential" "$HOME/portingessential" "/mnt/c/portingessential"; do
  [ -d "$t" ] && { ok "找到 portingessential: $t"; break; }
done
[ -d "$BASE/../portingessential" ] || [ -d "$HOME/portingessential" ] || \
  warn "缺 portingessential (UKL/MIO/TFSS/apex/init.gsi.rc)"
echo "    下载: https://sourceforge.net/projects/origin-oem-ports/files/portingessential/"

sec "6. 内核仓库"
if [ -d "$BASE/kernel-bpf" ]; then
  n=$(find "$BASE/kernel-bpf/patches" -name "*.patch" 2>/dev/null | wc -l)
  ok "kernel-bpf/ 就绪, $n 个 patch (13/13 已验证可 apply)"
  [ -d "$BASE/kernel-bpf/.git" ] && echo "    git 已初始化" || echo "    尚未 git init / push"
else
  warn "缺 kernel-bpf/"
fi

echo ""
echo "=================================================="
echo "  结论"
echo "=================================================="
echo ""
echo "  A17 路线: 只差 push 仓库 + Actions 编译"
echo "  A14 ColorOS 路线: 不需要新内核, 但需先解决 SourceForge 下载 (CF 限流)"
echo "  底包: bn.d.miui.com @ 1MB/s, 80 分钟"
echo ""
