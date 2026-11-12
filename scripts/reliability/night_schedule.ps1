# Night pause: the PC hibernates at 22:00 (as good as off: no power used, open apps kept) and wakes up at 07:00.
# A fully shut-down PC can't be woken by Windows, so hibernate + a wake timer is used instead.
# Usage: night_schedule.ps1 [-Off "22:00"] [-On "07:00"]      Remove: night_schedule.ps1 -Remove
param([string]$Off = "22:00", [string]$On = "07:00", [switch]$Remove)
$offName = "Media Hub - night off"; $onName = "Media Hub - morning wake"
if ($Remove) {
  Unregister-ScheduledTask -TaskName $offName -Confirm:$false -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $onName -Confirm:$false -ErrorAction SilentlyContinue
  "Night schedule removed."; return
}
# wake timers must be allowed (plugged in and on battery) or the 07:00 wake never happens
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
powercfg /setactive SCHEME_CURRENT
powercfg /hibernate on 2>$null

# 22:00 = start waiting: night_off.ps1 hibernates only after 20 min without anyone using the PC
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable:$false -ExecutionTimeLimit (New-TimeSpan -Hours 23)
$offAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'night_off.ps1')`""
Register-ScheduledTask -TaskName $offName -Trigger (New-ScheduledTaskTrigger -Daily -At $Off) -Action $offAction -Settings $set `
  -Description "Hibernates the PC every night (Media Hub night pause)." -Force | Out-Null

$watchdog = Join-Path $PSScriptRoot "watchdog.ps1"
$wakeSet = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$radios = Join-Path $PSScriptRoot "radios.ps1"
# leave airplane mode first, then check the services
$onAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& '$radios' -State On; & '$watchdog'`""
Register-ScheduledTask -TaskName $onName -Trigger (New-ScheduledTaskTrigger -Daily -At $On) -Action $onAction -Settings $wakeSet `
  -Description "Wakes the PC every morning and checks the Media Hub services." -Force | Out-Null
"Night schedule set: hibernate at $Off, wake at $On."
