# Meizu 21 Pro 内核来源与构建路线核对

核对日期：2026-10-19，Asia/Hong_Kong。研究范围为用户指定的 GitHub 源码、源码维护者的设备树、PixelOS/Lineage 构建代码和 AOSP AVB 代码；没有操作手机、刷写或修改现有内核源码。下载的配置、构建文件与 API 元数据保存在 `sources/meizu21pro-kernel-reference/`。

## 结论

当前手机由主任务实测为 PixelOS 17 / Android 17，内核 `6.1.176-g19e9b13339e2`，构建日期 2026-09-28，编译器 Android Clang 22.0.2 / r596125。它与 `meizu-8650-kernel/android_kernel_meizu_sm8650` 的提交 `19e9b13339e26612844b620c2bdd54228dc6d836` 对得上。最可行的重建起点是该提交、手机实际 `.config`、r596125 工具链和独立干净输出目录。相同版本字符串、相同 Git HEAD、相同配置或模块 CRC 都不能证明新的 Image 可以启动；源树未提交修改、编译参数、模块签名与打包过程仍需核对。[S1][S2][L1]

通用 Qualcomm/GKI 的 Bazel 路线与当前 ROM 的直接 `make Image` 路线是两套构建。前者 `pineapple_gki` 用 `common:kernel_aarch64` 提供基础 Image/boot；当前设备树和 PixelOS 的常规 Android 构建则直接对 `kernel/meizu/sm8650` 编译 Image。复现当前 ROM 时应先采用后一条路线。不能仅因两者都是 6.1.176 就交换产物。[S3][S4][S5]

## 仓库与固定版本

| 仓库 | 本次固定提交 | 作用 |
| --- | --- | --- |
| `meizu-8650-kernel/kernel_manifest` | `a96a90fa48fd9a3b987c89cc0b6c7ebe0b1ba5b1` | seventeen 的完整 Qualcomm kernel platform 布局 |
| `meizu-8650-kernel/android_kernel_common_meizu_sm8650` | `043dfdbb9ba312acfc3a8e23718cd7b3194bb190` | Android common 6.1.176，供 mixed GKI 构建使用 |
| `meizu-8650-kernel/android_kernel_meizu_sm8650` | `19e9b13339e26612844b620c2bdd54228dc6d836` | Qualcomm/Meizu 内核源码；当前设备内核的 SCM 后缀对应这里 |
| `meizu-8650-kernel/kernel_platform_build` | `7e444f6ead7487733899768623c42b2e7571fac7` | Qualcomm legacy/Kleaf 构建脚本 |
| `meizu-8650-kernel/android_kernel_meizu_sm8650-devicetrees` | `5b59cc310c679ce5b4d93794d0a8a87b946f50aa` | Meizu/Qualcomm 设备树 |
| `meizu-8650-kernel/vendor_meizu_opensource_kernel-modules` | `dafe79bf5dbb772def7805a05ac917fa55ae9855` | Meizu 自定义模块与 Bazel 构建扩展 |
| `guosasipo/android_device_meizu_meizu21Pro` | `c2dd0cbccafa5a86a407101050c508f0827d3178` | 当前 seventeen / PixelOS 设备树，提交时间 2026-09-28 08:05 UTC |
| 同一设备树 lineage-23.2 分支 | `379af1151a414a0213638470debcba1a9f7ee8ff` | Lineage 设备配置参考；来源是维护者个人仓库，并非确认过的 Lineage 官方设备支持 |
| `guosasipo/android_device_meizu_meizu21Pro-kernel` | `8c4460d20b02b87efc2b5a092ed79e5d8fa48fbf` | 已弃用的预编译文件仓库 |

common/msm/build 三个仓库的 seventeen、sixteen-qpr2、lineage-23.2 在本次查询时分别指向相同 HEAD；分支名不同不代表内核代码版本不同。完整组织的 29 个仓库及 seventeen SHA 已保存在 `org-repository-lock-20261019.json`，以后应使用固定 SHA，避免只记录会移动的分支名。[S1][S6]

旧 `*-kernel` 仓库描述明确标为弃用并指向 meizu-8650-kernel。它包含 `kernel`（33,892,864 字节）、dtb、dtbo.img 和预编译模块，`Module.symvers` 与 `System.map` 都是零字节文件。递归文件清单合计约 175.45 MB，包含 system_dlkm 57 个、vendor_dlkm 304 个、vendor_ramdisk 335 个 `.ko` 文件，可能存在分区间重复。其提取脚本还硬编码过 `6.1.25-android14-11-maybe-dirty` 的 system_dlkm 路径；该字符串不能用于判断当前 PixelOS 内核版本。[S7][S8]

