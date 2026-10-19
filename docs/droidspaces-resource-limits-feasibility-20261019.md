# Droidspaces CPU / process limit 的可行性核验

日期：2026-10-19，Asia/Hong_Kong。对象是 Meizu 21 Pro 当前 PixelOS 17 的 `Linux 6.1.176-g19e9b13339e2`；源码固定到 `meizu-8650-kernel/android_kernel_meizu_sm8650@19e9b13339e26612844b620c2bdd54228dc6d836`。本文只读源码、采集数据和对照构建结果，没有修改设备、原候选内核或配置。

## 结论与本轮实测

**可以研究加入这两项，Droidspaces 7 已实现对应 runtime；但直接打开后不能继续使用这台手机当前的一整套原版模块。** 主任务已经在原候选之上只改变 `CFS_BANDWIDTH=n→y`、`CGROUP_PIDS=n→y` 完成对照编译，Image 构建成功，同时测得实际结构和模块 CRC 不兼容。它是研究用对照构建，尚未刷写。[E1][E2][E3]

| 对照指标 | 结果 |
|---|---:|
| 原版模块文件 | 449 个 |
| 出现 core CRC mismatch 的模块 | 400 个 |
| 不匹配的 core 导入引用 | 5317 条 |
| 涉及的不同 core 符号 | 1095 个 |
| core 导出表整体的 CRC 变化 | 5710 个符号 |
| 仍匹配的 core 引用 | 16845 条 |
| 原模块之间的导入引用 | 3086 条，全部仍匹配 |

这把问题限定为新 core 与原模块之间的接口变化，而不是“源码编译不了”或“所有模块之间的符号都坏了”。相同 vermagic 不能消除这些不匹配。Linux 的 MODVERSIONS 会用导出符号原型 CRC 拒绝不匹配模块。[E2][S10]

实际测得的结构大小，单位 bytes：[E3]

| 类型 | 原版 | 直接开两项 | 原因 |
|---|---:|---:|---|
| `cfs_bandwidth` | 0 | 256 | 由空结构变为锁、两个 hrtimer、quota/runtime、节流链表与统计 |
| `task_group` | 512 | 768 | 按值嵌入完整 `cfs_bandwidth` |
| `cfs_rq` | 384 | 448 | 新增每 CPU group 的 runtime / throttling 状态 |
| `rq` | 3840 | 3904 | 按值嵌入变大的 `cfs_rq` |
| `css_set` | 424 | 448 | 按 controller 数量定义的两个数组增长 |
| `cgroup` | 1680 | 1704 | controller 指针与 list-head 数组增长 |
| `cgroup_root` | 5896 | 5920 | 按值嵌入变大的 `cgroup` |
| `sched_entity` | 320 | 320 | 没有直接由这两项增加的字段，仍通过指针引用受影响类型 |
| `task_struct` | 4800 | 4800 | 原字段保留，先前 SYSVIPC 保留槽方案也仍有效 |

前一版未打开这两项的 `final-btf-layouts.json` 与当前对照报告是两套独立证据，不能互相替代。本轮联合开关实验不能把每个具体 CRC 单独归因于 CFS 或 PIDs；下面的源码分析负责区分各自直接改变的结构。[E2][E3][S1][S2]

## CFS_BANDWIDTH：真实改变的路径

`init/Kconfig` 中该项依赖 `FAIR_GROUP_SCHED`。设备已经启用 CGROUP_SCHED 和 FAIR_GROUP_SCHED，因此启用本项即可生成 cpu quota 接口，不需要同时更换全部 cgroup 层次。[S1][S11]

- `kernel/sched/sched.h:344`：`struct cfs_bandwidth` 的成员全部受 CONFIG_CFS_BANDWIDTH 控制。原版 size 0，新版为 256。
- 同文件 `task_group:412`：原来的 `cfs_bandwidth` 在 offset 400 占 0 bytes，后面的 `uclamp_pct` 也始于 400。打开后，uclamp_pct 移到 656，Android vendor data 从 432 移到 688。`task_group` 尾部虽有 4 个 u64 保留槽，总计 32 bytes，不能直接装下 256 bytes。[E3][S1]
- 同文件 `cfs_rq:644`：新增 runtime_enabled、runtime_remaining、throttled_pelt_idle、throttled_clock、throttled_clock_pelt、throttled_clock_pelt_time、throttled、throttle_count、throttled_list。它们是 4/8-byte 标量与 16-byte list_head，总有效存储 68 bytes；默认布局部分吸收旧尾部 padding，最终 size 384→448。[S1][E3]
- `rq:1008` 的 cfs 按值嵌入，因此后方 rt/dl、curr、clock、cpu 和 Android vendor/OEM 数据等字段整体移动。例如 rt offset 896→960，curr 2720→2784，clock 2768→2832，cpu 3008→3072。[E3][S1]
- `include/linux/sched.h:555` 的 sched_entity 没有 CONFIG_CFS_BANDWIDTH 分支，本轮 size 和字段布局均相同。不能因此认为相关导出 CRC 也不变：它持有 cfs_rq 指针，导出类型的关联会把更深处类型变化传播到原型 CRC。[S3][S10]

