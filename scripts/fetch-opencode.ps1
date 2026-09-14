# Download the opencode Linux binary and place it at app/opencode.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/fetch-opencode.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/fetch-opencode.ps1 -Target x64
#   powershell -ExecutionPolicy Bypass -File scripts/fetch-opencode.ps1 -Version 1.15.6
param(
    [string]$Target = "x64-baseline",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "app\opencode"

if ($Version) {
    $base = "https://github.com/anomalyco/opencode/releases/download/v$Version"
}
else {
    $base = "https://github.com/anomalyco/opencode/releases/latest/download"
}
$url = "$base/opencode-linux-$Target.tar.gz"

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("opencode-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

Write-Host "Downloading $url ..."
$archive = Join-Path $tmp "pkg.tar.gz"
Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing

Write-Host "Extracting ..."
& tar -xzf $archive -C $tmp
$bin = Get-ChildItem -Path $tmp -Recurse -Filter "opencode" -File | Select-Object -First 1
if (-not $bin) { throw "opencode binary not found in archive" }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
Copy-Item $bin.FullName $out -Force
Remove-Item -Recurse -Force $tmp

$size = (Get-Item $out).Length / 1MB
Write-Host ("Done: {0} ({1:N1} MB)" -f $out, $size)
