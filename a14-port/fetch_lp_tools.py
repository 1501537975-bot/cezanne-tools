#!/usr/bin/env python3
"""
下载 AOSP partition tools (Windows 版) —— lpmake / lpunpack / lpdumps /
img2simg / simg2img / ext2simg / append2simg。

来源: Rprop/aosp15_partition_tools (静态链接, 官方 AOSP 15 版)

用法:
  python3 fetch_lp_tools.py <输出目录>
"""
import json
import io
import os
import subprocess
import sys

TOKEN = None
out = subprocess.run(["git", "credential", "fill"], input=b"protocol=https\nhost=github.com\n\n",
                     capture_output=True, timeout=20).stdout.decode("utf-8", "replace")
for line in out.splitlines():
    if line.startswith("password="):
        TOKEN = line.split("=", 1)[1]
if not TOKEN:
    print("[FAIL] 取不到 GitHub token")
    sys.exit(1)

REPO = "Rprop/aosp15_partition_tools"
BRANCH = "main"
API_IP = "140.82.113.6"
RAW_IP = "185.199.108.133"

WANT = ["lpmake.exe", "lpunpack.exe", "lpdumps.exe", "img2simg.exe",
        "simg2img.exe", "ext2simg.exe", "append2simg.exe", "lpadd.exe"]


def gh(path):
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "_gh_t.json")
    subprocess.run(["curl", "-s", "--max-time", "30", "--resolve",
                    "api.github.com:443:" + API_IP,
                    "-H", "Accept: application/vnd.github+json",
                    "-H", "Authorization: Bearer " + TOKEN,
                    "https://api.github.com" + path, "-o", tmp], capture_output=True)
    try:
        return json.load(io.open(tmp, encoding="utf-8"))
    except Exception as e:
        return {"_error": str(e)}


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else "./lp_tools"
    os.makedirs(dest, exist_ok=True)

    d = gh("/repos/%s/git/trees/%s?recursive=1" % (REPO, BRANCH))
    tree = d.get("tree", [])
    if not tree:
        print("[FAIL] 拿不到仓库树:", d.get("_error", d.get("message")))
        return 1

    files = {}
    for x in tree:
        name = x["path"].split("/")[-1]
        if name in WANT and x.get("type") == "blob":
            files[name] = x

    if not files:
        print("[FAIL] 没找到目标文件")
        return 1

    print("=== 下载 %d 个文件 ===" % len(files))
    ok = 0
    for name, x in files.items():
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (REPO, BRANCH, x["path"])
        out_path = os.path.join(dest, name)
        # GitHub raw 用不同 IP 池, 逐个试
        done = False
        for ip in (RAW_IP, "185.199.109.133", "185.199.110.133", "185.199.111.133"):
            r = subprocess.run(["curl", "-sL", "--max-time", "90", "--resolve",
                                "raw.githubusercontent.com:443:" + ip, url, "-o", out_path],
                               capture_output=True)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
                sz = os.path.getsize(out_path)
                print("  [OK] %-18s %8.1f MB" % (name, sz / 1024**2))
                ok += 1
                done = True
                break
        if not done:
            print("  [FAIL] %s 下载失败" % name)

    print()
    print("=== 验证 ===")
    for name in sorted(os.listdir(dest)):
        p = os.path.join(dest, name)
        if not os.path.isfile(p):
            continue
        sz = os.path.getsize(p)
        with open(p, "rb") as f:
            magic = f.read(2)
        kind = "PE/EXE" if magic == b"MZ" else ("ELF" if magic == b"\x7fE" else "?")
        print("  %-18s %8.1f MB  %s" % (name, sz / 1024**2, kind))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
