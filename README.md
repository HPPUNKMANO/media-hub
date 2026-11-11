# Media Hub: your laptop as a private, free entertainment server

One web page (`http://<laptop-ip>:8080`) for everything you watch, listen to and learn:

| Part | Tool | Port | What it does |
|---|---|---|---|
| **Hub** (custom) | FastAPI + web UI | 8080 | Home page: continue watching, recent music, live radio, legal free-streaming catalog (France) with favorites, global search, organizer control |
| Movies / TV / docs / personal videos | **Jellyfin** | 8096 | Posters, synopses, seasons, genres, subtitles, resume playback, playlists, users, apps for TV/phone |
| Music | **Navidrome** | 4533 | Artists/albums, shuffle, playlists, play history, ListenBrainz/Last.fm scrobbling, internet radio |
| Podcasts & audiobooks | **Audiobookshelf** | 13378 | Subscribe to RSS podcasts, auto-download episodes, remembers your position |
| Automatic filing | **Organizer** (custom) | internal only | Sorts `_Inbox`, renames, fetches metadata/cover art, flags duplicates, refreshes libraries. **Never deletes.** |

Everything is free and open source, runs in Docker Desktop, and stays on your home network.

```
C:\Media\                         ← your media (outside OneDrive on purpose)
  _Inbox\  (+ hint folders Movies, TV, Documentaries, Education, Personal, Music, Podcasts, Audiobooks)
  _Review\        files the organizer couldn't identify
  _Duplicates\    suspected duplicates (you decide what to do with them)
  Movies\Title (Year)\Title (Year).mkv
  TV\Show (Year)\Season 01\Show - S01E01 - Episode.mkv
  Documentaries\  Education\  Personal\YYYY\YYYY-MM\
  Music\Artist\Album (Year)\01 - Title.flac
  Podcasts\  Audiobooks\
C:\MediaServer\                   ← app databases, caches, organizer reports & undo journal
```

---

## 1. Install (about 30 minutes, once)

### Step 1: WSL 2 + Docker Desktop
In an **admin** PowerShell:
```powershell
wsl --install --no-distribution     # Docker's engine runs inside WSL 2
winget install -e --id Docker.DockerDesktop
```
**Reboot**, then start **Docker Desktop** and wait until the bottom-left corner says **Engine running**. (If you skip WSL, every docker command fails with *"failed to connect to the Docker API… check if the daemon is running"*.)
Then, accept the terms, and keep the WSL 2 backend (the default).
In Docker Desktop → *Settings → General*, tick **Start Docker Desktop when you sign in**.
Optionally, in *Settings → Resources → WSL*, give it 4–6 GB RAM (your laptop has 16 GB).

### Step 2: Run the setup script
Open **PowerShell as Administrator** in this folder (`C:\Users\HPPER\OneDrive\Bureau\media studio`):
```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```
It creates `C:\Media` and `C:\MediaServer`, creates `.env`, opens the four ports **to your home network only** (and blocks them on Public networks), and stops the laptop from sleeping while it's plugged in.

> Your home Wi-Fi must be a **Private** network in Windows: *Settings → Network & internet → Wi-Fi → your network → Private network*.

### Step 3: Free TMDb key (movie/TV metadata)
1. Create a free account at <https://www.themoviedb.org/signup>.
2. Go to <https://www.themoviedb.org/settings/api>, request an API key (choose "Personal / Developer"), and copy the **API Key**.
3. Paste it into `.env` after `TMDB_API_KEY=`.

### Step 4: Start everything
```powershell
docker compose up -d --build
docker compose ps        # all services should be "running" / "healthy" after ~1 min
```

### Step 5: First-time wizards
**Jellyfin**: <http://localhost:8096>
1. Choose your language, create the admin user (use a strong password).
2. Add libraries (all paths start with `/media`):

   | Name | Content type | Folder |
   |---|---|---|
   | Movies | Movies | `/media/Movies` |
   | TV Shows | Shows | `/media/TV` |
   | Documentaries | Movies (or Shows) | `/media/Documentaries` |
   | Education | Mixed / Shows | `/media/Education` |
   | Personal | Home videos & photos | `/media/Personal` |

   Metadata language: English (or French). Country: France.
