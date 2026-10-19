# DroidSpaces CPU / PID 限额：保留预编译模块的替代路线审计

日期：2026-10-19。此审计只读取源码、已捕获模块、主任务已经完成的构建报告；没有修改源码/配置、没有编译、没有操作手机。内核源 HEAD 为 `19e9b13339e26612844b620c2bdd54228dc6d836`，DroidSpaces 源为 `8b625e110270e2f0d32004f740b1e9a71b1f540c`。

## 结论与已测事实

**现成的“只开两个配置、继续用原模块”路线已被静态实测否定。** 绕过 CRC 不会改变旧模块的机器码内存偏移。为这一个固定机型定制保 ABI 的内核重构，技术上可以研究；它需要覆盖 cgroup、调度器和 WALT 语义，不能称为已经验证的免重编补丁。cpuset 或 RLIMIT_NPROC 可以提供另一种约束，但都不实现当前 DroidSpaces 的两个选项。

主任务已经在独立 `<limits-build-root>/out` 完成 `CONFIG_CFS_BANDWIDTH=y`、`CONFIG_CGROUP_PIDS=y` 对照。报告：

- `output/droidspaces-limits-20261019/verification/module-abi-vs-stock.json`：449 个原模块中 **400 个**包含 CRC 不匹配，共 **5,317 条引用、1,095 个不同内核符号**；`sched_walt` 也在不匹配集合。vermagic 保持原值。
- `output/droidspaces-limits-20261019/verification/btf-vs-stock.json`：出现实际物理布局变化。

主任务的全内核导出对照另统计 **5,710 个 core 导出符号 CRC 改变**；它的范围大于上面实际被原模块引用的 1,095 个变化符号，两者不能混为一个计数。

| 类型 | 原厂 size | 两项直接开启后的 size | 具体影响 |
|---|---:|---:|---|
| `cgroup` | 1680 | 1704 | `root` 784→792，`e_csets` 808→816，`ancestors` 1680→1704 |
| `css_set` | 424 | 448 | `refcount` 56→64，`dfl_cgrp` 72→80，`e_cset_node` 152→160 |
| `cfs_bandwidth` | 0 | 256 | 原来的空结构变成锁、timer、额度、统计等完整对象 |
| `task_group` | 512 | 768 | `uclamp_pct` 400→656，`android_vendor_data1` 432→688 |
| `cfs_rq` | 384 | 448 | 原字段偏移保留，但总尺寸增加 |
| `rq` | 3840 | 3904 | 内嵌 `cfs_rq` 增大；`rt` 896→960，`clock` 2768→2832 |
| `sched_entity` | 320 | 320 | 本体未变化；引用其他类型仍可能使符号 CRC 递归变化 |

`css_set`、`cfs_bandwidth` 的 size 另用 `pahole -F btf -C TYPE` 直接读取原厂 BTF 和新 `vmlinux` 核实。这里的编译成功、CRC/BTF 报告都不是实机启动或限额执行成功的证明。

## 1. 改 CRC、关 MODVERSIONS 或强制加载

`kernel/module/version.c:20–55` 只比较符号声明生成的版本校验值；去掉版本表或 force load 只改变是否拒载。它不会重写旧 `.ko` 中的 `ldr/str` 偏移、数组步长、内联函数或 `container_of` 算术。

两个具体反例：

- 旧 WALT 的 `boost.c:26`、`walt.h:584` 直接访问 `tg->android_vendor_data1`。旧机器码访问 task_group offset 432；直接开启 CFS 带宽后正确位置是 688。
- `walt.c:5384` 直接访问 `dst_cgrp->root->subsys_mask`。旧模块的 root 指针读取位置为 784；开启 PID controller 后该位置成为扩大的 subsys 数组最后一个槽，正确 root 位置是 792。

这类差异不会因“让 CRC 数字相等”而消失。内核 KCFI、模块签名信任和加载顺序也各有独立检查，不能被 CRC 通过一并证明。

还有本设备已确认的 GKI 签名约束：`kernel/module/signing.c:83–96` 将 `MODULE_INIT_IGNORE_MODVERSIONS/IGNORE_VERMAGIC` 标为 mangled module，不建立正常签名成功状态。原厂 system_dlkm 中 59 个签名模块需要受信任身份，其中一些会导出 protected symbols。因此 force load 还可能失去原本的 `sig_ok`，触发 `CONFIG_MODULE_SIG_PROTECT` 的另一组拒载条件。直接编辑签名 `.ko` 的内容也会破坏原签名内容验证。

