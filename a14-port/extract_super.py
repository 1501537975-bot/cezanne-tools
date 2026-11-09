#!/usr/bin/env python3
"""
从 Android super.img (dynamic partition) 中提取指定分区。

super.img 是两层结构:
  第 1 层: Android sparse (magic 0xed26ff3a) —— 稀疏封装
  第 2 层: super 分区格式 (magic 0x616c4467 "gDla") —— 动态分区表

本脚本的实测要点 (MTK cezanne 原厂包):
  · 第一个 chunk 是 FILL(1 块) = 4096 字节全零
  · 真正的 super header (gDla) 位于**文件偏移 56**,
    对应**逻辑偏移 4096** (0x1000)
  · 紧接着 0x1000+56 = 0x1038 处是第二个 gDla —— 那是 geometry 信息
  → 所以必须跳过逻辑 0 的那 4096 字节填充块

用法:
  python3 extract_super.py <super.img> <输出目录> [分区名...]
  不给分区名则列出全部分区
"""
import os
import struct
import sys

SPARSE_MAGIC = 0xED26FF3A
SUPER_MAGIC = 0x616C4467
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4


def build_logical_map(src_path):
    """走一遍 sparse chunk, 产出 逻辑偏移 -> (文件偏移, 字节数) 的映射。

    返回 (映射列表, 逻辑总大小)。映射按逻辑偏移升序。
    DONT_CARE / FILL 区域不产生映射 —— read_logical 会用零补齐这些空洞。

    ★ 若输入不是 sparse 镜像 (K40G 包里 zstd 解出来的就是裸 super),
      返回单个覆盖整个文件的大映射, 逻辑偏移 = 文件偏移。
    """
    maps = []
    logical = 0
    with open(src_path, "rb") as f:
        hdr = f.read(28)
        magic, major, minor, fhs, chs, blk, tb, tc, cks = struct.unpack_from("<IHHHHIIII", hdr, 0)
        if magic != SPARSE_MAGIC:
            # 裸 super 镜像 —— 逻辑偏移 = 文件偏移
            size = os.path.getsize(src_path)
            return [(0, 0, size)], size

        f.seek(fhs)
        for _ in range(tc):
            ch = f.read(chs)
            if len(ch) < chs:
                break
            ctype, _res, chunk_sz, _total_sz = struct.unpack_from("<HHII", ch, 0)
            if ctype == CHUNK_RAW:
                maps.append((logical, f.tell(), chunk_sz * blk))
                f.seek(chunk_sz * blk, 1)
                logical += chunk_sz * blk
            elif ctype == CHUNK_FILL:
                f.seek(4, 1)
                logical += chunk_sz * blk
            elif ctype == CHUNK_DONT_CARE:
                logical += chunk_sz * blk
            elif ctype == CHUNK_CRC32:
                f.seek(4, 1)
            else:
                raise ValueError("未知 chunk type 0x%x" % ctype)

    return maps, logical


def read_logical(src_path, maps, offset, size):
    """按逻辑偏移读取 size 字节。

    关键: sparse 的 FILL / DONT_CARE chunk 在物理文件里没有对应数据,
    但它们**占据逻辑空间**。所以必须按逻辑偏移精确重建,
    空洞部分用零填充 —— 否则逻辑偏移会整体前移, 找不到 super header。
    """
    out = bytearray()
    end = offset + size
    with open(src_path, "rb") as f:
        for m_off, m_file, m_len in maps:
            if m_off >= end:
                break
            m_end = m_off + m_len
            if m_end <= offset:
                # 这个 RAW 段完全在请求区间之前 —— 但中间可能有空洞要补零
                if len(out) < (m_off - offset):
                    out += b"\0" * (m_off - offset - len(out))
                continue
            lo = max(offset, m_off)
            hi = min(end, m_end)
            if len(out) < (lo - offset):
                out += b"\0" * (lo - offset - len(out))
            f.seek(m_file + (lo - m_off))
            out += f.read(hi - lo)
        if len(out) < size:
            out += b"\0" * (size - len(out))
    return bytes(out)