`runqueues` 是实际导出的 per-CPU rq 对象，`cpu_cgrp_subsys` 也被导出；Android scheduler hook 会把 rq/cfs_rq/sched_entity/task_group 传入模块。原版 `sched_walt.ko` 导入 `runqueues` 的 expected CRC 为 `0x5fc45fe1`，对照 core 提供 `0x9a1d0c95`，已发生真实 mismatch。[E2][S4][S5]

### 保留原版模块的理论方案与限制

**现成 SYSVIPC 的保留槽补丁不能照搬成这两个开关的补丁；但不能由此证明所有兼容实现都绝不可能。** 需要分别解决实际布局、genksyms 类型视图与 scheduler 行为。[S1][S9]

本机 stock BTF 的 `cfs_rq` 有三段可定位的隐式空洞：`100..127` 为 28 bytes，`316..319` 为 4 bytes，`348..383` 为 36 bytes。总计 68 bytes，理论上恰好可重新安排上述新增字段而不移动原字段：

| 理论新增字段 | byte offset | size |
|---|---:|---:|
| runtime_enabled | 100 | 4 |
| runtime_remaining | 104 | 8 |
| throttled_pelt_idle | 112 | 8 |
| throttled_clock | 120 | 8 |
| throttled | 316 | 4 |
| throttle_count | 348 | 4 |
| throttled_clock_pelt | 352 | 8 |
| throttled_clock_pelt_time | 360 | 8 |
| throttled_list | 368 | 16 |

这只是**针对当前精确配置的理论摆放**，未实现、未编译、未运行验证。BTF/pahole 所示空洞不是有明确维护承诺的 KABI reserve；完整实现还要确认实际 C 对齐、每种编译配置的 offset/sizeof 静态断言、邻接字段/原模块的内联访问是否会覆盖 padding，并让 genksyms 看见原来的类型序列。仅在 `__GENKSYMS__` 下隐藏新增成员而没有物理证明，不构成兼容修复。[E4][S9]

`task_group` 的 256-byte bandwidth state 仍然无法放进 32-byte 尾部保留槽。可以研究在保留槽里放一个 pointer，把完整 state 放到外部对象；为此须保持原零大小 member 的兼容视图，并把 core.c/fair.c 的全部直接 `tg->cfs_bandwidth` 访问替换为受控 accessor。还要覆盖 root_task_group 的早期初始化、普通 group 分配失败回滚、两个 hrtimer 的取消、RCU 生命周期和 CPU hotplug。源码确有 `tg_cfs_bandwidth()` helper，但 core.c 仍有多处绕过 helper 的直接访问，因此不是只改一行 accessor 就完成。[S4][S6]

若 cfs_rq 保持 384、task_group 保持 512，rq 的连锁膨胀有机会一并避免；这属于需要独立审计和验证的内核移植方案，不是已经得到的可用产物。能否复用所有原模块，还取决于下一节的 WALT 行为兼容和其余 CRC 是否真正保持。

## CGROUP_PIDS：现有编号没移动，数组确实变大

`include/linux/cgroup_subsys.h` 按配置列出 subsystem，`cgroup-defs.h` 据此生成 enum 与 CGROUP_SUBSYS_COUNT。设备配置没有启用 hugetlb/rdma/misc/debug，所以 PIDs 在当前列表中本来就是最后一个新增项。[S2][S7]

| subsystem | 原版 ID | 开启 PIDs 后 ID |
|---|---:|---:|
| cpuset | 0 | 0 |
| cpu | 1 | 1 |
| cpuacct | 2 | 2 |
| io | 3 | 3 |
| memory | 4 | 4 |
| freezer | 5 | 5 |
| net_prio | 6 | 6 |
| pids | 不存在 | 7 |
| CGROUP_SUBSYS_COUNT | 7 | 8 |

