#!/usr/bin/env python3
"""
从原厂 ext4 分区里提取 MT6885 专用的 .rc 文件。

用途: 移植包的 ramdisk 里是 ueventd.mt6893.rc / init.recovery.mt6893.rc,
这些是 K40G (MT6893) 专属的, 必须换成 cezanne (MT6885) 的版本,
否则硬件 (充电/指纹/摄像头/传感器) 会不工作。

用法:
  python3 extract_mt6885_rc.py <ext4分区镜像> <输出目录>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ext4 import Ext4


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    img = sys.argv[1]
    dest = sys.argv[2]
    os.makedirs(dest, exist_ok=True)

    fs = Ext4(img)
    print("=== %s ===" % os.path.basename(img))
    print("  块=%d inode 数=%d 卷名=%r"
          % (fs.block_size, fs.inodes_count, fs.volume_name))

    # 扫全树, 记录所有 .rc / fstab 文件
    all_rc = {}

    def walk(ino, prefix, depth=0):
        if depth > 10:
            return
        try:
            items = fs.listdir(ino)
        except Exception:
            return
        for name, i, isdir, size in items:
            p = (prefix + "/" + name).lstrip("/")
            if name.endswith(".rc") or name.startswith("fstab."):
                all_rc[p] = i
            if isdir:
                walk(i, prefix + "/" + name, depth + 1)

    walk(2, "")
    print()
    print("=== 分区里的 .rc / fstab 文件 (%d 个) ===" % len(all_rc))
    for p in sorted(all_rc):
        print("  %-58s ino=%d" % (p, all_rc[p]))

    # 导出
    print()
    print("=== 导出 ===")
    n = 0
    for p in sorted(all_rc):
        base = p.rsplit("/", 1)[-1]
        try:
            data = fs.read_file(all_rc[p])
        except Exception as e:
            print("  [FAIL] %s: %s" % (p, e))
            continue
        out = os.path.join(dest, base)
        with open(out, "wb") as f:
            f.write(data)
        print("  [OK] %-34s <- %s (%d 字节)" % (base, p, len(data)))
        n += 1
    print()
    print("共导出 %d 个 -> %s" % (n, dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
