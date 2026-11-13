"""Rebuild the two IR modules using the matching completed DroidSpaces build."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', required=True, type=Path)
    parser.add_argument('--kernel-out', required=True, type=Path)
    parser.add_argument('--clang', required=True, type=Path)
    parser.add_argument('--host-tools', required=True, type=Path)
    parser.add_argument('--clk-qcom', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    lock = json.loads((repository / 'sources/pixelos17-20261113.json').read_text())
    kernel, out = args.kernel.resolve(), args.kernel_out.resolve()
    revision = subprocess.check_output(['git', '-C', str(kernel), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != lock['kernel_source_commit']:
        raise ValueError('Use the pinned kernel source commit')
    for relative in ('drivers/clk/qcom/gcc-pineapple.c', 'drivers/media/rc/pwm-ir-tx.c', 'include/linux/sched.h'):
        subprocess.run(['git', '-C', str(kernel), 'diff', '--exit-code', 'HEAD', '--', relative], check=True)
    if (out / '.config').read_text().strip() != (repository / 'artifacts/kernel.config').read_text().strip():
        raise ValueError('Use the published DroidSpaces build configuration')
    core = (out / 'Module.symvers').read_bytes()
    if hashlib.sha256(core).hexdigest() != lock['public_assets']['artifacts/pixelos17/core.symvers']:
        raise ValueError('Kernel output has different exported symbol CRCs')
    if not (out / 'vmlinux').is_file():
        raise FileNotFoundError('The matching completed kernel build must provide vmlinux for BTF')

    spec = importlib.util.spec_from_file_location('module_abi', repository / 'scripts/verify_module_abi.py')
    abi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(abi)
    clock = args.clk_qcom.resolve()
    record = abi.parse_module(clock, clock.read_bytes())
    if record['parse_errors']:
        raise ValueError(record['parse_errors'])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    clang, host = args.clang.resolve(), args.host_tools.resolve()
    environment.update(
        PATH=f'{clang}/bin:{host}/bin:' + environment['PATH'],
        LD_LIBRARY_PATH=f'{host}/lib64' + (':' + environment['LD_LIBRARY_PATH']
                                          if environment.get('LD_LIBRARY_PATH') else ''),
        KBUILD_BUILD_USER='rin', KBUILD_BUILD_HOST='meizu21pro-droidspaces',
        KBUILD_BUILD_VERSION='1', KBUILD_BUILD_TIMESTAMP='Mon Oct 19 10:00:00 UTC 2026')
    with tempfile.TemporaryDirectory(prefix='ir-modules-', dir=output) as directory:
        modules = Path(directory)
        for relative in ('drivers/clk/qcom/gcc-pineapple.c', 'drivers/media/rc/pwm-ir-tx.c'):
            shutil.copyfile(kernel / relative, modules / Path(relative).name)
        (modules / 'Makefile').write_text('obj-m += gcc-pineapple.o pwm-ir-tx.o\n')
        extra = modules / 'qcom.symvers'
        extra.write_text(''.join(
            f"{symbol['crc']}\t{name}\tdrivers/clk/qcom/clk-qcom\t"
            f"{symbol['export_type']}\t{symbol['namespace']}\n"
            for name, symbol in sorted(record['exports'].items())))
        make = ['make', '-C', str(kernel), f'O={out}', 'ARCH=arm64', 'LLVM=1', 'LLVM_IAS=1',
                'CC=clang', 'LD=ld.lld', 'HOSTCC=clang', 'HOSTCXX=clang++', 'LOCALVERSION=',
                'KERNELRELEASE=' + lock['kernel_release']]
        subprocess.run(make + ['modules_prepare'], check=True, env=environment)
        subprocess.run(make + [f'M={modules}', f'EXTRA_CFLAGS=-I{kernel}/drivers/clk/qcom',
                               'CROSS_COMPILE=aarch64-linux-gnu-', 'CLANG_TRIPLE=aarch64-linux-gnu-',
                               f'HOSTCFLAGS=-I{host}/include',
                               f'HOSTLDFLAGS=-L{host}/lib64 -Wl,-rpath,{host}/lib64 -fuse-ld=lld --rtlib=compiler-rt',
                               f'PAHOLE={host}/bin/pahole', f'KBUILD_EXTRA_SYMBOLS={extra}',
                               'CONFIG_MEIZU_DEVICE_DTBS=y', '-j6', 'modules'], check=True, env=environment)
        for name in ('gcc-pineapple.ko', 'pwm-ir-tx.ko'):
            path = modules / name
            subprocess.run([str(clang / 'bin/llvm-strip'), '--strip-debug', str(path)], check=True)
            parsed = abi.parse_module(path, path.read_bytes())
            if parsed['parse_errors'] or lock['kernel_release'] not in str(parsed['modinfo']):
                raise ValueError(f'Invalid module or kernel release in {path}')
        for name in ('gcc-pineapple.ko', 'pwm-ir-tx.ko'):
            shutil.copyfile(modules / name, output / name)
    print(f'Built IR modules at {output}. Run the module ABI audit before packaging a new pair.')


if __name__ == '__main__':
    main()