因此“追加 pids enum 就能避免旧 ID 移位”这个条件，在该精确配置下本来就已满足；它不能解决 COUNT 增大带来的物理布局变化。[E3][S2][S7]

- css_set.subsys 是 COUNT 个 pointer，56→64 bytes，后续 refcount 从 offset 56 移动；e_cset_node 是 COUNT 个 list_head，112→128 bytes。
- cgroup.subsys 同样 56→64 bytes，仍从 offset 728 开始，root 因而从 784 移到 792；e_csets 从 offset 808 移到 816，size 112→128，后续字段再承受额外 16 bytes。
- cgroup_root 按值嵌入 cgroup，所以自己的后续字段也移动。这两个主要 cgroup 对象没有现成 ANDROID_KABI_RESERVE 区可直接换成足够大的扩展数组。[E3][S2]

内核核心与头文件还有大量直接 `cset->subsys[id]`、`cgrp->subsys[id]`、`cgroup->e_csets[id]`、`container_of(... e_cset_node[id])` 以及按 CGROUP_SUBSYS_COUNT 遍历的代码。单纯把数组在 genksyms 视图保持为 7、运行代码变成 8，会掩盖真实 offset 变化，使旧模块的内联访问仍指向错误地址。[S2][S8][S9]

理论上可以保持旧的 7-slot 数组，把 PIDs 对应 css/list 节点放到外部状态，并将内核里所有越过 legacy 范围的索引、遍历、迁移、哈希/比较、fork/exit/取消 fork 与 RCU 清理路径改走 accessor；也可以研究其他完整的对象布局兼容层。这样的方案必须同时保持旧 subsystem ID、旧字段 offset、旧数组语义和生命周期。本文没有实现或验证这种核心改造，不能把它视为“末尾 append 一项”规模的补丁。[S8]

## WALT 是真正使用这些字段的原版模块

设备为 `CONFIG_SCHED_WALT=m`。`kernel/sched/walt/walt.h` 直接包含内部 `kernel/sched/sched.h`。真实路径包括：

- `walt_cfs_replace_next_task_fair()` 读取 rq->clock，通过 cpu_of(rq)、cfs_rq_of(se) 走内联 offset，再调用 set_next_entity。[S12]
- `uclamp_task_colocated()` 从 task_css(cpu_cgrp_id) 得到 css，以 container_of 取 task_group，再把 tg->android_vendor_data1 当作 walt_task_group 数据。[S13]
- cgroup online/attach hook 的回调会读取 css->cgroup->kn，并初始化 top-app/foreground 对应的 WALT group；scheduler hook 的声明直接暴露 rq/cfs_rq/task_group。[S5][S13]

此外，`walt_cfs.c:1491` 的现有注释明确承认：开启 CFS_BANDWIDTH 时，MVP repick 路径可能从已经 throttled 的 cfs_rq 挑选任务，随后直接 set_next_entity。这是**布局/CRC之外的 quota 语义风险**：即便未来做到了原版 WALT 可加载，也仍须验证 MVP、boost、唤醒、跨 CPU 迁移、group 热销毁与 CPU hotplug 下限额是否执行，必要时修复并重编 WALT。源码里的 TODO 不能替代对实际 bypass 的量化测试，也不能被忽略。[S12]

## Droidspaces 7 支持当前的 CPU v1 / memory v2 混合层次

本机已采集的挂载为 `/dev/cpuctl` 的 cpu v1、`/dev/cpuset` 的 cpuset v1、`/dev/blkio` 的 blkio v1，以及 `/sys/fs/cgroup` 的 v2。memory 使用 v2；cpuacct/freezer/net_prio 的 `/proc/cgroups` hierarchy 为 0，但不能仅凭 0 就证明它们已作为可委派的 v2 controller 开放，仍应看 cgroup.controllers。当前 PIDs 未编译。此混合布局本身不是加入限额的阻碍。[E5]

Droidspaces v7.0.0 固定发布 SHA 为 `37e8b45de5ddc57d35cb8adfd8327add75e25159`；当前研究 main `8b625e1` 的 CPU/PIDs 路径与它相同，发布之后的 swap 改动不影响此结论。[S14]