3. Finish the wizard and log in.
4. *Dashboard → Libraries →* each library → **untick "Save subtitles in media folders"** and **untick "Save artwork into media folders"** (media is mounted read-only, so Jellyfin can never change or delete it; artwork lives in `C:\MediaServer`).
5. *Dashboard → Plugins → Catalog →* **Open Subtitles** → install, restart the container (`docker compose restart jellyfin`), and enter a free opensubtitles.com account in the plugin settings. Subtitles for missing languages then download automatically.
6. *Dashboard → API Keys → +* → name it `hub`, then copy the key into `.env` → `JELLYFIN_API_KEY=`, and put your user name in `JELLYFIN_USER=`.
7. Create a normal (non-admin) user for each family member; *Dashboard → Users*.

**Navidrome**: <http://localhost:4533>
1. Create the admin user, then put the same name and password in `.env` (`NAVIDROME_USER`, `NAVIDROME_PASSWORD`).
2. Listening history: *Personal settings* → connect **ListenBrainz** (free, open) or Last.fm.
3. Internet radio is already on the Hub's *Listen* page (Radio France streams). To add stations inside Navidrome too: *Radios → Create* (e.g. FIP: `https://icecast.radiofrance.fr/fip-hifi.aac`).

**Audiobookshelf**: <http://localhost:13378>
1. Create the root user.
2. *Settings → Libraries → Add*: **Podcasts** (type Podcast, folder `/podcasts`) and **Audiobooks** (folder `/audiobooks`).
3. Podcasts → *Search* (built-in iTunes directory) → e.g. "France Culture", "Arte Radio", "Collège de France" → subscribe, and turn on **auto-download** of new episodes.
4. Create an API token: *Settings → API Keys → Add* (recent versions) or *Settings → Users →* your user → **API token** (older versions). Copy it into `.env` → `ABS_API_TOKEN=`.

Then apply the keys:
```powershell
docker compose up -d
```
Open the Hub at <http://localhost:8080>. The **Status** page should show everything green.

### Step 6: Other devices on your Wi-Fi
- Find the laptop's IP: `ipconfig` → "IPv4 Address" (e.g. `192.168.1.20`).
- Phone, tablet or another PC: open `http://192.168.1.20:8080`.
- TV / Fire TV / Android TV / iPhone: install the **Jellyfin** app and use server `http://192.168.1.20:8096`.
- Music apps (Subsonic API): **Symfonium** (Android), **Substreamer** / **Amperfy** (iOS), **Feishin** (desktop) → server `http://192.168.1.20:4533`.
- Podcasts: the **Audiobookshelf** app (Android/iOS) → `http://192.168.1.20:13378`.
- Tip: reserve that IP for the laptop in your router (DHCP reservation) so it never changes.

---

## 2. Daily use

### Adding media
Drop files into `C:\Media\_Inbox`. Use a hint folder when it helps:

| Put it in | When |
|---|---|
| `_Inbox\` | movies and TV episodes with normal release names (`Movie.Name.2019.1080p.mkv`, `Show.S01E02.mkv`) |
| `_Inbox\Documentaries\`, `_Inbox\Education\` | docs, lectures, course videos |
| `_Inbox\Personal\` | your own videos and photos (phone/camera names like `VID_20240131_…` are detected anyway) |
| `_Inbox\Music\` | albums or tracks (tags are read; files without tags can be named `Artist - Title.mp3`) |
| `_Inbox\Podcasts\`, `_Inbox\Audiobooks\` | audio that isn't music (`.m4b` is detected as an audiobook automatically) |

Subtitles named like the video (`Movie.2019.fr.srt`) move with it.

### The organizer, step by step
1. **Detects** new files, skipping anything still downloading or modified in the last 2 minutes.
2. **Finds exact duplicates** (size, then SHA-256) against the whole library and within the inbox. They go to `_Duplicates`, and the best-named copy is the one kept in the library. A second version of a movie or episode you already have (e.g. another resolution) also goes to `_Duplicates`.
3. **Identifies** the file: `guessit` reads the name, **TMDb** confirms the title and year (low-confidence matches go to `_Review`), and audio tags are read with `mutagen`.
4. **Checks the file is readable** with `ffprobe`; broken files go to `_Review`.
5. **Renames and moves** it into the Jellyfin/Navidrome layout. It never overwrites: a name clash becomes `Name (2).ext`.
6. **Fetches album art** from MusicBrainz / Cover Art Archive (`cover.jpg`, never overwriting).
7. **Refreshes** Jellyfin, Navidrome and Audiobookshelf through their APIs.
8. **Journals** every move in `C:\MediaServer\organizer\moves.jsonl` and writes a report you can read on the Hub's **Organize** page.

**It starts in `dry-run` mode**: every 10 minutes it only *reports* what it would do. Check the plan on the Organize page (or click **Preview**). When you're happy, set `ORGANIZER_MODE=live` in `.env` and run `docker compose up -d`. You can also click **Organize now** on the Hub at any time.

**Undo a run:**
```powershell
docker compose exec organizer python -m app.undo --list            # list runs
docker compose exec organizer python -m app.undo                   # preview undo of the last run
docker compose exec organizer python -m app.undo --run 20261111-101500 --apply
```

**`_Review` and `_Duplicates`:** the Hub lists each file with the reason it landed there. For `_Review`, rename the file (`Title (Year).mkv` or `Show - S01E02.mkv`) and put it back in `_Inbox`. For `_Duplicates`, you decide; the tool will never delete anything for you.

### Free & legal content
- **Discover**: French TV and replay (ARTE, france.tv, TF1+, M6+, Molotov), free channels (Pluto TV, Samsung TV Plus), free films (Rakuten TV free section, Plex, ARTE Cinéma), public-domain archives (HENRI/Cinémathèque, INA, Internet Archive, Prelinger, Gallica, Europeana…), documentaries, podcasts and free music services. Filter by category, language and price model, and tap ☆ to save favorites (stored on the server, so they appear on every device).
- **Learn**: MOOCs (FUN-MOOC, Coursera/edX audit, MIT OCW, Khan Academy, freeCodeCamp, OpenClassrooms), lectures (Collège de France, Canal-U, Yale, Stanford, TED), science channels and school resources (Lumni).
- Legal media to **keep** in your library: public-domain films from Internet Archive, and Creative Commons music from Jamendo / Free Music Archive / Bandcamp free downloads.
- The catalog lives in `hub/app/data/catalog.json`; edit it to add your own entries. Check every link with:
  ```powershell
  python scripts/check_links.py
  ```
  (needs `pip install requests`). Free offers change over time: re-run it every few months. A 403 usually means the site blocks bots, not that it's down.

---

## 3. Security
- Nothing is exposed to the internet: no router port forwarding is needed or wanted.
- Windows Firewall allows the ports from your **local subnet on Private networks** only, and blocks them on Public networks.
- Jellyfin and Navidrome mount your media **read-only**; only the organizer can move files, and it can't delete them.
- API keys and passwords live in `.env` (server side only, never sent to the browser). Don't share that file.
- Use strong passwords and give family members non-admin accounts.
- **Remote access later?** Install **Tailscale** (free) on the laptop and your phone. You get an encrypted private network with no open ports, then use `http://<tailscale-ip>:8080`.

## 4. Maintenance
```powershell
docker compose pull; docker compose up -d --build   # update everything
docker compose logs -f organizer                     # watch the organizer
docker compose restart jellyfin                      # restart one service
docker compose down                                  # stop everything (your files stay untouched)
```
**Backup:** copy `C:\MediaServer` (settings, watch history, favorites) and `C:\Media` to an external drive.

## 5. Troubleshooting
| Problem | Fix |
|---|---|
| Other devices can't connect | Wi-Fi must be *Private*; re-run `setup.ps1` as admin; check the IP with `ipconfig`; Docker Desktop must be running |
| Hub sections are empty | **Status** page: is the service "not configured"? Add its key to `.env`, then `docker compose up -d` |
| Files stay in `_Inbox` | Is `ORGANIZER_MODE` still `dry-run`? Were they modified in the last 2 min? See the Organize page |
| Wrong movie match | Rename to `Title (Year).ext`; for a few files, fix it in Jellyfin → *Identify* |
| Playback stutters | Prefer direct play (MP4/MKV with H.264/HEVC + AAC). Docker Desktop can't use the Intel GPU, so transcoding is CPU-only (the i7-12650H handles 1–2 streams) |
| Smart TV with no Jellyfin app | DLNA doesn't work through Docker Desktop's network. Use the Jellyfin app, a Fire TV / Chromecast, or the TV's web browser |

## 6. Developer notes
```
organizer/app/   config.py · classify.py (guessit + patterns) · naming.py · dedupe.py (hash cache)
                 metadata.py (TMDb, mutagen, Cover Art Archive, ffprobe) · engine.py · fsops.py (safe moves)
                 refresh.py · undo.py · server.py (internal API + scheduler)
organizer/tests/ pytest suite, including a guard test that fails if any delete/overwrite call appears
hub/app/         main.py (API) · clients.py (Jellyfin/Navidrome/ABS) · static/ (UI) · data/catalog.json
```
Run the tests: `cd organizer; pip install -r requirements.txt pytest; python -m pytest -q`