**可证伪标准：** 一个方案若只改变 CRC/加载检查，而 `offsetof(task_group, android_vendor_data1)`、`offsetof(cgroup, root)` 或旧内联机器码使用的偏移仍不一致，它就没有解决这两个实际反例。即使某次侥幸启动，也不能据此宣布兼容。

## 2. 把 pids controller ID 放到最后

本机原厂实际启用的顺序是：

```text
cpuset=0 cpu=1 cpuacct=2 io=3 memory=4 freezer=5 net_prio=6
CGROUP_SUBSYS_COUNT=7
```

`include/linux/cgroup_subsys.h` 中 pids 后面的 rdma、misc、debug 在原配置都关闭。因此直接启用 pids 已经是 **pids=7、COUNT=8，所有旧 ID 不变**。对本机把它再挪到尾部，并不消除任何已测差异。

`include/linux/cgroup-defs.h` 中的四个成员都以 COUNT 决定物理长度：

```c
css_set.subsys[CGROUP_SUBSYS_COUNT]       /* 每新增一项增加 8 字节 */
css_set.e_cset_node[CGROUP_SUBSYS_COUNT] /* 每新增一项增加 16 字节 */
cgroup.subsys[CGROUP_SUBSYS_COUNT]       /* 每新增一项增加 8 字节 */
cgroup.e_csets[CGROUP_SUBSYS_COUNT]      /* 每新增一项增加 16 字节 */
```

源码没有独立名为 `cgroup_subsys_state_array` 的 ABI 容器可供替换；实际问题是这些内嵌定长数组。`task_css_check`/`task_css`（`include/linux/cgroup.h:488–512`）会内联数组访问，`task_under_cgroup_hierarchy` 也会内联读取移位后的 `dfl_cgrp`。

仅把数组继续固定成 7、却让新 pids 用索引 7，会越界到原来的下一个成员；仅对 genksyms 隐藏 COUNT 变化也只隐藏检查，仍不修物理布局。`cgroup`/`css_set` 本身没有可直接使用的 Android KABI reserve；`cgroup` 尾部还是柔性 `ancestors[]`，`cgroup_root` 特别要求其祖先存储紧接内嵌 cgroup，不能随意在尾部加一个字段。

**理论上的保 ABI 重构**需要保留旧 7 槽和所有后续偏移，把新 controller 的 css / cset 列表放到外部存储，并将核心所有按 controller 下标的访问、模板比较、hash、创建/迁移/退出、引用计数及 RCU 释放改成能够访问额外槽的接口；新增 ID 与 genksyms 的兼容视图也要分别处理。局部栈模板可以有新长度，公开结构中旧数组的物理长度却必须固定。这已经是 cgroup 核心移植，不能由“挪一行 SUBSYS(pids)”完成。

`init/Kconfig:1094` 中 `CGROUP_PIDS` 是 bool；这棵树没有直接 `insmod` 一个独立标准 pids-controller 模块、动态补齐上述内部结构的现成路线。

## 3. CFS_BANDWIDTH 移进保留位 / 外置存储

要保留原模块，至少要同时保住 `task_group`、`cfs_rq`、内嵌它的 `rq` 的所有原字段 offset/size/alignment、旧 Android vendor data、以及通过这些类型传播的 ABI 声明。`sched_entity` 本体当前没有新增字段，不应为了修复 CRC 误改它。

本机确有可研究的余地，不能笼统说“所有 padding 技巧都绝对不可能”：

- `task_group` 有 4 个 8-byte KABI reserve。它们总共 32 bytes，装不下新增的 256-byte `cfs_bandwidth`，但可以研究用一个 reserve 放指向外部对象的指针。随后必须把 `&tg->cfs_bandwidth` 的核心访问改成统一 accessor，处理 root_task_group、创建失败回滚、锁、两个 hrtimer 的取消、CPU hotplug、cgroup 离线及 RCU 生命周期。不能把已有 `android_vendor_data1[4]` 当空闲空间：WALT 实际占用它。
- 原厂 `cfs_rq` 没有 KABI reserve，不过现固定配置有 offset 100–127 的 28-byte 空洞、316–319 的 4-byte 空洞、348–383 的 36-byte 尾填充。新增字段的有效存储合计 68 bytes，理论上可拆分放进这些 68 bytes，而保持原 size=384、原字段偏移及内嵌它的 rq 不变。它需要针对当前配置重新排列声明，并检查所有对齐、每个原字段、嵌套类型及 genksyms 视图，不能把其他版本/配置也默认视为兼容。
- 另一种设计是把 cfs_rq 的新状态也外置；它会把调度热路径的直接字段访问换成额外查找/指针，且要处理每 CPU runqueue、group runqueue 的分配、锁序和 teardown。rq 自身 reserve 的存在不能解决每个独立 cfs_rq 对象都需要存储的问题。

