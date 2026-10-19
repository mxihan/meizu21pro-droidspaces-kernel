[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Serial,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$BaselineDirectory,
    [switch]$RunNativeProbe,
    [switch]$ExpectCandidate
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

function Read-Device([string]$Command) {
    $lines = & adb -s $Serial shell $Command 2>&1
    if ($LASTEXITCODE -ne 0) { throw "ADB command failed: $Command`n$lines" }
    return ($lines -join "`n").Trim()
}

$bootCompleted = Read-Device 'getprop sys.boot_completed'
$version = Read-Device 'cat /proc/version'
$release = Read-Device 'uname -r'
$slot = Read-Device 'getprop ro.boot.slot_suffix'
$selinux = Read-Device 'getenforce'
$audio = Read-Device 'service check media.audio_flinger'
$checkerText = Read-Device '/data/local/Droidspaces/bin/droidspaces --format check'
$checkerText | Set-Content -LiteralPath (Join-Path $OutputDirectory 'droidspaces-check.json') -Encoding utf8
$checks = $checkerText | ConvertFrom-Json
$failures = [System.Collections.Generic.List[string]]::new()
$missingSystemModules = @()
$nativeProbe = $null
if ($bootCompleted -ne '1') { $failures.Add('Android has not completed boot') }
if ($audio -notmatch ':\s*found\s*$') { $failures.Add('AudioFlinger service is unavailable') }
if ($selinux -ne 'Enforcing') { $failures.Add('Host SELinux is not Enforcing') }
if ($checks.requirements_met -ne 1) { $failures.Add('Droidspaces core requirements are not met') }
if ($ExpectCandidate) {
    if ($version -notmatch 'meizu21pro-droidspaces') { $failures.Add('Running kernel is not this candidate build') }
    if ($release -ne '6.1.176-g19e9b13339e2') { $failures.Add('Kernel release changed; module ABI needs rechecking') }
    $recommended = @('pid_ns', 'mnt_ns', 'uts_ns', 'ipc_ns', 'pivot_root', 'procfs', 'sysfs',
        'seccomp', 'epoll', 'signalfd', 'pty', 'devpts', 'loop', 'ext4', 'cgroup2',
        'cgroup_ns', 'devtmpfs', 'fuse', 'tun', 'overlayfs', 'net_ns', 'bridge',
        'veth', 'macvlan', 'ipv6_nat', 'memory_limit', 'cpu_accounting', 'user_ns')
    foreach ($name in $recommended) {
        if ($checks.$name -ne 1) { $failures.Add("Droidspaces capability unavailable: $name") }
    }
    if (-not $BaselineDirectory) {
        throw '-BaselineDirectory is required when verifying the candidate system modules'
    }
    $moduleManifest = Get-Content -LiteralPath (Join-Path $BaselineDirectory 'module-files.json') -Raw | ConvertFrom-Json
    $expectedModules = @($moduleManifest.system_dlkm.PSObject.Properties.Name | ForEach-Object {
        [IO.Path]::GetFileNameWithoutExtension($_).Replace('-', '_')
    })
    if ($expectedModules.Count -ne 59) { throw 'Expected the captured 59 system modules' }
    $loadedText = Read-Device 'cat /proc/modules'
    $loadedText | Set-Content -LiteralPath (Join-Path $OutputDirectory 'loaded-modules.txt') -Encoding utf8
    $loadedModules = @($loadedText -split "`n" | ForEach-Object { ($_ -split '\s+')[0] })
    $missingSystemModules = @($expectedModules | Where-Object { $_ -notin $loadedModules })
    if ($missingSystemModules.Count) {
        $failures.Add('Original system modules are missing: ' + ($missingSystemModules -join ', '))
    }
}
if ($RunNativeProbe) {
    $probeLines = & adb -s $Serial shell /data/local/tmp/droidspaces-kernel-probe-20261019 2>&1
    $probeExitCode = $LASTEXITCODE
    $probeText = ($probeLines -join "`n").Trim()
    $probeText | Set-Content -LiteralPath (Join-Path $OutputDirectory 'native-probe.txt') -Encoding utf8
    $nativeProbe = @{ exitCode = $probeExitCode; output = $probeText }
    if ($probeExitCode -ne 0 -or $probeText -notmatch 'SUMMARY tests=7 passed=7 failed=0') {
        $failures.Add('Native namespace, SYSVIPC, seccomp and devtmpfs probe did not pass')
    }
}
$report = [ordered]@{
    capturedAt = [DateTimeOffset]::Now.ToString('o')
    bootCompleted = $bootCompleted
    kernelVersion = $version
    kernelRelease = $release
    activeSlot = $slot
    hostSelinux = $selinux
    audioFlinger = $audio
    candidateRequired = [bool]$ExpectCandidate
    droidspaces = $checks
    missingSystemModules = $missingSystemModules
    nativeProbe = $nativeProbe
    failures = $failures.ToArray()
    passed = ($failures.Count -eq 0)
    scope = 'Boot and runtime capability checks only. An optional native probe runs isolated child syscalls. No container was started and no reboot or partition write was performed.'
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'device-verification.json') -Encoding utf8
if ($failures.Count) {
    $failures | ForEach-Object { Write-Output "FAIL: $_" }
    exit 1
}
Write-Output 'PASS: Android boot, audio service, SELinux and requested Droidspaces capability checks.'
exit 0

