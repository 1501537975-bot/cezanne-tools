import subprocess

IPS = ("185.199.108.133", "185.199.109.133", "185.199.110.133")
TREE = "MiCode/Xiaomi_Kernel_OpenSource"
BR = "cezanne-r-oss"

CHECKS = [
    ("include/linux/bio.h", "bio_alloc(", "4.16 only"),
    ("include/linux/bio.h", "bio_alloc_gfp(", "4.14 old API"),
    ("include/linux/bio.h", "bio_add_page(", "4.16 only"),
    ("include/linux/strscpy.h", "strscpy(", "strscpy"),
    ("include/linux/string.h", "strscpy(", "strscpy in string.h"),
    ("include/linux/xattr.h", "struct xattr_handler", "new xattr API"),
    ("include/linux/xattr.h", "xattr_prefix", "xattr_prefix"),
    ("include/linux/xattr.h", "xattr_foreach", "xattr_foreach"),
    ("include/linux/fs.h", "s_xattr", "sb->s_xattr field"),
    ("include/linux/err.h", "IS_ERR", "IS_ERR macro"),
    ("include/linux/mm.h", "filemap_get_folio", "4.17 folio"),
    ("include/linux/pagemap.h", "vmap_pages", "vmap_pages"),
    ("include/linux/crc32c.h", "crc32c", "crc32c"),
    ("include/linux/lz4.h", "LZ4HC", "LZ4HC"),
    ("include/linux/compression.h", "zstd", "zstd"),
]


def fetch(path):
    url = "https://raw.githubusercontent.com/%s/%s/%s" % (TREE, BR, path)
    for ip in IPS:
        r = subprocess.run(["curl", "-sL", "--max-time", "20", "--resolve",
                            "raw.githubusercontent.com:443:" + ip, url],
                           capture_output=True)
        out = r.stdout
        if out and b"404: Not Found" not in out[:40]:
            return out.decode("utf-8", "replace")
    return None


print("=== cezanne 4.14.186 tree symbol check ===")
cache = {}
for path, sym, note in CHECKS:
    if path not in cache:
        cache[path] = fetch(path)
    txt = cache[path]
    if txt is None:
        print("  [NOFILE]   %-30s %-20s %s" % (path, sym, note))
    elif sym in txt:
        print("  [OK]       %-30s %-20s %s" % (path, sym, note))
    else:
        print("  [MISSING]  %-30s %-20s %s" % (path, sym, note))
