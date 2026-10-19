#!/usr/bin/env bash
# Compile only; this script does not push, run, or install the target probe.
set -euo pipefail

probe_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace_dir=$(CDPATH= cd -- "$probe_dir/../.." && pwd)
probe_output="$workspace_dir/output/droidspaces-20261019/tests/kernel_probe"
probe_compiler=${AARCH64_CC:-aarch64-linux-gnu-gcc}

command -v "$probe_compiler" >/dev/null
mkdir -p -- "$(dirname -- "$probe_output")"
"$probe_compiler" -std=c11 -O2 -Wall -Wextra -Werror -static -s \
    -Wl,--build-id=sha1 -o "$probe_output" "$probe_dir/kernel_probe.c"
file -- "$probe_output"
readelf -h -- "$probe_output" | sed -n '/Class:/p; /Machine:/p; /Type:/p; /Entry point/p'
if readelf -l -- "$probe_output" | grep -q 'INTERP'; then
    printf '%s\n' 'FAIL build: probe unexpectedly needs a dynamic loader' >&2
    exit 1
fi
if readelf -d -- "$probe_output" | grep -q 'NEEDED'; then
    printf '%s\n' 'FAIL build: probe unexpectedly needs shared libraries' >&2
    exit 1
fi
sha256sum -- "$probe_output"
printf '%s\n' 'PASS build: static aarch64 probe generated; execution was not attempted'

