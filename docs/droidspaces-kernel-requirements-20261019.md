# Meizu 21 Pro 的 Droidspaces 内核需求核验

核验日期：2026-10-19，Asia/Hong_Kong。本文是编译前的功能与兼容性清单，不代表已完成编译、启动或手机功能测试。

## 固定版本与实际对象

- 设备基线：PixelOS 17 / Android 17，`Linux 6.1.176-g19e9b13339e2`，ARM64；编译器为 Android clang r596125 / 22.0.2。原始配置见 [stock.config](../output/droidspaces-20261019/device-baseline-v1/stock.config)。Android 用户空间版本不能代替实际内核的源码、KMI 和工具链版本。
- Meizu 内核源码固定为 `meizu-8650-kernel/android_kernel_meizu_sm8650@19e9b13339e26612844b620c2bdd54228dc6d836`，与运行内核的 `g19e9b13339e2` 对应。本文所说“该树”均指这一 SHA。[S8][S9]
- 截至核验时，Droidspaces 最新正式版为 **v7.0.0**，发布于 `2026-10-14T13:05:38Z`，即香港时间 2026-10-14 21:05:38；发布提交为 `37e8b45de5ddc57d35cb8adfd8327add75e25159`。[S1]
- 同日取得的 `main` 固定为 `8b625e110270e2f0d32004f740b1e9a71b1f540c`，本地克隆为 `sources/droidspaces-upstream`。**以下以此代码为需求真值**，同时检查了 v7.0.0 与它的差异。[S2][S3]
- 发布版之后，`main` 新增 swap accounting 探测和容器 swap 限制。正式版 APK 的检查项可能少一项，不能把“已通过正式版检查”当作 swap 上限已验证。[S3]

本任务的设备调查报告称 Droidspaces 7 的模块与 daemon 已运行，SELinux 为 Enforcing，暂时没有容器；cgroup 已有 v1 与 v2 混合布局。本文未通过 adb 操作或改写设备。

## 可直接用于下一阶段的文件

功能请求片段为 [research-fragment-6.1.config](../sources/droidspaces-upstream/research-fragment-6.1.config)，**114 个明确配置要求，相对采集的 stock.config 有 18 个直接差异**；自动选择的依赖尚须目标树 `olddefconfig` 展开。差异记录为 [fragment-direct-delta.json](../sources/droidspaces-upstream/research-20261019/fragment-direct-delta.json)。片段已冻结，SHA256 为 `9EA33BFE8DBB102B6E135BCF6B3F1274D0FD930F0C57F9BA11B1D211C144DDB3`。

片段预留了 Droidspaces 核心、IPv4/IPv6 NAT、macvlan、VPN、FUSE、ext4 sparse image、OverlayFS、NixOS 的 tmpfs 属性、用户命名空间，以及基于 legacy iptables 的 UFW/Fail2Ban。它明确保留当前 `CFS_BANDWIDTH=n`、`CGROUP_PIDS=n`、`CGROUP_DEVICE=n`、`NF_TABLES=n`、`BRIDGE_NETFILTER=n`。这是一组待 KMI 检查的请求，并非能跳过 ABI 验证的“安全配置”。[S2][S3][S8][S10][S11]

## 核心、推荐与功能扩展的区别

当前 `src/check.c` 把 root、内核版本、PID/mount/UTS/IPC namespace、pivot_root、procfs/sysfs、seccomp 列入 MUST HAVE。epoll、signalfd、PTY/devpts、loop/ext4、cgroup v2/cgroup namespace、devtmpfs 列入 RECOMMENDED；网络、FUSE、TUN、OverlayFS、USER_NS 与资源限额是按用途检查的 OPTIONAL。配置全开也不能替代权限、节点、挂载和实际 controller 可用性检查。[S3]

