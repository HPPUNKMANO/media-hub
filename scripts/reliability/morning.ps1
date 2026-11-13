# Started at 07:00 and 07:10 by "Media Hub - morning wake" (the task wakes the PC from the night hibernation).
# 1) start the all-day keeper as its own task, so it survives this task ending
# 2) screen on for 5 min: ends Windows' "unattended wake" state that put the PC back to sleep at 07:02
# 3) leave airplane mode, 4) check the services
$keep = Join-Path $PSScriptRoot "keepawake.ps1"
Start-ScheduledTask -TaskName "Media Hub - keep awake" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3   # let the keeper take the lock first
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$keep`" -DisplayMinutes 5"
& (Join-Path $PSScriptRoot "radios.ps1") -State On
& (Join-Path $PSScriptRoot "watchdog.ps1")
