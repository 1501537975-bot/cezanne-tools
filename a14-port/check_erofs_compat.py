#!/usr/bin/env python3
"""
检查 erofs 源码在 4.14.186 下可能的编译问题。

★ 重点检查:
  1. 用了 4.14 没有的内核 API
  2. 用到 4.16+ 才有的结构体字段
  3. 用到 EROFS_FS_ZIP 才有的符号 (但我们关掉了 ZIP)
"""
import os
import re
import sys

SRC = r"C:\Users\纪\WorkBuddy\2026-11-05-00-02-58\kernel-bpf\patches\erofs\fs\erofs"

# 4.16+ 才有的内核 API (在 4.14 里不存在)
NEW_APIS = [
    "add_vmap", "vmap_pages", "mapping_set_writable", "vma->vm_flags",
    "set_page_ext", "folio_file_page", "filemap_get_folio",
    "vfs_fadvise", "vfs_read", "vfs_write", "kernel_read_file",
    "mremap", "mmap_write", "do_dentry", "d_alloc",
    "IS_ERR", "errseq_t", "errseq_check_and_advance",
    "bio_alloc", "bio_add_page",
    "cpus_read_u32", "cpus_read_le32",
    "down_read_killable", "percpu_down_read",
    "memset_explicit",
    "bdev_discard", "blkdev_issue_flush",
    "xattr_handler", "xattr_prefix",
    "strscpy", "strscpy_pad",
    "get_random_long", "prandom_u32_max",
    "folio", "Folio",
]

# 4.16+ 才有的结构体字段
NEW_FIELDS = [
    r"\.rmd\b", r"->rmd", r"\.folio", r"->folio",
    r"sb->s_opflags", r"->s_flags",
]


def main():
    if not os.path.isdir(SRC):
        print("找不到 erofs 源码:", SRC)
        return 1

    files = [f for f in os.listdir(SRC) if f.endswith((".c", ".h"))]
    print("检查 %d 个文件 (%s)" % (len(files), SRC))
    print()

    issues = []
    for fn in sorted(files):
        path = os.path.join(SRC, fn)
        data = open(path, "r", encoding="utf-8", errors="replace").read()
        for i, line in enumerate(data.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("*") or stripped.startswith("/*"):
                continue
            for api in NEW_APIS:
                if api in stripped:
                    issues.append((fn, i, api, stripped[:90]))

    if not issues:
        print("★ 未发现 4.16+ 专有 API 的使用")
    else:
        print("★ 发现 %d 处可能不兼容的 API:" % len(issues))
        for fn, i, api, txt in issues:
            print("  %-18s 行%-5d %-24s %s" % (fn, i, api, txt))

    print()
    print("=== ZIP 相关符号 (我们关掉了 CONFIG_EROFS_FS_ZIP) ===")
    zip_syms = ["z_erofs", "z_decompress", "ZIP_ENABLE", "EROFS_FS_ZIP",
                "z_erofs_map_iter", "z_erofs_vle_compress"]
    for fn in sorted(files):
        data = open(path := os.path.join(SRC, fn), "r",
                    encoding="utf-8", errors="replace").read()
        for i, line in enumerate(data.splitlines(), 1):
            s = line.strip()
            if s.startswith("*"):
                continue
            for sym in zip_syms:
                if sym in s:
                    print("  %-18s 行%-5d %s" % (fn, i, s[:80]))

    print()
    print("=== 每个 .c 的 #ifdef 保护检查 ===")
    for fn in sorted(f for f in files if f.endswith(".c")):
        data = open(os.path.join(SRC, fn), "r",
                    encoding="utf-8", errors="replace").read()
        guards = set(re.findall(r"#ifdef\s+(CONFIG_\w+)", data))
        print("  %-18s 守卫: %s" % (fn, ", ".join(sorted(guards)) or "(无)"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
