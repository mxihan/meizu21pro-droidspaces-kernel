# Meizu 21 Pro PixelOS 17 build inputs

The November 13, 2026 release uses PixelOS 17 with SDK 37 and the November 1
security patch. Its incremental version is `1794511064`. The system includes
the published DroidSpaces Image, KernelSU v3.3.1 LKM, built-in signal overlays,
dual-microphone VoIP, and the clock-backed IR driver.

## Source checkout

```bash
repo init -u https://github.com/mxihan/android_manifest.git -b meizu21pro-droidspaces --git-lfs
repo sync
```

For the pinned source set, add `-m source-manifest.lock.xml` to `repo init`.
The manifest guide lists the modified source repositories and build commands.
[Build manifest guide](https://github.com/mxihan/android_manifest/blob/meizu21pro-droidspaces/docs-meizu21pro.md)

## Prepare device inputs

Supply the matching proprietary `vendor/meizu` tree for the device. Extract
`vendor_boot.img`, `vendor_dlkm.img`, `system_dlkm.img`, and `dtbo.img` from
your copy of `PixelOS_meizu21Pro-17.0-20260928-0803.zip` into a local directory.
The script also accepts the original `PixelOS-17.0-20260928-` filename prefix.
The exact input and output hashes are recorded in
`sources/pixelos17-20261113.json`.

From the Android source root, build the host tools and prepare the inputs.
Use Linux x86-64 with Python 3.11 or newer and the `lz4` command installed.

```bash
source build/envsetup.sh
breakfast meizu21Pro userdebug
m mkfs.erofs fsck.erofs
python3 prebuilts/meizu/droidspaces/scripts/prepare_pixelos_prebuilts.py \
  --android-root "$PWD" \
  --base-images /path/to/base-images
m pixelos -j12
```

The preparation script stages its output, verifies AVB, and checks every
generated file against the inputs used for the validated release before
installing `device/meizu/meizu21Pro/droidspaces-prebuilt/`. Repeated runs
verify an existing matching directory. `--output` selects another directory
for checking generated files.

For a build with the Meizu touch sampling rate tile, use the M2481
`goodix_ts.ko` built from commit `a7252cea545510034cb8f4d459ce43541f698edc`
with kernel commit `ddd872579d674cdd74033a30d37cd8de1286f5f3` and Android
Clang `r596125`.
[Goodix driver source](https://github.com/mxihan/vendor_qcom_opensource_touch-drivers/commit/a7252cea545510034cb8f4d459ce43541f698edc)

Pass the rebuilt module to the preparation script and stage the inputs in a
new directory. The script checks the module against the pinned kernel and
the `panel_event_notifier` and `qts` export CRCs, then installs it into
`vendor_boot` and `vendor_dlkm`.

```bash
python3 prebuilts/meizu/droidspaces/scripts/prepare_pixelos_prebuilts.py \
  --android-root "$PWD" --base-images /path/to/base-images \
  --touch-module /path/to/goodix_ts.ko --output /path/to/prepared-touch
```

Use the staged inputs as the device's `droidspaces-prebuilt` directory. The
stripped module used for the verified OTA has SHA-256
`14a1916ab567987977aea9f07401375bdaf605883fd76d55c64075a4b1013902`.

The build regenerates Android init and applies KernelSU before AVB signing.
The Android build fork also carries this patched init_boot into target-files
so OTA packaging preserves its ramdisk. KernelSU Manager is installed
separately by the user. The resulting package is a full manual A/B OTA.

## IR module sources and rebuild

The Image SHA-256 is
`7f8d7ed65ef5a636c11b952bbcdb534d7bf84cff6ffd17504b3e9fc27fb8a6d1`.
Its release is `6.1.176-g19e9b13339e2`. The two curated module binaries in
`artifacts/pixelos17/ir-modules/` are the pair used on the validated phone.
Their corresponding kernel source commit is pinned in
`sources/pixelos17-20261113.json`.

The GCC driver supplies 36, 38, 39.5, 40, and 56 kHz TCXO rates. The IR driver
supports the Meizu `gpio-pwm-clk` binding and `ir_active`/`ir_sleep` pinctrl
states. A priority-1 FIFO worker and up to 1 ms of busy-waiting before each
edge improve transmit timing. The measured 500 microsecond intervals ranged
from 472 to 531 microseconds in the final module test.

The rebuild helper uses the matching completed kernel output with its
`.config`, `Module.symvers`, and `vmlinux`, Android Clang r596125, the matching
kernel host tools, and the original `clk-qcom.ko` from the base vendor image.
Install `pyelftools` for the module parser.

```bash
python3 scripts/build_ir_modules.py \
  --kernel /path/to/pinned/kernel \
  --kernel-out /path/to/matching/kernel-out \
  --clang /path/to/clang-r596125 \
  --host-tools /path/to/kernel-build-tools/linux-x86 \
  --clk-qcom /path/to/original/clk-qcom.ko \
  --output /path/to/rebuilt-ir-modules
```

Use `scripts/verify_module_abi.py` with the original module set and the new
pair to check imports, CRCs, and vermagic before updating curated binaries.
`artifacts/pixelos17/core.symvers` records the original core exports.

## LG remote configuration

The validated LG profile in 遥控精灵 contained repeated identical complete NEC
frames inside a single command. `scripts/patch_lg_snapshot.py` prepares a
single-frame correction in an exported, quiescent host-side SQLite copy.
It produces guarded `apply.sql`, `restore.sql`, and a local manifest.
The driver transmits the application-supplied waveform faithfully.

```bash
python3 scripts/patch_lg_snapshot.py /path/to/kkappdb.sqlite \
  --output-dir /path/to/fresh-local-result \
  --did 1 --rid 3668 --all-keys --apply
```

Select `did` and `rid` for the intended LG remote. The script validates the
profile, compressed format, and repeated NEC commands, and verifies every
other table and column in the patched copy. Keep exported databases and
generated SQL in local storage. The release validation summary is in
`verification/pixelos17-20261113.json`.
