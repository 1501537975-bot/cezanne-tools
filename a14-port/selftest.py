#!/usr/bin/env python3
"""
全面功能自检 —— 确保所有工具在当前磁盘状态下真的能用。

★ 起因: bash 的 heredoc 会吞字符, 曾把 ext4.py 的
   "self.group_desc(g)" 写成 "self.group(g)" (语法仍合法, 运行才炸)。
   → 语法检查不够, 必须跑真实数据。
"""
import os
import subprocess
import sys

TOOLS = r"C:\Users\纪\WorkBuddy\2026-11-05-00-02-58\a14-port"
D = r"D:\cezanne-work"
sys.path.insert(0, TOOLS)

ok = fail = 0


def test(name, fn):
    global ok, fail
    try:
        r = fn()
        print("  [OK]   %-42s %s" % (name, r if r else ""))
        ok += 1
    except Exception as e:
        print("  [FAIL] %-42s %s: %s" % (name, type(e).__name__, e))
        fail += 1


print("=== 1. ramdisk_tools ===")
from ramdisk_tools import load_boot, cpio_mkbootfs


def t_boot():
    k, rd, c, n = load_boot(os.path.join(D, "rd_work", "..", "..", "rd_work", "rd_src"))
    return "cmdline=%s" % c[:40]


# 改用真实 boot.img
def t_boot2():
    src = r"D:\123pan\Downloads\K40G_Android16_OS3.0.311.0-Fiagelia-26.9.19\no-root\boot.img"
    k, rd, c, n = load_boot(src)
    ents = cpio_mkbootfs(rd)
    return "内核 %d 字节, ramdisk %d 字节, %d 个条目" % (len(k), len(rd), len(ents))


test("load_boot + cpio 解析", t_boot2)


def t_cpio_roundtrip():
    import gzip
    p = os.path.join(D, "rd_work", "ramdisk.img")
    blob = gzip.decompress(open(p, "rb").read())
    ents = cpio_mkbootfs(blob)
    names = {n for n, _, _ in ents}
    need = ("init", "avb/q-gsi.avbpubkey", "verity_key",
            "first_stage_ramdisk/fstab.emmc")
    miss = [k for k in need if k not in names]
    if miss:
        raise ValueError("缺 %s" % miss)
    return "%d 个条目, 关键文件齐全" % len(ents)


test("ramdisk cpio 闭环", t_cpio_roundtrip)

print()
print("=== 2. ext4 ===")
from ext4 import Ext4


def t_ext4():
    p = os.path.join(D, "rebuild", "orig_parts", "vendor.img")
    if not os.path.exists(p):
        return "跳过 (vendor.img 不在)"
    fs = Ext4(p)
    ents = fs.listdir(2)
    if not ents:
        raise ValueError("根目录为空")
    return "根目录 %d 项, 例如 %s" % (len(ents), ents[0][0])


test("ext4 listdir", t_ext4)

print()
print("=== 3. make_boot / ramdisk_tools 组合 ===")


def t_mkboot():
    out = os.path.join(D, "_selftest_boot.img")
    r = subprocess.run(
        [sys.executable, os.path.join(TOOLS, "make_boot.py"),
         "--orig", os.path.join(D, "firmware",
                               "cezanne_images_V12.5.11.0.RJNCNXM_20220301.0000.00_11.0_cn",
                               "images", "boot.img"),
         "--kernel", os.path.join(D, "artifacts", "extracted", "artifacts",
                                 "x_cezanne-kernel-bpf-2", "kernel", "Image.gz-dtb"),
         "--ramdisk", os.path.join(D, "rd_work", "ramdisk.img"),
         "--out", out],
        capture_output=True, timeout=600)
    if r.returncode != 0:
        raise ValueError(r.stderr.decode("utf-8", "replace")[-200:])
    # 读回验证
    k, rd, c, n = load_boot(out)
    ents = cpio_mkbootfs(rd)
    i = k.find(b"Linux version ")
    ver = k[i:k.find(b"\x00", i)].decode("utf-8", "replace").split("(")[0].strip()
    if "4.14.186-perf-00252-g2f26b5917fd6" not in ver:
        raise ValueError("版本串不对: %s" % ver)
    os.remove(out)
    return "boot.img %d 字节, 内核 %s, ramdisk %d 条" % (os.path.getsize(out) if os.path.exists(out) else 0, ver, len(ents))


test("make_boot + 回读验证", t_mkboot)

print()
print("=== 4. lpmake/lpunpack 工具 ===")


def t_lptools():
    t = os.path.join(D, "lp_tools")
    need = ["lpmake.exe", "lpunpack.exe", "lpdumps.exe", "img2simg.exe", "simg2img.exe"]
    miss = [n for n in need if not os.path.exists(os.path.join(t, n))]
    if miss:
        raise ValueError("缺 %s" % miss)
    return "%d 个工具齐全" % len(need)


test("AOSP partition 工具", t_lptools)

print()
print("=== 5. 内核产物 ===")


def t_kernel():
    p = os.path.join(D, "artifacts", "extracted", "kernel-release.txt")
    v = open(p).read().strip()
    if v != "4.14.186-perf-00252-g2f26b5917fd6":
        raise ValueError("版本串 %s" % v)
    return v


test("内核版本串", t_kernel)

print()
print("=== 6. super 产物 ===")


def t_super():
    p = os.path.join(D, "rebuild", "super_cezanne.img")
    if not os.path.exists(p):
        return "跳过"
    return "%d 字节 (sparse)" % os.path.getsize(p)


test("新 super.img", t_super)

print()
print("=" * 60)
print("通过 %d, 失败 %d" % (ok, fail))
sys.exit(1 if fail else 0)