| 限额 | Droidspaces 选择与写入 |
|---|---|
| CPU quota | 先查容器 v2 controller；本机 cpu 已绑定 v1，于是扫描 mountinfo 找到 `/dev/cpuctl`，建立 `/dev/cpuctl/droidspaces/<name>`，先写 cpu.cfs_period_us，再写 cpu.cfs_quota_us |
| PIDs | 若新 pids controller 留在 v2，则在 root 和 `/droidspaces` 的 cgroup.subtree_control 启用 +pids，然后写 `/sys/fs/cgroup/droidspaces/<name>/pids.max`；若已由 v1 hierarchy 持有，则沿该 hierarchy 建组并写同名 pids.max |
| Memory | 继续在 v2 的同一容器 subtree 写 memory.max；与 CPU quota 位于另一 hierarchy 并不冲突 |

具体实现是 find_host_cgroup_mount → ds_cgroup_ctrl_dir → apply_limit。它按**每个 controller 的实际归属**选择 v1 或 v2；不要求所有 controller 在同一版本。[S14]

监控进程留在限额 cgroup 外。每次开机周期的 intermediate 先调用 ds_cgroup_join 加入已有 v1 容器 cgroup 和容器的 v2 cgroup，再 unshare PID/NET/CGROUP namespace，之后 fork 容器 init。子孙正常继承 membership；enter/run 另加入 ds-enter leaf，避免只限制 PID 1 却漏掉后来进入的 shell。[S14][S15]

### 实际运行的前提和验收

- kernel 必须有 CFS_BANDWIDTH、CGROUP_PIDS，且对应 controller 未被 cgroup_disable 关闭；CPU checker 还检查 sched_cfs_bandwidth_slice_us。检查通过只说明功能可用性，不能证明某个容器已成功设限。[S16]
- daemon/root 需要有权限创建 cpuctl 子组、写 period/quota/procs，以及向 v2 root 与 droidspaces 的 subtree_control 写入 +pids。若父级没有委派 controller，容器目录里不会出现相应 knob；代码会记录失败并把未实际施加的限额从运行配置清零。[S14]
- 默认 v2 流程不会为了一个新容器抢占 Android 现有 cpu v1 hierarchy。pids 只需在 v2 中启用，cpu quota 可继续在 v1 生效。**不需要加入 `cgroup_no_v1=all`，也不应为此把 Android 的 cpu/cpuset/blkio 整体迁移。** Linux 官方明确支持这种混用；动态迁移已使用 controller 并不推荐。[S14][S17]
- v2 的内部节点/leaf 组织必须满足 no-internal-process 规则。Droidspaces 在建层级时把 monitor 留在外面，供容器 systemd 再划分 init.scope/services。存在其他 Android 服务占据目标 subtree、权限或挂载失败时，仍须看实际日志。[S14][S17]
- `--cpus=1.5` 是每 100000µs period 最多 150000µs 的累计 CFS CPU 时间，允许并行消耗，不是固定绑 1.5 个核心、频率上限或全调度类别的通用限流。RT scheduling 的行为必须另核，不能把 cpu quota 等同于 cpuset 或 Android UCLAMP。[S18]
- `--pids-limit=N` 实际统计 tasks/threads，而非仅进程组数。达到限制后新 fork/clone 返回 EAGAIN；迁移既有任务并不会被 PIDs policy 拒绝，所以 pids.current 可以临时大于 pids.max。Droidspaces 的最低 16 仅是参数底线，systemd/桌面/Docker 实际需要更高数值。[S19][S14]
- 验收应读回 period/quota/pids.max 与真实 membership，并测试 CPU 压力下 throttling、fork/thread 达限、systemd 新 service、enter/run、重启/停止清理。也要验证正常 Android 热管理、音频/前台流畅性和 WALT MVP 行为；这些尚未由本轮只读研究完成。

## 交付方式的条件

1. **直接开选项、全量匹配构建**：可作为明确路线。应使用同一源码/配置/工具链，重新构建所有已被 core CRC 或布局影响的模块；这次已有 400 个受影响，实际工程宜完整重建 vendor 与 system 模块集合，重做依赖、签名信任、加载顺序并同步打包相应 boot/vendor_boot/vendor_dlkm/system_dlkm。任何必须保留且无法重建的受影响 prebuilt 都会阻止这条直接路线。[E2][S10]
2. **坚持复用原版模块**：需要专门的 cgroup 与 scheduler ABI 兼容移植。上面的 padding/sidecar 是理论方向，尚未形成补丁；验收必须同时包含原字段/数组布局、原 CRC、编译进旧模块的内联访问和 WALT 执行语义。不能通过关闭 MODVERSIONS、重写 CRC 或强制载入来把真实变化称为已修复。[S2][S9][S10][S12]
3. **保持现有兼容候选**：其 CPU/PIDs 开关仍为 n，不把此次未通过模块审计的对照 Image 替换成原候选。即使暂不提供这两项，其他 Droidspaces 核心功能仍可独立验收。

