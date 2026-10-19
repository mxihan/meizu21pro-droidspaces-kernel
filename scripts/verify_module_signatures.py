#!/usr/bin/env python3
"""Verify captured GKI module PKCS#7 signatures using only the stock public cert.

Run inside WSL. Reads a saved boot image and saved modules; never contacts a device.
Module payload/signature buffers live in anonymous memory files, not build trees.
"""
import argparse
import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

ROOT = Path('.')
CERT_OFFSET_IN_RAW_IMAGE = 33361152
CERT_SIZE = 1324
CERT_SHA256 = '2b109cb2af82cbff5831331680a0108097a69fa5d1d88723e4c3cd0a2e225d89'
MARKER = b'~Module signature appended~\n'


def memory_file(name, content):
    descriptor = os.memfd_create(name, os.MFD_CLOEXEC)
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]
    os.lseek(descriptor, 0, os.SEEK_SET)
    return descriptor


def write_public_artifact(path, content):
    if path.exists() and path.read_bytes() != content:
        raise RuntimeError('Refusing to replace different existing public artifact: ' + str(path))
    path.write_bytes(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock-boot', type=Path, default=ROOT / 'output/droidspaces-20261019/device-baseline-v1/boot_b.img')
    parser.add_argument('--modules-dir', type=Path, default=ROOT / 'output/droidspaces-20261019/device-baseline-v1/system_dlkm-modules')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'output/droidspaces-20261019/verification')
    args = parser.parse_args()
    boot = args.stock_boot.read_bytes()
    if boot[:8] != b'ANDROID!' or struct.unpack_from('<I', boot, 40)[0] != 4:
        raise RuntimeError('Expected a captured Android boot header v4 image')
    kernel_size = struct.unpack_from('<I', boot, 8)[0]
    kernel = boot[4096:4096 + kernel_size]
    if len(kernel) != kernel_size:
        raise RuntimeError('Captured boot image has a truncated kernel payload')
    certificate = kernel[CERT_OFFSET_IN_RAW_IMAGE:CERT_OFFSET_IN_RAW_IMAGE + CERT_SIZE]
    if hashlib.sha256(certificate).hexdigest() != CERT_SHA256:
        raise RuntimeError('Stock public certificate SHA-256 does not match the audited certificate')
    pem = subprocess.run(['openssl', 'x509', '-inform', 'DER', '-outform', 'PEM'],
                         input=certificate, capture_output=True, check=True).stdout
    args.output_dir.mkdir(parents=True, exist_ok=True)
    der_path = args.output_dir / 'stock-module-signing.x509'
    pem_path = args.output_dir / 'stock-module-signing.pem'
    write_public_artifact(der_path, certificate)
    write_public_artifact(pem_path, pem)

    results = []
    for path in sorted(args.modules_dir.rglob('*.ko')):
        module = path.read_bytes()
        result = {'module': str(path.relative_to(args.modules_dir))}
        if not module.endswith(MARKER) or len(module) < len(MARKER) + 12:
            result.update(verified=False, reason='module signature marker missing')
            results.append(result)
            continue
        metadata_start = len(module) - len(MARKER) - 12
        metadata = module[metadata_start:metadata_start + 12]
        sig_len = int.from_bytes(metadata[8:12], 'big')
        signature_start = metadata_start - sig_len
        if metadata[2] != 2 or metadata[3] or metadata[4] or signature_start <= 0:
            result.update(verified=False, reason='unexpected kernel PKCS#7 signature metadata')
            results.append(result)
            continue
        payload_fd = memory_file('droidspaces-module-payload', module[:signature_start])
        signature_fd = memory_file('droidspaces-module-signature', module[signature_start:metadata_start])
        try:
            command = ['openssl', 'cms', '-verify', '-binary', '-inform', 'DER',
                       '-in', f'/proc/self/fd/{signature_fd}',
                       '-content', f'/proc/self/fd/{payload_fd}',
                       '-certfile', str(pem_path), '-nointern', '-noverify', '-out', '/dev/null']
            verified = subprocess.run(command, pass_fds=(payload_fd, signature_fd),
                                      capture_output=True, check=False)
        finally:
            os.close(payload_fd)
            os.close(signature_fd)
        result['verified'] = verified.returncode == 0
        if verified.returncode:
            result['reason'] = verified.stderr.decode(errors='replace').strip()
        results.append(result)

    report = {
        'stock_boot': str(args.stock_boot),
        'raw_kernel_sha256': hashlib.sha256(kernel).hexdigest(),
        'certificate_offset_in_raw_kernel': CERT_OFFSET_IN_RAW_IMAGE,
        'certificate_size': CERT_SIZE,
        'certificate_sha256': CERT_SHA256,
        'certificate_der': str(der_path),
        'certificate_pem': str(pem_path),
        'module_directory': str(args.modules_dir),
        'modules_checked': len(results),
        'signatures_verified': sum(result['verified'] for result in results),
        'failures': [result for result in results if not result['verified']],
        'verification': 'openssl cms -verify -binary -inform DER -certfile stock-module-signing.pem -nointern -noverify',
        'results': results,
    }
    (args.output_dir / 'module-signature-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}))
    return 0 if results and all(result['verified'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())


