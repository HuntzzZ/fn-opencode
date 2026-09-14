# Build the fnOS .fpk package.
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/build.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/build.ps1 -Version 1.0.1
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$tools = Join-Path $root "tools"
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force -Path $tools, $dist | Out-Null

# ---- fnpack ------------------------------------------------------------
$fnpack = Join-Path $tools "fnpack.exe"
if (-not (Test-Path $fnpack)) {
    $fnUrl = "https://static2.fnnas.com/fnpack/fnpack-1.2.3-windows-amd64"
    Write-Host "Downloading fnpack from $fnUrl ..."
    Invoke-WebRequest -Uri $fnUrl -OutFile $fnpack -UseBasicParsing
}

# ---- prerequisites -----------------------------------------------------
if (-not (Test-Path (Join-Path $root "app\opencode"))) {
    Write-Host "opencode binary missing, fetching ..."
    & (Join-Path $PSScriptRoot "fetch-opencode.ps1")
}
if (-not (Test-Path (Join-Path $root "ICON.PNG"))) {
    Write-Host "Icons missing, generating ..."
    & (Join-Path $PSScriptRoot "make-icons.ps1")
}

# ---- version -----------------------------------------------------------
$manifestPath = Join-Path $root "manifest"
if ($Version) {
    $content = Get-Content -Raw -Encoding UTF8 $manifestPath
    $content = [Regex]::Replace($content, "(?m)^version\s*=.*$", "version                    = $Version")
    Set-Content -Path $manifestPath -Value $content -Encoding UTF8 -NoNewline
    Write-Host "manifest version -> $Version"
}

$appname = (Select-String -Path $manifestPath -Pattern '^appname\s*=\s*(.+)$').Matches[0].Groups[1].Value.Trim()
$ver = (Select-String -Path $manifestPath -Pattern '^version\s*=\s*(.+)$').Matches[0].Groups[1].Value.Trim()
Write-Host "Building $appname v$ver ..."

# ---- fnpack build ------------------------------------------------------
Push-Location $root
try {
    & $fnpack build --directory $root
    if ($LASTEXITCODE -ne 0) { throw "fnpack build failed with exit code $LASTEXITCODE" }
}
finally {
    Pop-Location
}

$built = Join-Path $root "$appname.fpk"
if (-not (Test-Path $built)) { throw "Expected package not found: $built" }

$target = Join-Path $dist ("{0}_v{1}.fpk" -f $appname, $ver)
Move-Item -Force $built $target
Write-Host "Package: $target"
