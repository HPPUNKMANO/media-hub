# Started at 22:00 by "Media Hub - night off". Hibernates the PC only once nobody is using it:
# no keyboard / mouse / touch for $IdleMinutes AND no sound playing (a film, a video or music counts as "in use").
# While the PC is in use it keeps waiting (checks every 2 min) and gives up at $GiveUpHour so it never hibernates in the morning.
param([int]$IdleMinutes = 20, [int]$GiveUpHour = 6)
Add-Type -Namespace MediaHub -Name Idle -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
[DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
public static uint IdleMs() { var i = new LASTINPUTINFO(); i.cbSize = (uint)System.Runtime.InteropServices.Marshal.SizeOf(i); GetLastInputInfo(ref i); return (uint)System.Environment.TickCount - i.dwTime; }
'@
# Sound level of the speakers / headphones (Windows Core Audio peak meter), 0 = silence
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
namespace MediaHub {
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {}
  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator { int NotImpl1(); [PreserveSig] int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice); }
  [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice { [PreserveSig] int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface); }
  [Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioMeterInformation { [PreserveSig] int GetPeakValue(out float pfPeak); }
  public static class Audio {
    public static float Peak() {
      try {
        var en = (IMMDeviceEnumerator)(new MMDeviceEnumerator());
        IMMDevice dev; if (en.GetDefaultAudioEndpoint(0, 1, out dev) != 0) return 0;
        var iid = typeof(IAudioMeterInformation).GUID; object o;
        if (dev.Activate(ref iid, 23, IntPtr.Zero, out o) != 0) return 0;
        float p; ((IAudioMeterInformation)o).GetPeakValue(out p); return p;
      } catch { return 0; }
    }
  }
}
'@
function SoundPlaying {   # sampled over ~10 s so a quiet moment in a film doesn't count as silence
  for ($i = 0; $i -lt 20; $i++) { if ([MediaHub.Audio]::Peak() -gt 0.001) { return $true }; Start-Sleep -Milliseconds 500 }
  return $false
}
$log = "C:\MediaServer\weekly\night.log"
while ($true) {
  $idle = [MediaHub.Idle]::IdleMs() / 60000
  if ($idle -ge $IdleMinutes -and -not (SoundPlaying)) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm') hibernate (idle $([int]$idle) min, no sound), airplane mode on" | Add-Content $log
    & (Join-Path $PSScriptRoot "radios.ps1") -State Off | Add-Content $log   # airplane mode for the night
    shutdown.exe /h
    Start-Sleep -Seconds 120   # the PC hibernates during this wait; the script carries on when it wakes up
    & (Join-Path $PSScriptRoot "radios.ps1") -State On | Add-Content $log    # back online (07:00 task does it too)
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm') woke up, radios on" | Add-Content $log
    break
  }
  $h = (Get-Date).Hour
  if ($h -ge $GiveUpHour -and $h -lt 12) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm') PC used all night, no hibernate" | Add-Content $log; break }
  Start-Sleep -Seconds 120
}