| 用途 | 6.1 配置或条件 | 设备 stock 基线 | 决策 |
|---|---|---|---|
| 核心 namespace | `NAMESPACES`, `PID_NS`, `UTS_NS`, `IPC_NS` | 只有 `PID_NS=n` | 开启 PID namespace |
| SysV IPC | `SYSVIPC`，及现有 `SYSCTL` | `SYSVIPC=n` | 先修 task_struct KABI，再开启 |
| POSIX message queue | `POSIX_MQUEUE` | 已为 y | 保留，不套用 5.10 的 mqueue 补丁 |
| syscall 过滤 | `SECCOMP`, `SECCOMP_FILTER` | 已为 y | 保留；当前核心要求 |
| 基础伪文件系统 | `PROC_FS`, `SYSFS`, `TMPFS`，可用 `pivot_root` | 已为 y | 保留 |
| 终端与事件循环 | `UNIX98_PTYS`, `EPOLL`, `SIGNALFD`, `EVENTFD`，`/dev/ptmx` 与 devpts 挂载 | 配置已满足 | 验证运行节点及交互 |
| systemd 的 cgroup 视图 | `CGROUPS`，cgroup2 和 cgroup namespace 实际可用 | `CGROUPS=y`，混合 v1/v2 | 保留 Android 布局，交给 runtime 适配 |
| sparse rootfs | `BLK_DEV_LOOP`, `EXT4_FS`，ext4 ACL/security | 已为 y | 保留，优先使用 ext4 image |
| 硬件模式 | `DEVTMPFS` | n | 开启；普通模式有 tmpfs fallback |
| volatile 模式 | `OVERLAY_FS` | y | 保留 |
| NixOS/tmpfs 属性 | `TMPFS_POSIX_ACL`, `TMPFS_XATTR` | 均为 n，`FS_POSIX_ACL=y` | 开启 |
| FUSE、VPN | `FUSE_FS`, `TUN`，相应设备节点及权限 | 已为 y | 保留，运行时检查 |
| 嵌套 sandbox | `USER_NS` + 容器 Allow Sandboxing | n，运行开关默认关闭 | 编译开启，逐容器决定使用 |

来源：checker、启动/挂载代码、Meizu 配置与对应 Kconfig。[S3][S4][S5][S12]

`SYSVIPC=y` 能补齐许多 Linux 应用的 IPC，但 checker 不直接创建一组 SysV semaphore/shared-memory/message-queue 来验收；编译后仍须做功能测试。`IPC_NS=y` 当前可由已开启的 POSIX message queue 满足 Kconfig 依赖，并不说明 SYSVIPC 已存在。[S3][S12]

checker 的 seccomp 探测仅调用 `PR_GET_SECCOMP`，甚至把 EINVAL 当作可用；它并未实际安装一个 `SECCOMP_MODE_FILTER`。因此仍须核对 `SECCOMP_FILTER=y`，并从容器日志/实际 syscall 行为验证过滤器已经应用，不能只看该项 PASS。[S3][S17]

## 6.1 GKI 的 SYSVIPC / KMI 处理

上游为低于 6.12 的 GKI 提供三种 task_struct padding 补丁；本树不能随意轮换它们。[S2][S8]

1. 该树 `include/linux/sched.h:1102` 附近仍在原位置条件编入 `sysvsem`、`sysvshm`。直接从 `SYSVIPC=n` 改为 y 会使后面的 task_struct 字段移动。
2. 同文件 `1554` 行之后，padding 1 已装入 `saved_state`，2 已装入 `dmabuf_info`，3 已装入 `user_dumpable`；4 至 8 尚为保留槽。因此 **1_2_3 与 3_4_5 方案不适用于本树**。
3. 应适配 `001.GKI-below-6.12-fix_sysvipc_kabi_6_7_8.patch`，把 `sysv_sem` 放入槽 6、`sysv_shm` 放入槽 7+8，避免继续在原位置加入字段。必须检查目标源码上下文和宏的尺寸约束。
4. `002.5.10_or_lower_use_android_abi_padding_for_posix_mqueue.patch` 不适用本机 6.1；stock 已开启 POSIX_MQUEUE。
5. 上游“ABI-safe”陈述属于其测试经验；本机应以目标工具链编译后的 **Module.symvers、结构体大小/偏移、KMI/ABI 差异、所有实际 vendor 模块引用符号**为准。不能关闭 MODVERSIONS 或强制载入模块来掩盖结构变化。[S2][S8]

与上游对 CPU/process 限额的警告一致，本片段保留 `CFS_BANDWIDTH=n` 与 `CGROUP_PIDS=n`。它们是可选限额，不阻止基本容器、systemd、NAT 或普通 Docker 工作；CPU/进程上限在 runtime 中会被跳过。完整打开它们需要同时解决所有依赖其布局的模块，包含无源码预编译模块这一现实限制。[S2][S3]

## cgroup v1 / v2 与 systemd

6.1 没有要单独启用的 `CONFIG_CGROUP_V2` 或 `CONFIG_CGROUP_NS`。`CGROUPS=y` 提供 cgroup 核心和 namespace 支持；controller 是分别配置的。不能把从旧教程复制的不存在符号当作真实缺项。[S12]

Droidspaces 当前代码会寻找 Android 实际挂载位置，包括 `/dev/cg2_bpf`；没有 `/sys/fs/cgroup` 的 cgroup2 视图时可建立它。资源限制先找 v2 controller，再查持有相应 controller 的 v1 hierarchy。Android 将 cpu、memory 等交给 v1 并不自动意味着它们不可用。[S4]

