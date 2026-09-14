# Generate fnOS application icons from the official opencode logo.
# Requires Windows PowerShell 5.1 (System.Drawing).
# Usage: powershell -ExecutionPolicy Bypass -File scripts/make-icons.ps1

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$uiImages = Join-Path $root "app\ui\images"
New-Item -ItemType Directory -Force -Path $uiImages | Out-Null

# Source logo: prefer the copy committed under scripts/assets, else download.
$src = Join-Path $PSScriptRoot "assets\opencode-icon.png"
if (-not (Test-Path $src)) {
    $ProgressPreference = "SilentlyContinue"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $src) | Out-Null
    $url = "https://opencode.ai/web-app-manifest-512x512.png"
    Write-Host "Downloading official logo from $url ..."
    Invoke-WebRequest -Uri $url -OutFile $src -UseBasicParsing
}

function New-Resized([string]$srcPath, [string]$dstPath, [int]$size) {
    $img = [System.Drawing.Image]::FromFile($srcPath)
    try {
        $bmp = New-Object System.Drawing.Bitmap($size, $size)
        try {
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            try {
                $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                $g.Clear([System.Drawing.Color]::Transparent)
                $g.DrawImage($img, 0, 0, $size, $size)
            }
            finally { $g.Dispose() }
            $bmp.Save($dstPath, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally { $bmp.Dispose() }
    }
    finally { $img.Dispose() }
}

foreach ($s in @(64, 128, 256)) {
    New-Resized $src (Join-Path $uiImages "icon_$s.png") $s
    New-Resized $src (Join-Path $uiImages "console_$s.png") $s
}

New-Resized $src (Join-Path $root "ICON.PNG") 64
New-Resized $src (Join-Path $root "ICON_256.PNG") 256

Write-Host "Icons generated from official opencode logo -> $uiImages"
