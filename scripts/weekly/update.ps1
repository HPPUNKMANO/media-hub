<#
  Media Hub - weekly update (run by Windows Task Scheduler every Sunday; safe to run by hand any time).
    1. refreshes the free TV channel list (download, test every stream, legal/adult filters), keeps a backup
    2. checks the radio streams
    3. asks Claude (headless) to research the week's legal novelties and write a summary for the hub
    4. downloads the films Claude validated (max 5, archive.org only), adds podcasts
    5. rescans Jellyfin, Navidrome and the TV guide
  Nothing is ever deleted: replaced files are kept as .bak.
#>
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$work = "C:\MediaServer\weekly"; New-Item -ItemType Directory -Force $work | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $work "log-$stamp.txt"
function Log($m) { "[$(Get-Date -Format HH:mm:ss)] $m" | Tee-Object -FilePath $log -Append }
$envf = Get-Content (Join-Path $root ".env") -Encoding UTF8
function EnvVal($k) { ($envf | Where-Object { $_ -match "^$k=" } | Select-Object -First 1) -replace "^$k=", "" }
$jfKey = EnvVal "JELLYFIN_API_KEY"; $ndUser = EnvVal "NAVIDROME_USER"; $ndPass = EnvVal "NAVIDROME_PASSWORD"; $absTok = EnvVal "ABS_API_TOKEN"
$jfH = @{ Authorization = "MediaBrowser Token=`"$jfKey`"" }
Log "=== weekly update $stamp ==="

# ---------------------------------------------------------------- 1. TV channels
try {
  $tv = Join-Path $work "iptv"; New-Item -ItemType Directory -Force $tv | Out-Null
  & curl.exe -s -L -o "$tv\fr.m3u" https://iptv-org.github.io/iptv/countries/fr.m3u
  & curl.exe -s -L -o "$tv\fr-lang.m3u" https://iptv-org.github.io/iptv/languages/fra.m3u
  & powershell -ExecutionPolicy Bypass -File "$root\scripts\iptv\test.ps1" -Dir $tv | ForEach-Object { Log "tv: $_" }
  & powershell -ExecutionPolicy Bypass -File "$root\scripts\iptv\curate.ps1" -In "$tv\tested.m3u" -Dest "$tv\new.m3u" | Out-Null
  & powershell -ExecutionPolicy Bypass -File "$root\scripts\iptv\movies.ps1" -Playlist "$tv\new.m3u" | ForEach-Object { Log "tv-movies: $_" }
  $n = (Get-Content "$tv\new.m3u" -Encoding UTF8 | Where-Object { $_ -like "#EXTINF*" }).Count
  if ($n -ge 50) {
    foreach ($dst in "C:\MediaServer\jellyfin\config\iptv\france.m3u", "C:\MediaServer\hub\iptv\france.m3u") {
      if (Test-Path $dst) { Copy-Item $dst "$dst.bak" -Force }
      Copy-Item "$tv\new.m3u" $dst -Force
    }
    Log "tv: playlist updated, $n channels"
  } else { Log "tv: only $n channels found, kept last week's list" }
} catch { Log "tv: ERROR $_" }

# ---------------------------------------------------------------- 2. radios
try {
  $cat = Get-Content "$root\hub\app\data\catalog.json" -Raw -Encoding UTF8 | ConvertFrom-Json
  $dead = foreach ($r in $cat.radios) { $c = & curl.exe -s -L -o NUL --max-time 6 -w "%{http_code}" $r.url; if ($c -notin "200", "206") { $r.name } }
  Log "radios: $($cat.radios.Count) checked, offline: $(if ($dead) { $dead -join ', ' } else { 'none' })"
} catch { Log "radios: ERROR $_" }

# ---------------------------------------------------------------- 3. Claude research
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
if (Test-Path $claude) {
  $prompt = (Get-Content "$PSScriptRoot\prompt.md" -Raw -Encoding UTF8).Replace("{{DATE}}", $stamp).Replace("{{PD_YEAR}}", [string]((Get-Date).Year - 70))
  Log "claude: researching..."
  Push-Location $root
  $prompt | & $claude -p --allowedTools "WebSearch,WebFetch,Read,Write" --permission-mode acceptEdits --add-dir "C:\MediaServer\weekly" --add-dir "C:\MediaServer\hub" 2>&1 | Out-File (Join-Path $work "claude-$stamp.txt") -Encoding utf8
  Pop-Location
  Log "claude: done (exit $LASTEXITCODE)"
} else { Log "claude: CLI not found, research skipped" }

# AI recap (written by Claude for the hub's AI page)
& powershell -ExecutionPolicy Bypass -File "$root\scripts\ai_recap\run.ps1" | ForEach-Object { Log $_ }

# ---------------------------------------------------------------- 4. downloads (validated items only)
$cand = Join-Path $work "candidates.json"
if (Test-Path $cand) {
  try {
    $c = Get-Content $cand -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($f in @($c.films) | Select-Object -First 15) {
      if (-not $f.archive_id -or -not $f.license) { continue }
      $safe = ($f.title -replace '[\\/:*?"<>|]', '').Trim()
      $dest = if ($f.kind -eq "episode" -and $f.series) {
        $s = ($f.series -replace '[\\/:*?"<>|]', '').Trim()
        "C:\Media\TV\$s\Season {0:D2}\$s - S{0:D2}E{1:D2} - $safe" -f [int]$f.season, [int]$f.episode
      } else { "C:\Media\Movies\$safe ($($f.year))\$safe ($($f.year))" }
      $files = (Invoke-RestMethod "https://archive.org/metadata/$($f.archive_id)").files |
        Where-Object { $_.name -match '\.(mp4|m4v|mkv)$' -and [int64]$_.size -gt 5MB -and [int64]$_.size -lt 3GB -and $_.name -notmatch 'trailer|sample' }
      $pick = $files | Sort-Object { [int64]$_.size } -Descending | Select-Object -First 1
      if (-not $pick) { Log "film: no usable file for $($f.archive_id)"; continue }
      $out = $dest + [IO.Path]::GetExtension($pick.name)
      if (Test-Path $out) { Log "film: already have $safe"; continue }
      New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
      $url = "https://archive.org/download/$($f.archive_id)/" + ((($pick.name -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/')
      & curl.exe -L -s -f --retry 3 -o $out $url
      Log "film: $(if ($LASTEXITCODE -eq 0) { 'added' } else { 'FAILED' }) $safe [$($f.license)]"
    }
    # podcasts -> Audiobookshelf (with auto-download of new episodes)
    $H = @{ Authorization = "Bearer $absTok" }
    $lib = (Invoke-RestMethod http://localhost:13378/api/libraries -Headers $H).libraries | Where-Object mediaType -eq "podcast" | Select-Object -First 1
    $have = (Invoke-RestMethod "http://localhost:13378/api/libraries/$($lib.id)/items?limit=500" -Headers $H).results | ForEach-Object { $_.media.metadata.feedUrl }
    foreach ($p in @($c.podcasts) | Select-Object -First 10) {
      if (-not $p.rss -or $have -contains $p.rss) { continue }
      try {
        $pf = (Invoke-RestMethod http://localhost:13378/api/podcasts/feed -Method Post -Headers $H -ContentType "application/json" -Body (@{ rssFeed = $p.rss } | ConvertTo-Json)).podcast
        $m = $pf.metadata; $safe = ($m.title -replace '[\\/:*?"<>|]', '').Trim()
        $body = @{ path = "$($lib.folders[0].fullPath)/$safe"; folderId = $lib.folders[0].id; libraryId = $lib.id
          media = @{ metadata = @{ title = $m.title; author = $m.author; description = $m.description; feedUrl = $p.rss; imageUrl = $m.image; language = $m.language }
                     autoDownloadEpisodes = $true; autoDownloadSchedule = "0 6 * * *"; maxEpisodesToKeep = 10; maxNewEpisodesToDownload = 3 }
          episodesToDownload = @($pf.episodes | Select-Object -First 2) } | ConvertTo-Json -Depth 8
        Invoke-RestMethod http://localhost:13378/api/podcasts -Method Post -Headers $H -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
        Log "podcast: added $($m.title)"
      } catch { Log "podcast: failed $($p.rss)" }
    }
    Copy-Item $cand (Join-Path $work "candidates-$stamp.json") -Force
  } catch { Log "candidates: ERROR $_" }
}

# ---------------------------------------------------------------- 5. rescans
try { Invoke-RestMethod http://localhost:8096/Library/Refresh -Method Post -Headers $jfH | Out-Null; Log "jellyfin: library scan started" } catch { Log "jellyfin: scan failed" }
try { $t = (Invoke-RestMethod http://localhost:8096/ScheduledTasks -Headers $jfH) | Where-Object Key -eq "RefreshGuide"; Invoke-RestMethod "http://localhost:8096/ScheduledTasks/Running/$($t.Id)" -Method Post -Headers $jfH | Out-Null; Log "jellyfin: tv guide refresh started" } catch { Log "jellyfin: guide refresh failed" }
try { $q = "u=$ndUser&p=" + [uri]::EscapeDataString($ndPass) + "&v=1.16.1&c=weekly&f=json"; Invoke-RestMethod "http://localhost:4533/rest/startScan?$q" | Out-Null; Log "navidrome: scan started" } catch { Log "navidrome: scan failed" }
# ---------------------------------------------------------------- 6. GitHub backup (code + settings only; .env and media are never sent)
try {
  $git = "C:\Program Files\Git\cmd\git.exe"
  Push-Location $root
  & $git add -A
  & $git diff --cached --quiet; if ($LASTEXITCODE -ne 0) { & $git commit -q -m "Weekly update $stamp"; & $git push -q origin main; Log "github: backup pushed" } else { Log "github: nothing new to back up" }
  Pop-Location
} catch { Log "github: backup failed $_" }
Log "=== done ==="
