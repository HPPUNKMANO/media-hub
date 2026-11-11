# Freebox TV in the hub: reads the channel list the Freebox publishes on the home network (your own subscription),
# keeps the HD version of each channel, and writes:
#   - C:\MediaServer\mediamtx\mediamtx.yml : MediaMTX converts each channel (RTSP/UDP) to HLS on demand, port 8899
#   - C:\MediaServer\hub\iptv\freebox.m3u  : the hub's Live TV lists them in a "TNT (Freebox)" category
$ErrorActionPreference = "Stop"
$dir = "C:\MediaServer\mediamtx"; New-Item -ItemType Directory -Force $dir, "C:\MediaServer\hub\iptv" | Out-Null
$raw = (& curl.exe -s -m 15 "http://mafreebox.freebox.fr/freeboxtv/playlist.m3u") -join "`n"
if ($raw -notmatch "#EXTM3U") { throw "Freebox playlist not reachable (is this PC on the Freebox network?)" }
$lines = $raw -split "`n"
$ff = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
if (-not $ff) { throw "FFmpeg not found (winget install Gyan.FFmpeg)" }
# Freebox sends MPEG-TS over RTP/UDP: FFmpeg (started on demand by MediaMTX) takes the main picture + French audio,
# re-encodes the audio to plain AAC and publishes it to MediaMTX, which serves it as HLS to the hub.
$yml = @("logLevel: info", "hls: yes", "hlsAddress: :8899", "hlsVariant: mpegts", "hlsSegmentCount: 7", "hlsSegmentDuration: 2s",
         "hlsAllowOrigins: ['*']", "rtsp: yes", "rtspAddress: 127.0.0.1:8554", "rtspTransports: [tcp]", "rtmp: no", "webrtc: no", "srt: no", "api: no", "paths:")
$m3u = @("#EXTM3U"); $n = 0
for ($i = 0; $i -lt $lines.Count - 1; $i++) {
  if ($lines[$i] -notmatch '^#EXTINF:[^,]*,\s*(\d+)\s*-\s*(.+?)\s*\(HD\)\s*$') { continue }
  $num = $Matches[1]; $name = $Matches[2].Trim(); $url = $lines[$i + 1].Trim()
  if ($url -notmatch '^rtsp://') { continue }
  $path = "fbx$num"
  $cmd = "`"$ff`" -hide_banner -loglevel error -fflags +genpts+igndts+discardcorrupt -rtsp_transport udp -i `"$url`" -map 0:v:0 -map 0:a:0 -vf yadif=0:-1:0 -c:v libx264 -preset veryfast -tune zerolatency -profile:v high -b:v 6M -maxrate 7M -bufsize 12M -g 50 -keyint_min 50 -sc_threshold 0 -force_key_frames expr:gte(t,n_forced*2) -bf 0 -c:a aac -b:a 160k -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/$path"
  $yml += "  ${path}:"; $yml += "    runOnDemand: '$($cmd -replace "'", "''")'"; $yml += "    runOnDemandRestart: yes"; $yml += "    runOnDemandCloseAfter: 30s"; $yml += "    runOnDemandStartTimeout: 20s"
  $m3u += "#EXTINF:-1 tvg-id=`"$path`" tvg-logo=`"`" group-title=`"TNT (Freebox)`",$name (1080p)"
  $m3u += "http://host.docker.internal:8899/$path/index.m3u8"
  $n++
}
[IO.File]::WriteAllLines("$dir\mediamtx.yml", $yml, (New-Object Text.UTF8Encoding $false))
[IO.File]::WriteAllLines("C:\MediaServer\hub\iptv\freebox.m3u", $m3u, (New-Object Text.UTF8Encoding $false))
"freebox: $n HD channels configured"