## 完整度与获取体积

固定 manifest 有 46 个 project：27 个 Meizu 组织仓库、16 个 CodeLinaro 项目、2 个 AOSP 项目、1 个 LineageOS 设备树项目。它把 common、msm、构建系统、Qualcomm/Meizu 外部模块、设备树及 Linux x86 工具链放入预期目录，并通过 linkfile 形成构建布局。不能只 clone `android_kernel_meizu_sm8650` 后就认为已经得到整套设备内核/模块构建环境。[S9]

manifest 中外部项目大多固定 SHA，但 Meizu remote 默认继承 seventeen 分支，因此 manifest 自身固定不等于全部源码固定。Meizu 仓库可以用本次 lock JSON 补齐精确 SHA。`android_kernel_meizu_sm8650-modules` 本身是空仓库，完整 manifest 采用各模块仓库及 linkfile；空仓库不代表所有模块源码都不存在。[S6][S9]

GitHub API 返回整个组织的仓库 `size` 总和为 4,993,284 KiB（约 4.762 GiB）。这是 GitHub 的仓库存储统计，包含历史等因素，**不是**此次 shallow clone 的实际下载量，也不包含 manifest 外部工具链。msm 的递归 Git tree 被 API 截断于 76,160 项，已返回 blob 合计超过 1.30 GB，故也不能当作完整 checkout 精确体积。最小的直接 Image 重建可重用现有本地 Git 对象，再单独创建干净 checkout 与新的 O= 目录；完整平台和所有模块则需额外获取 manifest 的其余项目。本调研没有下载整套源码或工具链。[S6][S10]

本次已实测 CodeLinaro 的 `kernelplatform/prebuilts-master/clang/host/linux-x86` remote 可访问，但没有逐一验证所有固定外部对象都可下载，不能把“manifest 列齐”写成“完整编译已经通过”。

## 当前 ROM 的直接编译依据

设备树的关键值为：[S3]

```text
TARGET_KERNEL_SOURCE = kernel/meizu/sm8650
BOARD_KERNEL_IMAGE_NAME = Image
TARGET_KERNEL_ADDITIONAL_FLAGS = CONFIG_MEIZU_DEVICE_DTBS=y
TARGET_KERNEL_CONFIG = gki_defconfig + vendor/pineapple_GKI.config + vendor/meizu21pro_GKI.config
TARGET_KERNEL_EXT_MODULE_ROOT = kernel/meizu/sm8650-modules
```

PixelOS 十七分支使用的 Lineage 构建仓库固定为 `049661a85f5b47893fed9104e644a625b2a47840`；另取了 2026-09-28 当日之前的 `6c2a3a84facab437e695364cacfe9655baaa9fc6` 作时间对照。两者在以下直接内核编译参数上相同，但这不等于已经取得原 ROM 构建者当时的完整 manifest/命令行：[S4][S11]

| 项目 | 源码中的实际行为 |
| --- | --- |
| 内核产物 | `KERNEL_OUT/arch/arm64/boot/Image`，`make -C KERNEL_SRC ... Image` |
| 配置合并 | 复制基础 gki_defconfig；olddefconfig；依次 merge 两个 `.config` fragment，每步再 olddefconfig；可选覆盖 KERNEL_LTO/KERNEL_CONFIG_OVERRIDE |
| 工具链 | 若设备不指定 TARGET_KERNEL_CLANG_VERSION，则取 ROM 的 `LLVM_AOSP_PREBUILTS_VERSION`，而不是内核 legacy build.config.constants 的版本 |
| 核心 make 参数 | `ARCH=arm64 LLVM=1 LLVM_IAS=1 CC=clang LD=ld.lld CLANG_TRIPLE=aarch64-linux-gnu-`；附带设备的 `CONFIG_MEIZU_DEVICE_DTBS=y` |
| 工具 | LZ4、LEX、YACC、M4、PAHOLE 取 Android prebuilts；DTC_EXT 取 ROM 构建出的 host dtc |
| host 编译 | HOSTCFLAGS/HOSTLDFLAGS 使用 Android glibc2.17 sysroot、kernel-build-tools include/lib64、lld/compiler-rt |
| KCFLAGS | 直接配方未显式附加 legacy 构建的 `-D__ANDROID_COMMON_KERNEL__` |
| 外部模块 | 在编译 Image、dtbs、modules 后，按设备树列出的 TARGET_KERNEL_EXT_MODULES 逐个编译并安装 |

