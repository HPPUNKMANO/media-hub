# Keeps Windows from falling asleep on its own while you are logged in, so the phone app always works.
# (Same mechanism video players use. The screen can still turn off; closing the lid still puts the PC to sleep.)
# -DisplayMinutes N : also turns the SCREEN on (fake 1-pixel mouse move) and keeps it on for N minutes. Used by the
#   07:00 wake task: after a wake by timer with nobody in front of it, Windows stays in "screen-off standby" and puts
#   the PC back to sleep after the unattended timeout (seen 2026-11-12 and 2026-11-13: woke 06:59, "System Idle" 07:02).
#   The unattended timeout itself was raised from 2 to 30 min on 2026-11-13 (powercfg UNATTENDSLEEP = 1800 s).
param([int]$DisplayMinutes = 0)
Add-Type -Namespace MediaHub -Name Power -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
[DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, uint d, System.UIntPtr e);
[DllImport("user32.dll")] public static extern System.IntPtr SendMessageTimeout(System.IntPtr h, uint m, System.IntPtr w, System.IntPtr l, uint f, uint t, out System.IntPtr r);
public static void Nudge() {
  mouse_event(1, 1, 0, 0, System.UIntPtr.Zero); mouse_event(1, -1, 0, 0, System.UIntPtr.Zero);   // MOUSEEVENTF_MOVE
  System.IntPtr r; SendMessageTimeout((System.IntPtr)0xffff, 0x0112, (System.IntPtr)0xF170, (System.IntPtr)(-1), 2, 2000, out r); // monitor on
}
'@
$ES_CONTINUOUS = [uint32]"0x80000000"; $ES_SYSTEM_REQUIRED = [uint32]"0x00000001"; $ES_DISPLAY_REQUIRED = [uint32]"0x00000002"
$log = "C:\MediaServer\weekly\keepawake.log"
function Log($m) { try { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] pid $PID $m" | Add-Content $log } catch {} }

# only one long-running keeper: a second copy just does the screen kick, then leaves
$created = $false
$mutex = New-Object System.Threading.Mutex($true, "Global\MediaHubKeepAwake", [ref]$created)
Log ("start (keeper=$created, display=$DisplayMinutes min)")
$until = (Get-Date).AddMinutes($DisplayMinutes)
$nextNudge = Get-Date
try {
  while ($true) {
    $flags = $ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED   # no "away mode": closing the lid still really sleeps
    $now = Get-Date
    if ($now -lt $until) {
      $flags = $flags -bor $ES_DISPLAY_REQUIRED
      if ($now -ge $nextNudge) { try { [MediaHub.Power]::Nudge() } catch { Log "nudge failed: $_" }; $nextNudge = $now.AddSeconds(60) }
    }
    [void][MediaHub.Power]::SetThreadExecutionState($flags)
    if (-not $created -and $now -ge $until) { break }   # another keeper is running: our job is done
    Start-Sleep -Seconds 30
  }
} finally { Log "exit" }
