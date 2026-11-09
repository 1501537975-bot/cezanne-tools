import json, io, os, subprocess, sys

TOKEN = None
out = subprocess.run(["git", "credential", "fill"], input=b"protocol=https\nhost=github.com\n\n",
                     capture_output=True, timeout=20).stdout.decode("utf-8", "replace")
for line in out.splitlines():
    if line.startswith("password="):
        TOKEN = line.split("=", 1)[1]
if not TOKEN:
    print("[FAIL] 无 token")
    sys.exit(1)

RUN = sys.argv[1] if len(sys.argv) > 1 else "42653888338"
DEST = r"D:\cezanne-work\artifacts"
REPO = "1501537975-bot/kernel-bpf"
os.makedirs(DEST, exist_ok=True)
TMP = os.path.join(DEST, "_tmp")


def api(path, binary=False):
    subprocess.run(["curl", "-sL", "--max-time", "60", "--resolve",
                    "api.github.com:443:140.82.113.6",
                    "-H", "Accept: application/vnd.github+json",
                    "-H", "Authorization: Bearer " + TOKEN,
                    "https://api.github.com" + path, "-o", TMP], capture_output=True)
    if binary:
        return open(TMP, "rb").read()
    try:
        return json.load(io.open(TMP, encoding="utf-8"))
    except Exception as e:
        return {"_error": str(e)}


d = api("/repos/%s/actions/runs/%s/artifacts" % (REPO, RUN))
arts = d.get("artifacts", [])
if not arts:
    print("[FAIL]", d.get("_error"), d.get("message"))
    sys.exit(1)

for a in arts:
    print("artifact: %s | %d 字节 | id=%s" % (a["name"], a["size_in_bytes"], a["id"]))
    outp = os.path.join(DEST, "r%s_%s.zip" % (RUN, a["name"]))
    url = "https://api.github.com/repos/%s/actions/artifacts/%s/zip" % (REPO, a["id"])
    for attempt in range(5):
        subprocess.run(["curl", "-sL", "--retry", "8", "--retry-all-errors",
                        "--retry-delay", "4", "--max-time", "1800",
                        "--resolve", "api.github.com:443:140.82.113.6",
                        "-H", "Accept: application/vnd.github+json",
                        "-H", "Authorization: Bearer " + TOKEN,
                        url, "-o", outp], capture_output=True)
        sz = os.path.getsize(outp) if os.path.exists(outp) else 0
        print("  下载 %d / %d 字节" % (sz, a["size_in_bytes"]))
        if sz == a["size_in_bytes"]:
            print("  [OK] %s" % outp)
            break
    else:
        print("  [FAIL] 下载不完整")
if os.path.exists(TMP):
    os.remove(TMP)