完整的实际文件已保存为 `pixelos-lineage-seventeen-asof20260928-build_tasks_kernel.mk` 与 `pixelos-lineage-seventeen-asof20260928-config_BoardConfigKernel.mk`。重建时需要把工具路径映射到本机可用文件；更换 host 工具是否影响结果，应作为明确差异记录，不能默认为等价。

手机实际 stock.config 的关键值为：CFI_CLANG=y、LTO_NONE=y、MODVERSIONS=y、MODULE_SIG=y、MODULE_SIG_FORCE=n、MODULE_SIG_PROTECT=y、TRIM_UNUSED_KSYMS=n、LOCALVERSION_AUTO=y。应以该最终配置作第一轮重建对照，不能只检查三份 defconfig 的文本是否一致。[L1]

## 通用 GKI mixed 构建的区别

manifest 附带的 legacy `build.config.constants` 指定 `BRANCH=android14-6.1`、Clang r487747c；common/msm `build.config.common` 指定 KMI generation 11。因此 Android 17 ROM 仍可能运行 Android 14 代际的 GKI 内核接口，ROM 大版本与 GKI KMI 世代不能混淆。[S12]

`build_with_bazel.py -t pineapple gki` 是可识别的通用平台入口；Meizu 的 Bazel 扩展另外提供 `//vendor/meizu/opensource/kernel-modules:meizu21pro_gki_dist`。`msm_kernel_la.bzl` 对 gki 选择 `//common:kernel_aarch64` 作为 base kernel，并把 boot 镜像产物指向 common 的 GKI artifacts；它不是当前直接 msm Image 的重现命令。consolidate 使用 common 的调试变体，同时关闭 ABI 比较目标，更不宜作为保留现有模块的一步替换方案。[S5][S13][S14]

若未来选择完整 mixed GKI 构建，需要对 common 树实施影响 Image 的配置修改，并完整重建配套模块/设备树/相关镜像。仅修改 msm defconfig 不能保证 common 最终 Image 获得该选项。[S5][S12]

## DroidSpaces、KSU 与模块兼容性

stock.config 当前明确关闭 USER_NS、PID_NS、CGROUP_DEVICE、CGROUP_PIDS、CHECKPOINT_RESTORE；UTS_NS、IPC_NS、NET_NS 与 CGROUPS 已打开。源码基础 gki_defconfig 也明确关闭 PID_NS。DroidSpaces 适配应让后续配置审计逐项决定最终 fragment，并在编译后核对最终 `.config`，不能只追加文本后假设依赖全部满足。[S15][L1]

本次检查的源码树入口、drivers/Kconfig、drivers/Makefile 未发现集成 KernelSU 的构建入口，stock.config 也没有 CONFIG_KSU。CONFIG_KPROBES、KALLSYMS、KALLSYMS_ALL 与 ANDROID_VENDOR_HOOKS 已开启。现有 KSU 很可能来自另外的安装/注入途径，但仅凭这些配置无法确认具体方案；必须由主任务读取实际 KSU 安装状态后决定如何保留 ADB 所依赖的模块。[S16][L1]

模块兼容性至少需要覆盖 vermagic、CONFIG_MODVERSIONS/CRC、CFI、导出符号及签名保护。源码 `kernel/module/main.c` 会对未受信模块的符号访问/导出执行额外检查；即使未启用 MODULE_SIG_FORCE，MODULE_SIG_PROTECT 的规则仍可能影响模块。新构建的签名 key 和生成的 GKI 保护列表需要与实际模块关系一起审计。此处仅列待验证条件，没有把它判断为已经定位的启动故障。[S17]

## AVB key 与 2026-09-28 设备配置

当前设备树提交 c2dd0cb 的 BoardConfig 与其提交日期都对应 2026-09-28；Verified Boot 配置如下：[S18]

