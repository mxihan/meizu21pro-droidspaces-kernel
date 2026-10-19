"""Read-only device snapshot and partition backup; never reboot or write the phone."""
import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    adb = [shutil.which("adb") or "adb", "-s", args.serial]

    def capture(name, command):
        result = subprocess.run(adb + ["exec-out", command],
                                capture_output=True, check=True, timeout=90)
        (args.output / name).write_bytes(result.stdout)
        if result.stderr:
            (args.output / (name + ".stderr")).write_bytes(result.stderr)
        return result.stdout

    status = capture("device-status.txt", "uname -a; cat /proc/version; id; "
        "getprop ro.product.device; getprop ro.build.version.release; "
        "getprop ro.boot.slot_suffix; getprop sys.boot_completed; "
        "getprop ro.boot.verifiedbootstate; getprop ro.boot.flash.locked; "
        "getprop sys.usb.config; getprop persist.sys.usb.config; "
        "getenforce; cat /proc/cgroups; mount | grep cgroup")
    compressed = capture("config.gz", "cat /proc/config.gz")
    (args.output / "stock.config").write_bytes(gzip.decompress(compressed))
    capture("modules.txt", "cat /proc/modules")
    capture("module-properties.txt", "for p in /data/adb/modules/*/module.prop; "
        "do echo $p; cat $p; done")
    capture("adb-services.txt", "ls -la /data/adb/modules/dsdebug; "
        "cat /data/adb/modules/dsdebug/service.sh; "
        "cat /data/adb/modules/dsdebug/post-fs-data.sh")
    slot = subprocess.check_output(adb + ["shell", "getprop", "ro.boot.slot_suffix"],
                                   text=True, timeout=20).strip()
    if slot not in ("_a", "_b"):
        raise RuntimeError(f"Unexpected active slot {slot!r}")
    hashes = {}
    for stem in ("boot", "init_boot", "vendor_boot", "dtbo", "vbmeta"):
        partition = stem + slot
        block = "/dev/block/by-name/" + partition
        size = int(subprocess.check_output(adb + ["shell", "blockdev", "--getsize64", block],
                                            text=True, timeout=20).strip())
        if not 0 < size <= 256 * 1024 * 1024:
            raise RuntimeError(f"Unexpected partition size for {partition}: {size}")
        image = args.output / (partition + ".img")
        with image.open("xb") as stream:
            result = subprocess.run(adb + ["exec-out", "cat", block],
                                    stdout=stream, stderr=subprocess.PIPE, timeout=180)
        result.check_returncode()
        if image.stat().st_size != size:
            raise RuntimeError(f"Incomplete {partition}: {image.stat().st_size} != {size}")
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        remote = subprocess.check_output(adb + ["shell", "sha256sum", block],
                                         text=True, timeout=60).split()[0]
        if digest != remote:
            raise RuntimeError(f"Read-back hash mismatch: {partition}")
        hashes[partition] = {"bytes": size, "sha256": digest}
        print(f"VERIFIED {partition}: {size} bytes, sha256={digest}", flush=True)
    metadata = {"captured_hong_kong": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "serial": args.serial, "active_slot": slot, "partitions": hashes,
                "device_status": status.decode(errors="replace")}
    (args.output / "snapshot.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