Linux 6.1 的 cgroup 文档明确允许 v1/v2 混合；同一 controller 不会同时被两边持有。**不为 Droidspaces 强加 `cgroup_no_v1=all`，不在运行的 Android 上卸载、迁移现有 controller。** `--force-cgroupv1` 主要为老内核准备，6.1 第一轮保留默认自动选择。[S4][S13]

- 内存上限依赖 `MEMCG=y`，且不能被 `cgroup_disable=memory` 关闭。
- CPU 配额依赖 `CGROUP_SCHED`、`FAIR_GROUP_SCHED`、`CFS_BANDWIDTH` 及可用 cpu controller；本版保留 stock 的无 CPU 配额状态。
- 进程上限依赖 `CGROUP_PIDS`；本版保留 stock 的无进程上限状态。
- 6.1 的 CPU 使用量可来自 v2 `cpu.stat`，旧内核才必须用 v1 cpuacct；本机也已经有 `CGROUP_CPUACCT=y`。
- `CONFIG_MEMCG_SWAP` 已不在 6.1 Kconfig；不添加此旧符号或旧版 `swapaccount=1` 配方。swap 上限应检查 v2 子 cgroup 的 `memory.swap.max`，或实际 memory v1 hierarchy 的 `memory.memsw.limit_in_bytes`，并以当前 backend 版本的功能为准。[S3][S4][S12]

systemd 容器还需要 runtime 正确提供 `/proc`、只读 `/sys`、cgroup 视图、私有 `/dev` 和 capability。kernel config 本身不能保证容器内每一个 unit 不再显示 degraded。systemd 的 PrivateDevices/PrivateTmp 等功能需要这些挂载和权限接口，不能通过盲目关闭 seccomp 或改全局 SELinux 来替代。[S14]

systemd 官方 README 固定至 `f18365107051ce3b8c924f430a189ff027474e3b` 后补查得到：本机已有 TIMERFD、INOTIFY_USER、KCMP、SHMEM、BPF 等前提，但 `FHANDLE=n`、`AUTOFS_FS=n`。前者用于 libudev/mount/bind handling，后者为 automount 的强烈推荐项，因此片段补上二者；它们不属于 Droidspaces checker 的 MUST 项。FHANDLE 选择的 EXPORTFS 本机已开，仍须和其他修改一起检查 ABI。FANOTIFY 主要用于 udev device watch，而 systemd 容器的 udev 不按宿主方式工作，本轮不扩展它。README 对 FW_LOADER_USER_HELPER 的通用建议也不能覆盖 Android 的实际固件需求，本轮保留 stock=y。[S26][S14][S12]

## 网络与防火墙

### Droidspaces 自身 NAT、gateway、端口映射

本机已具备 NET_NS、VETH、BRIDGE、IPv4 iptables/NAT、conntrack、TCPMSS 和 policy routing 的大部分要求。本片段补上 `NETFILTER_XT_MATCH_ADDRTYPE`，使端口转发可使用 `--dst-type LOCAL` 的精确匹配；当前 backend 没有它时会退回较宽的 DNAT 规则。[S5]

需保留的 6.1 网络前提完整列在片段中，主要包括：

```text
NET, UNIX, PACKET, INET, NET_NS, NETDEVICES, NET_CORE, VETH, BRIDGE
NETFILTER, NETFILTER_ADVANCED, NETFILTER_XTABLES
NF_CONNTRACK, NF_CT_NETLINK, NF_NAT, NF_NAT_MASQUERADE, NF_NAT_REDIRECT
IP_NF_IPTABLES, IP_NF_FILTER, IP_NF_NAT, IP_NF_MANGLE, IP_NF_RAW
IP_NF_TARGET_MASQUERADE, IP_NF_TARGET_REDIRECT
NETFILTER_XT_TARGET_MASQUERADE, NETFILTER_XT_TARGET_TCPMSS
NETFILTER_XT_TARGET_REDIRECT, NETFILTER_XT_MATCH_ADDRTYPE
NETFILTER_XT_MATCH_CONNTRACK, NETFILTER_XT_MARK
IP_ADVANCED_ROUTER, IP_MULTIPLE_TABLES
```

没有 BRIDGE 时，Droidspaces NAT 有 direct-veth fallback；没有 VETH 时则没有相同回退。Gateway 的 LAN 连接需要 bridge。macvlan 另需 `MACVLAN=y`，主要面向以太网/USB 网卡，不能承诺它让 Wi-Fi 任意扮演多个独立 MAC 设备。[S3][S5][S6]

