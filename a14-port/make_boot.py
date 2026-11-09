#!/usr/bin/env python3
"""
为 cezanne 组装 boot.img。

用途:
    把移植包里的 **内核 + ramdisk** 与 **cezanne 原厂 boot.img 的头部** 组合,
    产出可直接 fastboot flash boot 的 boot.img。

为什么需要这个:
    移植包的 boot.img 自带 K40G (MT6893) 的内核与设备相关配置,
    但 **设备树不在 boot.img 里** —— 它在独立的 dtbo.img 分区。
    所以真正需要替换的只有 kernel + ramdisk, 头部参数
    (cmdline / page_size / header_version) 可以直接沿用原厂。

输入:
    --orig    cezanne 原厂 boot.img (提供头部模板)
    --kernel  内核文件 (Image.gz 或 Image)
    --ramdisk ramdisk 文件 (可选; 不给则沿用原厂的)
    --out     输出 boot.img

用法:
    python3 make_boot.py --orig <orig boot.img> \\
        --kernel <Image.gz> [--ramdisk <ramdisk.img>] --out <out boot.img>
"""
import argparse
import gzip
import os
import struct
import sys

BOOT_MAGIC = b"ANDROID!"


def read_boot_header(data):
    """解析 boot.img 头, 返回 (header_bytes, 解析结果 dict)。"""
    if data[:8] != BOOT_MAGIC:
        raise ValueError("不是标准 boot.img")
    (k_size, k_addr, r_size, r_addr, s_size, s_addr,
     t_addr, page_size, hdr_ver) = struct.unpack_from("<9I", data, 8)

    off = 8 + 36
    if hdr_ver >= 1:
        off += 4          # os_version

    fields = dict(
        kernel_size=k_size, kernel_addr=k_addr,
        ramdisk_size=r_size, ramdisk_addr=r_addr,
        second_size=s_size, second_addr=s_addr,
        tags_addr=t_addr, page_size=page_size,
        header_version=hdr_ver,
        name=data[off:off + 16],
        cmdline=data[off + 16:off + 16 + 512],
        id=data[off + 16 + 512:off + 16 + 512 + 32],
        extra_cmdline=data[off + 16 + 512 + 32:off + 16 + 512 + 32 + 1024],
    )
    # 头部总长 (到 extra_cmdline 结束)
    hdr_len = off + 16 + 512 + 32 + 1024
    return data[:hdr_len], fields


def main():
    ap = argparse.ArgumentParser(description="为 cezanne 组装 boot.img")
    ap.add_argument("--orig", required=True, help="cezanne 原厂 boot.img")
    ap.add_argument("--kernel", required=True, help="新内核文件")
    ap.add_argument("--ramdisk", help="新 ramdisk (可选)")
    ap.add_argument("--out", required=True, help="输出 boot.img")
    ap.add_argument("--kernel-addr", type=lambda x: int(x, 0), default=0x80000,
                    help="内核加载地址 (默认 0x80000)")
    ap.add_argument("--ramdisk-addr", type=lambda x: int(x, 0), default=0x1000000,
                    help="ramdisk 加载地址 (默认 0x1000000)")
    ap.add_argument("--tags-addr", type=lambda x: int(x, 0), default=0x100,
                    help="tags 地址 (默认 0x100)")
    args = ap.parse_args()

    with open(args.orig, "rb") as f:
        orig = f.read()
    hdr, fld = read_boot_header(orig)

    page = fld["page_size"]
    print("=== 原厂 boot.img 头 ===")
    print("  header_version=%d page_size=%d" % (fld["header_version"], page))
    print("  kernel_size=%d ramdisk_size=%d second_size=%d"
          % (fld["kernel_size"], fld["ramdisk_size"], fld["second_size"]))
    print("  cmdline=%s" % fld["cmdline"].split(b"\0")[0].decode("utf-8", "replace"))

    def page_align(x):
        return (x + page - 1) // page * page

    # ── 组装各段 ──
    with open(args.kernel, "rb") as f:
        kernel = f.read()
    if args.ramdisk:
        with open(args.ramdisk, "rb") as f:
            ramdisk = f.read()
    else:
        # 沿用原厂 ramdisk
        hdr_len = len(hdr)
        k_off = page_align(hdr_len)
        r_off = k_off + page_align(fld["kernel_size"])
        ramdisk = orig[r_off:r_off + fld["ramdisk_size"]]
        print("  [info] 未指定 ramdisk, 沿用原厂的 (%d 字节)" % len(ramdisk))

    second = b""
    if fld["second_size"]:
        k_off = page_align(len(hdr))
        r_off = k_off + page_align(fld["kernel_size"])
        s_off = r_off + page_align(fld["ramdisk_size"])
        second = orig[s_off:s_off + fld["second_size"]]

    print()
    print("=== 新段 ===")
    print("  kernel : %d 字节 (%.1f MB)" % (len(kernel), len(kernel) / 1024**2))
    print("  ramdisk: %d 字节 (%.1f MB)" % (len(ramdisk), len(ramdisk) / 1024**2))

    # ── 写新的头 ──
    out = bytearray()
    out += BOOT_MAGIC
    out += struct.pack("<9I",
                       len(kernel), args.kernel_addr,
                       len(ramdisk), args.ramdisk_addr,
                       len(second), fld["second_addr"],
                       args.tags_addr, page, fld["header_version"])
    # os_version (header_version >= 1)
    if fld["header_version"] >= 1:
        out += struct.pack("<I", 0)
    out += fld["name"]
    out += fld["cmdline"]
    out += fld["id"]
    out += fld["extra_cmdline"]

    # 补齐到页边界
    out += b"\0" * (page_align(len(out)) - len(out))

    out += kernel
    out += b"\0" * (page_align(len(kernel)) - len(kernel))
    out += ramdisk
    out += b"\0" * (page_align(len(ramdisk)) - len(ramdisk))
    if second:
        out += second
        out += b"\0" * (page_align(len(second)) - len(second))

    with open(args.out, "wb") as f:
        f.write(out)
    print()
    print("已生成: %s (%d 字节, %.1f MB)" % (args.out, len(out), len(out) / 1024**2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
