"""Read-only copy of the running ROM's vendor and system kernel modules."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
adb = [shutil.which("adb") or "adb", "-s", args.serial]
manifest = {}
for partition in ("vendor_dlkm", "system_dlkm"):
    archive = args.output / (partition + "-modules.tar")
    with archive.open("xb") as stream:
        subprocess.run(adb + ["exec-out", "tar", "-C", "/" + partition + "/lib/modules",
                              "-cf", "-", "."], stdout=stream, check=True, timeout=180)
    target = args.output / (partition + "-modules")
    target.mkdir(exist_ok=False)
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            path = target / member.name
            if not path.resolve().is_relative_to(target.resolve()):
                raise RuntimeError("Archive member escapes its output directory")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(bundle.extractfile(member).read())
    modules = sorted(target.rglob("*.ko"))
    manifest[partition] = {str(path.relative_to(target)): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in modules}
    print(f"Copied {partition}: {len(modules)} modules", flush=True)
(args.output / "module-files.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

