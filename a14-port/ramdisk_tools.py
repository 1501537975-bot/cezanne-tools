#!/usr/bin/env python3
"""
解析 Android ramdisk 里的 cpio (mkbootfs 变体)。

★ 与标准 newc 的关键差异 (实测自 K40G GSI ramdisk):
    1. 名字长度含结尾 '\\0' -> namesize-1 是名字长度, 但对齐按 namesize 计算
    2. **条目之间不做 4 字节对齐** —— 下一个 '070701' magic 紧跟在上一个
       条目的数据之后 (标准 newc 会补 0~3 字节)
    3. 根节点名字是 '.' (而不是 'TRAILER!!!' 结尾)

用法:
  python3 ramdisk_tools.py <boot.img> [--export <目录>]
"""
import os
import struct
import sys
import zlib


def gunzip_all(data):
    """解压所有 gzip 成员 (Android 镜像常用 concatenated gzip)。"""
    result = b""
    pos = 0
    n = 0
    while pos < len(data) and n < 60:
        if data[pos:pos + 2] != b"\x1f\x8b":
            nxt = data.find(b"\x1f\x8b", pos)
            if nxt < 0:
                break
            pos = nxt
            continue
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            chunk = d.decompress(data[pos:])
        except Exception:
            break
        result += chunk
        pos += max(len(data) - pos - len(d.unused_data), 1)
        n += 1
    return result


def load_boot(path):
    """从 boot.img 提取 (kernel, ramdisk, cmdline)。"""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"ANDROID!":
        raise ValueError("不是 boot.img")
    (k_size, _ka, r_size, _ra, s_size, _sa, _ta,
     page_size, hdr) = struct.unpack_from("<9I", data, 8)
    off = 8 + 36
    if hdr >= 1:
        off += 4
    name = data[off:off + 16].split(b"\0")[0].decode("utf-8", "replace")
    off += 16
    cmdline = data[off:off + 512].split(b"\0")[0].decode("utf-8", "replace")
    off += 512 + 32 + 1024
    pa = lambda x: (x + page_size - 1) // page_size * page_size
    k_off = pa(off)
    r_off = k_off + pa(k_size)
    return (gunzip_all(data[k_off:k_off + k_size]),
            gunzip_all(data[r_off:r_off + r_size]),
            cmdline, name)


def cpio_mkbootfs(blob):
    """解析 POSIX newc 格式的 cpio (Android ramdisk)。

    ★★★ 关键: newc 的所有数值字段都是 **8 位 ASCII 十六进制字符**,
       不是二进制整数!  (之前用 struct.unpack("<13I") 按二进制读 -> 全错)

       字段顺序 (每个 8 字节 ASCII hex):
         0: magic "070701" (6 字节)
         1: ino        2: mode       3: uid        4: gid
         5: nlink      6: mtime      7: filesize   8: devmajor
         9: devminor  10: rdevmajor 11: rdevminor 12: namesize
        13: check
       -> header = 6 + 13*8 = 110 字节
       -> 名字从 110 开始, 长度 namesize-1 (含结尾 NUL)
       -> 数据从 110+namesize 开始, **4 字节对齐**

    返回 [(name, filesize, data_offset)]。
    """
    entries = []
    pos = 0
    n = len(blob)
    MAGIC = b"070701"
    # ★ 实测 (K40G GSI ramdisk) 的 header 布局:
    #   magic    @0   (6 字节 ASCII "070701")
    #   ino      @6   (8 字节 ASCII hex)
    #   mode     @14
    #   uid      @22   gid @30   nlink @38   mtime @46
    #   filesize @54  devmajor @62  devminor @70
    #   rdevmajor @78 rdevminor @86  namesize @94  check @102
    #   名字从 @110 开始 (namesize 含结尾 NUL)
    #   => header = 110 字节
    HDR = 110
    OFF_INO = 6
    OFF_MODE = 14
    OFF_NLINK = 38
    OFF_MTIME = 46
    OFF_FILESIZE = 54
    OFF_NAMESIZE = 94

    def hexfield(buf, off):
        """读 8 字节 ASCII 十六进制并转 int。"""
        s = buf[off:off + 8]
        try:
            return int(s.decode("ascii"), 16)
        except (ValueError, UnicodeDecodeError):
            return -1

    while pos + HDR <= n:
        if blob[pos:pos + 6] != MAGIC:
            nxt = blob.find(MAGIC, pos)
            if nxt < 0:
                break
            pos = nxt
            continue

        filesize = hexfield(blob, pos + OFF_FILESIZE)
        namesize = hexfield(blob, pos + OFF_NAMESIZE)

        if namesize <= 0 or namesize > 4096 or filesize < 0:
            break

        name_off = pos + HDR
        name = blob[name_off:name_off + namesize - 1].decode("utf-8", "replace")
        data_off = (name_off + namesize + 3) & ~3      # 4 字节对齐

        entries.append((name, filesize, data_off))

        if name == "TRAILER!!!":
            break

        pos = (data_off + filesize + 3) & ~3             # 数据后 4 字节对齐

    return entries


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    boot = sys.argv[1]
    export_dir = None
    if "--export" in sys.argv:
        i = sys.argv.index("--export")
        export_dir = sys.argv[i + 1] if i + 1 < len(sys.argv) else "rd_files"

    kern, rd, cmdline, name = load_boot(boot)
    print("=== %s ===" % os.path.basename(boot))
    print("  cmdline: %s" % cmdline[:160])
    print("  内核 %d 字节 / ramdisk %d 字节" % (len(kern), len(rd)))

    # 内核版本串
    i = kern.find(b"Linux version ")
    if i >= 0:
        e = kern.find(b"\x00", i)
        print("  内核: %s" % kern[i:e].decode("utf-8", "replace"))

    ents = cpio_mkbootfs(rd)
    print()
    print("  ramdisk 条目 %d 个" % len(ents))
    print()
    print("  ── 目录结构 (深度<=2) ──")
    for n, sz, _ in ents:
        if n.count("/") <= 1:
            print("    %-56s %10d" % (n, sz))

    print()
    print("  ── 关键文件 ──")
    keys = ("init.gsi.rc", "prop.default", "default.prop", "fstab.postinstall",
            "ueventd.rc", "init.rc", "init", "fstab.qcom", "fstab.mt68")
    hits = []
    for n, sz, do in ents:
        b = n.rsplit("/", 1)[-1]
        if b in keys or "gsi" in n.lower():
            hits.append((n, sz, do))
            print("    ★ %-56s %10d" % (n, sz))

    if export_dir:
        os.makedirs(export_dir, exist_ok=True)
        cnt = 0
        for n, sz, do in ents:
            b = n.rsplit("/", 1)[-1]
            if b.endswith(".rc") or b in ("prop.default", "default.prop",
                                          "fstab.postinstall", "fstab.qcom"):
                safe = n.replace("/", "_").lstrip("_") or "root"
                with open(os.path.join(export_dir, safe), "wb") as f:
                    f.write(rd[do:do + sz])
                cnt += 1
        print()
        print("  已导出 %d 个文件 -> %s/" % (cnt, export_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