IPv6 NAT 需要 `IPV6`、`IPV6_MULTIPLE_TABLES`、`IP6_NF_IPTABLES/FILTER/MANGLE`、`IP6_NF_NAT`、`IP6_NF_TARGET_MASQUERADE`。本机后两者尚未开启；本片段补齐。IPv6 NAT 探测通过后，还须上游网络有可用地址和路由；缺失时保持 IPv4 是 runtime 的预期行为。[S3][S5]

### UFW / Fail2Ban

普通使用采用 legacy iptables backend。stock 已有多数 comment/state/conntrack/multiport/limit/hashlimit/owner/mark 匹配、IPv4/IPv6 REJECT、NFLOG/QUEUE。片段新增 recent、LOG、IP_SET、hash:ip、hash:net 和 xt_set。UFW 与 Fail2Ban 仍需容器内安装相应用户空间工具；选择 nftables action 则进入下一项的扩展范围。[S6][S15]

### 为什么第一版保持 NF_TABLES 与 BRIDGE_NETFILTER 关闭

这不是把所有网络配置当作可互换模块处理：

- **NF_TABLES**：该树 `include/net/net_namespace.h:145-147` 在 `CONFIG_NF_TABLES` 或 `_MODULE` 下直接把 `struct netns_nftables nft` 嵌入 `struct net`，没有 KABI 包装。从 n 改成 y **或 m** 都会使其后字段偏移变化。这个源码证据足以否定“模块化就一定 KMI 安全”的假定。当前 Droidspaces 的主路径使用 legacy iptables raw socket API，不需要此项。[S9][S5]
- **BRIDGE_NETFILTER**：该树 `include/linux/skbuff.h:4704` 的 `enum skb_ext_id` 在开启此项后先插入 `SKB_EXT_BRIDGE_NF`，会移动现有 XFRM 的 `SKB_EXT_SEC_PATH` 值，`struct skb_ext` 的 `offset[SKB_EXT_NUM]` 也改变。`net/bridge/br_private.h:479` 同时增添 bridge 内部字段。应先做专门 ABI/枚举语义检查或完整模块适配，而不是在首版中无条件开启。[S10]
- **CGROUP_DEVICE**：该树 `include/linux/cgroup_subsys.h:32` 会插入 devices 子系统项，改变 subsystem 编号/数量以及引用它的布局。本机已有 `CGROUP_BPF=y`，可供 cgroup v2 的设备访问控制使用；先保持 v1 devices controller 原值。[S11][S14]

它们可以成为下一版候选，但本研究没有证明其直接开启能兼容当前 vendor 模块。实际导出 CRC 是否不同、模块是否使用受影响枚举，还须编译/模块证据；不能仅因某项没出现在 Droidspaces 推荐片段里就推导其必然会坏或必然安全。

## Docker / Podman 的边界

Droidspaces 的基本嵌套 Docker 配方需要独立网络模式 NAT 或 gateway，以及 ext4 sparse rootfs 供 overlay2 使用。自行准备的 Debian/Ubuntu rootfs 要确认 iptables 为 legacy backend；正式仓库镜像已做相应配置。[S15]

Moby 自家的 checker 还列出 cgroup、KEYS、veth/bridge、bridge netfilter、IPv4/IPv6 filter/mangle/NAT、addrtype/conntrack/mark、POSIX_MQUEUE，以及存储驱动等要求。该脚本覆盖多种版本、驱动与 cgroup 用法，不能把每一条 generic 检查警告都当作当前 cgroup v2 容器必定不能启动的结论。[S16]

本片段覆盖普通的 rootful Docker 用户空间、overlay2 和 legacy NAT 所需的大部分机制，但 **没有承诺完整 Docker bridge firewall 隔离、Swarm、IPVS、overlay/VXLAN 或 nftables backend**。BRIDGE_NETFILTER、CGROUP_DEVICE、NF_TABLES 的限制应在试验中单独记录。需要这些能力时，再根据真实失败信息决定 KMI 适配或全模块重编译范围。[S10][S11][S16]

`USER_NS=y` 是 rootless Docker/Podman、Docker userns-remap、Flatpak/bwrap/浏览器 sandbox 的内核前提。容器还需启用 `--allow-sandboxing`；用户空间可能还需要 subuid/subgid、newuidmap/newgidmap 以及适用的 rootless 网络工具。这些用户空间依赖不由内核镜像提供。[S6][S17][S25]

## NFS / CIFS：独立扩展候选

它们是远程存储客户端功能，不属于 Droidspaces 核心，也不是普通 Docker 的必要条件。本机 NFS_FS、NFSD、CIFS 均为 n。若后续需要 NAS 挂载，可以以以下候选为起点，**不要混入本轮已经冻结的默认片段**：[S18][S19]

