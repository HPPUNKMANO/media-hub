<#
  Media Hub - one-time Windows setup. Run from this folder in an ADMIN PowerShell:
      powershell -ExecutionPolicy Bypass -File .\setup.ps1
  What it does (nothing is ever deleted):
    1. checks Docker Desktop is installed and running
    2. creates C:\Media (library + _Inbox) and C:\MediaServer (app data)
    3. creates .env from .env.example if missing
    4. firewall: allows the Hub/Jellyfin/Navidrome/Audiobookshelf ports from your home network only,
       and blocks them on Public networks (cafes, hotels...)
    5. power: never sleep while plugged in (so the server stays reachable)
#>
param(
  [string]$MediaDir = "C:\Media",
  [string]$ServerDir = "C:\MediaServer",
  [switch]$SkipFirewall,
  [switch]$SkipPower
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Step($t) { Write-Host "`n==> $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "    OK  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    !!  $t" -ForegroundColor Yellow }

Step "WSL 2 (required by Docker Desktop)"
# These checks only warn: the rest of the setup does not need Docker to be running.
$ErrorActionPreference = "Continue"
$wslOk = $false
try {
  $wslOut = (& wsl.exe --status 2>&1 | Out-String) -replace "`0", ""
  $wslOk = ($LASTEXITCODE -eq 0) -and ($wslOut -notmatch "not installed|n.est pas install")
} catch { $wslOk = $false }
if ($wslOk) { Ok "WSL is installed" }
else {
  Warn "WSL is NOT installed, so Docker's engine cannot start."
  Warn "Fix (admin PowerShell):  wsl --install --no-distribution   then REBOOT."
}

Step "Docker Desktop"
$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker -and (Test-Path "C:\Program Files\Docker\Docker\resources\bin\docker.exe")) {
  $env:Path += ";C:\Program Files\Docker\Docker\resources\bin"
  $docker = Get-Command docker -ErrorAction SilentlyContinue
}
if (-not $docker) {
  Warn "Docker is not installed. Install it with:  winget install -e --id Docker.DockerDesktop  then reboot."
} else {
  $null = & docker info 2>&1
  if ($LASTEXITCODE -eq 0) { Ok "Docker engine is running" }
  else {
    Warn "Docker is installed but its engine is not running."
    Warn "Start 'Docker Desktop' from the Start menu and wait until it says 'Engine running' (bottom-left)."
  }
}
$ErrorActionPreference = "Stop"

Step "Folders"
$libs = "Movies","TV","Documentaries","Education","Personal","Music","Podcasts","Audiobooks"
$dirs = @("_Inbox","_Review","_Duplicates") + $libs | ForEach-Object { Join-Path $MediaDir $_ }
$dirs += $libs | ForEach-Object { Join-Path (Join-Path $MediaDir "_Inbox") $_ }
$dirs += "jellyfin\config","jellyfin\cache","navidrome","audiobookshelf\config","audiobookshelf\metadata","organizer","hub" |
  ForEach-Object { Join-Path $ServerDir $_ }
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
Ok "$MediaDir and $ServerDir are ready"
$readme = Join-Path $MediaDir "_Inbox\README.txt"
if (-not (Test-Path $readme)) {
@"
Drop new files here. The organizer files them into the library automatically.
Optional hint folders: Movies, TV, Documentaries, Education, Personal, Music, Podcasts, Audiobooks.
Nothing is ever deleted: unidentified files go to _Review, duplicates go to _Duplicates.
"@ | Out-File -Encoding utf8 $readme
}

Step ".env"
$envFile = Join-Path $here ".env"
if (Test-Path $envFile) { Ok ".env already exists (left untouched)" }
else {
  (Get-Content (Join-Path $here ".env.example") -Raw) `
    -replace "MEDIA_DIR=.*", ("MEDIA_DIR=" + ($MediaDir -replace "\\","/")) `
    -replace "SERVER_DIR=.*", ("SERVER_DIR=" + ($ServerDir -replace "\\","/")) |
    Out-File -Encoding utf8 $envFile
  Ok "created .env - open it and add your TMDb key"
}

if (-not $SkipFirewall) {
  Step "Firewall (home network only)"
  if (-not $isAdmin) { Warn "Not running as administrator: firewall rules skipped. Re-run as admin." }
  else {
    $ports = 8080, 8096, 4533, 13378
    Get-NetFirewallRule -DisplayName "Media Hub*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName "Media Hub - allow LAN" -Direction Inbound -Action Allow -Protocol TCP `
      -LocalPort $ports -Profile Private -RemoteAddress LocalSubnet | Out-Null
    New-NetFirewallRule -DisplayName "Media Hub - block public networks" -Direction Inbound -Action Block -Protocol TCP `
      -LocalPort $ports -Profile Public | Out-Null
    Ok "ports $($ports -join ', ') open to your local network only (Private profile)"
    $profiles = Get-NetConnectionProfile | Select-Object -ExpandProperty NetworkCategory -Unique
    if ($profiles -contains "Public") {
      Warn "Your current network is set to Public, so other devices can't connect."
      Warn "If this is your home Wi-Fi: Settings > Network & internet > Wi-Fi > (your network) > Private network"
    }
  }
}

if (-not $SkipPower) {
  Step "Power (stay awake on AC power)"
  powercfg /change standby-timeout-ac 0 | Out-Null
  powercfg /change hibernate-timeout-ac 0 | Out-Null
  Ok "the laptop won't sleep while plugged in (battery settings unchanged)"
}

Step "Done"
$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.PrefixOrigin -in "Dhcp","Manual" -and $_.IPAddress -notlike "169.*" -and $_.InterfaceAlias -notmatch "vEthernet|WSL|Loopback" } |
  Select-Object -First 1).IPAddress
Write-Host "Next:  docker compose up -d --build"
Write-Host "Then open  http://localhost:8080   (other devices: http://$ip`:8080)"
