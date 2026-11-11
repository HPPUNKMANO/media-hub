# Writes the hub's "Récap IA" with Claude Code (headless). Run by the weekly task; safe to run by hand.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$stamp = Get-Date -Format "yyyy-MM-dd"
$out = "C:\MediaServer\hub\ai_recap.json"
if (Test-Path $out) { Copy-Item $out "$out.bak" -Force }
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
$prompt = (Get-Content "$PSScriptRoot\prompt.md" -Raw -Encoding UTF8).Replace("{{DATE}}", $stamp)
Push-Location $root
$prompt | & $claude -p --allowedTools "WebSearch,WebFetch,Read,Write" --permission-mode acceptEdits --add-dir "C:\MediaServer\hub" 2>&1 |
  Out-File "C:\MediaServer\weekly\ai-recap-$stamp.txt" -Encoding utf8
Pop-Location
try { Get-Content $out -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null; "ai recap: ok" }
catch { if (Test-Path "$out.bak") { Copy-Item "$out.bak" $out -Force }; "ai recap: invalid output, kept the previous one" }