```config
# Candidate only: build + dependency + KMI validation required.
CONFIG_NFS_FS=y
CONFIG_NFS_V3=y
CONFIG_NFS_V3_ACL=y
CONFIG_NFS_V4=y
CONFIG_NFS_V4_1=y
CONFIG_NFS_V4_2=y
CONFIG_CIFS=y
CONFIG_CIFS_XATTR=y
CONFIG_CIFS_UPCALL=y
CONFIG_CIFS_DFS_UPCALL=y
# CONFIG_CIFS_ALLOW_INSECURE_LEGACY is not set
```

- NFS_FS 选择 LOCKD/SUNRPC；v4 再选择 SUNRPC_GSS/KEYS，v4.1 引入 backchannel。需要实际展开 Kconfig 依赖及检查新模块/导出，而不只看上面十余行。容器侧需要 nfs-utils 等 mount 工具。[S18]
- 该树 CIFS 配置的路径为 `fs/smb/client/Kconfig`。CIFS 选择 DNS_RESOLVER、KEYS、NLS、ASN1、OID_REGISTRY 和 MD5/SHA256/SHA512/CMAC/HMAC/AES/CCM/GCM 等加密依赖。Kerberos/DFS upcall 还需 cifs-utils、keyutils 和正确 helper 配置。不要虚构 `CONFIG_CIFS_SMB3`、`CONFIG_CIFS_SMB311` 等不存在的独立开关。[S19]
- `CIFS_ALLOW_INSECURE_LEGACY=n` 保留 SMB2.1 及更新 dialect，避免为不需要的 SMB1/SMB2.0 引入默认支持；老式 CIFS_POSIX 的依赖也与这个选项相关。[S19]
- 这些是客户端选项；容器里以 Samba 用户空间程序提供 SMB 服务不要求内核 CIFS 客户端。NFS 内核服务器 NFSD、ksmbd 则是另一组功能，默认不增加。
- 新 filesystem 是否保持全部原有导出 KMI，本文没有编译结果证明。应比较 `inode`、`super_block`、`file_operations`、net namespace 相关布局和 vendor 引用符号；需要 m 模块时还须设计模块安装/加载路径。Droidspaces 默认会过滤容器直接加载宿主内核模块的系统调用，因此不能假定容器内 modprobe 能补齐宿主功能。[S17]

## SELinux、KernelSU、USER_NS

保留 `SECURITY_SELINUX=y` 和当前宿主 Enforcing。Droidspaces 的 boot module 定义 `droidspacesd` 及 `droidspacesd_exec`，仅把该域标记 permissive，并允许从 KSU/Magisk/su 域转换；启动脚本会给 backend 设置对应标签。daemon 也会尝试 exec/dyntransition。这套运行时 policy 是能否正常使用的一部分，编译内核本身不安装它。[S20][S21]

`--selinux-permissive` 是另一个容器选项，会把 **整个宿主** 切到 permissive，最后一个要求该模式的容器停止时恢复 enforcing；不是一般 Droidspaces 内核需求。不要为核心支持改变内核的 SELinux 默认模式。[S6]

启用 USER_NS 不会自动让 Droidspaces 顶层容器成为 rootless。当前 runtime 顶层仍以真实 root 运行；默认 seccomp 拒绝创建 user namespace。Allow Sandboxing 会放行这些 syscall，并提供 pristine `/proc`、只读 `/sys` 等嵌套 sandbox 所需视图，代价是容器 root 可能通过 pristine proc 触及宿主 sysctl。这个能力应在可信容器上逐个启用。[S6][S17]

当前 seccomp 还阻止 module loading、kexec、改宿主时钟等操作，ARM64 backend 会验证 syscall 架构。`noseccomp` 与 hw-access 都不是“完善支持”的通用修复。KernelSU root escape 的隔离逻辑在 backend 中已有专门处理；更换内核时仍须保留与当前 Manager、模块及 ADB 保活方案兼容的 root 实现。[S17]

## 文件系统、桌面与硬件

优先用 ext4 sparse image。直接在 `/data` 的 f2fs 目录放 rootfs 可能遇到 OverlayFS 基底限制，以及 Android restorecon 改写 Linux 文件标签的问题；全局 permissive 既不能修复已经改错的标签，也不替代正确存储方式。[S6][S22]

Adreno GPU、音频、Wayland/X11 支持仍需要匹配的用户空间。Droidspaces 能暴露 kgsl/DMA heap/binder 等节点并启动 Termux:X11、VirGL、PulseAudio 或 Anland；它不随内核提供 Termux 包、Turnip、patch 过的 compositor 或完整硬件虚拟化。第一版应保留已正常工作的 Meizu/Qualcomm GPU、显示、音频和 USB 驱动组合，随后逐项测试。[S23]

