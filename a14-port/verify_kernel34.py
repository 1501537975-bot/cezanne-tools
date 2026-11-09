import io
import json
import os
import struct
import zipfile

D = r"D:\cezanne-work\artifacts"
SRC = os.path.join(D, "r42668555316_cezanne-kernel-bpf.zip")
OUT = os.path.join(D, "x34")

if not os.path.isdir(OUT):
    os.makedirs(OUT)
    z = zipfile.ZipFile(SRC)
    z.extractall(OUT)

print("=== 第 34 轮产物 ===")
rel = os.path.join(OUT, "kernel-release.txt")
print("kernel-release.txt:", open(rel).read().strip())

bi = os.path.join(OUT, "BUILD-INFO.txt")
txt = io.open(bi, encoding="utf-8", errors="replace").read()
print()
print("=== BUILD-INFO.txt ===")
print(txt)

# 找内核文件
kern = None
for root, dirs, files in os.walk(OUT):
    for f in files:
        if f.startswith("Image"):
            p = os.path.join(root, f)
            if kern is None or os.path.getsize(p) > os.path.getsize(kern):
                kern = p
print("=== 内核文件: %s (%d 字节) ===" % (kern, os.path.getsize(kern)))

# 解 gzip 找 EROFS 特征串
import zlib
with open(kern, "rb") as f:
    d = f.read()
raw = b""
if d[:2] == b"\x1f\x8b":
    pos = 0
    while pos < len(d) and len(raw) < 40 * 1024 * 1024:
        if d[pos:pos + 2] != b"\x1f\x8b":
            nx = d.find(b"\x1f\x8b", pos)
            if nx < 0:
                break
            pos = nx
            continue
        do = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            c = do.decompress(d[pos:])
        except Exception:
            break
        raw += c
        pos += max(len(d) - pos - len(do.unused_data), 1)
    print("解压出 %d 字节" % len(raw))

print()
print("=== 内核里的 EROFS 特征 ===")
for pat in (b"erofs", b"EROFS", b"erofs_init", b"erofs_fill_super",
            b"erofs_read_superblock", b"0xE0F5E1E2"):
    idx = raw.find(pat)
    print("  %-26s %s" % (pat.decode("utf-8", "replace"),
                          ("@0x%x" % idx) if idx >= 0 else "无"))

# 版本串
i = raw.find(b"Linux version ")
if i >= 0:
    e = raw.find(b"\x00", i)
    print()
    print("内核版本:", raw[i:e].decode("utf-8", "replace")[:120])

# config
cfg = os.path.join(OUT, "config.txt")
if os.path.exists(cfg):
    c = io.open(cfg, encoding="utf-8", errors="replace").read()
    print()
    print("=== config 关键项 ===")
    for k in ("CONFIG_EROFS_FS", "CONFIG_EROFS_FS_XATTR", "CONFIG_EROFS_FS_ZIP",
              "CONFIG_MODVERSIONS", "CONFIG_BPF_SYSCALL", "CONFIG_CGROUP_BPF",
              "CONFIG_FHANDLE", "CONFIG_LOCALVERSION"):
        hits = [l for l in c.splitlines() if l.startswith(k)]
        print("  %-26s %s" % (k, hits[0] if hits else "(未设置)"))
