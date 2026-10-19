# Meizu 21 Pro DroidSpaces kernel

This repository contains the reproducible configuration, KABI patch, packaging scripts, verification reports, and a candidate Android 17 / Linux 6.1.176 boot image for Meizu 21 Pro (`meizu21Pro`).

The candidate was built from `meizu-8650-kernel/android_kernel_meizu_sm8650` commit `19e9b13339e26612844b620c2bdd54228dc6d836` with Android Clang 22.0.2 / r596125. DroidSpaces configuration is based on upstream commit `8b625e110270e2f0d32004f740b1e9a71b1f540c`.

## Candidate artifacts

- `artifacts/boot-droidspaces-meizu21pro-avb.img` — AVB-signed boot partition image, SHA-256 `eab3f1d4ea2da3df4623ec44292cadf9c511821aeea14647bdaf12959ac3b006`
- `artifacts/Image` — uncompressed arm64 kernel, SHA-256 `7f8d7ed65ef5a636c11b952bbcdb534d7bf84cff6ffd17504b3e9fc27fb8a6d1`
- `artifacts/kernel.config` — final embedded configuration
- `config/droidspaces-fragment-6.1.config` — frozen feature fragment

The candidate enables PID/IPC namespaces, SYSVIPC, devtmpfs, user namespaces, IPv6 NAT, macvlan, tmpfs ACL/xattr, and related DroidSpaces networking features. `CONFIG_CFS_BANDWIDTH` and `CONFIG_CGROUP_PIDS` remain disabled because enabling them changes the GKI ABI and breaks existing vendor modules without a complete module rebuild.

## Verification status

Static verification passed for the embedded configuration, AVB packaging, selected BTF layouts, 449 captured vendor/system modules, and 59 signed system modules. The candidate was also booted and used on a Meizu 21 Pro running the current PixelOS setup on October 20, 2026, with no problems reported during the real-device validation. This runtime result is user-reported and is recorded separately from the automated static reports; the generated reports intentionally retain their original `boot_tested: false` metadata. Read `verification/` and the research documents for exact scope and limitations.

The candidate does not enable `CONFIG_CFS_BANDWIDTH` or `CONFIG_CGROUP_PIDS`. These options remain unavailable because enabling them changes the GKI ABI and breaks the captured vendor modules without a complete module rebuild. See `verification/runtime-validation-20261020.md` for the runtime validation record.

The native probe in `tests/kernel_probe` is a root-only aarch64 smoke test for namespaces, SYSVIPC, seccomp, and devtmpfs registration. It was run against the stock kernel as a negative baseline; run it again after booting a candidate.

## Build and test

The repository intentionally does not include the full Qualcomm kernel source, Android toolchains, phone partition backups, or private signing keys. Obtain the pinned sources and toolchain separately, then adapt the paths in the scripts for the local environment. The provenance files and source assessment document record the required commits.

Before flashing any boot image, verify the device, active slot, bootloader state, ROM build, AVB policy, and a tested recovery path. Keep the original boot and init_boot backups outside this repository.

## Attribution

DroidSpaces, the Meizu kernel sources, Android AVB tooling, and PixelOS/Lineage build files remain under their upstream licenses. This repository contains the project-specific configuration, patches, scripts, reports, and build artifacts collected for this device.