non-GKI 教程出现的 FW_LOADER_USER_HELPER、firmware 压缩、qtaguid/cgroup legacy 修复，不自动成为本机 6.1 的新增需求。保留现有 firmware/GPU 驱动配置，不把 3.18–4.19 补丁套在该树。[S2]

## 本版本不能直接照抄的符号

对照所取 Linux 6.1 与 Meizu Kconfig 后，这些常见教程条目要区别处理：[S12][S24]

| 旧写法或误写 | 本机处理 |
|---|---|
| `CONFIG_MEMCG_SWAP`, `CONFIG_MEMCG_SWAP_ENABLED` | 6.1 无需这些独立开关；检查实际 swap accounting 接口 |
| `CONFIG_CGROUP_V2`, `CONFIG_CGROUP_NS`, `CONFIG_MNT_NS` | 不添加这些不存在的独立 6.1 选项 |
| `CONFIG_DEVPTS_MULTIPLE_INSTANCES` | 新内核不再需要独立选项；保留 UNIX98_PTYS 并验证挂载 |
| `CONFIG_NF_CONNTRACK_IPV4/IPV6`, `CONFIG_NF_NAT_IPV4/IPV6` | 已合并的旧式协议选项，不复制 |
| `CONFIG_NF_CONNTRACK_NETLINK` | 本树为 `CONFIG_NF_CT_NETLINK` |
| `CONFIG_NETFILTER_XT_TARGET_REJECT` | 本树用 `IP_NF_TARGET_REJECT` 和 `IP6_NF_TARGET_REJECT` |
| `CONFIG_IP_NF_TARGET_ULOG` | 不能当 6.1 必要项；使用现有 NFLOG/netlink logging |
| `CONFIG_ANDROID_PARANOID_NETWORK` | 是旧 Android 内核的限制；本树无此 symbol，不新增虚假的 n 行 |

## 编译后验收清单

这些项目尚未执行，供主任务使用。每次设备测试前先确认 `adb devices`，当前 ADB 依赖 KernelSU 模块这一条件必须保留。

1. 保存原 `.config`、Module.symvers、boot/init_boot/vendor_boot/dtbo 和实际模块清单；核实槽位 6/7/8 的 SYSVIPC 适配没有覆盖现有字段。
2. 合并片段后运行目标树 `olddefconfig`，比较最终配置：无未知/被依赖取消的必需项，尤其 SYSVIPC/PID_NS、IPv6 MASQUERADE、IP_SET 依赖；CFS/PIDS/device/nft/bridge_nf 仍为 n。
3. 使用相同工具链、构建模式和 KMI 版本先做 baseline，再做修改版；对比导出 CRC 和相关布局，检查保留的每个 vendor 模块导入符号，避免把“编译成功”当作“模块兼容”。
4. 启动后验证 KSU、ADB 恢复、SELinux Enforcing、modprobe/模块加载日志，以及电话、数据、Wi-Fi、蓝牙、相机、显示、GPU、音频、充电、USB、休眠等原有功能。
5. 运行匹配版本的 `droidspaces check --format` 和人类可读检查，保存结果；创建 ext4 sparse Debian/Ubuntu systemd 容器，验证 init=PID1、终端、shutdown/reboot、DNS、IPv4、IPv6、端口转发、容器停止后的网络清理。
6. 验证 SysV IPC、POSIX message queue、tmpfs ACL/xattr；验证 FUSE/TUN 和 volatile OverlayFS；macvlan 选真实以太网/USB 网卡测试。
7. 在明确开启 Allow Sandboxing 的测试容器中验证 bwrap/USER_NS；另测 rootful Docker 的启动、overlay2、DNS、出网、端口映射和容器间防火墙，再记录 bridge netfilter 未开启带来的实际差异。rootless、nftables、Swarm 等另外建表验收。
8. 检查实际 memory controller 和 swap cap。当前片段不提供 CPU/进程限额，预期 checker 对这两项显示缺失，不能用禁用 ABI 检查来消除它们。

## 来源与可复核材料

下列项目均为第一方代码、文档或本机采集；Droidspaces 固定 SHA 的文件也可在本地 clone 复查。

