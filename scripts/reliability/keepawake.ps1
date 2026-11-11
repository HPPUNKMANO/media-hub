# Keeps Windows from falling asleep on its own while you are logged in, so the phone app always works.
# (Same mechanism video players use. The screen can still turn off; closing the lid does nothing — see power settings.)
Add-Type -Namespace MediaHub -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$ES_CONTINUOUS = [uint32]"0x80000000"; $ES_SYSTEM_REQUIRED = [uint32]"0x00000001"; $ES_AWAYMODE_REQUIRED = [uint32]"0x00000040"
while ($true) {
  [void][MediaHub.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED -bor $ES_AWAYMODE_REQUIRED)
  Start-Sleep -Seconds 60
}