这些是**实现方向**，不是已写好或验证的补丁。本次没有对源码做上述重排。只有物理 ABI 已证明保持后，才可以用 Android KABI/genksyms 的旧视图维持 CRC；提前隐藏声明差异会掩盖错误。

### 还需要验证 WALT 的限额语义

旧模块不仅保存偏移，也保存调度决策。当前 `walt_cfs.c:1488–1495` 的 MVP repick 路径明确留下“启用 CFS_BANDWIDTH 时可能选到 throttled cfs_rq”的 TODO，随后直接 `set_next_entity`。核查结果如下，避免把一条注释误写成已实测绕过：

1. 原厂 `CONFIG_SCHED_WALT=m`；`kernel/sched/walt/Makefile` 无额外开关地把 `walt_cfs.o` 编入 `sched-walt.ko`。`walt_init` 调 `walt_cfs_init` 注册 `android_rvh_replace_next_task_fair`，初始化 stop handler 把 `walt_disabled` 从 true 改为 false。
2. 从实机保存的 `vendor_dlkm-modules/sched-walt.ko` 的 `modinfo` 得到 `scmversion=g19e9b13339e2`，符号表包含 `walt_cfs_replace_next_task_fair`、`walt_cfs_init`、`walt_get_mvp_task_prio`。反汇编存在选第一个 MVP、设置 repick、遍历实体直接调 `set_next_entity` 的代码，与源码风险路径相符。
3. 路径需要 WALT 已激活、`wrq->skip_mvp=false` 且 MVP 列表非空。普通容器忙循环不自动成为 MVP。任务入列还受任务类型和执行额度限制。
4. `sysctl_walt_low_latency_task_threshold` 源默认是 0；`sysctl_walt_rtg_cfs_boost_prio=99`，对普通 FAIR 线程默认关闭该 RTG 入口。pipeline/heavy 标志、`TASK_BOOST_STRICT_MAX` 是另外的 MVP 入口；Binder/procfs 路径又受低延迟阈值限制。每 rq 默认 `skip_mvp=false`，但初始 MVP 列表为空。
5. MVP slice 为 3 ms，通常总额度为 12 ms、Binder MVP 为 3 ms；这是 WALT 自身的优先任务时间策略，**不是**用户配置的 CFS cgroup quota。持续执行后的自动降级也不能证明它尊重某容器 0.1/0.5 CPU 的限额。

当前保存资料没有实际 MVP 命中 trace、相关运行时 sysctl 快照、或者受限组在 throttled 期间仍运行的观测。结论是 **编入实际模块、条件可达的未验证兼容性风险**，不是已证实的 quota 绕过。原厂 CONFIG_CFS_BANDWIDTH=n，自然也不能用于证明新 quota 路径正常。

最小修复候选位置是 `walt_cfs_replace_next_task_fair` 在写入 `*p/*se/*repick` 之前：验证所选候选及祖先 cfs_rq 的 throttle/runtime 状态，不适合时保留内核原选择，或继续寻找合格候选。保守设计可以在存在 bandwidth 约束的场景完全放弃该 repick。必须覆盖 scheduler core 的 `simple=true` 与 `false` 两个调用路径；只在 TODO 下加判断、却已经覆盖了输出参数，或仅判断叶子而忽略祖先限额，仍不充分。若继续沿用原预编译 WALT，这种决策逻辑只能在核心调用边界提供等价校验；若修改模块函数，就需要重编至少该模块并重做 ABI 依赖验证。

## 4. cpuset、ulimit 能提供什么

当前 DroidSpaces 的真实实现是 `src/cgroup.c:832–869`：`--cpus` 写 v2 `cpu.max` 或 v1 `cpu.cfs_period_us/cpu.cfs_quota_us`；`--pids-limit` 写 `pids.max`。写入失败后会清除该运行时限制，不会自动切换成 cpuset 或 RLIMIT。

