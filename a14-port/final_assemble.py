import os
import subprocess
import sys

TOOLS = r"C:\Users\纪\WorkBuddy\2026-11-05-00-02-58\a14-port"
sys.path.insert(0, TOOLS)

D = r"D:\cezanne-work"
AK = os.path.join(D, "artifacts", "_ak34", "kernel", "Image.gz")
ORIG = os.path.join(D, "firmware",
                    "cezanne_images_V12.5.11.0.RJNCNXM_20220301.0000.00_11.0_cn",
                    "images", "boot.img")
RD = os.path.join(D, "rd_work", "ramdisk.img")
OUT = os.path.join(D, "boot_cezanne.img")

print("内核    :", AK, os.path.exists(AK))
print("原厂boot:", ORIG, os.path.exists(ORIG))
print("ramdisk :", RD, os.path.exists(RD))
if not all(os.path.exists(x) for x in (AK, ORIG, RD)):
    sys.exit(1)

r = subprocess.run([sys.executable, os.path.join(TOOLS, "make_boot.py"),
                    "--orig", ORIG, "--kernel", AK, "--ramdisk", RD,
                    "--out", OUT], capture_output=True, timeout=900)
print(r.stdout.decode("utf-8", "replace"))
if r.returncode != 0:
    print(r.stderr.decode("utf-8", "replace")[-800:])
    sys.exit(1)

print()
print("=== 验证 ===")
from ramdisk_tools import load_boot, cpio_mkbootfs
k, rd, cmd, nm = load_boot(OUT)
i = k.find(b"Linux version ")
e = k.find(b"\x00", i)
print("大小    :", os.path.getsize(OUT), "字节")
print("内核版本:", k[i:e].decode("utf-8", "replace")[:120])
ents = cpio_mkbootfs(rd)
print("ramdisk:", len(rd), "字节,", len(ents), "个条目")
names = {n for n, _, _ in ents}
for m in ("init", "avb/q-gsi.avbpubkey", "verity_key",
          "first_stage_ramdisk/fstab.emmc", "ueventd.mt6893.rc"):
    print("  %-38s %s" % (m, "OK" if m in names else "MISSING"))