| 字段 | 值 |
| --- | --- |
| BOARD_AVB_ENABLE | true |
| BOARD_AVB_ALGORITHM / BOOT_ALGORITHM | SHA256_RSA4096 |
| BOARD_AVB_KEY_PATH / BOOT_KEY_PATH | external/avb/test/data/testkey_rsa4096.pem |
| BOARD_AVB_BOOT_ROLLBACK_INDEX | `$(PLATFORM_SECURITY_PATCH_TIMESTAMP)` |
| BOARD_AVB_BOOT_ROLLBACK_INDEX_LOCATION | 3 |
| BOOT_SECURITY_PATCH | `$(PLATFORM_SECURITY_PATCH)` |
| VENDOR_SECURITY_PATCH | 2023-10-05 |
| 顶层 vbmeta 的 args | `--flags 3`，以及 boot.os_version=`$(PLATFORM_VERSION_LAST_STABLE)`、boot.security_patch=`$(BOOT_SECURITY_PATCH)` |

`--flags 3` 和上述两个 prop 在这里属于 BOARD_AVB_MAKE_VBMETA_IMAGE_ARGS，不能未经检查就把它们原样当成 boot footer 的所有元数据。BOOT rollback 值也是构建变量而非该设备树里固定的数字。主任务新实测已确认 boot_b 存在 AVB footer/RSA4096 签名；boot header v4 的 signature_size=0 并不排除该 footer。这一实测结论替代旧笔记“没有 AVB”的说法。

主任务的原镜像 AVB 实测值为：rollback index `1788220800`、boot.os_version `17`、boot.security_patch `2026-09-01`、flags `0`、footer rollback index location `0`，公钥 SHA-1 `2597c218aae470a130f61162feaae70afd97f011` 与顶层 vbmeta 的 boot chain 公钥相同。设备树的 location=3 是顶层 `--chain_partition boot:3:...` 的索引；Android Makefile 没把它设成 boot footer 自己的 location，因此两个位置的值并不矛盾。该 Makefile 会另外给 boot footer 添加 os_version、fingerprint、security_patch 属性，重建时应保留原镜像实际属性和值、salt、key 与 release string。[S20]

AOSP 官方公开测试 key 已下载至 `sources/meizu21pro-kernel-reference/aosp-testkey_rsa4096.pem`，来源与完整性如下：[S19]

```text
repository: https://android.googlesource.com/platform/external/avb
commit: 761178607206f4cb2af79ed9eec52d8cbd814adb
path: test/data/testkey_rsa4096.pem
git blob SHA-1: 26db5c3c06ee75de106e07ca47d7b26d7a1d7c6a
file SHA-256: 6a224754880a57ab9cbd308267cd157d94cf05a1c8cb851aec4090e045d24121
```

同目录 `aosp-testkey_rsa4096-provenance.json` 保存下载地址和元数据。源码引用该测试 key 不等于实际 ROM 必然使用它；应由主任务针对原始 boot 计算/验证公钥匹配，匹配后才用于重建签名。

原镜像记录的是 avbtool 1.4.0。AOSP 的 main 提交 `761178607206f4cb2af79ed9eec52d8cbd814adb` 中工具常量仍为 1.3.0，已按请求保存为 `aosp-avbtool.py`，不能把 main 自动视作与手机匹配的工具版本。额外保存了真正的 1.4.0：[S21]

| 本地文件 | 固定来源 | SHA-256 |
| --- | --- | --- |
| `aosp-avbtool.py` | AOSP main `761178607206f4cb2af79ed9eec52d8cbd814adb`；blob `595936c88d24b6e571b303a23a0e7cfe2e185bc7` | `e5a664a38db623da00f080219bc0ee60a640a9dc4a872803616fae4938ac749b` |
| `aosp-android17-avbtool.py` | AOSP android17-release `ba2dec4b035b0a3b61c5f8f8a74d86bcd450b1ee`；blob `c0f3c7c62c4121edca58727ae60e17818d46155c` | `1aa6f2b462aa67aa3fdf488bee83ab517de8ad9d8228c7b45c35267ab2cf6781` |
| `pixelos17-avbtool.py` | PixelOS seventeen `15b4e85b56cdd7e32601074dbb269f5d3ba43eaf`；2026-08-07，2026-09-28 之前该分支的 HEAD | 见同目录 `pixelos17-avbtool-provenance.json` |

建议先用原 Image、相同属性/salt/key 复刻出逐字节一致的原 boot，再替换为新内核。这能直接检验打包与签名流程，而非仅凭 `avbtool info_image` 看起来相近即认为正确。该建议不要求修改 vbmeta。

## 来源

