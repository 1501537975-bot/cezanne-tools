import os
import subprocess
import sys

LP = r"D:\cezanne-work\lp_tools\lpunpack.exe"
OUT = r"D:\cezanne-work\verify_erofs"
SRC = r"D:\123pan\Downloads\K40G_Android16_OS3.0.311.0-Fiagelia-26.9.19\images\super.img"

os.makedirs(OUT, exist_ok=True)
print("源:", SRC)
print("存在" if os.path.exists(SRC) else "★不存在")
if not os.path.exists(SRC):
    sys.exit(1)

# lpunpack 只认 raw, 先转
SIMG = r"D:\cezanne-work\lp_tools\simg2img.exe"
RAW = os.path.join(OUT, "super_raw.img")
if not os.path.exists(RAW):
    print("转 raw ...")
    subprocess.run([SIMG, SRC, RAW], capture_output=True, timeout=1800)
    print("raw:", os.path.getsize(RAW), "字节")

r = subprocess.run([LP, "-p", "system_a", RAW, OUT],
                   capture_output=True, timeout=900)
print(r.stdout.decode("utf-8", "replace")[-300:])
for fn in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, fn)
    print("  %-24s %d 字节" % (fn, os.path.getsize(p)))
