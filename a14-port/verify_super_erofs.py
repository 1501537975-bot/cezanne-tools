import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_super import build_logical_map, read_logical

D = r"D:\cezanne-work"
SUPER = os.path.join(D, "rebuild", "super_cezanne.img")

SYST_START_SECTOR = 9934848
EROFS_SUPER_OFFSET = 1024
EROFS_SUPER_MAGIC_V1 = 0xE0F5E1E2

print("=== 从新 super (sparse) 读 system 的 EROFS 超级块 ===")
maps, logical = build_logical_map(SUPER)
print("  RAW 段 %d 个, 逻辑总大小 %.2f GB" % (len(maps), logical / 1024**3))

off = SYST_START_SECTOR * 512 + EROFS_SUPER_OFFSET
data = read_logical(SUPER, maps, off, 128)
import struct

magic, = struct.unpack_from("<I", data, 0)
print("  逻辑偏移 0x%x -> magic=0x%08x" % (off, magic))

if magic != EROFS_SUPER_MAGIC_V1:
    print("  [FAIL] 不是 EROFS 超级块")
    # 扫一下这个区间找 EROFS magic
    print("  扫 0x%x..0x%x 找 EROFS magic ..." % (
        SYST_START_SECTOR * 512, (SYST_START_SECTOR + 8192) * 512))
    for probe in range(SYST_START_SECTOR * 512, (SYST_START_SECTOR + 8192) * 512, 512):
        d = read_logical(SUPER, maps, probe, 8)
        if len(d) >= 4:
            m, = struct.unpack_from("<I", d, 0)
            if m == EROFS_SUPER_MAGIC_V1:
                print("  → 找到! 在逻辑偏移 0x%x (sector +%d)" % (probe, (probe - SYST_START_SECTOR * 512) // 512))
                break
    sys.exit(1)

blkszbits = data[12]
inos = struct.unpack_from("<Q", data, 16)[0]
blocks = struct.unpack_from("<I", data, 36)[0]
feat_compat = struct.unpack_from("<I", data, 8)[0]
feat_incompat = struct.unpack_from("<I", data, 92)[0]
print()
print("  OK magic = 0x%08X" % magic)
print("    块大小     = %d" % (1 << blkszbits))
print("    inode 数   = %d" % inos)
print("    总块数     = %d" % blocks)
print("    feature_compat   = 0x%08x" % feat_compat)
print("    feature_incompat = 0x%08x" % feat_incompat)
print()
print("  ✓ 新 super 里的 system 确认是 EROFS, 与自编内核的驱动格式匹配")
