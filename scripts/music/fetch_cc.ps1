# Downloads free, legal (Creative Commons) albums from netlabels on archive.org into the music library.
# Usage: fetch_cc.ps1 -Genre rap -Count 80     (genres: rap, pop)
param([string]$Genre = "rap", [int]$Count = 60, [int]$MaxMB = 500)
$ErrorActionPreference = "Continue"
$subjects = @{
  rap = '(subject:"hip hop" OR subject:"hip-hop" OR subject:rap OR subject:hiphop OR subject:"rap français" OR subject:trap)'
  pop = '(subject:pop OR subject:"indie pop" OR subject:electropop OR subject:synthpop OR subject:"pop rock") AND NOT subject:podcast'
}
$q = "mediatype:audio AND $($subjects[$Genre]) AND licenseurl:*creativecommons* AND collection:netlabels"
$u = "https://archive.org/advancedsearch.php?q=" + [uri]::EscapeDataString($q) + "&fl[]=identifier&fl[]=title&fl[]=creator&fl[]=item_size&fl[]=licenseurl&sort[]=downloads+desc&rows=400&output=json"
$docs = (Invoke-RestMethod $u).response.docs | Where-Object { [int64]$_.item_size -lt ($MaxMB * 1MB) }
$log = "C:\MediaServer\weekly\music-$Genre.log"; $done = 0
function Safe($s) { (($s -replace '[\\/:*?"<>|]', '') -replace '\s+', ' ').Trim().TrimEnd('.') }
foreach ($d in $docs) {
  if ($done -ge $Count) { break }
  try {
    $meta = Invoke-RestMethod "https://archive.org/metadata/$($d.identifier)"
    $mp3 = $meta.files | Where-Object { $_.name -match '\.mp3$' -and $_.format -notmatch '64Kbps|Sample' } | Sort-Object name
    if (-not $mp3 -or @($mp3).Count -gt 40) { continue }
    $artist = Safe ($(if ($d.creator) { @($d.creator)[0] } else { "Various Artists" }))
    $album = Safe ($d.title -replace [regex]::Escape($artist) + '\s*-\s*', '')
    if (-not $artist) { $artist = "Various Artists" }; if (-not $album) { $album = $d.identifier }
    $dest = "C:\Media\Music\$artist\$album"
    if (Test-Path $dest) { $done++; continue }
    New-Item -ItemType Directory -Force $dest | Out-Null
    foreach ($f in $mp3) {
      $url = "https://archive.org/download/$($d.identifier)/" + ((($f.name -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/')
      & curl.exe -L -s -f --retry 2 -o (Join-Path $dest (Safe (Split-Path $f.name -Leaf))) $url
    }
    "$artist - $album [$($d.licenseurl)]" | Add-Content (Join-Path $dest "LICENSE.txt")
    "OK $artist / $album ($(@($mp3).Count) tracks)" | Add-Content $log; $done++
  } catch { "ERR $($d.identifier) $_" | Add-Content $log }
}
"DONE $Genre : $done albums" | Add-Content $log
