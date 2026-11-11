param([string]$In, [string]$Dest)
# Keep only official broadcasters / official free ad-supported (FAST) services, regroup for the user.
$badHost = 'githubusercontent|streambox|freem3u|ddns\.net|servehttp|playtv4k|voozmedia|foxkidstv|mediacdn\.ru|presstv|rttv|panaccess|vps|fastcast4u|odysee|cdnsun|getstreamhosting|berosat|vdopanel|az-multimedia|lnmlive|bild-und-ton|tulix|srfms'
$badName = 'Adult|XXX|Erotic|Girlfriends|Playboy|Hustler|Brazzers|Dorcel|Hot |Geo-blocked|Turkmenistan|Greek|Lebanon|Iqraa|Gospel|Eglise|Religion|Louange|Telepace|Miracle|Evangile|Sentinel|Puissance|Esaie|Baraka|EWTN|3ABN|MTA\d|Sophia|Mana |Dating|Tele Boston|Haiti|Cameroon|Algeria|Senegal|Benin|Tchad|Sahel|Ivoire|Ivory|Louga|SenJeunes|Burundi|RTNB|Togo|Kajou|HMI|Chandel|Amou|Afrik|DRTV|Digital Channel|Eden TV|Espoir|Ginen|4VEH|Full Gospel|RTH-TV|TVCARiB|Laura Dave|For You|Zitata|Savane|Tal TV|ILTV|CNA|Afrique Media|AL24|OTV|Evandis|ADO TV|EVI TV|Ev-tele|Benie|Champion TV|Lollywood|Le Monde en 24h|CAM 10|Diaspora|Seneweb|P2M|Identite|Reflet|Tele Zoukla|Tele Peyi|RHT|ETV|Basse-Terre|TMA|Madras|Kalac|DBM|FUSION|Espace TV|BPX|7 Info|Serie Max|Radio Tele|Max TV|My TV|Play TV|PLEX|StoryChannel|GMS|zenith|Medi1|2M|RTVC|RT JVA|TV Famille|Mondeduloisir|MDL|A2i|Tele Sahel|Trace (Africa|Afrikora|Ayiti|Brazuca|Caribbean|Ivoire|Jama|Kitoko|Latina|Mboa|Muzika|Mziki|Naija|Vanilla|Urban (Africa|Caribbean|Southern))|Southern Africa|NTV|Generations TV|HANDICAP|viaTele|Matele|ViaMatele|Montreal|Savoir|Canal Z|ACTV|Bouke|BX1|Telesambre|QU4TRE|Tele MB|TVcom|Vedia|RTL Zwee|Leman|Antenne Reunion|Alpe|Brionnais|Cannes|Carac|TV3V|TV7|Vosges|Tebeo|Monaco Info|Nouvelle Caledonie|EbS|Fun Vision|Nautical|FashionTV \(Russia\)|CGTN|Africa 24|NW |Le Nouveau|Gong|Kozoom|Africanews'
function Group-Of($n) {
  switch -Regex ($n) {
    '^Cin|Nanar|Western|ScreamIN|Emotion|Sony One|Into Crime|Frequence Novelas|French Collection|Instant Saga' { return "Cinéma" }
    'Toons|Kids|Super Kids|Teen|Bob l|One Piece|Conan|Inazuma|Caillou|Mr Bean|ADN|ANIME|Tortues|BabyFirst|Turbo|Ninja|Retro Toons|JapanimTV' { return "Enfants & Anime" }
    'BFM|RMC Story|i24|Euronews|20 Minutes|Figaro|France 24|LCP|TV Monaco' { return "Info" }
    "L'Equipe|FIFA|Sport" { return "Sport" }
    'Trace|MTV|Stingray|Qwest|Fashion' { return "Musique" }
    'Decouverte|NatureTime|Histoire|Investigation|Voyages|Animaux|Aventure|Cuisine|Chefs|True Crime|RMC Life|Inside' { return "Docs & Découverte" }
    default { return "Séries" }
  }
}
$lines = Get-Content $In -Encoding UTF8
$out = @("#EXTM3U"); $kept = @{}
for ($i = 1; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -notlike "#EXTINF*") { continue }
  $inf = $lines[$i]; $opts = @(); $j = $i + 1
  while ($lines[$j] -like "#EXTVLCOPT*") { $opts += $lines[$j]; $j++ }
  $url = $lines[$j]; $i = $j
  $name = ($inf -split '",', 2)[-1]; if ($name -eq $inf) { $name = ($inf -split ",", 2)[1] }
  $h = ([uri]$url).Host
  if ($h -match $badHost -or $name -match $badName) { continue }
  $g = Group-Of $name
  $inf = $inf -replace 'group-title="[^"]*"', "group-title=`"$g`""
  $out += $inf; $out += $opts; $out += $url
  $kept[$g] = @($kept[$g]) + $name
}
[IO.File]::WriteAllLines($Dest, $out, (New-Object Text.UTF8Encoding $false))
foreach ($k in $kept.Keys | Sort-Object) { "== $k ($(@($kept[$k] | Where-Object { $_ }).Count)): " + ((@($kept[$k] | Where-Object { $_ }) | ForEach-Object { $_ -replace ' \(\d+p\)','' }) -join ', ') }
