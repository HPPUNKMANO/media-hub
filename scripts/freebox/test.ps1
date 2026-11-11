# Tests which Freebox channels are actually included in the subscription (ffprobe, 6 in parallel), keeps the working ones.
$ff = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffprobe.exe | Select-Object -First 1).FullName
$m3u = "C:\MediaServer\hub\iptv\freebox.m3u"; $lines = Get-Content $m3u -Encoding UTF8
$raw = (& curl.exe -s -m 15 "http://mafreebox.freebox.fr/freeboxtv/playlist.m3u") -split "`n"
$src = @{}; for ($i = 0; $i -lt $raw.Count - 1; $i++) { if ($raw[$i] -match ',\s*(\d+)\s*-\s*.+\(HD\)') { $src["fbx$($Matches[1])"] = $raw[$i + 1].Trim() } }
$pool = [runspacefactory]::CreateRunspacePool(1, 2); $pool.Open(); $jobs = @()
for ($i = 1; $i -lt $lines.Count; $i += 2) {
  $path = [regex]::Match($lines[$i + 1], '/(fbx\d+)/').Groups[1].Value
  $ps = [powershell]::Create(); $ps.RunspacePool = $pool
  [void]$ps.AddScript({ param($ff, $url) $o = & $ff -v error -rtsp_transport udp -timeout 12000000 -analyzeduration 5000000 -show_entries stream=codec_type -of csv=p=0 $url 2>$null; ($o -join " ") -match "video" }).AddArgument($ff).AddArgument($src[$path])
  $jobs += [pscustomobject]@{ I = $i; PS = $ps; H = $ps.BeginInvoke() }
}
$out = @("#EXTM3U"); $ok = 0
foreach ($j in $jobs) { $r = $j.PS.EndInvoke($j.H); $j.PS.Dispose(); if ($r -contains $true) { $out += $lines[$j.I]; $out += $lines[$j.I + 1]; $ok++ } }
$pool.Close()
if (-not (Test-Path "$m3u.all")) { Copy-Item $m3u "$m3u.all" -Force }
[IO.File]::WriteAllLines($m3u, $out, (New-Object Text.UTF8Encoding $false))
"freebox: $ok channels work out of $($jobs.Count)"
