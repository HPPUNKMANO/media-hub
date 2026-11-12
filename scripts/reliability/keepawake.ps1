# Keeps Windows from falling asleep on its own while you are logged in, so the phone app always works.
# (Same mechanism video players use. The screen can still turn off; closing the lid still puts the PC to sleep.)
# -DisplayMinutes N : also keeps the SCREEN on for N minutes. Used by the 07:00 wake task: after a wake by timer with
#   nobody in front of it, Windows treats the PC as "unattended" and puts it back to sleep after 2 minutes
#   (seen on 2026-11-12: woke 06:59, "System Idle" sleep 07:02). Turning the screen on ends that unattended state.
param([int]$DisplayMinutes = 0)
Add-Type -Namespace MediaHub -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$ES_CONTINUOUS = [uint32]"0x80000000"; $ES_SYSTEM_REQUIRED = [uint32]"0x00000001"; $ES_DISPLAY_REQUIRED = [uint32]"0x00000002"

# only one long-running keeper: a second copy just does the screen kick, then leaves
$created = $false
$mutex = New-Object System.Threading.Mutex($true, "Global\MediaHubKeepAwake", [ref]$created)
$until = (Get-Date).AddMinutes($DisplayMinutes)
while ($true) {
  $flags = $ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED   # no "away mode": closing the lid still really sleeps
  if ((Get-Date) -lt $until) { $flags = $flags -bor $ES_DISPLAY_REQUIRED }
  [void][MediaHub.Power]::SetThreadExecutionState($flags)
  if (-not $created -and (Get-Date) -ge $until) { break }   # another keeper is running: our job is done
  Start-Sleep -Seconds 30
}