def parse_super(data, maps, src_path, out_dir, wanted):
    # 在前 64KB 内找 gDla
    head = data[:65536]
    pos = head.find(b"gDla")
    if pos < 0:
        raise ValueError("前 64KB 内找不到 gDla")

    # ★ SuperGeometry / GEET 布局 (AOSP liblp, 52 字节):
    #   u32 magic          = 0x616c4467 ("gDla")
    #   u32 struct_size    = 52
    #   u8  checksum[32]
    #   u32 metadata_max_size
    #   u32 metadata_slot_count
    #   u32 logical_block_size
    magic = struct.unpack_from("<I", data, pos)[0]
    struct_size = struct.unpack_from("<I", data, pos + 4)[0]
    meta_max, slot_cnt, lblk = struct.unpack_from("<III", data, pos + 40)
    print("  [super] geometry @0x%x struct_size=%d metadata_max_size=%d slot_count=%d logical_block_size=%d"
          % (pos, struct_size, meta_max, slot_cnt, lblk))

    # metadata slot 0 的 GEET 头紧跟其后 (间隔 = metadata_max_size 对齐)
    # 实测: geometry @0x1000, slot0 @0x2000
    slot0 = pos + 0x1000
    if data[slot0:slot0 + 4] != b"gDla":
        # 扫描找下一个 gDla
        slot0 = data.find(b"gDla", pos + 52)
        if slot0 < 0:
            raise ValueError("找不到 metadata slot 0")
    print("  [super] metadata slot 0 @0x%x" % slot0)

    # slot0 的 GEET 头之后是它的 entry 表
    g_hdr_sz, g_geom_sz = struct.unpack_from("<II", data, slot0 + 12)
    ent_off = slot0 + 52
    parts = []
    while ent_off + 24 <= len(data):
        em, _pad, emaj, emin, edata_sz, emeta_sz, emeta_blk = struct.unpack_from(
            "<IHHIIII", data, ent_off)
        if em != 0x616C4467:
            break
        parts.append(dict(major=emaj, minor=emin, data_sz=edata_sz,
                          meta_sz=emeta_sz, meta_blk=emeta_blk))
        ent_off += 24

    primary = None
    for p in parts:
        if p["major"] == 0:
            primary = p
            break
    if primary is None:
        raise ValueError("找不到 primary 元数据块")

    # primary 元数据块内的分区表
    pm_off = slot0 + primary["meta_blk"] * lblk
    pm_magic, pm_major, pm_minor, pm_hdr_sz, pm_geom_sz, pm_flags = struct.unpack_from(
        "<IHHIII", data, pm_off)
    te_size, te_count, te_off = struct.unpack_from("<III", data, pm_off + pm_hdr_sz)
    base = pm_off + pm_hdr_sz + te_off
    print("  [super] 分区数 = %d (entry_size=%d)" % (te_count, te_size))

    results = {}
    for i in range(te_count):
        e = base + i * te_size
        emaj, emin, attr, esize, erofs, eflags = struct.unpack_from("<HHIIQI", data, e)
        name = data[e + 48:e + 48 + 36].split(b"\0")[0].decode("utf-8", "replace")
        results[name] = dict(major=emaj, minor=emin, attr=attr, size=esize,
                              rofs=erofs, flags=eflags)

    print()
    print("  %-22s %-6s %-12s %s" % ("分区", "属性", "大小", "flags"))
    print("  " + "-" * 58)
    for name, r in sorted(results.items()):
        attr = "RO" if (r["attr"] & 1) else "RW"
        print("  %-22s %-6s %-12d 0x%x" % (name, attr, r["size"], r["flags"]))

    if not wanted:
        return results

    # 扩展索引 (extents) 在主元数据块的分区表之后
    ext_off = pm_off + pm_hdr_sz + (te_count * te_size)
    extents = {}
    cur = ext_off
    while cur + 16 <= len(data):
        xm, xtype, xdata_sz, xents = struct.unpack_from("<IIII", data, cur)
        if xm != SUPER_MAGIC:
            break
        if xtype == 0x2C7A:  # EXTENTS
            for k in range(xents):
                eo = cur + 16 + k * 24
                num_sectors, target_type, target_data, target_meta = struct.unpack_from(
                    "<QIQI", data, eo)
                extents.setdefault((target_meta, target_type), []).append(
                    (target_data, num_sectors))
        cur += 16 + xents * 24

    os.makedirs(out_dir, exist_ok=True)
    for name in wanted:
        if name not in results:
            print("  [warn] 没有分区 %s" % name)
            continue
        r = results[name]
        ext = extents.get((r["major"], 0), [])
        if not ext:
            print("  [warn] 分区 %s 没有 extent 信息, 跳过" % name)
            continue

        # 分区数据在 super 数据区中的位置:
        #   super 数据区起点 = metadata 区结束处
        #   target_data 是相对该起点的 512 字节扇区号
        data_region = meta_start + gmeta_max
        out_path = os.path.join(out_dir, name + ".img")
        written = 0
        with open(out_path, "wb") as out:
            for (tgt_data, num_sec) in sorted(ext):
                off = data_region + tgt_data * 512
                chunk = read_logical(src_path, maps, off, num_sec * 512)
                out.write(chunk)
                written += len(chunk)
        print("  [ok] 已提取 %-14s -> %s  (%d 字节)" % (name, out_path, written))

    return results


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    out_dir = sys.argv[2]
    wanted = sys.argv[3:]

    print("解析: %s" % src)
    maps, logical = build_logical_map(src)
    print("  [sparse] RAW 段 %d 个, 逻辑总大小 %.2f GB" % (len(maps), logical / 1024**3))

    # super header 在前 64KB 内
    head = read_logical(src, maps, 0, 65536)
    try:
        parse_super(head, maps, src, out_dir, wanted)
    except Exception as e:
        print("  [FAIL] %s" % e)
        sys.exit(1)


if __name__ == "__main__":
    main()
