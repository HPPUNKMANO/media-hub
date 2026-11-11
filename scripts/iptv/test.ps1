param([string]$Dir)
# Parse both iptv-org lists, drop anonymous restreams (bare IP hosts), test every remaining stream.
$entries = @{}
foreach ($f in "fr.m3u", "fr-lang.m3u") {
  $lines = Get-Content (Join-Path $Dir $f) -Encoding UTF8
  $inf = $null; $opts = @()
  foreach ($l in $lines) {
    if ($l -like "#EXTINF*") { $inf = $l; $opts = @() }
    elseif ($l -like "#EXTVLCOPT*") { $opts += $l }
    elseif ($l -match "^https?://" -and $inf) {
      $u = [uri]$l
      $isIp = $u.Host -match '^\d{1,3}(\.\d{1,3}){3}$'
      if (-not $isIp -and -not $entries.ContainsKey($l)) {
        $name = ($inf -split ",", 2)[1]
        $ua = if ($inf -match 'http-user-agent="([^"]+)"') { $Matches[1] } else { "" }
        $ref = if ($inf -match 'http-referrer="([^"]+)"') { $Matches[1] } else { "" }
        $entries[$l] = [pscustomobject]@{ Inf = $inf; Opts = $opts; Url = $l; Name = $name; UA = $ua; Ref = $ref; Host = $u.Host }
      }
      $inf = $null
    }
  }
}
"candidates after dropping bare-IP restreams: $($entries.Count)"

$pool = [runspacefactory]::CreateRunspacePool(1, 24); $pool.Open()
$jobs = foreach ($e in $entries.Values) {
  $ps = [powershell]::Create(); $ps.RunspacePool = $pool
  [void]$ps.AddScript({
    param($e)
    $a = @("-s", "-L", "--max-time", "8", "-r", "0-4000", "-w", "`n%{http_code}")
    if ($e.UA) { $a += @("-A", $e.UA) }
    if ($e.Ref) { $a += @("-e", $e.Ref) }
    $out = & curl.exe @a $e.Url 2>$null
    $txt = ($out -join "`n")
    $code = ($out | Select-Object -Last 1)
    $ok = ($code -eq "200" -or $code -eq "206") -and ($txt -match "#EXTM3U|#EXT-X")
    [pscustomobject]@{ E = $e; Ok = $ok; Code = $code }
  }).AddArgument($e)
  [pscustomobject]@{ PS = $ps; H = $ps.BeginInvoke() }
}
$res = foreach ($j in $jobs) { $j.PS.EndInvoke($j.H); $j.PS.Dispose() }
$pool.Close()
$good = $res | Where-Object Ok | Sort-Object { $_.E.Name }
"working: $($good.Count) / $($res.Count)"
$m3u = @("#EXTM3U")
foreach ($g in $good) { $m3u += $g.E.Inf; $m3u += $g.E.Opts; $m3u += $g.E.Url }
[IO.File]::WriteAllLines((Join-Path $Dir "tested.m3u"), $m3u, (New-Object Text.UTF8Encoding $false))
$good | ForEach-Object { "{0} | {1}" -f $_.E.Name, $_.E.Host } | Set-Content (Join-Path $Dir "tested.txt") -Encoding UTF8
