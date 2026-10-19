# Meizu 21 Pro 内核启动失败：现存证据审计

日期：2026-10-19（Asia/Hong_Kong）。本次只读取已有日志、源码、构建产物和主任务已保存的原厂 BTF；未访问 ADB/fastboot、未重启或刷机，未改变既有源码和构建目录。

## 结论

**现有资料没有给出目标 HAL 的确切失败 syscall。** `received SIGSYS` 是现象；现有档案没有目标进程的 `SYS_SECCOMP`、`si_syscall`、`si_arch` 或 `type=1326` 记录，不能据此把 `unshare`、`setns`、syscall 42 或任何其他 syscall 写成根因。

原厂配置控制版 B 仍失败，足以否定“只有开启 DroidSpaces namespace 才导致失败”。同时发现原厂内核的一份完整历史启动日志也有三次 c2audio SIGSYS，但随后完成启动，证明 **SIGSYS 计数不能单独判断卡开机，也不能证明重编内核造成所有 SIGSYS**。

进一步比较实际原厂 BTF：控制版 B 的 20 种核心结构体布局与原厂完全一致；完整 DroidSpaces 版除 `task_struct` 的保留位被等尺寸 union 使用外，其余 19 种逐字一致。此前只凭 CRC 猜测核心结构体布局已经损坏，证据不足。

## 已运行的红绿命令

