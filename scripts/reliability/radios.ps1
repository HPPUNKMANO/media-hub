# Turns the wireless radios (Wi-Fi, Bluetooth, mobile) Off = airplane mode, or back On.
# Usage: radios.ps1 -State Off|On [-Kind All|WiFi|Bluetooth]     Prints each radio and its new state.
param([ValidateSet("On", "Off")][string]$State = "On", [ValidateSet("All", "WiFi", "Bluetooth", "MobileBroadband")][string]$Kind = "All")
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
$access = Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])
if ($access -ne "Allowed") { "radios: access $access"; exit 1 }
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
foreach ($r in $radios) {
  if ($Kind -ne "All" -and "$($r.Kind)" -ne $Kind) { continue }
  $res = Await ($r.SetStateAsync([Windows.Devices.Radios.RadioState]::$State)) ([Windows.Devices.Radios.RadioAccessStatus])
  "radios: $($r.Kind) '$($r.Name)' -> $State ($res)"
}
