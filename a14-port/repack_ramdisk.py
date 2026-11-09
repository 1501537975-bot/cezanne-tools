#!/usr/bin/env python3
"""
把解开的 ramdisk 文件目录重新打包成 cpio (newc 格式) + gzip。

★ 格式要点 (实测自 K40G GSI ramdisk):
    - magic "070701" (6 字节 ASCII)
    - header 110 字节, 13 个字段, 每个 8 字节 **ASCII 十六进制**
      magic@0(6) ino@6 mode@14 uid@22 gid@30 nlink@38 mtime@46
      filesize@54 devmajor@62 devminor@70 rdevmajor@78 rdevminor@86
      namesize@94 check@102
    - 名字 @110, 长度 namesize-1 (含结尾 NUL)
    - 数据紧跟名字, **4 字节对齐**
    - 条目之间: 数据末尾 4 字节对齐, 下一个 header 紧跟
    - 根目录条目名是 "."

用法:
  python3 repack_ramdisk.py <文件目录> <输出cpio> [--gzip <输出.gz>]
"""
import os
import struct
import sys


def align4(n):
    return (n + 3) & ~3


def build_cpio(root):
    """把目录树打成 newc cpio 字节流。

    ★ 对齐规则 (实测自 K40G GSI ramdisk, 逐字节对比确认):
        header(110) + name(namesize) -> **4 字节对齐** -> data(filesize)
        -> **4 字节对齐** -> 下一个 header
    """
    out = bytearray()

    def entry(name, mode, ino, nlink, data=b""):
        nonlocal out
        namesize = len(name) + 1           # 含结尾 NUL
        fields = [
            ino, mode, 0, 0, nlink, 0, len(data),
            0, 0, 0, 0, namesize, 0,
        ]
        hdr = b"070701" + b"".join(b"%08X" % f for f in fields)
        out += hdr
        out += name.encode("utf-8") + b"\0"
        # 名字后对齐到 4
        out += b"\0" * (align4(len(out)) - len(out))
        out += data
        # 数据后对齐到 4
        out += b"\0" * (align4(len(out)) - len(out))

    ino = 1
    # 收集所有条目 (相对路径, 用 '/' 分隔)
    dirs = []   # (relpath, abspath, is_dir)
    files = []  # (relpath, abspath)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            rel = ""
        for d in sorted(dirnames):
            p = os.path.join(rel, d) if rel else d
            dirs.append((p.replace(os.sep, "/"), os.path.join(dirpath, d)))
        for f in sorted(filenames):
            p = os.path.join(rel, f) if rel else f
            files.append((p.replace(os.sep, "/"), os.path.join(dirpath, f)))

    # 根目录
    root_nlink = len(dirs) + 2
    entry(".", 0o040755, ino, root_nlink)
    ino += 1

    # 子目录的 nlink = 子目录数 + 2
    child_count = {}
    for p, _ in dirs + files:
        parent = os.path.dirname(p)
        if parent:
            child_count[parent] = child_count.get(parent, 0) + 1

    for name, path in dirs:
        mode = 0o040755
        try:
            mode = os.lstat(path).st_mode & 0o7777
        except OSError:
            pass
        entry(name, mode, ino, child_count.get(name, 0) + 2)
        ino += 1

    for name, path in files:
        try:
            mode = os.lstat(path).st_mode & 0o7777
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        entry(name, mode, ino, 1, data)
        ino += 1

    # TRAILER
    entry("TRAILER!!!", 0, 0, 1)
    return bytes(out)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    src = sys.argv[1]
    out = sys.argv[2]
    gz_out = None
    if "--gzip" in sys.argv:
        i = sys.argv.index("--gzip")
        if i + 1 < len(sys.argv):
            gz_out = sys.argv[i + 1]

    if not os.path.isdir(src):
        print("[FAIL] 不是目录: %s" % src)
        return 1

    blob = build_cpio(src)
    with open(out, "wb") as f:
        f.write(blob)
    print("[ ok ] cpio: %s (%d 字节)" % (out, len(blob)))

    if gz_out:
        import gzip
        # mtime=0 -> 可复现
        with open(gz_out, "wb") as f:
            with gzip.GzipFile(fileobj=f, mode="wb", compresslevel=9, mtime=0) as gz:
                gz.write(blob)
        print("[ ok ] gzip: %s (%d 字节)" % (gz_out, os.path.getsize(gz_out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
