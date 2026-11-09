#!/usr/bin/env python3
"""
纯 Python ext4 只读解析器 (不挂载, 不需要管理员权限)。

用途: 从原厂 super 的 vendor/system 分区里提取 MT6885 专用的
      ueventd.rc / init.recovery.mt6885.rc 等文件。

实测要点 (vendor.img, ext4 裸分区镜像):
  · 超级块在文件偏移 1024, s_magic 在超级块内偏移 0x38
  · GDT 位置 = 1024 + 1024 + reserved_gdt * 2048
      (s_reserved_gdt_blocks 在超级块偏移 0x0FC)
  · inode 表在 inode 位图的**下一个块** (ext4 规范: 位图块 N, 表块 N+1)
  · extent magic (0xF30A) 在 i_block 前 2 字节 = inode 偏移 0x28

用法:
  python3 ext4.py <镜像> --ls /                列根目录
  python3 ext4.py <镜像> --find ueventd         搜索文件名
  python3 ext4.py <镜像> /etc/init/ueventd.rc  导出文件
"""
import os
import struct
import sys

SB_OFF = 1024
SB_SIZE = 1024
ROOT_INODE = 2


class Ext4:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        sb = self._read(SB_OFF, SB_SIZE)
        if sb[0x38:0x3A] != b"\x53\xef":
            raise ValueError("不是 ext4 镜像 (s_magic=%s)" % sb[0x38:0x3A].hex())
        self.sb = sb

        u32 = lambda o: struct.unpack_from("<I", sb, o)[0]
        u16 = lambda o: struct.unpack_from("<H", sb, o)[0]

        self.inodes_count = u32(0x00)
        self.blocks_count = u32(0x04)
        self.first_data_block = u32(0x14)
        self.log_block_size = u32(0x18)
        self.block_size = 1024 << self.log_block_size
        self.blocks_per_group = u32(0x20)
        self.inodes_per_group = u32(0x28)
        self.feature_incompat = u32(0x60)
        self.feature_ro_compat = u32(0x64)
        self.volume_name = sb[0x78:0x88].split(b"\0")[0].decode("utf-8", "replace")
        self.inode_size = u16(0x58) or 128
        self.desc_size = u16(0xFE) or 32
        self.is_64bit = bool(self.feature_incompat & 0x80)

        if self.is_64bit:
            self.gdt_off = struct.unpack_from("<Q", sb, 0x28)[0]
        else:
            reserved_gdt = u32(0x0FC)
            self.gdt_off = SB_OFF + SB_SIZE + reserved_gdt * 2048

    def close(self):
        self.f.close()

    def _read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)

    def read_block(self, n):
        return self._read(n * self.block_size, self.block_size)

    def group_desc(self, g):
        """返回 (block_bitmap_blk, inode_bitmap_blk)。"""
        d = self._read(self.gdt_off + g * self.desc_size, self.desc_size)
        return struct.unpack_from("<II", d, 0)

    def read_inode(self, ino):
        g = (ino - 1) // self.inodes_per_group
        idx = (ino - 1) % self.inodes_per_group
        _, ibm = self.group_desc(g)
        itab = ibm + 1          # inode 表在 inode 位图的下一个块
        off = itab * self.block_size + idx * self.inode_size
        return self._read(off, self.inode_size)

    @staticmethod
    def inode_fields(raw):
        (mode, uid, size_lo, atime, ctime, ctime_hi, mtime, mtime_hi, dtime,
         gid, links, blocks_lo, flags, osd1) = struct.unpack_from(
            "<HHIIIIIIIIHHII", raw, 0)
        size_hi = struct.unpack_from("<I", raw, 108)[0]
        size = size_lo | (size_hi << 32) if (flags & 0x80000000) else size_lo
        return dict(mode=mode, size=size, flags=flags, links=links,
                    uid=uid, gid=gid)

    def extents(self, area, size):
        """解析 extent 树, 返回 [(phys_start, count)]。"""
        out = []
        magic = struct.unpack_from("<H", area, 0)[0]
        if magic != 0xF30A:
            return out
        entries, max_entries, depth = struct.unpack_from("<HHH", area, 2)
        for i in range(entries):
            p = 12 + i * 12
            if p + 12 > len(area):
                break
            ee_block, ee_len, ee_start_hi, ee_start_lo = struct.unpack_from(
                "<IHHI", area, p)
            if ee_len > 32768:
                ee_len -= 32768
            phys = ee_start_lo | (ee_start_hi << 32)
            if depth == 0:
                out.append((phys, ee_len))
            else:
                out.extend(self.extents(self.read_block(phys), size))
        return out

    def inode_blocks(self, ino):
        raw = self.read_inode(ino)
        info = self.inode_fields(raw)
        out = []
        magic = struct.unpack_from("<H", raw, 0x28)[0]
        if magic == 0xF30A:
            out = self.extents(raw[0x28:0x28 + 60], info["size"])
        else:
            n = self.block_size // 4
            for b in struct.unpack_from("<15I", raw, 40):
                if b:
                    out.append((b, 1))
            for b in struct.unpack_from("<12I", raw, 100):
                if b:
                    for x in struct.unpack_from("<%dI" % n, self.read_block(b), 0):
                        if x:
                            out.append((x, 1))
            for b in struct.unpack_from("<12I", raw, 148):
                if b:
                    for x in struct.unpack_from("<%dI" % n, self.read_block(b), 0):
                        if x:
                            for y in struct.unpack_from("<%dI" % n, self.read_block(x), 0):
                                if y:
                                    out.append((y, 1))
        return info, out

    def read_file(self, ino):
        info, blocks = self.inode_blocks(ino)
        data = bytearray()
        for start, cnt in blocks:
            for i in range(cnt):
                data += self.read_block(start + i)
        return bytes(data[:info["size"]])

    def listdir(self, ino):
        """返回 [(name, inode, is_dir, size)]。"""
        info, blocks = self.inode_blocks(ino)
        out = []
        for start, cnt in blocks:
            for i in range(cnt):
                d = self.read_block(start + i)
                off = 0
                while off < len(d) - 8:
                    ino_, rec_len, name_len, ft = struct.unpack_from("<IHBB", d, off)
                    if rec_len < 8 or ino_ == 0:
                        break
                    name = d[off + 8:off + 8 + name_len].split(b"\0")[0].decode("utf-8", "replace")
                    if name not in (".", ".."):
                        out.append((name, ino_, ft == 2, 0))
                    off += rec_len
        res = []
        for name, i, isdir, _ in out:
            try:
                f = self.inode_fields(self.read_inode(i))
                res.append((name, i, isdir, f["size"]))
            except Exception:
                res.append((name, i, isdir, 0))
        return res

    def lookup(self, path):
        """路径解析, 返回 (inode, is_dir)。"""
        cur = ROOT_INODE
        last = True
        for part in [p for p in path.split("/") if p]:
            found = None
            for name, i, isdir, _ in self.listdir(cur):
                if name == part:
                    found = (i, isdir)
                    break
            if not found:
                return None, None
            cur, last = found
        return cur, last


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    args = sys.argv[2:]
    fs = Ext4(path)
    print("=== %s ===" % os.path.basename(path))
    print("  块大小=%d inode 数=%d 每组 inode=%d 卷名=%r"
          % (fs.block_size, fs.inodes_count, fs.inodes_per_group, fs.volume_name))
    print("  GDT @0x%x  inode 表 = 位图块+1" % fs.gdt_off)

    if not args:
        return 0

    if args[0] == "--ls":
        target = args[1] if len(args) > 1 else "/"
        ino, _ = fs.lookup(target)
        if ino is None:
            print("  找不到 %s" % target)
            return 1
        for name, i, isdir, size in sorted(fs.listdir(ino)):
            print("  %-52s %-5s %10d  ino=%d"
                  % (name, "DIR" if isdir else "", size, i))
        return 0

    if args[0] == "--find":
        needle = args[1]
        print("  搜索 '%s' ..." % needle)
        found = []

        def walk(ino, prefix, depth=0):
            if depth > 8:
                return
            try:
                items = fs.listdir(ino)
            except Exception:
                return          # 个别 inode 读失败就跳过, 不中断整棵树
            for name, i, isdir, size in items:
                p = prefix + "/" + name
                if needle in name:
                    found.append((p, size, isdir))
                if isdir:
                    walk(i, p, depth + 1)

        walk(ROOT_INODE, "")
        for p, size, isdir in found:
            print("  ★ %-62s %10d %s" % (p, size, "<DIR>" if isdir else ""))
        if not found:
            print("  未找到")
        return 0

    for p in args:
        ino, isdir = fs.lookup(p)
        if ino is None:
            print("  [FAIL] 找不到 %s" % p)
            continue
        if isdir:
            print("  %s 是目录:" % p)
            for name, i, d, size in sorted(fs.listdir(ino)):
                print("    %-48s %-5s %d" % (name, "<DIR>" if d else "", size))
        else:
            data = fs.read_file(ino)
            out = p.strip("/").replace("/", "_") or "root"
            with open(out, "wb") as f:
                f.write(data)
            print("  已导出 %s -> %s (%d 字节)" % (p, out, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