| 方法 | 实际保证 | 与 DroidSpaces 选项的差异 |
|---|---|---|
| CFS `cpu.max` / quota+period | FAIR 任务组每周期 CPU 时间额度，可跨多个 CPU、可取小数 | `--cpus` 的当前实现；不是对所有调度类的通用 CPU 上限 |
| cpuset / CPU affinity | 指定可运行在哪些 CPU 上 | 不定义每周期总时间；不能表达 `--cpus=0.5`；异构核的性能与绑核选择相关 |
| cpu.weight / nice | 竞争时的相对权重 | 系统空闲时仍可使用更多 CPU，没有硬 quota |
| RLIMIT_CPU | 单进程累计 CPU 时间的终止/信号阈值 | 不是周期性恢复的整个容器 CPU 预算 |
| cgroup pids.max | 容器子树内任务/TID 数量，跨 UID、含线程，fork/clone 超限返回 EAGAIN | `--pids-limit` 的当前实现 |
| RLIMIT_NPROC / `ulimit -u` | 与 real UID/user namespace 计数相关的 fork 限制，阈值由进程继承 | 不等于整个容器跨 UID 总数；相同 UID 的容器/宿主任务可能共享计数；特权豁免也不同 |

例如 cpuset 只允许一颗 CPU 时，忙循环仍可以消耗该 CPU 每个周期的全部可用时间；`--cpus=0.5` 则要求约半颗逻辑 CPU 的时间额度。将两者在 UI 中都叫“0.5 CPU 上限”会误导用户。cpuset 可作为单独的“允许使用哪些核心”功能，但需要 DroidSpaces 或启动脚本明确实现并展示新语义。

`kernel/fork.c:2349–2352` 显示 RLIMIT_NPROC 达限后，`INIT_USER` 或拥有相关宿主能力的进程可能豁免；rootful 容器不能直接假设 `ulimit -u` 已经隔离了 fork 数量。专用 UID/user namespace、映射和降权可以改善其适用范围，但依然是另一种限制模型。`kernel/cgroup/pids.c:238–259` 的 pids 额度检查按 cgroup 层级计费，控制器路径本身没有这组 UID/能力豁免；组织性迁移可以使 current>max，控制器限制的是后续 fork/clone，不能描述成“任何时候绝不超过 N”。

## 判断一条新路线是否真正成立

ABI 兼容方案首先要让这 400 个旧模块涉及的实际布局与调用契约得到证明；全面重编路线则要为变化的 ABI 产出匹配模块集合和依赖。两条路线都不能止于 Image 编译通过。

限额验证至少需要：

- 在正确、可写并已启用 controller 的子 cgroup 中写入额度并读回；确认测试线程确实属于它，而非只检查配置或文件存在。
- 对单线程、多线程、跨 CPU、跨子组的 FAIR 负载测量 cgroup 累计 CPU 时间，结合周期、slice 与 burst 允许量判断额度；同时观察 `cpu.stat` 的 throttled 数据。要覆盖普通任务和实际能触发 MVP 的 pipeline/boost/唤醒负载、`simple` 两种路径、睡眠唤醒与 CPU hotplug。若没有 MVP 命中证据，通过普通压力测试不能消除上面的 WALT 候选。
- 对 pids 检查既包括 fork 也包括线程 clone；用现有任务基数确定剩余额度，确认超限 EAGAIN、释放后恢复、子组继承最紧额度，以及不同 UID 仍共同计数。
- 实机确认模块加载、音频/显示/触控/WLAN 等基础功能，以及 DroidSpaces 实际读取和展示的生效限制。只测 CPU/PID 数值、却通过强制加载破坏厂商模块，不构成可交付结果。

本审计没有实施这些运行时实验。直接开启配置的构建/静态对照已经完成，尚不能称为完整可刷并正确执行限额的内核。保 ABI 重构不是被理论禁止；目前缺少的是实现、全量 ABI 证明和上述语义验证。

## 可复核的本地证据

- 内核源码：`<build-root>/kernel/{include/linux/cgroup-defs.h,include/linux/cgroup_subsys.h,include/linux/cgroup.h,kernel/sched/sched.h,kernel/sched/core.c,kernel/sched/fair.c,kernel/sched/walt,kernel/cgroup/pids.c,kernel/fork.c,kernel/module/version.c,kernel/module/signing.c}`。
- 规范文档：同树 `Documentation/admin-guide/cgroup-v2.rst`、`Documentation/scheduler/sched-bwc.rst`；DroidSpaces `src/cgroup.c`、`src/main.c`、`Documentation/Features.md`。
- 实际原模块/BTF：`output/droidspaces-20261019/device-baseline-v1/{vendor_dlkm-modules,system_dlkm-modules,vmlinux.btf,modules.txt}`。
- 两项启用后的实测静态报告：`output/droidspaces-limits-20261019/verification/{module-abi-vs-stock.json,btf-vs-stock.json}`；这些输入均只读。


