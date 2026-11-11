# Renders the Media Hub logo ("M." in Bodoni, white on near-black, vermilion dot) at every size the
# app needs: PWA icons, Apple touch icon, favicon and a real multi-size Windows .ico for the desktop shortcut.
param([string]$OutDir = "$PSScriptRoot\..\hub\app\static\icons", [string]$IcoPath = "C:\MediaServer\mediahub.ico")
Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $OutDir | Out-Null

function Render([int]$S, [bool]$Maskable) {
  $bmp = New-Object Drawing.Bitmap $S, $S
  $g = [Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = "AntiAlias"; $g.TextRenderingHint = "AntiAliasGridFit"; $g.InterpolationMode = "HighQualityBicubic"; $g.PixelOffsetMode = "HighQuality"
  $g.Clear([Drawing.Color]::Transparent)
  # rounded square ("squircle"-ish); maskable icons fill the whole square, the OS applies its own mask
  $r = if ($Maskable) { 0 } else { [int]($S * 0.225) }
  $path = New-Object Drawing.Drawing2D.GraphicsPath
  if ($r -gt 0) {
    $d = 2 * $r
    $path.AddArc(0, 0, $d, $d, 180, 90); $path.AddArc($S - $d - 1, 0, $d, $d, 270, 90)
    $path.AddArc($S - $d - 1, $S - $d - 1, $d, $d, 0, 90); $path.AddArc(0, $S - $d - 1, $d, $d, 90, 90); $path.CloseFigure()
  } else { $path.AddRectangle((New-Object Drawing.Rectangle 0, 0, $S, $S)) }
  $bg = New-Object Drawing.Drawing2D.LinearGradientBrush (New-Object Drawing.Rectangle 0, 0, $S, $S), ([Drawing.Color]::FromArgb(24, 23, 22)), ([Drawing.Color]::FromArgb(8, 8, 9)), 90
  $g.FillPath($bg, $path)
  # faint warm glow, top-right (the "projector light")
  $glow = New-Object Drawing.Drawing2D.GraphicsPath
  $glow.AddEllipse([int]($S * 0.35), [int](-$S * 0.45), [int]($S * 1.1), [int]($S * 1.1))
  $pgb = New-Object Drawing.Drawing2D.PathGradientBrush $glow
  $pgb.CenterColor = [Drawing.Color]::FromArgb(46, 255, 91, 46); $pgb.SurroundColors = @([Drawing.Color]::FromArgb(0, 255, 91, 46))
  $g.SetClip($path); $g.FillPath($pgb, $glow); $g.ResetClip()
  # hairline border
  if (-not $Maskable) { $pen = New-Object Drawing.Pen ([Drawing.Color]::FromArgb(40, 255, 255, 255)), ([Math]::Max(1, $S / 256)); $g.DrawPath($pen, $path) }
  # the "M"
  $scale = if ($Maskable) { 0.50 } else { 0.62 }
  $font = New-Object Drawing.Font "Bodoni MT", ($S * $scale), ([Drawing.FontStyle]::Regular), ([Drawing.GraphicsUnit]::Pixel)
  $fmt = New-Object Drawing.StringFormat; $fmt.Alignment = "Center"; $fmt.LineAlignment = "Center"
  $tp = New-Object Drawing.Drawing2D.GraphicsPath
  $tp.AddString("M", $font.FontFamily, [int]$font.Style, $font.Size, (New-Object Drawing.RectangleF 0, 0, $S, $S), $fmt)
  $b = $tp.GetBounds()
  $m = New-Object Drawing.Drawing2D.Matrix; $m.Translate(($S - $b.Width) / 2 - $b.X - $S * 0.035, ($S - $b.Height) / 2 - $b.Y)
  $tp.Transform($m); $b = $tp.GetBounds()
  $g.FillPath((New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(242, 240, 235))), $tp)
  # vermilion full stop, sitting on the baseline right of the M
  $dot = $S * 0.085
  $g.FillEllipse((New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(255, 91, 46))), [float]($b.Right + $S * 0.02), [float]($b.Bottom - $dot), [float]$dot, [float]$dot)
  $g.Dispose()
  return $bmp
}

function Save([Drawing.Bitmap]$bmp, [string]$file) { $bmp.Save($file, [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose() }

foreach ($s in 512, 192) { Save (Render $s $false) (Join-Path $OutDir "icon-$s.png") }
foreach ($s in 512, 192) { Save (Render $s $true) (Join-Path $OutDir "maskable-$s.png") }
Save (Render 180 $true) (Join-Path $OutDir "icon-180.png")      # iOS rounds the corners itself
Save (Render 64 $false) (Join-Path $OutDir "favicon-64.png")

# multi-size .ico (PNG-compressed entries, supported since Windows Vista)
$sizes = 16, 24, 32, 48, 64, 128, 256
$pngs = foreach ($s in $sizes) { $ms = New-Object IO.MemoryStream; $bm = Render $s $false; $bm.Save($ms, [Drawing.Imaging.ImageFormat]::Png); $bm.Dispose(); , $ms.ToArray() }
$fs = [IO.File]::Create($IcoPath); $w = New-Object IO.BinaryWriter $fs
$w.Write([UInt16]0); $w.Write([UInt16]1); $w.Write([UInt16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
  $s = $sizes[$i]; $len = $pngs[$i].Length
  $w.Write([byte]($(if ($s -ge 256) { 0 } else { $s }))); $w.Write([byte]($(if ($s -ge 256) { 0 } else { $s })))
  $w.Write([byte]0); $w.Write([byte]0); $w.Write([UInt16]1); $w.Write([UInt16]32); $w.Write([UInt32]$len); $w.Write([UInt32]$offset)
  $offset += $len
}
foreach ($p in $pngs) { $w.Write($p) }
$w.Close()
"icons written to $OutDir and $IcoPath"
