import os
import struct
import zipfile
import zlib

D = r"D:\cezanne-work\artifacts"
AK = os.path.join(D, "x34", "artifacts",
                  "cezanne-kernel-bpf-20261109181330-gz-anykernel3.zip")
TMP = os.path.join(D, "_ak34")

if not os.path.isdir(TMP):
    os.makedirs(TMP)
    zipfile.ZipFile(AK).extractall(TMP)

kern = None
for root, dirs, files in os.walk(TMP):
    for f in files:
        if f.startswith("Image"):
            p = os.path.join(root, f)
            if kern is None or os.path.getsize(p) > os.path.getsize(kern):
                kern = p

print("=== 第 34 轮内核: %s (%d 字节) ===" % (kern, os.path.getsize(kern)))

with open(kern, "rb") as f:
    d = f.read()

raw = b""
if d[:2] == b"\x1f\x8b":
    pos = 0
    while pos < len(d) and len(raw) < 60 * 1024 * 1024:
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

i = raw.find(b"Linux version ")
if i >= 0:
    e = raw.find(b"\x00", i)
    print("内核版本: %s" % raw[i:e].decode("utf-8", "replace")[:130])
print()

print("=== EROFS 驱动是否在内核里 ===")
feats = [
    (b"erofs_fill_super", "erofs_fill_super (读超级块)"),
    (b"erofs_read_superblock", "erofs_read_superblock"),
    (b"erofs_init", "erofs_init (文件系统注册)"),
    (b"erofs_fill_inode", "erofs_fill_inode"),
    (b"erofs_readdir", "erofs_readdir"),
    (b"erofs_lookup", "erofs_lookup"),
    (b"erofs_map_blocks", "erofs_map_blocks"),
    (b"erofs_xattr", "erofs_xattr"),
    (b"erofs", "字符串 'erofs'"),
]
missing = []
for pat, desc in feats:
    idx = raw.find(pat)
    print("  %-34s %s" % (desc, ("@0x%x" % idx) if idx >= 0 else "★无"))
    if idx < 0 and pat != b"erofs":
        missing.append(desc)

print()
print("=== 其他关键驱动 ===")
for pat, desc in [(b"bpf_prog_load", "BPF syscall"),
                   (b"netlink_bpf", "netlink_bpf"),
                   (b"BPF_PROG_TYPE", "BPF prog type"),
                   (b"__modversions", "MODVERSIONS 表"),
                   (b"crc32c", "crc32c")]:
    idx = raw.find(pat)
    print("  %-34s %s" % (desc, ("@0x%x" % idx) if idx >= 0 else "★无"))

print()
if missing:
    print("★ 缺: %s" % ", ".join(missing))
else:
    print("=== 结论: EROFS 驱动完整编入内核 ✓ ===")