新增 `diagnostics/droidspaces-20261019/Test-BootArchive.ps1`。它只解析捕获日志，针对“HAL 崩溃且未完成启动”分类；存在明确 `sys.boot_completed=1` action 时，单独报告启动通过与 HAL 崩溃状态。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\diagnostics\droidspaces-20261019\Test-BootArchive.ps1 -Dmesg .\output\debug\B1-dmesg.log -Logcat .\output\debug\B1-logcat.log
```

实际输出（退出码 1）：

```json
{"Status":"FAIL","HalHealth":"CRASH_OBSERVED","VendorHalSigsys":6,"LoggedSeccompCrashes":0,"AudioServerDied":0,"FrameworkWatchdogs":0,"BootCompleteActions":0}
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\diagnostics\droidspaces-20261019\Test-BootArchive.ps1 -Dmesg .\output\debug\stock-current-dmesg.log -Logcat .\output\debug\stock-current-logcat.log
```

实际输出（退出码 0）：

```json
{"Status":"PASS","HalHealth":"NO_CAPTURED_CRASH","VendorHalSigsys":0,"LoggedSeccompCrashes":0,"AudioServerDied":0,"FrameworkWatchdogs":0,"BootCompleteActions":18}
```

已对以下档案实跑；加 `-Expect PASS` 或 `-Expect FAIL` 可检查归档分类是否符合预期（预期匹配时退出码 0）：

| 已保存档案 | 启动分类 | 目标 HAL SIGSYS | AudioServerDied | 完成启动 action |
|---|---|---:|---:|---:|
| `output/debug/B1-*` | FAIL | 6 | 0（捕获窗口内） | 0 |
| `output/debug/B2-*` | FAIL | 5 | 24 | 0 |
| `output/device-dsdebug/*19710614-134008.log` | FAIL | 18 | 39 | 0 |
| `output/debug/stock-current-*` | PASS | 0 | 0 | 18 |
| `output/debug/ksu-*.old.log` | PASS | 0 | 0 | 18 |
| `output/debug/ksu-dmesg.log` + `ksu-logcat.log` | PASS；有 HAL 崩溃 | 3 | 0 | 18 |

本命令是离线日志回放判据，不能重新驱动实机启动；FAIL 代表所捕获窗口中的上述失败证据，不证明该设备永远不能恢复。PASS 也只证明档案中出现完成启动标记，不能代替 DroidSpaces 功能和长时间稳定性验证。没有失败证据、也没有完成标记的片段返回 UNKNOWN，避免把截断日志判成成功。

## 目标 syscall 的证据缺口

检查的 6 个 tombstone：

| 文件 | 进程 | ABI | 实际信号 |
|---|---|---|---|
| `tombstone_00.txt` | `vendor.qti.camera.provider-service_64` | arm64 | SIGABRT / SI_QUEUE |
| `tombstone_01.txt` | 同上 | arm64 | SIGABRT / SI_QUEUE |
| `tombstone_02.txt` | `mediacodeclist_generator` | arm64 | SIGSEGV / SEGV_MAPERR，null pointer |
| `tombstone_03.txt` | 相机 provider | arm64 | SIGABRT / SI_QUEUE |
| `tombstone_new00.txt` | 相机 provider | arm64 | SIGABRT / SI_QUEUE |
| `tombstone_new01.txt` | 相机 provider | arm64 | SIGABRT / SI_QUEUE |

相机栈为 `CameraProvider::binderDied` 主动 abort；mediacodeclist 栈在 `Codec2ConfigurableClient::HidlImpl::HidlImpl`。它们支持 Binder/媒体依赖服务异常后的连锁故障，不提供 c2audio/codec2/wfdhdcp 的被拒 syscall。

`output/debug/seccomp-policy-list.txt` 只列出 policy 文件名；`seccomp-unshare.txt`、`seccomp-setns.txt` 是空文件，既不能证明进程调用过它们，也不能证明它们就是被拒调用。`libminijail: logging seccomp filter failures` 表示启用记录，不是已经记录了一次具体过滤失败。

全量针对性查找没有找到：`SYS_SECCOMP`、`si_syscall`、`si_arch`、`syscall=`、`type=1326`、`seccomp prevented` 等可归属目标失败的记录。下次诊断的最小新增证据应同时记录 **pid/tgid/comm、nr、arch、action、instruction_pointer**；若 policy 对参数过滤，再记录相关参数。仅拿到 nr 而缺少 arch 也不能可靠映射：本树 arm64 `unshare=97,setns=268`，compat ARM `unshare=337,setns=375`。

## 原厂也有 SIGSYS 的反例

`output/debug/ksu-dmesg.log:2`：

```text
Linux version 6.1.176-g19e9b13339e2 (guosasipo@ideal) ... clang version 22.0.2 ... Mon Sep 28 00:23:59 KST 2026
```

同档案 `:5548,:14281,:14463`，c2audio 在启动后约 4.67、9.57、14.57 秒收到 SIGSYS；约 22.57 秒出现 `sys.boot_completed=1` action，KSU 随后打印 `on_boot_completed!`。因此要区分早期可恢复服务重启与持续重启、框架 watchdog、未完成开机。

原厂通过基线 `stock-current-*` 的确为 0 次 SIGSYS，但不能外推所有原厂启动都为 0 次。历史文件名的 `19710614` 是设备早期时间，不应当作真实采集日期或内核编译日期。

## 源码及构建输入

确认存在：

```text
<kernel-platform-root>/kernel_platform/msm-kernel
<control-build-root>
<droid-build-root>
```

源码 HEAD：`19e9b13339e26612844b620c2bdd54228dc6d836`。工作树有 6 个已修改文件：构建配置 3 个、`certs/extract-cert.c`、`include/linux/sched.h`、`init/main.c`，并有 `.orig` 备份文件。控制版 B 因 `CONFIG_SYSVIPC=n` 不启用新增 sysv union；DSDBG 标记仍存在。

新增只读脚本：

```powershell
wsl -d Debian -- python3 <workspace>/diagnostics/droidspaces-20261019/audit_build_inputs.py
```

控制版 `.config` 相对 `output/config-stock-device.txt` 的非空差异只有：

```text
CONFIG_CC_CAN_LINK / CONFIG_CC_CAN_LINK_STATIC: absent -> y
CONFIG_LOCALVERSION: "" -> "-g19e9b13339e2"
CONFIG_LOCALVERSION_AUTO: y -> n
CONFIG_MODULE_SCMVERSION: y -> absent
```

`CONFIG_SECCOMP_FILTER/CFI_CLANG/ANDROID_KABI_RESERVE/ANDROID_VENDOR_OEM_DATA` 等一致。原厂 `CONFIG_LTO_NONE=y`，所以旧 README 所称“保留 LTO”不准确。

`control22/kernel/.seccomp.o.cmd` 和 `msmout-droid22/kernel/.seccomp.o.cmd` 实际都有 `-fsanitize=kcfi`、`-fsanitize=array-bounds`、`-fsanitize=local-bounds`；二者均没有 `-D__ANDROID_COMMON_KERNEL__`。两个 `compile.h` 的编译器文本为 Android r596125 clang 22.0.2、commit `de03d430485c884861198b25459851f429cbdbad`。

`build.config.common:11` 的确设置 `KCFLAGS="${KCFLAGS} -D__ANDROID_COMMON_KERNEL__"`，但对整棵已跟踪源码执行 `git grep -n __ANDROID_COMMON_KERNEL__` **唯一命中就是该定义行**，没有 C/H/asm 消费者。`android_kabi.h` 由 `CONFIG_ANDROID_KABI_RESERVE` 控制；`android_vendor.h` 由 `CONFIG_ANDROID_VENDOR_OEM_DATA` 控制。因此当前源码下，仅补这个宏不会改变这些布局或运行分支，不能当作已经找到的修复。

同样，编译器版本字符串、uname 提交后缀或模块 CRC 一致，并不等于已证明源码及所有构建输入逐字相同。公开工作树与原厂真实构建之间仍没有完整可复现构建证明。

## 原厂 BTF 与两版重编布局实测

输入为主任务采集的 `output/droidspaces-20261019/device-baseline-v1/vmlinux.btf`，以及两版构建的 `vmlinux` 内嵌 BTF。命令：

```powershell
wsl -d Debian -- python3 <workspace>/diagnostics/droidspaces-20261019/compare_btf_layouts.py
```

以下 19 种类型的 `pahole -F btf -C TYPE` 输出在原厂、B、完整 DroidSpaces 版中 **逐字相同**：

```text
seccomp seccomp_filter seccomp_data action_cache cred mm_struct signal_struct
thread_info thread_struct cgroup cgroup_subsys_state cgroup_namespace task_group
cfs_rq sched_entity rq linux_binprm file file_operations
```

`task_struct`：原厂与 B 逐字相同，size 都为 4800；DroidSpaces 版只将 offset 3640 的 reserved6（8 字节）、offset 3648/3656 的 reserved7/8（共 16 字节）换为含原保留位的 sysv union。后续 `thread` 的 offset 3664 和总 size 4800 均不变。

这否定了“这 20 种核心结构的简单偏移变化就是 B 失败原因”，但没有覆盖每个厂商私有类型、每个函数签名/CFI type hash、或函数执行语义。

`output/crc-verification-clang22.txt` 证明 390 个模块的 21,720 条版本项中，18,984 条匹配、0 条不匹配、2,736 条不由当前树导出。其范围不能扩大成“所有模块运行时已验证”。在当前已保存 dmesg 中未找到具体 `CFI failure`、`BUG: KASAN`、`Unknown symbol` 或 CRC 拒载证据，故这些也不能被写成已发生的根因。

## 仍可证伪的候选（按当前优先顺序）

1. **KSU LKM / 模块栈与重编内核的交互。** 历史原厂日志明确加载 KSU version 32680，提示 `no symbol version for module_layout`，并注册 syscall/kretprobe hooks。预测：在保持同一 B Image、ROM 和 policy 的条件下，移除 KSU LKM 或只禁用具体相关 hook，会消除启动失败；若失败完全相同则削弱此假设。安全模式只排除部分 KSU 用户模块，不能等同无 LKM。`output/test-noksu-log.txt` 中 init_boot 刷入失败，不能视为已做成这个对照。

2. **有效构建输入或源码与原厂不等价。** 预测：匹配原厂源与有效编译/链接参数的最小 B 能启动；只引入某一差异便重新失败。应先列出确实消费的 flags、源码差异和生成文件。`__ANDROID_COMMON_KERNEL__` 已查无消费者，不是此假设的正面证据。

3. **真实被过滤 syscall / 参数或进程状态不同。** 预测：在目标退出前能观察到稳定的 `nr/arch/action`，且原厂对应路径无同样拒绝；修正产生该调用/状态的原因后能启动。没有这个记录，不能有针对性地扩大 policy，更不能沿用 unshare/setns 猜测。

4. **尚未覆盖的厂商调用契约或 KCFI 语义。** 预测：能找到明确模块回调、type hash、函数原型或私有布局差异，且只修该差异就消除失败。20 种核心结构布局相同、无已保存的 CFI/KASAN 报错，已降低其优先级；CRC 相同既不是完整证明，也不是反证。

5. **持久化状态、挂载覆盖或启动时序差异。** 原厂同一构建也存在可恢复 SIGSYS，显示仅凭 Image 因果归属可能混入状态/时序。预测：固定 Image 和 init_boot，只改变可明确列举的模块覆盖或持久化状态，失败率/目标调用发生率会可重复变化；若完全不变则削弱。应先比较已有成功/失败档案与模块清单，避免把整个模块栈一次清空后误归因。

下一次若需要诊断构建，最有信息量的单个新增探针是 **seccomp 非允许分支的带唯一前缀的 nr/arch/action/进程记录**，同时保留现有过滤行为。现阶段不应宣称已修复启动故障，也不能以离线通过或成功编出 Image 代替实机启动和 DroidSpaces 检查。

## MODULE_SIG_PROTECT 与 GKI 模块签名（追加审计）

`CONFIG_MODULE_SIG_PROTECT=y` 在原厂和 control22 配置中都开启，`CONFIG_MODULE_SIG_FORCE` 关闭，`CONFIG_SYSTEM_TRUSTED_KEYS=""`。内核源码的保护逻辑是：未被认可为 signed GKI module 的模块不能访问 GKI protected exports；因此只比较 vermagic/CRC 不足以证明可加载。

已新增 `diagnostics/droidspaces-20261019/audit_module_protection.py`。结果：

- 原厂 raw kernel、control22、msmout-droid22 的 protected/unprotected GKI 名单内容逐字相同；两个生成 header 的 SHA-256 分别为 `7bbc9408…eec1d`、`7a8914d3…a46cb`。
- 原厂 `vendor_dlkm` 390 个和 vendor ramdisk 281 个模块没有附加 PKCS#7 签名；它们依赖未签名模块规则和 protected/unprotected 名单。
- 原厂 `system_dlkm` 的 59 个 GKI 模块全部带签名，25 个导出 protected symbols（包括 `bluetooth`、`rfkill`、`usbnet`、`mii`、`can`、`ppp_generic` 等）。
- 原厂 boot raw kernel 内嵌签名证书位于 raw Image offset `33361152`，DER 1324 bytes，SHA-256 为 `2b109cb2af82cbff5831331680a0108097a69fa5d1d88723e4c3cd0a2e225d89`。control22/droid22 使用了不同的自动生成 key。

这与旧失败日志中的模块状态相符：当前原厂 `modules.txt` 有 59 个 system_dlkm 模块全部加载；失败档案 `hang-lsmod.txt` 只看到 6 个 system_dlkm 模块（`8021q`,`cdc_acm`,`kheaders`,`rtl8150`,`zram`,`zsmalloc`），缺失包括 `bluetooth`,`rfkill`,`usbnet`,`mii` 等。这个差异是重编内核保留新签名证书时最需要先修复的兼容性候选。旧日志没有直接出现 `exports protected symbol` 或模块拒载字符串，因而仍不能把它写成已证实的音频 SIGSYS 根因。

新增 `diagnostics/droidspaces-20261019/verify_module_signatures.py`，从保存的真实 `device-baseline-v1/boot_b.img` 提取证书，并用该公开证书逐一执行 OpenSSL CMS 内容核验；没有读取或输出私钥。实跑结果保存在 `output/droidspaces-20261019/verification/module-signature-verification.json`：

```json
{"modules_checked":59,"signatures_verified":59,"failures":[]}
```

公开材料 `stock-module-signing.x509` 与 `.pem` 也写入同一 verification 目录，可供新构建设置 `CONFIG_SYSTEM_TRUSTED_KEYS`。这只验证原厂 GKI 模块的公钥归属；它不能为原厂签名生成新模块，也不应替代新 Image 的实机验证。

## 可选 seccomp 追踪补丁

`diagnostics/droidspaces-20261019/seccomp-trace.patch` 只在 `SECCOMP_RET_TRAP`、`SECCOMP_RET_KILL_THREAD`、`SECCOMP_RET_KILL_PROCESS` 决策处分支加入 `pr_warn_ratelimited`，记录 `nr/arch/action/pid/comm`，不记录指针或 syscall 参数；允许 fast path 和过滤行为保持不变。补丁未应用到任何源码；在旧树和 `<build-root>/kernel` 均 `git apply --check` 通过，`checkpatch.pl --no-tree --terse` 无输出退出 0。


