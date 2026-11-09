# cezanne 刷机工具集

> Redmi K30 至尊纪念版（cezanne / MT6889 / 天玑1000+）刷 Android 16/17 的完整工具链与调研成果
> 2026-11-10

## 目录结构

```
a14-port/          分析与适配工具（主力）
tools/kernel-scripts/  内核构建脚本（与 kernel-bpf 仓库同步的副本）
```

## 一、核心结论（先看这个）

1. **移植包的分区全是 EROFS**（magic `0xE0F5E1E2`），而 cezanne 原厂内核**没有 EROFS 驱动**
   → 自编内核是**必需项**，不是可选项
2. **K40G (MT6893) 的 dtbo/vendor 不能用**（MT6889 ≠ MT6893，硬件全不同）
   → dtbo 和 vendor **必须用 cezanne 原厂**
3. **移植包的 system/product/system_ext 可以用**（用户空间，跨 SoC 通用）
4. **必须用能加载原厂 vendor 的内核**：vermagic 必须是
   `4.14.186-perf-00252-g2f26b5917fd6`，才能加载原厂那 10 个 `.ko`

## 二、四个环节的工具

| 环节 | 工具 | 说明 |
|---|---|---|
| 内核 | `kernel-bpf/` 仓库 | GitHub Actions 云编译，产出 AnyKernel3 包 |
| super 重组 | `rebuild_super.sh` | lpunpack + lpmake + img2simg |
| ramdisk 适配 | `adapt_ramdisk_full.sh` | 提取原厂 MT6885 rc + 5 项适配 + 重打包 |
| boot.img 组装 | `make_boot.py` | 用原厂 boot 头组装 |

### 完整流程

```bash
# 1. super 重组 (移植包的 system/product/system_ext + 原厂 vendor)
bash a14-port/rebuild_super.sh <移植包super.img> <原厂super.img> <工作目录>

# 2. ramdisk 适配 (一步到位: 提取原厂 rc + 适配 + 重打包 + 验证)
bash a14-port/adapt_ramdisk_full.sh \
  <移植包boot.img> <原厂boot.img> <原厂vendor.img> <工作目录>

# 3. boot.img 组装
python3 a14-port/make_boot.py \
  --orig <原厂boot.img> --kernel <Image.gz> --ramdisk <ramdisk.img> --out <boot.img>

# 4. 自检
python3 a14-port/selftest.py
```

## 三、底层工具

| 工具 | 用途 | 关键点 |
|---|---|---|
| `ramdisk_tools.py` | boot.img 解剖 + cpio 解析 | **cpio newc 字段是 ASCII 十六进制**，header=110 字节 |
| `repack_ramdisk.py` | cpio 重打包 | 对齐规则：header+name→4字节→data→4字节 |
| `ext4.py` | 纯 Python ext4 只读解析 | **inode 表 = inode 位图的下一个块**；extent magic @inode+0x28 |
| `extract_super.py` | super.img 双层解包 | sparse 首 chunk 是 FILL(4096B)，header 在逻辑 0x1000 |
| `extract_mt6885_rc.py` | 从原厂 vendor 提取 MT6885 的 .rc | 129 个文件（ueventd.rc 等） |

## 四、外部依赖

**AOSP partition 工具（Windows 原生）** —— `fetch_lp_tools.py` 自动下载
```
lpmake.exe  lpunpack.exe  lpdumps.exe  lpadd.exe
img2simg.exe  simg2img.exe  ext2simg.exe  append2simg.exe
```
来源：`Rprop/aosp15_partition_tools`（Android 15 静态编译版）

## 五、报告

| 文件 | 内容 |
|---|---|
| `完整执行清单.md` | **从零到刷机的完整步骤** |
| `三个文件深度分析报告.md` | 用户提供的三个文件的字节级分析 |
| `三个文件的价值-阶段性结论.md` | 那三个文件到底有什么用 |
| `酷安K30至尊专项_完整技术链.md` | 酷安专项调研（A16/A17 在 4.14 上跑通的配方） |
| `现状与下一步.md` | 进度快照 |

## 六、踩坑速查

| 坑 | 症状 | 解法 |
|---|---|---|
| `setlocalversion` 双渠道 | 版本后缀翻倍 | `.config` 留空 + 只走 make 命令行 |
| `set -e` + grep | 脚本静默退出无报错 | 全加 `\|\| true`；用 `scan_sete.py` 扫 |
| `set -u` + 未定义变量 | 同样静默退出 | 用 `check_undef_vars.py` 扫 |
| cpio newc 格式 | 解析出乱码名字 | 字段是 **ASCII 十六进制**不是二进制 |
| EROFS magic | 认成 `e2e1f0e3` | 实际是 **`0xE0F5E1E2`** |
| super.img | 找不到 gDla | sparse 首 chunk 是 FILL，header 在**逻辑 0x1000** |
| ext4 inode | 读到全 0xff | inode 表 = inode 位图的**下一个块** |
| bash heredoc | 中文/特殊字符被吞 | 用 Write 工具写文件 + 运行时自检 |
| GitHub push | TLS handshake failed | DNS 被劫持到 fake-IP，用 `curloptResolve` |

## 七、内核构建仓库

https://github.com/1501537975-bot/kernel-bpf

自编内核的 CI 流水线。关键脚本：
- `scan_sete.py` —— shell set -e 静默退出扫描器
- `check_undef_vars.py` —— shell 未定义变量扫描器
- `force_release.sh` —— setlocalversion 强制改写（版本串兜底）
- `patches/erofs/` —— 预置的 EROFS 源码（来自 mt6873-dev 4.14.336 原生版）
