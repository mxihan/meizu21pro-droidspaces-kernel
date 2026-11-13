"""Patch a freshly generated init_boot before the normal Android AVB footer."""
import pathlib
import shutil
import subprocess
import sys
import tempfile

assets = pathlib.Path(__file__).resolve().parent
image = pathlib.Path(sys.argv[1]).resolve()
if not image.is_file() or image.read_bytes()[:8] != b'ANDROID!':
    raise ValueError('Expected a generated Android init_boot image')
with tempfile.TemporaryDirectory(prefix='ksu-init-boot-', dir=image.parent) as tmp:
    subprocess.run([
        str(assets / 'ksud'), 'boot-patch', '--boot', str(image),
        '--kmi', 'android14-6.1', '--arch', 'aarch64',
        '--module', str(assets / 'kernelsu.ko'), '--init', str(assets / 'ksuinit'),
        '--out', tmp, '--out-name', 'init_boot-kernelsu.img',
    ], check=True)
    patched = pathlib.Path(tmp) / 'init_boot-kernelsu.img'
    if not patched.is_file() or patched.read_bytes()[:8] != b'ANDROID!':
        raise ValueError('KernelSU patch did not produce an Android boot image')
    shutil.copyfile(patched, image)
