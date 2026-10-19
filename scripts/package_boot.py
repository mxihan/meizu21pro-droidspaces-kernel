"""Repack and sign boot using the running ROM's AVB recipe; no device writes."""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock", required=True, type=Path)
    parser.add_argument("--kernel", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--avbtool", required=True, type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--verification", required=True, type=Path)
    args = parser.parse_args()
    if bool(args.kernel) != bool(args.output):
        parser.error("--kernel and --output must be provided together")
    args.verification.mkdir(parents=True, exist_ok=True)
    avb = [sys.executable, str(args.avbtool)]

    def run(*command):
        return subprocess.check_output([str(c) for c in command], text=True, stderr=subprocess.STDOUT)

    def avbrun(*command):
        return run(*avb, *command)

    def verify(image):
        # Hash descriptors use the partition name to resolve boot.img. The
        # delivery filename and backup's slot suffix need not be boot.img.
        with tempfile.TemporaryDirectory(prefix="droidspaces-avb-verify-") as directory:
            named = Path(directory) / "boot.img"
            named.symlink_to(image.resolve())
            return avbrun("verify_image", "--image", named, "--key", args.key)

    stock = args.stock.read_bytes()
    assert stock[:8] == b"ANDROID!"
    assert struct.unpack_from("<I", stock, 40)[0] == 4, "Only the observed v4 boot format is supported"
    old_kernel_size, ramdisk_size = struct.unpack_from("<2I", stock, 8)
    assert ramdisk_size == 0 and struct.unpack_from("<I", stock, 1580)[0] == 0
    footer = struct.unpack_from(">4s2I3Q28s", stock, len(stock) - 64)
    assert footer[:3] == (b"AVBf", 1, 0)
    original_size, vbmeta_offset, vbmeta_size = footer[3:6]
    assert original_size == vbmeta_offset and vbmeta_size > 0
    original_kernel = stock[4096:4096 + old_kernel_size]

    def payload(kernel):
        assert kernel[56:60] == b"ARMd", "Not an uncompressed arm64 kernel Image"
        header = bytearray(stock[:4096])
        struct.pack_into("<I", header, 8, len(kernel))
        data = bytes(header) + kernel
        return data + bytes((-len(data)) % 4096)

    assert payload(original_kernel) == stock[:original_size], "Unrecognised boot payload or padding"
    info = avbrun("info_image", "--image", args.stock)
    (args.verification / "stock-boot-avb.txt").write_text(info)

    def field(name, text=info, indented=False):
        prefix = r"\s*" if indented else ""
        match = re.search(r"^" + prefix + re.escape(name) + r":\s+(.+)$", text, re.M)
        assert match, (name, text)
        return match.group(1).strip()

    algorithm = field("Algorithm")
    rollback = field("Rollback Index")
    rollback_location = field("Rollback Index Location")
    flags = field("Flags")
    salt = field("Salt", indented=True)
    key_sha1 = re.search(r"^Public key \(sha1\):\s+([0-9a-f]+)$", info, re.M).group(1)
    assert algorithm == "SHA256_RSA4096" and flags == "0"
    assert field("Partition Name", indented=True) == "boot"
    props = re.findall(r"^\s+Prop: ([^ ]+) -> '(.*)'$", info, re.M)
    assert len(props) == 3
    verify_original = verify(args.stock)
    (args.verification / "stock-boot-avb-verify.txt").write_text(verify_original)

    with tempfile.TemporaryDirectory(prefix="boot-package-", dir=args.verification) as temp:
        temporary = Path(temp)
        public = temporary / "avb-public-key.bin"
        avbrun("extract_public_key", "--key", args.key, "--output", public)
        assert hashlib.sha1(public.read_bytes()).hexdigest() == key_sha1, "AVB key differs from the ROM"

        def sign(image):
            command = ["add_hash_footer", "--image", image,
                       "--partition_size", str(len(stock)), "--partition_name", "boot",
                       "--hash_algorithm", "sha256", "--salt", salt,
                       "--algorithm", algorithm, "--key", args.key,
                       "--rollback_index", rollback, "--rollback_index_location", rollback_location,
                       "--flags", flags]
            for key, value in props:
                command += ["--prop", key + ":" + value]
            avbrun(*command)

        # The packaging control must reproduce the original signed partition
        # byte for byte before the same recipe is used for the new kernel.
        control = temporary / "boot-stock-reproduction.img"
        control.write_bytes(payload(original_kernel))
        sign(control)
        reproduced = control.read_bytes()
        assert reproduced == stock, "AVB packaging control did not reproduce the original partition"
        report = {"stock_boot_sha256": sha(stock), "stock_reproduction_sha256": sha(reproduced),
                  "stock_reproduction_identical": True, "partition_size": len(stock),
                  "avb_tool_version": avbrun("version").strip(),
                  "avb_tool_sha256": sha(args.avbtool.read_bytes()),
                  "public_test_key_source_sha256": sha(args.key.read_bytes()),
                  "avb_public_key_sha1": key_sha1, "algorithm": algorithm,
                  "rollback_index": int(rollback), "rollback_index_location": int(rollback_location),
                  "flags": int(flags), "props": dict(props), "salt": salt}
        print("PASS: original signed boot reproduced byte for byte", flush=True)

        if args.output:
            if args.output.exists():
                raise FileExistsError(args.output)
            kernel = args.kernel.read_bytes()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(payload(kernel))
            sign(args.output)
            verification = verify(args.output)
            (args.verification / "candidate-boot-avb-verify.txt").write_text(verification)
            candidate_info = avbrun("info_image", "--image", args.output)
            (args.verification / "candidate-boot-avb.txt").write_text(candidate_info)
            for name in ("Algorithm", "Rollback Index", "Rollback Index Location", "Flags"):
                assert field(name, candidate_info) == field(name)
            signed = args.output.read_bytes()
            assert len(signed) == len(stock)
            size = struct.unpack_from("<I", signed, 8)[0]
            assert size == len(kernel) and signed[4096:4096 + size] == kernel
            assert signed[:8] + signed[12:4096] == stock[:8] + stock[12:4096]
            report.update({"candidate_file": args.output.name, "candidate_boot_sha256": sha(signed),
                           "kernel_size": size, "kernel_sha256": sha(kernel),
                           "header_preserved_except_kernel_size": True,
                           "candidate_avb_verified": True, "candidate_boot_tested": False})
            print("PASS: candidate boot AVB signature, hash, header and kernel read-back", flush=True)
        (args.verification / "boot-packaging.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

