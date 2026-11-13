"""Prepare the validated PixelOS 17 device inputs from matching base images."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


REPOSITORY = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_digest(path, expected):
    if digest(path) != expected:
        raise ValueError(f'SHA-256 mismatch for {path}')


def run(*command):
    return subprocess.check_output([str(value) for value in command])


def read_cpio(data):
    entries = []
    position = 0
    while position + 110 <= len(data):
        if data[position:position + 6] != b'070701':
            raise ValueError('Expected a newc vendor ramdisk')
        fields = [int(data[position + 6 + 8 * i:position + 14 + 8 * i], 16)
                  for i in range(13)]
        position += 110
        name = data[position:position + fields[11] - 1].decode()
        position = (position + fields[11] + 3) & ~3
        contents = data[position:position + fields[6]]
        if len(contents) != fields[6]:
            raise ValueError('Truncated CPIO entry')
        position = (position + fields[6] + 3) & ~3
        entries.append((name, fields, contents))
        if name == 'TRAILER!!!':
            return entries
    raise ValueError('Missing CPIO trailer')


def write_cpio(entries):
    result = bytearray()
    for name, fields, contents in entries:
        encoded_name = name.encode() + b'\0'
        fields = fields.copy()
        fields[6], fields[11] = len(contents), len(encoded_name)
        result += b'070701' + ''.join(f'{value:08x}' for value in fields).encode()
        result += encoded_name
        result += b'\0' * (-len(result) % 4)
        result += contents
        result += b'\0' * (-len(result) % 4)
    result += b'\0' * (-len(result) % 512)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-root', type=Path, required=True)
    parser.add_argument('--base-images', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    build = args.android_root.resolve()
    output = (args.output or build / 'device/meizu/meizu21Pro/droidspaces-prebuilt').resolve()
    lock = json.loads((REPOSITORY / 'sources/pixelos17-20261113.json').read_text())
    tools = build / 'out/host/linux-x86/bin'
    os.environ['PATH'] = str(tools) + os.pathsep + os.environ['PATH']
    unpack = build / 'system/tools/mkbootimg/unpack_bootimg.py'
    mkbootimg = build / 'system/tools/mkbootimg/mkbootimg.py'
    avbtool = build / 'external/avb/avbtool.py'
    for tool in (unpack, mkbootimg, avbtool, tools / 'mkfs.erofs', tools / 'fsck.erofs'):
        if not tool.is_file():
            raise FileNotFoundError(f'Build the required Android host tool first: {tool}')
    if shutil.which('lz4') is None:
        raise FileNotFoundError('Install the lz4 command-line tool')

    inputs = {}
    for name, record in lock['base_images'].items():
        path = args.base_images / name
        if not path.is_file():
            path = args.base_images / record['original_name']
        check_digest(path, record['sha256'])
        inputs[name] = path.resolve()
    for relative, expected in lock['public_assets'].items():
        check_digest(REPOSITORY / relative, expected)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pixelos-prebuilts-', dir=output.parent) as directory:
        work = Path(directory)
        staged = work / 'droidspaces-prebuilt'
        (staged / 'dtb').mkdir(parents=True)
        (staged / 'kernelsu').mkdir()
        for name in ('Image', 'kernel.config'):
            shutil.copyfile(REPOSITORY / 'artifacts' / name, staged / name)
        for name in ('dtbo.img', 'system_dlkm.img'):
            shutil.copyfile(inputs[name], staged / name)
        for name in ('ksud', 'ksuinit', 'kernelsu.ko', 'LICENSE'):
            shutil.copyfile(REPOSITORY / 'artifacts/pixelos17/kernelsu' / name,
                            staged / 'kernelsu' / name)
        for name in ('ksud', 'ksuinit'):
            (staged / 'kernelsu' / name).chmod(0o755)
        shutil.copyfile(REPOSITORY / 'scripts/patch_init_boot_kernelsu.py',
                        staged / 'kernelsu/patch_init_boot_kernelsu.py')

        unpacked = work / 'vendor_boot-original'
        boot_args = shlex.split(run(sys.executable, unpack, '--boot_img', inputs['vendor_boot.img'],
                                    '--out', unpacked, '--format=mkbootimg').decode())
        if boot_args.count('--vendor_ramdisk_fragment') != 1:
            raise ValueError('Expected one vendor ramdisk fragment')
        entries = read_cpio(run('lz4', '-dc', unpacked / 'vendor_ramdisk00'))
        changed = set()
        modified = []
        for name, fields, contents in entries:
            if name in ('lib/modules/gcc-pineapple.ko', 'lib/modules/pwm-ir-tx.ko'):
                contents = (REPOSITORY / 'artifacts/pixelos17/ir-modules' / Path(name).name).read_bytes()
                changed.add(name)
            if name == 'lib/modules/modules.load':
                lines = contents.decode().splitlines()
                if not any(line in ('pwm-ir-tx', 'pwm-ir-tx.ko') for line in lines):
                    index = next(i for i, line in enumerate(lines)
                                 if line in ('gcc-pineapple', 'gcc-pineapple.ko'))
                    lines.insert(index + 1, 'pwm-ir-tx.ko' if lines[index].endswith('.ko') else 'pwm-ir-tx')
                    contents = ('\n'.join(lines) + '\n').encode()
                    changed.add(name)
            fields = fields.copy()
            fields[6] = len(contents)
            modified.append((name, fields, contents))
        if changed != {'lib/modules/gcc-pineapple.ko', 'lib/modules/pwm-ir-tx.ko', 'lib/modules/modules.load'}:
            raise ValueError(f'Unexpected vendor ramdisk changes: {changed}')
        raw = work / 'vendor_ramdisk.cpio'
        raw.write_bytes(write_cpio(modified))
        compressed = work / 'vendor_ramdisk.lz4'
        run('lz4', '-l', '-12', '--favor-decSpeed', '-f', raw, compressed)
        boot_args[boot_args.index('--vendor_ramdisk_fragment') + 1] = str(compressed)
        vendor_boot = staged / 'vendor_boot.img'
        run(sys.executable, mkbootimg, *boot_args, '--vendor_boot', vendor_boot)
        before, after = inputs['vendor_boot.img'].read_bytes(), vendor_boot.read_bytes()
        if before[:24] != after[:24] or before[28:2128] != after[28:2128]:
            raise ValueError('Vendor boot header changed beyond the ramdisk size')
        run(sys.executable, avbtool, 'add_hash_footer', '--image', vendor_boot,
            '--partition_name', 'vendor_boot', '--partition_size', len(before),
            '--salt', lock['vendor_boot_avb_salt'], '--prop',
            'com.android.build.vendor_boot.fingerprint:' + lock['base_fingerprint'])
        verified = work / 'vendor_boot-verified'
        run(sys.executable, unpack, '--boot_img', vendor_boot, '--out', verified)
        for component in ('dtb', 'bootconfig'):
            if digest(unpacked / component) != digest(verified / component):
                raise ValueError(f'Changed vendor boot {component}')
        if read_cpio(run('lz4', '-dc', verified / 'vendor_ramdisk00')) != modified:
            raise ValueError('Repacked vendor ramdisk differs from the expected entries')
        shutil.copyfile(unpacked / 'dtb', staged / 'dtb/stock.dtb')

        tree = work / 'vendor_dlkm-tree'
        run(tools / 'fsck.erofs', '--extract=' + str(tree), inputs['vendor_dlkm.img'])
        for name in ('gcc-pineapple.ko', 'pwm-ir-tx.ko'):
            shutil.copyfile(REPOSITORY / 'artifacts/pixelos17/ir-modules' / name,
                            tree / 'lib/modules' / name)
        paths = [tree] + sorted(tree.rglob('*'))
        config = work / 'vendor_dlkm.fs_config'
        config.write_text('/ 0 0 0755 capabilities=0x0\n' + ''.join(
            f'vendor_dlkm{("/" + str(path.relative_to(tree))) if path != tree else ""}'
            f' 0 0 {"0755" if path.is_dir() else "0644"} capabilities=0x0\n'
            for path in paths))
        contexts = work / 'vendor_dlkm.file_contexts'
        contexts.write_text('/vendor_dlkm(/.*)? u:object_r:vendor_file:s0\n'
                            '/vendor_dlkm/etc(/.*)? u:object_r:vendor_configs_file:s0\n')
        dlkm = staged / 'vendor_dlkm.img'
        run(tools / 'mkfs.erofs', '-zlz4hc,9', '-T0', '-U', lock['vendor_dlkm_uuid'],
            '--mount-point', '/vendor_dlkm', '--fs-config-file', config,
            '--file-contexts', contexts, dlkm, tree)
        size = max(inputs['vendor_dlkm.img'].stat().st_size,
                   (dlkm.stat().st_size + 2 * 1024 * 1024 + 4095) // 4096 * 4096)
        run(sys.executable, avbtool, 'add_hashtree_footer', '--image', dlkm,
            '--partition_name', 'vendor_dlkm', '--partition_size', size,
            '--hash_algorithm', 'sha256', '--salt', lock['vendor_dlkm_avb_salt'],
            '--prop', 'com.android.build.vendor_dlkm.os_version:17',
            '--prop', 'com.android.build.vendor_dlkm.fingerprint:' + lock['base_fingerprint'])
        for image in (vendor_boot, dlkm):
            run(sys.executable, avbtool, 'verify_image', '--image', image)
        for relative, expected in lock['prepared_files'].items():
            check_digest(staged / relative, expected)
        if output.exists():
            for relative, expected in lock['prepared_files'].items():
                check_digest(output / relative, expected)
        else:
            staged.rename(output)
    print(f'Verified PixelOS build inputs at {output}')


if __name__ == '__main__':
    main()
