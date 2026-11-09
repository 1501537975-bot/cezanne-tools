#!/usr/bin/env python3
"""
最小 EROFS 只读解析器 —— 验证镜像的超级块能否被 EROFS 驱动识别。

★ 目的: 在刷机之前就确认 "自编的 EROFS 驱动 + 移植包的镜像" 格式匹配。
  依据的是内核 drivers 侧的真实格式定义:
    - EROFS_SUPER_OFFSET = 1024      (erofs_fs.h)
    - EROFS_SUPER_MAGIC_V1 = 0xE0F5E1E2

用法:
  python3 erofs_check.py <分区镜像> ...
"""
import os
import struct
import sys

EROFS_SUPER_OFFSET = 1024
EROFS_SUPER_MAGIC_V1 = 0xE0F5E1E2

# struct erofs_super_block (内核 fs/erofs/erofs_fs.h)
#   __le32 magic; __le32 checksum; __le32 feature_compat;
#   __u8 blkszbits; __u8 sb_extslots; __le16 root_nid;
#   __le64 inos; __le64 build_time; __le32 build_time_nsec;
#   __le32 blocks; __le32 meta_blkaddr; __le32 xattr_blkaddr;
#   __u8 uuid[16]; __u8 volume_name[16]; __le32 feature_incompat;
FMT = "<IIIBBHQQII I I 16s16s I"


def check(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(EROFS_SUPER_OFFSET)
        sb = f.read(128)
    if len(sb) < 128:
        print("  [FAIL] 读不到超级块")
        return False

    magic, = struct.unpack_from("<I", sb, 0)
    if magic != EROFS_SUPER_MAGIC_V1:
        print("  [FAIL] magic=0x%08x (期望 0x%08X)" % (magic, EROFS_SUPER_MAGIC_V1))
        return False

    (magic, checksum, feat_compat, blkszbits, sb_extslots, root_nid,
     inos, build_time, bt_nsec, blocks, meta_blkaddr, xattr_blkaddr,
     uuid, volname, feat_incompat) = struct.unpack(FMT, sb[:128])

    print("  ✓ magic=0x%08X" % magic)
    print("    块大小      = %d (blkszbits=%d)" % (1 << blkszbits, blkszbits))
    print("    超级块扩展槽 = %d" % sb_extslots)
    print("    root_nid    = %d" % root_nid)
    print("    inode 数    = %d" % inos)
    print("    总块数      = %d" % blocks)
    print("    meta 起始块 = %d" % meta_blkaddr)
    print("    xattr 起始块= %d" % xattr_blkaddr)
    print("    feature_compat   = 0x%08x" % feat_compat)
    print("    feature_incompat = 0x%08x" % feat_incompat)
    print("    volume_name = %r" % volname.split(b"\0")[0].decode("utf-8", "replace"))

    # 兼容性判断
    print()
    ok = True
    if blkszbits != 12:
        print("  [WARN] 块大小不是 4096 —— 老驱动只支持 PAGE_SIZE")
        ok = False
    else:
        print("  [OK] 块大小 4096, 与 PAGE_SIZE 一致")
    if feat_compat & ~0x7:
        print("  [WARN] 有未知的 feature_compat 位 (0x%08x) —— 4.14 的驱动可能拒绝挂载" % feat_compat)
    else:
        print("  [OK] feature_compat 只含 SB_CHKSUM/Mtime/XattrFilter, 4.14 驱动都认")
    if feat_incompat & 0x2:
        print("  [WARN] feature_incompat 含 COMPR_CFGS/BIG_PCLUSTER")
    else:
        print("  [OK] feature_incompat 无压缩相关位 -> 不需要 CONFIG_EROFS_FS_ZIP")
    if blocks * (1 << blkszbits) > size:
        print("  [FAIL] 超级块声明的容量 %d > 文件大小 %d" % (blocks * (1 << blkszbits), size))
        ok = False
    else:
        print("  [OK] 容量声明合理 (文件 %d 字节)" % size)
    return ok


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    allok = True
    for p in sys.argv[1:]:
        print("=== %s ===" % os.path.basename(p))
        if not os.path.exists(p):
            print("  [SKIP] 不存在")
            continue
        if not check(p):
            allok = False
        print()
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