- [S1] [Droidspaces v7.0.0 release](https://github.com/ravindu644/Droidspaces-OSS/releases/tag/v7.0.0)，另存 [GitHub release API 响应](../sources/droidspaces-upstream/research-20261019/droidspaces-latest-release.json)。
- [S2] [Droidspaces kernel guide，固定 SHA](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Documentation/Kernel-Configuration.md)。
- [S3] [Droidspaces src/check.c，固定 SHA](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/check.c)。
- [S4] [Droidspaces src/cgroup.c，固定 SHA](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/cgroup.c)。
- [S5] [Droidspaces src/net/iptables.c](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/net/iptables.c)、[network.c](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/net/network.c)、[netlink.c](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/net/netlink.c)。
- [S6] [Droidspaces Features](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Documentation/Features.md)。
- [S8] [Meizu sched.h@19e9b133](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/linux/sched.h#L1102)，[task_struct 保留槽](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/linux/sched.h#L1554)，[Droidspaces 6/7/8 补丁](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Documentation/resources/kernel-patches/GKI/below-kernel-6.12/001.GKI-below-6.12-fix_sysvipc_kabi_6_7_8.patch)。
- [S9] [Meizu struct net 中 NF_TABLES 条件字段](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/net/net_namespace.h#L145)。
- [S10] [Meizu skb_ext_id 和 skb_ext](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/linux/skbuff.h#L4704)，[net_bridge 条件字段](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/net/bridge/br_private.h#L479)。
- [S11] [Meizu cgroup subsystem 顺序](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/include/linux/cgroup_subsys.h#L32)。
- [S12] [Meizu init/Kconfig](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/init/Kconfig)，对照 [Linux v6.1 init/Kconfig@830b3c68](https://github.com/torvalds/linux/blob/830b3c68c1fb1e9176028d02ef86f3cf76aa2476/init/Kconfig)。
- [S13] [Linux 6.1 cgroup v2 文档](https://docs.kernel.org/6.1/admin-guide/cgroup-v2.html)。
- [S14] [systemd Container Interface](https://systemd.io/CONTAINER_INTERFACE/)。
- [S15] [Droidspaces Docker/UFW recipes](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Documentation/Cool-things-you-can-do.md)。
- [S16] [Moby contrib/check-config.sh@a4c5b2be](https://github.com/moby/moby/blob/a4c5b2be6f69f86fe7b13eb4822676f8d273cf8b/contrib/check-config.sh)，另存 [本地快照](../sources/droidspaces-upstream/research-20261019/moby-check-config-a4c5b2be6f69f86fe7b13eb4822676f8d273cf8b.sh)。
- [S17] [Droidspaces seccomp.c](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/seccomp.c)、[boot.c](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/boot.c)、[mount.c](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/mount.c)。
- [S18] [Meizu NFS Kconfig](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/fs/nfs/Kconfig)，[fs/Kconfig](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/fs/Kconfig)。
- [S19] [Meizu CIFS Kconfig](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/fs/smb/client/Kconfig)。
- [S20] [Droidspaces boot-module sepolicy.rule](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Android/app/src/main/assets/boot-module/sepolicy.rule)，[post-fs-data.sh](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Android/app/src/main/assets/boot-module/post-fs-data.sh)。
- [S21] [Droidspaces daemon.c](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/daemon.c)、[utils.c](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/src/utils.c)。
- [S22] [Droidspaces Troubleshooting](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Documentation/Troubleshooting.md)。
- [S23] [Droidspaces Graphics and Audio](https://github.com/ravindu644/Droidspaces-OSS/blob/8b625e110270e2f0d32004f740b1e9a71b1f540c/Documentation/Graphics-and-Audio.md)。
- [S24] [Meizu netfilter Kconfig](https://github.com/meizu-8650-kernel/android_kernel_meizu_sm8650/blob/19e9b13339e26612844b620c2bdd54228dc6d836/net/netfilter/Kconfig)，对照 [Linux 6.1 netfilter Kconfig](https://github.com/torvalds/linux/blob/830b3c68c1fb1e9176028d02ef86f3cf76aa2476/net/netfilter/Kconfig)。
- [S25] [Docker 官方 rootless prerequisites](https://docs.docker.com/engine/security/rootless/)。
- [S26] [systemd README@f1836510](https://github.com/systemd/systemd/blob/f18365107051ce3b8c924f430a189ff027474e3b/README)，另存 [README 快照](../sources/droidspaces-upstream/research-20261019/systemd-README.txt) 和 [来源 SHA](../sources/droidspaces-upstream/research-20261019/systemd-source-manifest.json)。

辅助证据下载在 `sources/droidspaces-upstream/research-20261019/`，包括固定 SHA 的 Linux 6.1 和 Meizu 头文件/Kconfig，以及来源清单。只下载了本研究所需文本；404 的不存在路径未作为证据使用。

## 2026-10-19 最终产物的只读 BTF 结构验证

本节追加的是 **实际执行结果**。验证脚本为 [verify_final_btf.py](../diagnostics/droidspaces-20261019/verify_final_btf.py)，脚本 SHA256 为 `28dd2037a0121cac2b57d5d271ccb196a17019e77dac7e4157b6f9ab06112d02`。机器可读结果为 [final-btf-layouts.json](../output/droidspaces-20261019/verification/final-btf-layouts.json)，SHA256 为 `c62cd2e521d0f6196c7cdee6362c57810bf1c4ba4304fab5ad5546253d4fd0d3`。

- 原机输入为采集的 raw `vmlinux.btf`，SHA256 `5494183ec97c342c42e627aba9af742719a48589c16a04446f4fa5ee18255fb4`，共 130877 个 BTF type。
- 最终输入为 WSL `<build-root>/out/vmlinux`，SHA256 `e247edbe6805ab527d9c32c24a3403c63c679d21bf191e383914c580560ec939`。它的 ELF `.BTF` SHA256 为 `11a050ea4658f5e3aabcbfc929e3660c93b0596cbc0be61b40676ae083265f99`，共 132053 个 BTF type。
- 脚本请求 **87 种类型**，其中 **71 种存在完整的原版与最终版定义**。70 种逐字段相同，另 1 种为仅使用预留槽新增 SYSVIPC 的 `task_struct`。原有 20 种核心类型全部完成实比，未出现含糊的同名多布局或需要解释的字段差异。
- `task_struct` 总大小双方均为 **4800 字节**，**648 个原有递归命名字段**的绝对 bit offset、存储大小、bitfield 宽度与规范化类型签名全部相同，包括原来的 reserve 6/7/8。只新增 `sysvsem`、`sysvshm` 及其 4 个递归成员。
- 明确断言通过：`sysvsem=3640/8`、`sysvshm=3648/16`、reserve6=`3640/8`、reserve7=`3648/8`、reserve8=`3656/8`、`thread=3664/1120`，格式为 byte offset/size。双方均为 `RANDSTRUCT_NONE=y`，结构字段随机化未启用；KASLR/stack offset 随机化与这个结论不同。
- 对所有实际可比的 struct/union，原始 BTF parser 的 size 与独立 `pahole v1.30` 渲染 size 均一致。对齐属性的 pahole 重构也没有差异，但没有将其误写成完整 C 对齐证明。

重点结构的实际大小及递归字段比较如下，表内每一项均经过实比：

| 类型 | 原版/最终版 byte size | 结果 |
|---|---:|---|
| `net` | 4096 / 4096 | 相同 |
| `netns_ipv4` | 704 / 704 | 相同 |
| `netns_ipv6` | 896 / 896 | 相同 |
| `skb_ext` | 8 / 8 | 相同，另比较 `skb_ext_id` 枚举值 |
| `net_bridge` | 1720 / 1720 | 相同 |
| `inode` | 704 / 704 | 相同 |
| `super_block` | 1536 / 1536 | 相同 |
| `user_namespace` | 656 / 656 | 相同 |
| `ipc_namespace` | 1272 / 1272 | 相同 |
| `nsproxy` | 72 / 72 | 相同 |
| `device` | 912 / 912 | 相同 |
| `class` | 152 / 152 | 相同 |

其余 **16 种没有原版可比较定义，明确记为 `not_present`，不算 PASS**。`netns_nftables` 与 `netns_ipvs` 双方均无完整定义，对应 NF_TABLES/IP_VS 双方均为 n。其余 14 种只在最终版存在：IP_SET 的 `ip_set_net/ip_set/ip_set_type`，devtmpfs 私有 `req`，autofs 的 4 种私有类型，以及 SYSVIPC 的 6 种类型。JSON 每一项都有控制配置和源码解释；IP_SET 的新 per-netns 对象通过 `net_generic` 动态分配，未嵌入 shared `struct net`。devtmpfs 引用的 device、VFS、completion 等 shared 类型已单独比较。

比较会透明展开匿名 struct/union，让 KABI union 外观变化不会伪装成字段移动；它递归展开所有按值嵌入的命名字段，数组核对元素布局、数量与 stride。它在指针处停止，所选列表内的指针目标类型另做独立比较。BTF v1 不完整编码 aggregate/member 的 C alignment/packing，故报告为 `encoded_alignment_bytes=null`，只附 pahole 的重构结果。**这证明所选现存类型的物理字段布局保持，不等于整个 kernel ABI 或实机兼容性已被证明**；module CRC、符号 ABI、签名信任与启动功能仍属于主任务的独立验证范围。本子任务未修改内核源码、编译配置或设备，也未刷写手机。