- [S1] [MSM 精确提交与提交历史](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/commit/19e9b13339e26612844b620c2bdd54228dc6d836)
- [S2] [MSM Makefile 6.1.176](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/Makefile)
- [S3] [当前设备 BoardConfig](https://github.com/guosasipo/android_device_meizu_meizu21Pro/blob/c2dd0cbccafa5a86a407101050c508f0827d3178/BoardConfig.mk#L103-L167)
- [S4] [PixelOS 直接 kernel.mk 配方](https://github.com/PixelOS-AOSP/android_vendor_lineage/blob/049661a85f5b47893fed9104e644a625b2a47840/build/tasks/kernel.mk#L288-L320)
- [S5] [MSM mixed build 选择 base kernel 与 boot artifacts](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/msm_kernel_la.bzl)
- [S6] [GitHub 组织仓库 API](https://api.github.com/orgs/meizu-8650-kernel/repos?per_page=100)，配合逐仓库 `git ls-remote --heads ... refs/heads/seventeen`，结果保存在 reference JSON。
- [S7] [弃用预编译仓库 API](https://api.github.com/repos/guosasipo/android_device_meizu_meizu21Pro-kernel) 与 [固定 Git tree](https://api.github.com/repos/guosasipo/android_device_meizu_meizu21Pro-kernel/git/trees/8c4460d20b02b87efc2b5a092ed79e5d8fa48fbf?recursive=1)
- [S8] [旧预编译提取脚本](https://github.com/guosasipo/android_device_meizu_meizu21Pro-kernel/blob/8c4460d20b02b87efc2b5a092ed79e5d8fa48fbf/extract-files.sh)
- [S9] [固定 seventeen manifest](https://github.com/meizu-8650-kernel/kernel_manifest/blob/a96a90fa48fd9a3b987c89cc0b6c7ebe0b1ba5b1/meizu_21_pro.xml)
- [S10] [MSM Git tree API](https://api.github.com/repos/meizu-8650-kernel/android_kernel_meizu_sm8650/git/trees/19e9b13339e26612844b620c2bdd54228dc6d836?recursive=1)（truncated=true，不是完整文件总数）。
- [S11] [PixelOS 2026-09-28 时点 BoardConfigKernel](https://github.com/PixelOS-AOSP/android_vendor_lineage/blob/6c2a3a84facab437e695364cacfe9655baaa9fc6/config/BoardConfigKernel.mk) 与 [kernel.mk](https://github.com/PixelOS-AOSP/android_vendor_lineage/blob/6c2a3a84facab437e695364cacfe9655baaa9fc6/build/tasks/kernel.mk)
- [S12] [legacy 工具链常量](https://github.com/meizu-8650-kernel/android_kernel_common_meizu_sm8650/blob/043dfdbb9ba312acfc3a8e23718cd7b3194bb190/build.config.constants) 与 [KMI/公共配置](https://github.com/meizu-8650-kernel/android_kernel_common_meizu_sm8650/blob/043dfdbb9ba312acfc3a8e23718cd7b3194bb190/build.config.common)
- [S13] [Bazel wrapper 的参数定义](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/build_with_bazel.py#L330-L389)
- [S14] [Meizu 完整源代码构建 dist target](https://github.com/meizu-8650-kernel/vendor_meizu_opensource_kernel-modules/blob/dafe79bf5dbb772def7805a05ac917fa55ae9855/BUILD.bazel)
- [S15] [MSM gki_defconfig](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/arch/arm64/configs/gki_defconfig)
- [S16] [drivers/Kconfig](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/drivers/Kconfig) 与 [drivers/Makefile](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/drivers/Makefile)
- [S17] [模块符号与签名检查](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/module/main.c#L1103-L1124) 与 [签名验证](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/module/signing.c)
- [S18] [2026-09-28 BoardConfig AVB 字段](https://github.com/guosasipo/android_device_meizu_meizu21Pro/blob/c2dd0cbccafa5a86a407101050c508f0827d3178/BoardConfig.mk#L242-L270)
- [S19] [AOSP 官方公开测试 key 固定版本](https://android.googlesource.com/platform/external/avb/+/761178607206f4cb2af79ed9eec52d8cbd814adb/test/data/testkey_rsa4096.pem)
- [S20] [PixelOS 2026-09-28 前已存在的 Android 构建 Makefile](https://github.com/PixelOS-AOSP/android_build/blob/f201c9c3ec3184695f012df5ef79d79b04fe2d36/core/Makefile#L4871-L5071)，本机参考文件 `pixelos-build17-core_Makefile`。
- [S21] [AOSP main avbtool 1.3.0](https://android.googlesource.com/platform/external/avb/+/761178607206f4cb2af79ed9eec52d8cbd814adb/avbtool.py)、[AOSP Android 17 avbtool 1.4.0](https://android.googlesource.com/platform/external/avb/+/ba2dec4b035b0a3b61c5f8f8a74d86bcd450b1ee/avbtool.py)、[PixelOS avbtool 1.4.0 固定提交](https://github.com/PixelOS-AOSP/android_external_avb/blob/15b4e85b56cdd7e32601074dbb269f5d3ba43eaf/avbtool.py)。
- [L1] 本机只读证据：`output/droidspaces-20261019/device-baseline-v1/stock.config`；设备 uname/ROM 构建信息和 boot AVB footer 检测由主任务独立采集，本研究没有执行 ADB。

## 最终构建的全量模块 ABI 核对

2026-10-19 已新增并运行只读脚本 `diagnostics/droidspaces-20261019/verify_module_abi.py`，最终报告位于 `output/droidspaces-20261019/verification/module-abi.json`。正式输入全部来自本次实机拉取：vendor_dlkm 390 个模块、system_dlkm 59 个模块，共 449 个。辅助核对 `~/rom/vbrd/lib/modules` 的 281 个 vendor_boot 模块时，其名字都已被这 449 个覆盖，且同名文件的 SHA-256 全部相同，因此正式报告没有依赖旧 ROM 路径。

目标符号表为 `<build-root>/out/vmlinux.symvers`，SHA-256 `4046401c08ac81d5d42207185880c1a0b024d5806b7f7c2ad082a1971112a304`。目标 `.config` 与 `include/config/kernel.release` 推导出的完整 vermagic 为 `6.1.176-g19e9b13339e2 SMP preempt mod_unload modversions aarch64`，449 个模块全部一致；脚本在结束前再次核对目标符号表/配置/release 的哈希，确认检查期间没有改变。

| 核对项 | 结果 |
| --- | --- |
| 模块 ELF 解析 | 449 / 449 通过 |
| 最终 core 导出 | 15,660 个 |
| 模块导出 | 4,346 个，CRC 全部成功读取 |
| 模块版本导入总数 | 25,248 条 |
| 与最终 core CRC 匹配 | 22,162 条 |
| 与其他实机模块导出 CRC 匹配 | 3,086 条 |
| 真实缺失/无法解析的导出 | 0 |
| core/module CRC 不匹配 | 0 |
| 同名文件/模块身份冲突 | 0 |
| 多个 provider 或 core/module 导出重名 | 0 |
| 无版本记录的强/弱未定义符号 | 0 |
| 总结论 | passed=true，进程退出码 0 |

脚本通过 pyelftools 读取 ELF64 ARM64 的每个 64 字节 `__versions` 记录、完整 vermagic、`__ksymtab_*` 的符号名/namespace relocation 和 `__crc_*` 对应的 `__kcrctab`。模块私有导出还按 `__ksymtab` 顺序与 CRC 表交叉验证。报告包含每个模块的文件 SHA-256、全部版本导入、实际 provider、CRC 和符号解析结果，未把“不在 vmlinux.symvers 内”直接当作无害，也未忽略解析异常。缺失符号、CRC 冲突、输入缺失、重复名字但哈希不同、无法解析或 vermagic 不符都会使脚本以非零状态退出。

已执行只读的负面自检：在内存中把实际 `module_layout` core CRC 改错、删除它的导出、提供错误完整 vermagic，均被准确报告为失败；截断 ELF 也被拒绝。自检没有改动模块文件或目标符号表。

复跑命令（WSL）：

```bash
python3 <workspace>/diagnostics/droidspaces-20261019/verify_module_abi.py \
  --symvers <build-root>/out/vmlinux.symvers \
  --modules \
    <workspace>/output/droidspaces-20261019/device-baseline-v1/vendor_dlkm-modules \
    <workspace>/output/droidspaces-20261019/device-baseline-v1/system_dlkm-modules \
  --expected-count 449 \
  --report <workspace>/output/droidspaces-20261019/verification/module-abi.json
```

此轮脚本 SHA-256：`d9cce7ce373513cd22a0c6b68e3ae942d630a7184800407ff09e0d14316bdd3d`。报告 SHA-256：`ac3d8d172faab6a9254353984d17d464d8c63b95b41af513a1c87c141c57e51c`，12,789,079 字节。这里的通过结论只覆盖本次输入的符号版本、导出解析、完整 vermagic 和文件身份；它不能代替真实启动、CFI 类型 ID、结构布局、模块签名信任链或加载顺序的独立验证。