本轮没有把用户“能否加入”的询问扩展成 scheduler sidecar 工程或设备刷写；可行性研究、直接配置对照与风险范围已经具体化。

## 第一方来源与本机证据

- [E1] [只改两项的 config 对照](../output/droidspaces-limits-20261019/verification/config-vs-compatible-profile.txt)。
- [E2] [对照构建对原版 449 模块的 ABI 审计](../output/droidspaces-limits-20261019/verification/module-abi-vs-stock.json)，SHA256 `5c81a55b79727ba06b912b1fdbf3ab1f89b8434c619d4c80a145409821ee9c5f`。
- [E3] [对照构建的 BTF 审计](../output/droidspaces-limits-20261019/verification/btf-vs-stock.json)，SHA256 `289c24477c1582d5223fec169d9d413c94128c9208fc8651e305b029a813fe95`。css_set/cgroup_root/cfs_bandwidth 的大小另通过同一只读 BTF parser 从此 vmlinux 直接读取。
- [E4] [原机 raw BTF](../output/droidspaces-20261019/device-baseline-v1/vmlinux.btf) 与 `pahole -F btf -C cfs_rq` 输出；[原兼容候选 BTF 验证](../output/droidspaces-20261019/verification/final-btf-layouts.json)。BTF 不能独立完整证明 C alignment。
- [E5] [原设备 cgroup/mountinfo 采集](../output/droidspaces-20261019/device-baseline-v1/device-status.txt)；[stock.config](../output/droidspaces-20261019/device-baseline-v1/stock.config)。
- [E6] [主任务合并的 limits-impact.json](../output/droidspaces-limits-20261019/verification/limits-impact.json)，含 5710 个 core export CRC 变化、模块影响及补充类型布局。
- [S1] [Meizu scheduler 内部结构](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/sched/sched.h#L344)。
- [S2] [cgroup-defs.h 的 enum 与数组](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/linux/cgroup-defs.h#L42)。
- [S3] [sched_entity 定义](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/linux/sched.h#L555)。
- [S4] [scheduler core.c](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/sched/core.c)，runqueues export 位于 128 行，bandwidth 配置位于 10883 行以后。
- [S5] [Android scheduler hook 原型](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/trace/hooks/sched.h)。
- [S6] [fair.c bandwidth 分配、定时器与销毁](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/sched/fair.c#L5232)。
- [S7] [controller 列表顺序](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/linux/cgroup_subsys.h)。
- [S8] [cgroup 核心数组与迁移](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/cgroup/cgroup.c)，[PIDs fork/exit 计数](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/cgroup/pids.c)。
- [S9] [Android KABI 宏及 size/alignment 静态断言](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/linux/android_kabi.h)。
- [S10] [Linux 6.1 module versioning](https://docs.kernel.org/6.1/kbuild/modules.html#module-versioning)。
- [S11] [Meizu init/Kconfig](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/init/Kconfig#L1048)。
- [S12] [WALT MVP repick 与 CFS_BANDWIDTH TODO](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/sched/walt/walt_cfs.c#L1445)。
- [S13] [WALT 的 task_group/cgroup 实际读取](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/sched/walt/walt.c#L3229)，[内部头文件 include](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/kernel/sched/walt/walt.h#L12)。
- [S14] [Droidspaces v7.0.0 cgroup runtime](https://github.com/ravindu644/Droidspaces-OSS/blob/37e8b45de5ddc57d35cb8adfd8327add75e25159/src/cgroup.c)，同时核对当前 [main 固定 SHA](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/cgroup.c)。
- [S15] [Droidspaces monitor 的 join 与 namespace 顺序](https://github.com/ravindu644/Droidspaces-OSS/blob/37e8b45de5ddc57d35cb8adfd8327add75e25159/src/monitor.c#L204)。
- [S16] [Droidspaces checker](https://github.com/ravindu644/Droidspaces-OSS/blob/37e8b45de5ddc57d35cb8adfd8327add75e25159/src/check.c)。
- [S17] [Linux 6.1 cgroup v2 的混合、controller 分发与 delegation 规则](https://docs.kernel.org/6.1/admin-guide/cgroup-v2.html)。
- [S18] [Linux 6.1 CFS bandwidth 语义](https://docs.kernel.org/6.1/scheduler/sched-bwc.html)。
- [S19] [Linux 6.1 PIDs controller 语义](https://docs.kernel.org/6.1/admin-guide/cgroup-v1/pids.html)。


