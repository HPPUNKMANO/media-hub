<#
  Media Hub watchdog — runs at logon and every 10 minutes (Task Scheduler; it never wakes the PC: closing the lid = sleep).
  Makes sure everything the phone app needs is up, restarts what is not, and writes a status file for the hub.
#>
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$log = "C:\MediaServer\weekly\watchdog.log"
function Log($m) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $m" | Add-Content $log }
$status = [ordered]@{ checked = (Get-Date).ToString("s"); docker = $false; services = $false; freebox_tv = $false; tailscale = $false; restarted = @() }

# 1. Docker Desktop
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  $dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  if (-not (Get-Process "Docker Desktop" -ErrorAction SilentlyContinue) -and (Test-Path $dd)) { Start-Process $dd; $status.restarted += "docker"; Log "docker: started Docker Desktop" }
  for ($i = 0; $i -lt 36; $i++) { Start-Sleep 5; docker info *> $null; if ($LASTEXITCODE -eq 0) { break } }
}
$status.docker = ($LASTEXITCODE -eq 0)

# 2. the media services (Jellyfin, Navidrome, Audiobookshelf, hub, gate, organizer)
if ($status.docker) {
  $running = docker ps --format "{{.Names}}"
  $want = "jellyfin", "navidrome", "audiobookshelf", "hub", "gate", "organizer"
  if (@($want | Where-Object { $running -notcontains $_ }).Count) {
    Push-Location $root; docker compose up -d 2>&1 | Out-Null; Pop-Location
    $status.restarted += "services"; Log "services: brought containers back up"
  }
  $code = & curl.exe -s -o NUL -m 10 -w "%{http_code}" http://127.0.0.1:8080/api/config
  $status.services = ($code -eq "200")
}

# 3. Freebox TV converter (MediaMTX)
$mtx = "C:\MediaServer\mediamtx"
if ((Test-Path "$mtx\mediamtx.exe") -and (Test-Path "$mtx\mediamtx.yml")) {
  if (-not (Get-Process mediamtx -ErrorAction SilentlyContinue)) {
    Start-Process "$mtx\mediamtx.exe" -ArgumentList "`"$mtx\mediamtx.yml`"" -WorkingDirectory $mtx -WindowStyle Hidden -RedirectStandardOutput "$mtx\out.log" -RedirectStandardError "$mtx\err.log"
    $status.restarted += "freebox_tv"; Log "freebox: started MediaMTX"; Start-Sleep 2
  }
  $status.freebox_tv = [bool](Get-Process mediamtx -ErrorAction SilentlyContinue)
}

# 4. Tailscale + the secure addresses used by the phone
$ts = "C:\Program Files\Tailscale\tailscale.exe"
if (Test-Path $ts) {
  if ((Get-Service Tailscale -ErrorAction SilentlyContinue).Status -ne "Running") { Start-Service Tailscale -ErrorAction SilentlyContinue; $status.restarted += "tailscale" }
  if (-not (Get-Process tailscale-ipn -ErrorAction SilentlyContinue)) { Start-Process "C:\Program Files\Tailscale\tailscale-ipn.exe"; $status.restarted += "tailscale-app"; Log "tailscale: started the app"; Start-Sleep 10 }
  $serve = (& $ts serve status 2>$null) -join "`n"
  foreach ($p in @(@("8080", "443"), @("8096", "8096"), @("4533", "4533"), @("13378", "13378"))) {
    if ($serve -notmatch "127\.0\.0\.1:$($p[0])") {
      $args = if ($p[1] -eq "443") { "serve --bg --yes $($p[0])" } else { "serve --bg --yes --https=$($p[1]) http://127.0.0.1:$($p[0])" }
      $pr = Start-Process $ts -ArgumentList $args -WindowStyle Hidden -PassThru; Start-Sleep 6; if (-not $pr.HasExited) { $pr | Stop-Process -Force }
      $status.restarted += "tailscale-serve-$($p[0])"; Log "tailscale: re-published port $($p[0])"
    }
  }
  $st = & $ts status --json 2>$null | ConvertFrom-Json
  $status.tailscale = ($st.BackendState -eq "Running")
}

# keep the log small
if ((Test-Path $log) -and (Get-Item $log).Length -gt 1MB) { Get-Content $log -Tail 2000 | Set-Content $log }
$status | ConvertTo-Json | Set-Content "C:\MediaServer\hub\health.json" -Encoding UTF8
