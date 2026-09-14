# Generate placeholder application icons.
# Requires Windows PowerShell 5.1 (System.Drawing).
# Usage: powershell -ExecutionPolicy Bypass -File scripts/make-icons.ps1

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$uiImages = Join-Path $root "app\ui\images"
New-Item -ItemType Directory -Force -Path $uiImages | Out-Null

function New-RoundedPath([int]$x, [int]$y, [int]$w, [int]$h, [int]$r) {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $r * 2
    $p.AddArc($x, $y, $d, $d, 180, 90)
    $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $p.CloseFigure()
    return $p
}

function New-Icon([string]$path, [int]$size, [string]$text, [string]$c1, [string]$c2) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)

    $pad = [int]($size * 0.06)
    $rect = New-Object System.Drawing.Rectangle($pad, $pad, ($size - 2 * $pad), ($size - 2 * $pad))
    $radius = [int]($size * 0.22)
    $gp = New-RoundedPath $rect.X $rect.Y $rect.Width $rect.Height $radius

    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        $rect,
        [System.Drawing.ColorTranslator]::FromHtml($c1),
        [System.Drawing.ColorTranslator]::FromHtml($c2),
        45.0)
    $g.FillPath($brush, $gp)

    $fontSize = [single]($size * 0.40)
    $font = New-Object System.Drawing.Font("Segoe UI", $fontSize, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = [System.Drawing.StringAlignment]::Center
    $fmt.LineAlignment = [System.Drawing.StringAlignment]::Center
    $white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
    $g.DrawString($text, $font, $white, (New-Object System.Drawing.RectangleF(0, 0, $size, $size)), $fmt)

    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose()
    $bmp.Dispose()
    $brush.Dispose()
    $gp.Dispose()
    $font.Dispose()
    $white.Dispose()
}

$sizes = @(64, 128, 256)

foreach ($s in $sizes) {
    New-Icon (Join-Path $uiImages "icon_$s.png") $s "oc" "#2F6DF6" "#7C3AED"
    New-Icon (Join-Path $uiImages "console_$s.png") $s "</>" "#334155" "#0F172A"
}

New-Icon (Join-Path $root "ICON.PNG") 64 "oc" "#2F6DF6" "#7C3AED"
New-Icon (Join-Path $root "ICON_256.PNG") 256 "oc" "#2F6DF6" "#7C3AED"

Write-Host "Icons generated under $uiImages"
