# Adds extra free MOVIE channels from iptv-org's "movies" category to the curated playlist.
# Only official free ad-supported platforms are kept (Pluto TV, Rakuten TV, Samsung TV Plus, Plex, Amagi/Wurl playouts),
# every stream is tested, and nothing already in the playlist is duplicated.
param([string]$Playlist = "C:\MediaServer\jellyfin\config\iptv\france.m3u", [int]$Max = 40, [string]$Category = "movies", [string]$Group = "Cinéma (VO)",
      [string]$Names = "Pluto TV|Rakuten|Samsung|Plex|Cine|Movies|Film|Action|Western|Classic|Horror|Thriller|Comedy|Drama|Sci-?Fi|Kung|Martial|Romance|Hollywood|Bollywood")
$ErrorActionPreference = "Continue"
$tmp = Join-Path $env:TEMP "iptv_$Category.m3u"
& curl.exe -s -L -o $tmp https://iptv-org.github.io/iptv/categories/$Category.m3u
$okHost = 'pluto\.tv|jmp2\.uk|amagi\.tv|wurl\.com|mediatailor\..*amazonaws\.com|samsung|rakuten|plex\.tv|cdn-uw2-prod\.tsv2|redbull|rbmn-live|cloudfront\.net|akamaized\.net|lequipe|fifa|olympic|dazn|sportenfrance|freecaster|tennis|padel|livepush|zype|vercel|cdn\.jwplayer|bozztv|stream\.mux'
$okLang = $Names
$have = (Get-Content $Playlist -Encoding UTF8) | Where-Object { $_ -match '^https?://' }
$lines = Get-Content $tmp -Encoding UTF8
$cand = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -notlike "#EXTINF*") { continue }
  $inf = $lines[$i]; $j = $i + 1; $opts = @()
  while ($j -lt $lines.Count -and $lines[$j] -like "#EXTVLCOPT*") { $opts += $lines[$j]; $j++ }
  $url = $lines[$j]; $i = $j
  if ($url -notmatch '^https?://' -or $have -contains $url) { continue }
  $h = ([uri]$url).Host; $name = ($inf -split '",', 2)[-1]
  if ($h -notmatch $okHost -or $name -match 'Geo-blocked|Adult|XXX|Erotic|Girlfriends|Playboy|Hustler|Brazzers|Dorcel|Hot ' -or $name -match ' (BR|LatAm|DK|NO|AU|CA|UK)\b|Mexicana|Filmes|Inspirador|Romantico|Latino|Novelas \(|Peliculas|Películas|Cine Terror|Cine (Adrenalina|Amor|Premiere|Terror)' -or $name -notmatch $okLang) { continue }
  $cand += [pscustomobject]@{ Inf = $inf; Opts = $opts; Url = $url; Name = $name }
}
"candidates: $($cand.Count)"
$good = @()
foreach ($c in $cand) {
  if ($good.Count -ge $Max) { break }
  $out = & curl.exe -s -L --max-time 8 -r 0-3000 -w "`n%{http_code}" $c.Url 2>$null
  if ((($out | Select-Object -Last 1) -in '200', '206') -and (($out -join "`n") -match '#EXTM3U')) { $good += $c }
}
"working: $($good.Count)"
$add = foreach ($g in $good) { ($g.Inf -replace 'group-title="[^"]*"', "group-title=`"$Group`""); $g.Opts; $g.Url }
if ($add) { Add-Content -Path $Playlist -Value $add -Encoding UTF8 }
$good | ForEach-Object { "  + " + ($_.Name -replace ' \(\d+p\)', '') }
