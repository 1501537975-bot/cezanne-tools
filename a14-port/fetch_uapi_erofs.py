import io
import os
import subprocess

DST = r"C:\Users\纪\WorkBuddy\2026-11-05-00-02-58\kernel-bpf\patches\erofs"
IPS = ("185.199.108.133", "185.199.109.133", "185.199.110.133", "185.199.111.133")

CANDIDATES = [
    ("torvalds/linux", "v4.19", "include/uapi/linux/erofs_fs.h"),
    ("torvalds/linux", "v5.4", "include/uapi/linux/erofs_fs.h"),
    ("torvalds/linux", "v5.10", "include/uapi/linux/erofs_fs.h"),
    ("gregkh/linux", "v4.19", "include/uapi/linux/erofs_fs.h"),
    ("aosp-mirror/kernel_common", "android-4.19", "include/uapi/linux/erofs_fs.h"),
]


def raw_get(repo, br, path):
    url = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, br, path)
    for ip in IPS:
        r = subprocess.run(["curl", "-sL", "--max-time", "40", "--resolve",
                            "raw.githubusercontent.com:443:" + ip, url],
                           capture_output=True)
        out = r.stdout
        if out and b"404: Not Found" not in out[:40] and len(out) > 300:
            return out.decode("utf-8", "replace")
    return None


txt = None
src = None
for repo, br, path in CANDIDATES:
    t = raw_get(repo, br, path)
    if t:
        txt = t
        src = "%s@%s:%s" % (repo, br, path)
        print("  [OK] %s" % src)
    else:
        print("  [X]  %s@%s" % (repo, br))

if not txt:
    print("[FAIL] 都取不到")
    raise SystemExit(1)

print()
print("=== 来源: %s (%d 字节) ===" % (src, len(txt)))
print()
print("=== 关键定义检查 ===")
need = ["EROFS_SUPER_MAGIC_V1", "EROFS_SUPER_OFFSET", "EROFS_FEATURE_COMPAT",
        "EROFS_FEATURE_INCOMPAT", "EROFS_INODE_LAYOUT_COMPACT",
        "EROFS_INODE_CHUNK_FORMAT", "EROFS_XATTR_IBODY_HEADER",
        "EROFS_COMPR_LZ4", "EROFS_COMPR_ZSTD"]
missing = []
for k in need:
    ok = k in txt
    print("  %-30s %s" % (k, "有" if ok else "缺"))
    if not ok:
        missing.append(k)

print()
print("=== MAGIC 相关定义 ===")
for i, line in enumerate(txt.splitlines(), 1):
    if "MAGIC" in line or "0xE0F5" in line:
        print("  行%-4d %s" % (i, line.strip()[:100]))

if "EROFS_SUPER_MAGIC_V1" not in txt:
    print("[FAIL] 没有 MAGIC_V1")
    raise SystemExit(1)

d = os.path.join(DST, "include", "uapi", "linux")
os.makedirs(d, exist_ok=True)
p = os.path.join(d, "erofs_fs.h")
io.open(p, "w", encoding="utf-8", newline="\n").write(txt)
print()
print("已保存 -> %s (%d 字节)" % (p, os.path.getsize(p)))
if missing:
    print("[注意] 缺: %s" % missing)
