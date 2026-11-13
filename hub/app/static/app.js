"use strict";

/* ------------------------------------------------------------ helpers */
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && !path.startsWith("/api/auth/")) showLogin();   // signed out: show the login screen
  if (!r.ok && !data.error) data.error = `HTTP ${r.status}`;
  return data;
};
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

let PORTS = { jellyfin: 8096, navidrome: 4533, audiobookshelf: 13378 };
const serviceUrl = (service, path = "/") => `${location.protocol}//${location.hostname}:${PORTS[service]}${path}`;
const appLink = (service, path = "") => `#app/${service}${path ? `?p=${encodeURIComponent(path)}` : ""}`;

/* ---- in-hub apps: each service lives in its own iframe that is never destroyed,
   so a film or an album keeps playing while you browse the rest of the hub */
const APP_HOME = { jellyfin: "/web/", navidrome: "/app/", audiobookshelf: "/" };
const APP_NAME = { jellyfin: "Films & TV", navidrome: "Music", audiobookshelf: "Books & podcasts" };
const frames = {};
function openApp(service, path) {
  if (!APP_HOME[service]) return false;
  const want = serviceUrl(service, path || APP_HOME[service]);
  let f = frames[service];
  if (!f) {
    f = document.createElement("iframe");
    f.className = "app-frame"; f.title = APP_NAME[service];
    f.allow = "autoplay; fullscreen; picture-in-picture; encrypted-media";
    f.src = want; frames[service] = f; $("#apps-frames").appendChild(f);
  } else if (path) {
    f.src = want;   // only a hash change for Jellyfin/Navidrome: no reload
  }
  Object.entries(frames).forEach(([k, x]) => x.classList.toggle("on", k === service));
  $("#apps-tabs").innerHTML = `<button class="apps-nav" id="apps-back" title="Back to the hub">← <span>Retour</span></button><button class="apps-nav apps-menu" id="apps-menu" title="Menu">☰</button>` + Object.keys(APP_HOME).map((k) =>
    `<a href="${appLink(k)}" class="${k === service ? "on" : ""}${frames[k] ? " live" : ""}">${APP_NAME[k]}</a>`).join("") +
    `<button class="apps-reload" id="apps-reload" title="Back to the start of this app">⟲</button>`;
  $("#apps-reload").onclick = () => { f.src = serviceUrl(service, APP_HOME[service]); };
  $("#apps-back").onclick = () => { if (history.length > 1 && document.referrer !== location.href) history.back(); else location.hash = "#home"; };
  $("#apps-menu").onclick = () => setNav(true);
  document.body.classList.add("in-app");
  document.querySelectorAll("#service-links a").forEach((a) => a.classList.toggle("active", a.dataset.app === service));
  return true;
}
function closeApps() {
  document.body.classList.remove("in-app");
  document.querySelectorAll("#service-links a").forEach((a) => a.classList.remove("active"));
}

const SERVICES = [
  ["jellyfin", "Jellyfin", "Movies & TV"],
  ["navidrome", "Navidrome", "Music"],
  ["audiobookshelf", "Audiobookshelf", "Podcasts"],
];

let CATALOG = null;
let FAVS = new Set();
async function loadCatalog() {
  if (!CATALOG) {
    CATALOG = await api("/api/catalog");
    FAVS = new Set(CATALOG.favorites || []);
  }
  return CATALOG;
}

/* ------------------------------------------------------------ components */
function poster(item, { square = false } = {}) {
  const href = item.service ? appLink(item.service, item.link) : item.link;
  const initial = esc((item.title || "?").trim().charAt(0).toUpperCase());
  const prog = item.progress ? `<div class="progress"><i style="width:${Math.min(100, item.progress)}%"></i></div>` : "";
  const nd = item.nd_album ? ` data-nd-album="${esc(item.nd_album)}"` : "";
  const on = item.nd_album && albumQ && albumQ.id === item.nd_album ? " on" : "";
  return `<a class="poster${square ? " square" : ""}${on}" href="${esc(href)}"${nd}${item.service ? "" : ' target="_blank" rel="noopener"'} title="${esc(item.title)}">
    <div class="art"><div class="fallback">${initial}</div>
      <img src="${esc(item.image)}" alt="" loading="lazy" onerror="this.remove()">${prog}${item.nd_album ? '<span class="play-badge">▶</span>' : ""}</div>
    <div class="t">${esc(item.title)}</div><div class="s">${esc(item.subtitle || item.type || "")}</div></a>`;
}

function row(title, items, opts = {}, emptyHtml = "") {
  if (!items || !items.length) return emptyHtml ? `<h2>${esc(title)}</h2>${emptyHtml}` : "";
  return `<h2>${esc(title)} <small>${items.length}</small></h2><div class="row">${items.map((i) => poster(i, opts)).join("")}</div>`;
}

/* line icons (consistent 1.75 stroke) instead of emoji */
const ICON = {
  film: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/></svg>`,
  tv: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M7 2l5 5 5-5"/></svg>`,
  music: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
  book: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/></svg>`,
  radio: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect x="2" y="8" width="20" height="13" rx="2"/><path d="M6 8l12-5"/><circle cx="16" cy="14.5" r="2.5"/><path d="M6 13h4M6 16h4"/></svg>`,
  play: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg>`,
  arrow: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg>`,
};
function serviceTiles() {
  const icons = { jellyfin: ICON.film, navidrome: ICON.music, audiobookshelf: ICON.book };
  return `<div class="tiles">${SERVICES.map(([id, name, sub]) => `
    <a class="tile" href="${appLink(id)}">
      <div class="ico">${icons[id]}</div><div><b>${name}</b><span>${sub} · port ${PORTS[id]}</span></div></a>`).join("")}</div>`;
}

function entryCard(e) {
  const cost = CATALOG.cost_labels[e.cost] || e.cost;
  const on = FAVS.has(e.id);
  return `<article class="entry">
    <header><h3><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.name)}</a></h3>
      <button class="fav${on ? " on" : ""}" data-fav="${esc(e.id)}" aria-pressed="${on}" title="${on ? "Remove from" : "Add to"} favorites">${on ? "★" : "☆"}</button></header>
    <p>${esc(e.description)}</p>
    <div class="meta"><span class="tag cost">${esc(cost)}</span>
      ${(e.languages || []).map((l) => `<span class="tag">${esc(l.toUpperCase())}</span>`).join("")}
      ${(e.topics || []).slice(0, 4).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    <footer><span>⏱ ${esc(e.duration)}</span><span>${esc(CATALOG.categories[e.category] || e.category)}</span></footer>
  </article>`;
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-fav]");
  if (!b) return;
  const id = b.dataset.fav;
  const on = !FAVS.has(id);
  b.disabled = true;
  const res = await api(`/api/favorites/${encodeURIComponent(id)}`, { method: on ? "PUT" : "DELETE" });
  b.disabled = false;
  if (res.error) return;
  on ? FAVS.add(id) : FAVS.delete(id);
  document.querySelectorAll(`[data-fav="${CSS.escape(id)}"]`).forEach((x) => {
    x.classList.toggle("on", on); x.textContent = on ? "★" : "☆"; x.setAttribute("aria-pressed", on);
  });
});

/* ---- catalog browser (Discover + Learn share it) */
function catalogBrowser(page, cats) {
  const key = `hub-filters-${page}`;
  const state = store.get(key, { cat: "all", lang: "all", cost: "all", text: "", favs: false });
  const entries = CATALOG.entries.filter((e) => cats.includes(e.category));
  const langs = [...new Set(entries.flatMap((e) => e.languages))].sort();
  const costs = [...new Set(entries.map((e) => e.cost))];

  const render = () => {
    store.set(key, state);
    const t = state.text.toLowerCase();
    const list = entries.filter((e) =>
      (state.cat === "all" || e.category === state.cat) &&
      (state.lang === "all" || e.languages.includes(state.lang)) &&
      (state.cost === "all" || e.cost === state.cost) &&
      (!state.favs || FAVS.has(e.id)) &&
      (!t || `${e.name} ${e.description} ${e.topics.join(" ")}`.toLowerCase().includes(t)));
    $("#chips").innerHTML = ["all", ...cats].map((c) =>
      `<button class="chip${state.cat === c ? " on" : ""}" data-cat="${c}">${c === "all" ? "All" : esc(CATALOG.categories[c])}</button>`).join("") +
      `<button class="chip${state.favs ? " on" : ""}" data-favs>★ Favorites</button>`;
    $("#results").innerHTML = list.length ? list.map(entryCard).join("") :
      `<div class="empty">Nothing matches these filters${state.favs ? " — tap ☆ on a card to save favorites" : ""}.</div>`;
    $("#count").textContent = `${list.length} of ${entries.length}`;
  };

  view.querySelector("#catalog").innerHTML = `
    <div class="filters" id="chips"></div>
    <div class="filters">
      <input type="search" id="ftext" placeholder="Filter by topic or name…" value="${esc(state.text)}">
      <select id="flang"><option value="all">All languages</option>${langs.map((l) => `<option value="${l}" ${state.lang === l ? "selected" : ""}>${l.toUpperCase()}</option>`).join("")}</select>
      <select id="fcost"><option value="all">Any price model</option>${costs.map((c) => `<option value="${c}" ${state.cost === c ? "selected" : ""}>${esc(CATALOG.cost_labels[c])}</option>`).join("")}</select>
      <small class="lead" id="count"></small>
    </div>
    <div class="cards" id="results"></div>`;
  $("#chips").addEventListener("click", (e) => {
    const c = e.target.closest(".chip"); if (!c) return;
    if (c.hasAttribute("data-favs")) state.favs = !state.favs; else state.cat = c.dataset.cat;
    render();
  });
  $("#ftext").addEventListener("input", (e) => { state.text = e.target.value; render(); });
  $("#flang").addEventListener("change", (e) => { state.lang = e.target.value; render(); });
  $("#fcost").addEventListener("change", (e) => { state.cost = e.target.value; render(); });
  document.addEventListener("click", function favRerender(ev) {
    if (ev.target.closest("[data-fav]") && state.favs) setTimeout(render, 300);
    if (!document.body.contains($("#results"))) document.removeEventListener("click", favRerender);
  });
  render();
}

/* ------------------------------------------------------------ radio player */
const audio = $("#audio"), player = $("#player");
let playingUrl = null;
function playRadio(name, url, genre) {
  if (playingUrl === url && !audio.paused) { audio.pause(); return; }
  albumQ = null; player.classList.remove("album"); markAlbum();
  audio.src = url; playingUrl = url;
  audio.volume = Number($("#vol").value);
  audio.play().catch(() => { $("#now-sub").textContent = "Could not start the stream"; });
  $("#now-name").textContent = name; $("#now-sub").textContent = `Live · ${genre || "radio"}`;
  nowGenre = genre; pollNow();
  player.classList.add("show");
  markPlaying();
}
function markPlaying() {
  document.querySelectorAll(".radio").forEach((r) => r.classList.toggle("playing", r.dataset.url === playingUrl && !audio.paused));
  $("#pp").textContent = audio.paused ? "▶" : "❚❚";
}
audio.addEventListener("play", markPlaying); audio.addEventListener("pause", markPlaying);
$("#pp").onclick = () => (audio.paused ? audio.play() : audio.pause());
$("#vol").oninput = (e) => { audio.volume = Number(e.target.value); };
$("#stop").onclick = () => { albumQ = null; player.classList.remove("album"); markAlbum(); audio.pause(); audio.removeAttribute("src"); audio.load(); playingUrl = null; player.classList.remove("show"); markPlaying(); };
document.addEventListener("click", (e) => {
  const r = e.target.closest(".radio"); if (r) playRadio(r.dataset.name, r.dataset.url, r.dataset.genre);
});
const hue = (s) => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const radioButton = (r) => `<button class="radio${playingUrl === (r.url || r.streamUrl) && !audio.paused ? " playing" : ""}" style="--h:${hue(r.name)}" data-name="${esc(r.name)}" data-url="${esc(r.url || r.streamUrl)}" data-genre="${esc(r.genre || "")}">
  <div class="dot">${esc(r.name.replace(/[^\p{L}\p{N}]/gu, "").slice(0, 3).toUpperCase())}</div><div class="rt"><b>${esc(r.name)}</b><small>${esc(r.genre || "Internet radio")}</small></div><span class="eq"><i></i><i></i><i></i></span></button>`;
audio.addEventListener("play", () => {
  const n = $("#now-name").textContent; $("#now-art").style.setProperty("--h", hue(n));
});

/* ---- song title on the radio player ("now playing"), for stations that publish it in their stream */
let nowGenre = "", nowTimer = null;
async function pollNow() {
  clearTimeout(nowTimer);
  if (!playingUrl || audio.paused || albumQ) return;
  const url = playingUrl;
  const n = await api(`/api/radio/now?url=${encodeURIComponent(url)}`);
  if (url !== playingUrl) return;
  $("#now-sub").innerHTML = n.title ? `<span class="np">♪ ${esc(n.artist ? `${n.artist} — ${n.title}` : n.title)}</span>` : `Live · ${esc(nowGenre || "radio")}`;
  nowTimer = setTimeout(pollNow, 20000);
}
audio.addEventListener("play", () => pollNow());

/* ---- albums: 1st tap plays a random song of the album right here (then the rest, shuffled); 2nd tap opens the album */
let albumQ = null;   // { id, songs, i }
const shuffle = (a) => { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
function markAlbum() {
  document.querySelectorAll(".poster[data-nd-album]").forEach((p) => p.classList.toggle("on", !!albumQ && p.dataset.ndAlbum === albumQ.id));
}
function showSong() {
  const s = albumQ.songs[albumQ.i];
  if (!s) return;
  $("#now-name").textContent = s.title;
  $("#now-sub").textContent = [s.artist, s.album].filter(Boolean).join(" · ");
  if ("mediaSession" in navigator && window.MediaMetadata) {
    navigator.mediaSession.metadata = new MediaMetadata({ title: s.title, artist: s.artist, album: s.album,
      artwork: [{ src: new URL(s.image, location.href).href, sizes: "400x400" }] });
  }
}
function startAudio(url) {
  audio.src = url; playingUrl = url; audio.volume = Number($("#vol").value);
  audio.play().catch(() => { $("#now-sub").textContent = "Tap ▶ to start"; });
  player.classList.add("show", "album"); markPlaying(); markAlbum();
}
function nextSong(step = 1) {
  if (!albumQ || !albumQ.songs.length) return;
  albumQ.i = (albumQ.i + step + albumQ.songs.length) % albumQ.songs.length;
  startAudio(`/api/nd/stream/${encodeURIComponent(albumQ.songs[albumQ.i].id)}`);
  showSong();
}
function playAlbum(id, poster) {
  // the sound must start inside the tap (iPhone rule), so the server picks the random song from n, and we
  // fetch the track list in parallel to know which one it is and to queue the rest
  const n = Number(Math.random().toFixed(6));   // same value the server sees
  albumQ = { id, songs: [], i: 0 };
  $("#now-name").textContent = poster.querySelector(".t")?.textContent || "Album";
  $("#now-sub").textContent = "Loading…";
  startAudio(`/api/nd/album/${encodeURIComponent(id)}/play?n=${n.toFixed(6)}`);
  poster.classList.add("loading");
  api(`/api/nd/album/${encodeURIComponent(id)}`).then((d) => {
    if (!albumQ || albumQ.id !== id) return;
    const songs = d.songs || [];
    if (!songs.length) { toast(d.error || "No playable songs in this album"); return; }
    const first = songs[Math.min(songs.length - 1, Math.floor(n * songs.length))];
    albumQ.songs = [first, ...shuffle(songs.filter((s) => s !== first))];
    showSong();
  }).finally(() => poster.classList.remove("loading"));
}
audio.addEventListener("ended", () => { if (albumQ) nextSong(1); });
$("#next").onclick = () => nextSong(1);
if ("mediaSession" in navigator) {
  try {
    navigator.mediaSession.setActionHandler("nexttrack", () => nextSong(1));
    navigator.mediaSession.setActionHandler("previoustrack", () => nextSong(-1));
  } catch { /* older browsers */ }
}
document.addEventListener("click", (e) => {
  const p = e.target.closest(".poster[data-nd-album]");
  if (!p || e.metaKey || e.ctrlKey) return;
  if (albumQ && albumQ.id === p.dataset.ndAlbum) return;   // already this album: this tap opens it
  e.preventDefault();
  playAlbum(p.dataset.ndAlbum, p);
}, true);

/* ---- small message at the bottom of the screen */
function toast(msg) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove("show"), 3200);
}

/* ------------------------------------------------------------ live TV (persistent player) */
const tvDock = $("#tv-dock");
let tvHls = null, tvNow = null;
function syncTvDock() {
  if (!tvNow) { tvDock.hidden = true; return; }
  tvDock.hidden = false;
  const ph = $(".media-stage");
  if (ph) {
    const r = ph.getBoundingClientRect();
    tvDock.classList.add("big"); tvDock.classList.remove("mini");
    Object.assign(tvDock.style, { top: `${r.top}px`, left: `${r.left}px`, width: `${r.width}px`, height: `${r.height}px` });
  } else { tvDock.classList.add("mini"); tvDock.classList.remove("big"); tvDock.style.cssText = ""; }
}
addEventListener("scroll", () => requestAnimationFrame(syncTvDock), { passive: true });
addEventListener("resize", () => requestAnimationFrame(syncTvDock));
async function playTV(id) {
  const r = await api(`/api/tv/play/${id}`);
  if (r.error) return;
  tvNow = { id, name: r.name };
  if (!tvDock.querySelector("video")) {
    tvDock.innerHTML = "";
    tvDock.innerHTML = `<div class="dock-bar tv-bar"><a href="#tv"><b>●</b> <span id="tv-name"></span></a><button id="tv-x" title="Close">✕</button></div>
      <video id="tv-video" controls autoplay playsinline></video><div class="tv-msg" id="tv-msg"></div>
      <button class="tv-cc" id="tv-cc" title="Sous-titres" aria-pressed="false">CC</button>`;
    $("#tv-x").onclick = () => { tvHls?.destroy(); tvHls = null; tvNow = null; tvDock.innerHTML = ""; syncTvDock(); markTv(); };
  }
  if (!audio.paused) $("#stop").click();   // one sound at a time
  $("#tv-name").textContent = r.name; $("#tv-msg").textContent = "Loading…"; $("#tv-msg").hidden = false;
  const v = $("#tv-video");
  v.onplaying = () => { $("#tv-msg").hidden = true; };
  // subtitles: on when the CC button is on (remembered) OR the sound is muted in the player.
  // The iPhone's volume buttons / silent switch can't be seen by a web page, hence the CC button.
  const applySubs = () => {
    const on = store.get("hub-tv-cc", false) || v.muted || v.volume === 0;
    const btn = $("#tv-cc"); if (btn) { btn.classList.toggle("on", on); btn.setAttribute("aria-pressed", on); }
    if (tvHls) { tvHls.subtitleDisplay = on; if (on && tvHls.subtitleTrack < 0 && tvHls.subtitleTracks?.length) tvHls.subtitleTrack = Math.max(0, tvHls.subtitleTracks.findIndex((t) => /^fr/i.test(t.lang || ""))); }
    const tracks = [...v.textTracks].filter((t) => t.kind === "subtitles" || t.kind === "captions");
    const pick = Math.max(0, tracks.findIndex((t) => /^fr/i.test(t.language)));
    tracks.forEach((t, i) => { t.mode = on && i === pick ? "showing" : "disabled"; });
    return tracks.length + (tvHls?.subtitleTracks?.length || 0);
  };
  v.onvolumechange = applySubs;
  v.onloadedmetadata = applySubs;            // started without sound (autoplay) -> subtitles right away
  v.textTracks.onaddtrack = applySubs;       // Safari adds the tracks after the metadata
  $("#tv-cc").onclick = () => {
    store.set("hub-tv-cc", !store.get("hub-tv-cc", false));
    if (!applySubs() && store.get("hub-tv-cc", false)) { $("#tv-msg").hidden = false; $("#tv-msg").textContent = "Pas de sous-titres sur cette chaîne."; setTimeout(() => { $("#tv-msg").hidden = true; }, 3000); }
  };
  tvHls?.destroy(); tvHls = null;
  if (window.Hls && Hls.isSupported()) {
    // Stable first: hls.js picks the quality from the measured speed and can always step DOWN when the connection
    // weakens (before, the top quality was forced as a manual level, so ABR was off and weak links froze), and it
    // starts high on a good link. It stays a few segments behind live so short hiccups don't freeze the picture.
    tvHls = new Hls({ subtitleDisplay: false, lowLatencyMode: false, backBufferLength: 30, capLevelToPlayerSize: false,
      abrEwmaDefaultEstimate: 5e6, startLevel: -1, liveSyncDurationCount: 4, maxBufferLength: 30, maxMaxBufferLength: 60,
      fragLoadPolicy: { default: { maxTimeToFirstByteMs: 10000, maxLoadTimeMs: 30000,
        timeoutRetry: { maxNumRetry: 4, retryDelayMs: 0, maxRetryDelayMs: 0 },
        errorRetry: { maxNumRetry: 6, retryDelayMs: 1000, maxRetryDelayMs: 8000 } } } });
    tvHls.on(Hls.Events.SUBTITLE_TRACKS_UPDATED, applySubs);
    let fails = 0;
    tvHls.on(Hls.Events.FRAG_LOADED, () => { fails = 0; });
    tvHls.on(Hls.Events.ERROR, (_, e) => {
      if (!e.fatal) return;
      const hls = tvHls;
      if (++fails <= 6 && e.type === Hls.ErrorTypes.NETWORK_ERROR) {   // connection dropped: try again, without giving up
        $("#tv-msg").hidden = false; $("#tv-msg").textContent = "Connexion instable — reconnexion…";
        setTimeout(() => { if (tvHls === hls) hls.startLoad(); }, Math.min(1000 * fails, 5000));
      } else if (fails <= 6 && e.type === Hls.ErrorTypes.MEDIA_ERROR) {
        hls.recoverMediaError();
      } else { $("#tv-msg").hidden = false; $("#tv-msg").textContent = "This channel is off the air right now — try another one."; }
    });
    tvHls.loadSource(r.src); tvHls.attachMedia(v);
  } else {   // Safari / iPhone play HLS natively: if the stream drops, reload it (a few times)
    v.src = r.src; let tries = 0;
    v.onerror = () => { if (++tries <= 4 && tvNow?.id === id) setTimeout(() => { v.src = r.src; v.play().catch(() => {}); }, 1500 * tries); };
  }
  v.play().catch(() => {});
  store.set("hub-tv-last", id); syncTvDock(); markTv();
}
function markTv() {
  document.querySelectorAll(".ch").forEach((c) => c.classList.toggle("on", !!tvNow && tvNow.id === +c.dataset.ch && !tvNow.yt));
  document.querySelectorAll(".vid").forEach((c) => c.classList.toggle("on", !!tvNow && tvNow.yt === c.dataset.yt));
}
/* YouTube videos share the same persistent player (one video at a time) */
function playYT(vid, title) {
  tvHls?.destroy(); tvHls = null;
  if (!audio.paused) $("#stop").click();
  tvNow = { id: -1, yt: vid, name: title };
  const from = location.hash || "#sport";
  tvDock.innerHTML = `<div class="dock-bar tv-bar"><a href="${esc(from)}"><b>▶</b> <span>${esc(title)}</span></a><button id="tv-x" title="Close">✕</button></div>
    <iframe class="yt-frame" id="yt-frame" src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(vid)}?autoplay=1&rel=0&modestbranding=1&playsinline=1&enablejsapi=1&hl=fr&cc_lang_pref=fr&cc_load_policy=1&origin=${encodeURIComponent(location.origin)}"
      referrerpolicy="strict-origin-when-cross-origin" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen title="${esc(title)}"></iframe>`;
  ytCaptions = true;
  $("#yt-frame").onload = () => [0, 1500, 4000].forEach((ms) => setTimeout(() => ytSend({ event: "listening", id: "hub" }), ms));
  $("#tv-x").onclick = () => { tvNow = null; tvDock.innerHTML = ""; syncTvDock(); markTv(); };
  syncTvDock(); markTv();
}
/* captions: on when the sound is muted or at 0, off again when it comes back (YouTube's iframe messages) */
let ytCaptions = null;
const ytSend = (msg) => $("#yt-frame")?.contentWindow?.postMessage(JSON.stringify(msg), "*");
addEventListener("message", (e) => {
  if (!/youtube(-nocookie)?\.com$/.test(new URL(e.origin).hostname)) return;
  let d; try { d = JSON.parse(e.data); } catch { return; }
  const info = d?.info; if (!info || (info.muted === undefined && info.volume === undefined)) return;
  const quiet = !!info.muted || info.volume === 0;
  if (quiet === ytCaptions) return;
  ytCaptions = quiet;
  if (quiet) {
    ytSend({ event: "command", func: "loadModule", args: ["captions"] });
    ytSend({ event: "command", func: "setOption", args: ["captions", "track", { languageCode: "fr" }] });
  } else ytSend({ event: "command", func: "unloadModule", args: ["captions"] });
});
document.addEventListener("click", (e) => {
  const v = e.target.closest(".vid"); if (!v) return;
  if (v.dataset.noembed) return;   // this channel only allows its videos on YouTube: the link opens YouTube
  e.preventDefault(); playYT(v.dataset.yt, v.dataset.title);
  $(".media-stage")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
// the server marks the sentences that answer the headline: they are shown in bold
const rdText = (b) => b.s ? b.s.map(([s, hl]) => hl ? `<strong class="hl">${esc(s)}</strong>` : esc(s)).join(" ") : esc(b.x);
/* ---- in-app reader: articles open inside the app, never in another site */
document.addEventListener("click", async (e) => {
  const a = e.target.closest("a.art-card"); if (!a) return;
  e.preventDefault();
  let rd = $("#reader");
  if (!rd) { rd = document.createElement("div"); rd.id = "reader"; rd.className = "reader"; document.body.appendChild(rd); }
  rd.innerHTML = `<div class="reader-bar"><button class="btn ghost" id="rd-back">← Back</button></div><article class="reader-page"><div class="skeleton"></div></article>`;
  rd.classList.add("open"); document.body.classList.add("reading"); rd.scrollTop = 0;
  const close = () => { rd.classList.remove("open"); document.body.classList.remove("reading"); };
  $("#rd-back").onclick = close;
  const r = await api(`/api/read?url=${encodeURIComponent(a.href)}`);
  const meta = a.querySelector(".art-meta")?.innerHTML || "";
  const title = r.title || a.querySelector("h3")?.textContent || "";
  const summary = a.querySelector("p")?.textContent || "";
  rd.querySelector(".reader-page").innerHTML = `<div class="art-meta">${meta}</div><h1>${esc(title)}</h1>
    ${r.image ? `<img class="reader-img" src="${esc(r.image)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
    ${r.error || r.detail ? `<p class="lead">${esc(summary)}</p><div class="empty">This newspaper doesn't let its articles be read outside its site.</div>` :
      (r.blocks || []).map((b) => b.t === "p" ? `<p>${rdText(b)}</p>` : b.t === "li" ? `<p class="li">• ${rdText(b)}</p>` : b.t === "blockquote" ? `<blockquote>${esc(b.x)}</blockquote>` : `<h3>${esc(b.x)}</h3>`).join("")}
    ${r.short ? `<div class="empty">This article is reserved for the newspaper's subscribers — only the beginning is available.</div>` : ""}`;
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#rd-back")?.click(); });

/* ---- AI recap blocks: text + images, plus the week's videos (after the news) and an interactive 3D model (after the showcase) */
function recapSection(s, rc) {
  const item = (i) => `<div class="recap-item${i.image ? " has-img" : ""}">${i.image ? `<img class="recap-img" src="${esc(i.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.classList.remove('has-img');this.remove()">` : ""}<div><h3>${esc(i.title)}</h3><p>${esc(i.text)}</p>${i.source ? `<span class="recap-src">${esc(i.source)}</span>` : ""}</div></div>`;
  let html = `<section class="recap-sec"><h2>${esc(s.title)}</h2><div class="recap-items">${(s.items || []).map(item).join("")}</div></section>`;
  if (s.id === "news" && rc.videos?.length) {
    html += `<section class="recap-sec"><h2>À regarder</h2><div class="tv-stage media-stage"><div class="tv-hint">Choisis une vidéo</div></div><div class="vid-grid">${rc.videos.map((v) =>
      videoCard({ id: v.youtube_id, title: v.title, channel: v.why || "", published: "", thumb: `https://i.ytimg.com/vi/${v.youtube_id}/hqdefault.jpg` })).join("")}</div></section>`;
  }
  if (s.id === "showcase" && rc.model3d?.embed) {
    html += `<section class="recap-sec"><h2>En 3D <small>fais-le tourner</small></h2><div class="model3d"><iframe src="${esc(rc.model3d.embed)}?autostart=1&ui_infos=0&ui_watermark=0" allow="autoplay; fullscreen; xr-spatial-tracking" allowfullscreen title="${esc(rc.model3d.title || "3D")}"></iframe></div><p class="lead small"><b>${esc(rc.model3d.title || "")}</b> — ${esc(rc.model3d.text || "")}</p></section>`;
  }
  return html;
}

const timeAgo = (iso) => { if (!iso) return "trending"; const s = (Date.now() - new Date(iso)) / 1000; return s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : s < 86400 ? `${Math.round(s / 3600)} h` : s < 2592000 ? `${Math.round(s / 86400)} d` : `${Math.round(s / 2592000)} mo`; };
const fmtViews = (n) => !n ? "" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M views` : n >= 1e3 ? `${Math.round(n / 1e3)}k views` : `${n} views`;
const noEmbed = (v) => v.embed === false ? ` target="_blank" rel="noopener" data-noembed="1"` : "";
const ytBadge = (v) => v.embed === false ? `<span class="yt-only">↗ sur YouTube</span>` : "";
const videoCard = (v) => `<a class="vid${tvNow && tvNow.yt === v.id ? " on" : ""}" href="https://www.youtube.com/watch?v=${esc(v.id)}" data-yt="${esc(v.id)}" data-title="${esc(v.title)}"${noEmbed(v)}>
  <div class="vid-thumb"><img src="${esc(v.thumb)}" alt="" loading="lazy"><span class="vid-play">${ICON.play}</span>${ytBadge(v)}</div>
  <div class="vid-t">${esc(v.title)}</div><div class="vid-s">${esc(v.channel)} · ${timeAgo(v.published)}${v.views ? ` · ${fmtViews(v.views)}` : ""}</div></a>`;
document.addEventListener("click", (e) => { const c = e.target.closest(".ch"); if (c) { e.preventDefault(); playTV(+c.dataset.ch); $("#tv-stage")?.scrollIntoView({ behavior: "smooth", block: "nearest" }); } });

/* ------------------------------------------------------------ "Today" on the home page: weather, tasks, alarms, shopping, note */
const WMO = [[0, "☀️", "Clear"], [1, "🌤️", "Mostly clear"], [2, "⛅", "Partly cloudy"], [3, "☁️", "Cloudy"], [45, "🌫️", "Fog"], [48, "🌫️", "Fog"],
  [51, "🌦️", "Drizzle"], [53, "🌦️", "Drizzle"], [55, "🌦️", "Drizzle"], [56, "🌧️", "Freezing drizzle"], [57, "🌧️", "Freezing drizzle"],
  [61, "🌧️", "Light rain"], [63, "🌧️", "Rain"], [65, "🌧️", "Heavy rain"], [66, "🌧️", "Freezing rain"], [67, "🌧️", "Freezing rain"],
  [71, "🌨️", "Light snow"], [73, "🌨️", "Snow"], [75, "❄️", "Heavy snow"], [77, "🌨️", "Snow grains"], [80, "🌦️", "Showers"], [81, "🌧️", "Showers"],
  [82, "⛈️", "Violent showers"], [85, "🌨️", "Snow showers"], [86, "🌨️", "Snow showers"], [95, "⛈️", "Thunderstorm"], [96, "⛈️", "Thunderstorm, hail"], [99, "⛈️", "Thunderstorm, hail"]];
const wmo = (c) => WMO.find((w) => w[0] === c) || [c, "🌡️", ""];
const getCity = () => store.get("hub-city", null);
// no city chosen yet: use where the device is (asked once), Paris only if that is refused
const locate = () => new Promise((ok) => {
  if (!navigator.geolocation) return ok(null);
  navigator.geolocation.getCurrentPosition((p) => ok({ name: "My location", lat: +p.coords.latitude.toFixed(3), lon: +p.coords.longitude.toFixed(3), auto: true }),
    () => ok(null), { timeout: 10000, maximumAge: 3600e3 });
});

// tomorrow's rain: the amount (mm) and hours of rain are more reliable than the probability alone
const rainTomorrow = (d) => {
  const mm = d.precipitation_sum[1] || 0, h = d.precipitation_hours[1] || 0, pr = d.precipitation_probability_max[1] ?? 0;
  const wet = mm >= 1 || pr >= 50;
  return `${wet ? "☔" : "☂️"} ${mm >= 0.1 ? `rain ${mm.toFixed(mm < 10 ? 1 : 0)} mm${h ? ` over ${Math.round(h)} h` : ""} (${pr}%)` : `rain ${pr}%`}`;
};
async function weatherCard() {
  const box = $("#t-weather");
  if (!box) return;
  let c = getCity();
  if (!c) { c = (await locate()) || { name: "Paris", lat: 48.853, lon: 2.349 }; store.set("hub-city", c); }
  let w;
  try {
    w = await (await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${c.lat}&longitude=${c.lon}&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m&hourly=precipitation_probability,temperature_2m,weather_code&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,precipitation_hours,wind_speed_10m_max&forecast_days=2&timezone=auto`)).json();
  } catch { box.innerHTML = `<span class="eyebrow">Weather</span><p class="lead small">Weather unavailable right now.</p>`; return; }
  if (!$("#t-weather")) return;
  const [, ico, label] = wmo(w.current.weather_code);
  const nowIdx = w.hourly.time.findIndex((t) => new Date(t) > new Date()) || 0;
  const next = w.hourly.time.slice(nowIdx, nowIdx + 12);
  const rain = next.findIndex((_, i) => w.hourly.precipitation_probability[nowIdx + i] >= 50);
  const rainTxt = rain < 0 ? "No rain in the next 12 h" : `Rain likely around ${new Date(next[rain]).getHours()}:00 (${w.hourly.precipitation_probability[nowIdx + rain]}%)`;
  box.innerHTML = `<span class="eyebrow"><button class="linkish" id="t-city" title="Change city">📍 ${esc(c.name)}</button></span>
    <div class="wx-now"><span class="wx-ico">${ico}</span><div><div class="wx-t">${Math.round(w.current.temperature_2m)}°</div>
      <small>${esc(label)} · feels ${Math.round(w.current.apparent_temperature)}°</small></div></div>
    <p class="wx-line">↑ ${Math.round(w.daily.temperature_2m_max[0])}° ↓ ${Math.round(w.daily.temperature_2m_min[0])}° · wind ${Math.round(w.current.wind_speed_10m)} km/h</p>
    <p class="wx-line ${rain < 0 ? "" : "warn"}">${rain < 0 ? "☂️ " : "☔ "}${esc(rainTxt)}</p>
    <div class="wx-tomorrow"><span class="eyebrow">Tomorrow</span>
      <div><span class="wx-ico sm">${wmo(w.daily.weather_code[1])[1]}</span>
        <div><b>${Math.round(w.daily.temperature_2m_max[1])}° / ${Math.round(w.daily.temperature_2m_min[1])}°</b>
          <small>${esc(wmo(w.daily.weather_code[1])[2])} · ${rainTomorrow(w.daily)} · wind ${Math.round(w.daily.wind_speed_10m_max[1])} km/h</small></div></div></div>
    <div class="wx-hours">${[0, 3, 6, 9].map((k) => { const i = nowIdx + k; return `<span><small>${new Date(w.hourly.time[i]).getHours()}h</small>${wmo(w.hourly.weather_code[i])[1]}<b>${Math.round(w.hourly.temperature_2m[i])}°</b></span>`; }).join("")}</div>`;
  $("#t-city").onclick = () => {
    box.innerHTML = `<span class="eyebrow">Your city</span><form id="t-city-form" class="t-city"><input placeholder="e.g. Lyon" autocomplete="off" enterkeyhint="search"><button class="btn accent">OK</button></form><button class="btn ghost" id="t-loc">📍 Use my location</button><small id="t-city-err" class="lead small"></small>`;
    const f = $("#t-city-form"); f.querySelector("input").focus();
    $("#t-loc").onclick = async () => {
      const loc = await locate();
      if (!loc) { $("#t-city-err").textContent = "Location not allowed. Type your city instead."; return; }
      store.set("hub-city", loc); weatherCard();
    };
    f.onsubmit = async (e) => {
      e.preventDefault();
      const q = f.querySelector("input").value.trim();
      if (!q) return weatherCard();
      try {
        const g = await (await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=1&language=fr`)).json();
        const r = g.results?.[0];
        if (!r) { $("#t-city-err").textContent = "City not found."; return; }
        store.set("hub-city", { name: r.name, lat: r.latitude, lon: r.longitude });
      } catch { $("#t-city-err").textContent = "Can't search right now."; return; }
      weatherCard();
    };
  };
}

async function todayPanel() {
  const box = $("#today");
  if (!box) return;
  box.innerHTML = `<div class="today">
    <div class="t-card wx" id="t-weather"><span class="eyebrow">Weather</span><div class="skeleton small"></div></div>
    <div class="t-card" id="t-tasks"><span class="eyebrow">To do</span><div class="skeleton small"></div></div>
    <div class="t-card" id="t-side"></div></div>`;
  weatherCard();
  if (!can("notetask")) { $("#t-tasks").remove(); $("#t-side").remove(); return; }
  const today = localDay(new Date());
  const [d, n] = await Promise.all([api("/api/tasks"), api(`/api/notes/${today}`)]);
  if (!$("#t-tasks")) return;
  const all = d.tasks || [], now = Date.now() / 1000;
  const todo = all.filter((t) => !t.done && (t.list || "todo") === "todo");
  const shop = all.filter((t) => !t.done && t.list === "shopping");
  const alarms = todo.flatMap((t) => t.reminders.filter((r) => r.sent === 0).map((r) => ({ ...r, text: t.text }))).sort((a, b) => a.due - b.due);
  const late = todo.filter((t) => t.reminders.some((r) => isMissed(r, t)));
  const doneToday = all.filter((t) => t.done && t.done_at && localDay(new Date(t.done_at * 1000)) === today).length;
  $("#t-tasks").innerHTML = `<a class="eyebrow" href="#tasks">To do <b>${todo.length}</b>${doneToday ? ` · ${doneToday} done today` : ""} ${ICON.arrow}</a>
    ${todo.length ? `<ul class="t-list">${todo.slice(0, 5).map((t) => `<li class="${late.includes(t) ? "late" : ""}"><button class="tick" data-ttick="${t.id}" aria-label="Mark as done"></button><span>${esc(t.text)}</span></li>`).join("")}</ul>
      ${todo.length > 5 ? `<a class="more" href="#tasks">+ ${todo.length - 5} more</a>` : ""}`
      : `<p class="lead small">Nothing to do. ${doneToday ? "Well done!" : ""}</p>`}
    <form class="t-quick" id="t-quick"><input placeholder="Quick add a task…" maxlength="500" enterkeyhint="done"><button class="icon-btn small" aria-label="Add">+</button></form>`;
  $("#t-side").innerHTML = `
    <a class="t-mini" href="#tasks"><span class="eyebrow">Next alarm</span>${alarms[0] ? `<b>⏰ ${esc(alarms[0].repeat ? "every day " + hhmm(alarms[0].due) : fmtDue(alarms[0].due))}</b><span>${esc(alarms[0].text)}</span>` : `<span>No alarm set</span>`}</a>
    <a class="t-mini" href="#tasks" data-golist="shopping"><span class="eyebrow">Shopping</span>${shop.length ? `<b>${shop.length} item${shop.length > 1 ? "s" : ""}</b><span>${esc(shop.slice(0, 4).map((t) => t.text).join(", "))}</span>` : `<span>List is empty</span>`}</a>
    <a class="t-mini" href="#notes"><span class="eyebrow">Today's note</span>${(n.body || "").trim() ? `<span class="clamp">${esc(n.body.trim().slice(0, 140))}</span>` : `<span>✏️ Write today's note</span>`}</a>`;
  $("#t-tasks").onclick = async (e) => {
    const b = e.target.closest("[data-ttick]"); if (!b) return;
    b.closest("li").classList.add("done");
    await api(`/api/tasks/${b.dataset.ttick}`, { method: "PATCH", body: JSON.stringify({ done: true }) });
    setTimeout(todayPanel, 400);
  };
  $("#t-quick").onsubmit = async (e) => {
    e.preventDefault();
    const inp = e.target.querySelector("input"), text = inp.value.trim();
    if (!text) return;
    await api("/api/tasks", { method: "POST", body: JSON.stringify({ text, list: "todo" }) });
    todayPanel();
  };
  $("#t-side").querySelectorAll("[data-golist]").forEach((a) => a.onclick = () => store.set("hub-task-list", a.dataset.golist));
  $("#t-side").querySelector('a[href="#tasks"]:not([data-golist])').onclick = () => store.set("hub-task-list", "todo");
  $("#t-tasks").querySelectorAll('a[href="#tasks"]').forEach((a) => a.addEventListener("click", () => store.set("hub-task-list", "todo")));
}

/* ------------------------------------------------------------ pages */
const EMPTY_VIDEO = `<div class="empty">Nothing here yet. Drop video files into <code>C:\\Media\\_Inbox</code> (or its <code>Movies</code>, <code>TV</code>, <code>Documentaries</code>, <code>Education</code>, <code>Personal</code> sub-folders) and the organizer files them into Jellyfin. A good legal start: the public-domain films on <a href="#discover">Discover</a>.</div>`;
const EMPTY_MUSIC = `<div class="empty">No local music yet. Put albums in <code>C:\\Media\\_Inbox\\Music</code>. Free, legal sources: Jamendo, Free Music Archive, Bandcamp free downloads.</div>`;

/* ---- "right now on the big channels": the most interesting programme of each channel */
async function onAirBox() {
  const box = $("#onair"); if (!box) return;
  const d = await api("/api/tv/onair");
  if (!$("#onair") || !d.now?.length) return;
  d.now = d.now.filter(okTV); d.next = (d.next || []).filter(okTV);   // nothing paid
  const pct = (g) => Math.min(100, Math.max(0, (Date.now() - new Date(g.start)) / (new Date(g.stop) - new Date(g.start)) * 100));
  const t = (iso) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const card = (g) => `<div class="oa${g.free ? "" : " paid"}">${g.img ? `<img src="${esc(g.img)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
    <div class="oa-body"><span class="oa-ch">${esc(g.channel)} · ${esc(g.kind)}</span><b>${esc(g.title)}</b><small>${esc(g.sub || g.desc)}</small>
    <div class="oa-bar"><i style="width:${pct(g).toFixed(0)}%"></i></div><span class="oa-t">${t(g.start)} – ${t(g.stop)}</span>
    ${g.free ? `<a class="btn small ch" href="#tv" data-ch="${g.tv_id}">${ICON.play} Regarder</a>` : `<a class="btn small" href="${esc(g.web)}" target="_blank" rel="noopener">↗ Free TV</a>`}</div></div>`;
  $("#onair").innerHTML = `<h2>En ce moment sur les grandes chaînes <small>le plus intéressant d'abord</small></h2><div class="oa-row">${d.now.slice(0, 12).map(card).join("")}</div>` +
    (d.next?.length ? `<h3 class="mc-day">Juste après</h3><div class="epg">${d.next.slice(0, 8).map((g) => `<div class="epg-row"><span class="epg-time">${t(g.start)}</span><div class="epg-main"><b>${esc(g.title)}</b><span>${esc(g.kind)}</span></div><span class="epg-ch">${esc(g.channel)}</span>${g.free ? `<a class="btn small ch epg-play" href="#tv" data-ch="${g.tv_id}">${ICON.play}</a>` : ""}</div>`).join("")}</div>` : "");
}

/* ---- free to watch: in the hub, or TF1/M6 groups in the Free TV app (Freebox subscription). Paid channels are hidden. */
const okTV = (g) => g && (g.free || !!g.web);

/* ---- sport: TV guide row (▶ when the channel is in the hub) */
function epgRow(g) {
  const t = (iso) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const day = localDay(new Date(g.start)) === localDay(new Date()) ? "" : new Date(g.start).toLocaleDateString("fr-FR", { weekday: "short" }) + " ";
  const play = g.free ? `<a class="btn small ch epg-play" href="#sport" data-ch="${g.tv_id}">${ICON.play} Regarder</a>` : `<a class="btn small epg-play" href="${esc(g.web)}" target="_blank" rel="noopener">↗ Free TV</a>`;
  return `<div class="epg-row${g.live ? " live" : ""}"><span class="epg-time">${g.live ? `<b class="live-dot">●</b> ` : ""}${esc(day + t(g.start))}</span>
    <div class="epg-main"><b>${SPORT_ICO[g.sport] || "🏟️"} ${esc(g.title)}</b><span>${esc(g.sub || g.desc || "")}</span></div>
    <span class="epg-ch">${esc(g.channel)}</span>${play}</div>`;
}

/* ---- sport: score cards (foot, basket, tennis, F1) */
const SPORT_NAME = { foot: "Foot", basket: "Basket", tennis: "Tennis", rugby: "Rugby", hand: "Handball", volley: "Volley", pingpong: "Ping-pong", darts: "Fléchettes",
  padel: "Padel", f1: "F1", moteur: "Moto & auto", velo: "Cyclisme", combat: "Boxe & MMA", nfl: "Foot US", hockey: "Hockey", athle: "Athlé & natation", hiver: "Ski & hiver", golf: "Golf", autre: "Autres" };
const SPORT_ICO = { "": "🏟️", foot: "⚽", basket: "🏀", tennis: "🎾", rugby: "🏉", hand: "🤾", volley: "🏐", pingpong: "🏓", darts: "🎯", padel: "🥎", f1: "🏎️",
  moteur: "🏍️", velo: "🚴", combat: "🥊", nfl: "🏈", hockey: "🏒", athle: "🏃", hiver: "⛷️", golf: "⛳", autre: "🏟️" };
function matchCard(m) {
  const when = new Date(m.date).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const st = m.state === "in" ? `<b class="live-dot">●</b> ${esc(m.detail || "en cours")}` : m.state === "pre" ? esc(when) : "Terminé";
  const side = (t) => `<div class="mc-t">${t.logo ? `<img src="${esc(t.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<i></i>`}
    <span title="${esc(t.full)}">${esc(t.name || t.full)}</span>${m.state === "pre" ? "" : `<b>${esc(t.score)}</b>`}</div>`;
  const body = m.sport === "f1"
    ? `<div class="mc-f1"><b>${esc(m.gp)}</b><span>${esc(m.session)}</span>${m.podium?.length ? `<small>🏆 ${m.podium.map(esc).join(" · ")}</small>` : ""}</div>`
    : side(m.home) + side(m.away);
  const tv = okTV(m.tv) ? `<div class="mc-tv">📺 <b>${esc(m.tv.channel)}</b>${m.tv.free ? ` <a class="btn small ch" href="#sport" data-ch="${m.tv.tv_id}">${ICON.play} Regarder ici</a>`
    : ` <a class="btn small" href="${esc(m.tv.web)}" target="_blank" rel="noopener">↗ Free TV</a>`}</div>` : "";
  return `<div class="mc ${m.state}${m.big ? " big" : ""}${m.tv?.free ? " on-tv" : ""}"><div class="mc-top"><span>${SPORT_ICO[m.sport] || ""} ${esc(m.league)}</span><span class="mc-st">${st}</span></div>${body}${tv}</div>`;
}
const pages = {
  async home() {
    const hour = new Date().getHours();
    const greet = hour < 5 ? "Late night" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    const date = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
    view.innerHTML = `<section class="hero plain" id="hero"><div class="hero-txt">
        <span class="kicker">${esc(date)}</span><h1>${greet}.</h1>
        <p>Films, live TV, music, radio and books — one place, yours.</p></div></section>
      <div id="home-rows"><div class="skeleton" style="margin-top:28px"></div></div>`;
    const [d] = await Promise.all([api("/api/home"), loadCatalog()]);
    const favs = CATALOG.entries.filter((e) => FAVS.has(e.id));

    // hero: a rotating mix of what's fresh — sport live, then the news
    const [sl, nw] = await Promise.all([can("sport") ? api("/api/sport/live") : {}, can("journal") ? api("/api/news") : {}]);
    const ess = (nw.essentials || []).filter((s) => s.image);
    const st = (sl.streams || [])[0], bg = (sl.big_live || [])[0];
    const feats = [
      st && { kind: "sport", kicker: `${SPORT_NAME[st.sport] || "Sport"} · EN DIRECT`, title: st.title, text: `${sl.streams.length} direct${sl.streams.length > 1 ? "s" : ""} gratuit${sl.streams.length > 1 ? "s" : ""} — ${st.channel}`, img: st.thumb.replace("hqdefault", "maxresdefault"), href: "#sport" },
      bg && ess[0] && { kind: "sport", kicker: `${bg.league} · EN DIRECT`, title: `${bg.home.full} ${bg.home.score} – ${bg.away.score} ${bg.away.full}`, text: bg.detail, img: ess[0].image, href: "#sport" },
      ess[0] && { kind: "news", kicker: `À la une · ${ess[0].count} journaux`, title: ess[0].title, text: ess[0].summary, img: ess[0].image, link: ess[0].link },
      ess[1] && { kind: "news", kicker: `Actu · ${ess[1].count} journaux`, title: ess[1].title, text: ess[1].summary, img: ess[1].image, link: ess[1].link },
      ess[2] && { kind: "news", kicker: `Actu · ${ess[2].count} journaux`, title: ess[2].title, text: ess[2].summary, img: ess[2].image, link: ess[2].link },
    ].filter(Boolean);
    if (feats.length) {
      const hero = $("#hero"); hero.classList.remove("plain");
      hero.innerHTML = feats.map((f, i) => `<div class="hero-bg${i ? "" : " on"}" style="--bgimg:url('${esc(f.img)}')"></div>`).join("") +
        `<div class="hero-txt" id="hero-txt"></div>` +
        (feats.length > 1 ? `<div class="hero-dots">${feats.map((_, i) => `<button data-i="${i}" class="${i ? "" : "on"}" aria-label="Slide ${i + 1}"></button>`).join("")}</div>` : "");
      let cur = 0;
      const show = (i) => {
        cur = i; const f = feats[i];
        hero.querySelectorAll(".hero-bg").forEach((b, k) => b.classList.toggle("on", k === i));
        hero.querySelectorAll(".hero-dots button").forEach((b, k) => b.classList.toggle("on", k === i));
        const btn = f.kind === "news" ? `<a class="btn big art-card" href="${esc(f.link)}">Lire</a>`
          : `<a class="btn big" href="${f.href}">${ICON.play} Voir le direct</a>`;
        const more = f.kind === "news" ? `<a class="btn big ghost" href="#journal">Le Journal</a>` : "";
        $("#hero-txt").innerHTML = `<span class="kicker"><b>●</b> ${esc(f.kicker)}</span>
          <h1 id="hero-title" class="${f.title.length > 70 ? "long" : ""}">${esc(f.title)}</h1>
          ${f.text ? `<p>${esc(f.text)}</p>` : ""}<div class="hero-btns">${btn}${more}</div>`;
        splitWords($("#hero-title"));
      };
      show(0);
      hero.querySelector(".hero-dots")?.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) show(+b.dataset.i); });
      clearInterval(window.__heroTimer);
      if (feats.length > 1) window.__heroTimer = setInterval(() => { if (!document.body.contains(hero)) return clearInterval(window.__heroTimer); show((cur + 1) % feats.length); }, 8000);
    } else splitWords($("#hero h1"));

    const R = CATALOG.radios.length;
    if (can("tv")) api("/api/tv/channels").then((t) => { const el = $("#tv-count"); if (el && t.channels) el.firstChild.textContent = t.channels.length; });
    checkSport();
    api("/api/weekly").then((w) => {
      const box = $("#weekly"); if (!box || !w.items || !w.items.length) return;
      box.innerHTML = `<h2>This week <small>${esc(w.week || "")} · curated by Claude</small></h2>${w.headline ? `<p class="lead">${esc(w.headline)}</p>` : ""}
        <ol class="weekly">${w.items.map((i) => `<li><span class="tag">${esc(i.kind || "")}</span><div><b>${i.link ? `<a href="${esc(i.link)}" target="_blank" rel="noopener">${esc(i.title)}</a>` : esc(i.title)}</b><p>${esc(i.text || "")}</p></div></li>`).join("")}</ol>`;
    });
    $("#home-rows").innerHTML =
      `<div id="today"></div><div class="bento">
        <a class="big tv-cell" href="#tv"${can("tv") ? "" : " hidden"}><span class="eyebrow">Live TV</span>
          <div><div class="num" id="tv-count">—<small>channels</small></div><b>Films, series, news & kids — free, no account.</b></div><span class="go">${ICON.arrow}</span></a>
        <a href="#listen"${can("listen") ? "" : " hidden"}><span class="eyebrow">Radio</span><div><div class="num">${R}<small>stations</small></div><b>NRJ, Skyrock, FIP…</b></div><span class="go">${ICON.arrow}</span></a>
      </div>` +
      `<div id="sport-banner"></div><div id="onair"></div><div id="weekly"></div>` +
      (can("listen") ? `<h2>On air <small><a href="#listen">all stations</a></small></h2><div class="radios strip">${CATALOG.radios.slice(0, 8).map(radioButton).join("")}</div>` : "") +
      row("Continue watching", d.resume) +
      row("Recently added", d.latest, {}, EMPTY_VIDEO) +
      row("Recently played music", d.recent_albums, { square: true }) +
      row("New albums", d.new_albums, { square: true }) +
      row("New podcast episodes", d.podcasts, { square: true }) +
      (favs.length ? `<h2>Your favorite free sites <small>${favs.length}</small></h2><div class="cards">${favs.map(entryCard).join("")}</div>`
        : `<h2>Free & legal streaming</h2><div class="empty">Browse <a href="#discover">Discover</a> and <a href="#learn">Learn</a> and tap ☆ to pin your favorite free services here.</div>`) +
      `<h2>Your apps</h2>${serviceTiles()}`;
    todayPanel();
  },

  async sport() {
    let s = store.get("hub-sport", "");
    if (!SPORT_NAME[s]) s = "";
    view.innerHTML = `<h1>Sport</h1><p class="lead">Les gros matchs en premier, les scores en direct, ce qui passe à la télé, et tous les directs gratuits et officiels. Mis à jour toutes les minutes.</p>
      <div class="filters" id="sp-chips">${[["", "Tout"], ...Object.entries(SPORT_NAME)].map(([k, n]) =>
        `<button class="chip${k === s ? " on" : ""}" data-s="${k}">${SPORT_ICO[k] || "🏟️"} ${esc(n)}</button>`).join("")}</div>
      <div class="tv-stage media-stage"><div class="tv-hint">Choisis un direct ou une chaîne</div></div><div id="sp"><div class="skeleton"></div></div>`;
    $("#sp-chips").onclick = (e) => { const b = e.target.closest("[data-s]"); if (b) { store.set("hub-sport", b.dataset.s); pages.sport(); } };
    syncTvDock();
    const d = await api(`/api/sport${s ? `?s=${s}` : ""}`);
    if (!$("#sp")) return;   // left the page meanwhile
    const lc = d.live_counts || {};
    $("#sp-chips").querySelectorAll("[data-s]").forEach((b) => {
      const n = b.dataset.s ? lc[b.dataset.s] || 0 : Object.values(lc).reduce((a, x) => a + x, 0);
      if (n) b.insertAdjacentHTML("beforeend", ` <span class="chip-live">● ${n}</span>`);
    });
    if (d.error) { $("#sp").innerHTML = `<div class="empty">Le sport ne répond pas pour l'instant (${esc(d.error)}). Réessaie dans une minute.</div>`; return; }
    const what = s ? SPORT_NAME[s].toLowerCase() : "sport";
    const liveCard = (v) => `<a class="vid live-vid" href="https://www.youtube.com/watch?v=${esc(v.id)}" data-yt="${esc(v.id)}" data-title="${esc(v.title)}"${noEmbed(v)}>
      <div class="vid-thumb"><img src="${esc(v.thumb)}" alt="" loading="lazy"><span class="live-badge">● LIVE</span><span class="vid-play">${ICON.play}</span>${ytBadge(v)}</div>
      <div class="vid-t">${esc(v.title)}</div><div class="vid-s">${SPORT_ICO[v.sport] || ""} ${esc(v.channel)}</div></a>`;
    const tvCard = (c) => `<a class="ch${tvNow && tvNow.id === c.id ? " on" : ""}" href="#sport" data-ch="${c.id}" title="${esc(c.name)}">
      <div class="ch-logo">${c.logo ? `<img src="${esc(c.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span>${esc(c.name.slice(0, 2).toUpperCase())}</span>`}</div>
      <div class="ch-name">${esc(c.name.replace(/ x Pluto TV$/, ""))}</div><div class="ch-sub">Live TV</div></a>`;
    const byDay = (list) => {
      const out = {}; list.forEach((m) => { (out[localDay(new Date(m.date))] ||= []).push(m); }); return out;
    };
    const today = localDay(new Date());
    const days = byDay(d.big || []);
    d.tv_now = (d.tv_now || []).filter(okTV); d.tv_next = (d.tv_next || []).filter(okTV);   // nothing paid
    $("#sp").innerHTML =
      // 0. on French TV right now, first: which channel shows which match (free ones play here)
      (d.tv_now?.length ? `<h2><span class="live-dot">●</span> À la télé en ce moment <small>${d.tv_now.length} retransmission${d.tv_now.length > 1 ? "s" : ""} · chaîne indiquée</small></h2><div class="epg">${d.tv_now.map(epgRow).join("")}</div>` : "") +
      // 1. free official streams, live now
      (d.streams?.length ? `<h2><span class="live-dot">●</span> En direct · gratuit <small>${d.streams.length} direct${d.streams.length > 1 ? "s" : ""}, ça se regarde ici</small></h2><div class="vid-grid">${d.streams.map(liveCard).join("")}</div>`
        : `<h2>En direct · gratuit</h2><div class="empty">Aucun direct gratuit en ${esc(what)} en ce moment. Les directs programmés sont plus bas. La page vérifie toute seule.</div>`) +
      // 2. live scores of the big competitions
      (d.live?.length ? `<h2><span class="live-dot">●</span> Scores en direct <small>${d.live.length} match${d.live.length > 1 ? "s" : ""}</small></h2><div class="mc-grid">${d.live.map(matchCard).join("")}</div>` : "") +
      // 3. the big matches coming up, day by day
      (Object.keys(days).length ? `<h2>Les gros matchs à venir</h2>` + Object.entries(days).map(([day, ms]) =>
        `<h3 class="mc-day">${esc(day === today ? "Aujourd'hui" : day === shiftDay(today, 1) ? "Demain" : new Date(`${day}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" }))}</h3><div class="mc-grid">${ms.map(matchCard).join("")}</div>`).join("") : "") +
      (d.friendlies?.length ? `<h2>Matchs amicaux <small>à part des compétitions</small></h2><div class="mc-grid">${d.friendlies.map(matchCard).join("")}</div>` : "") +
      (d.upcoming_streams?.length ? `<h2>Directs gratuits programmés</h2><ol class="weekly">${d.upcoming_streams.map((u) => `<li><span class="tag">${SPORT_ICO[u.sport] || ""} ${esc(SPORT_NAME[u.sport] || "")}</span><div><b>${esc(u.title)}</b><p>${esc(new Date(u.start).toLocaleString("fr-FR", { weekday: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }))} · ${esc(u.channel)}</p></div></li>`).join("")}</ol>` : "") +
      (d.tv_next?.length ? `<h2>À la télé bientôt <small>programme TV</small></h2><div class="epg">${d.tv_next.map(epgRow).join("")}</div>` : "") +
      (d.tv?.length ? `<h2>Chaînes sport <small>en direct dans le hub</small></h2><div class="tv-grid">${d.tv.map(tvCard).join("")}</div>` : "") +
      (d.results?.length ? `<h2>Derniers résultats</h2><div class="mc-grid">${d.results.map(matchCard).join("")}</div>` : "") +
      (d.replays?.length ? `<h2>Résumés & replays</h2><div class="vid-grid">${d.replays.slice(0, 16).map(videoCard).join("")}</div>` : "") +
      `<p class="lead small sp-note">Matchs sur TF1, M6, TMC, W9 : bouton « ↗ Free TV » (gratuit avec ta Freebox, connecte-toi avec ton compte Free).</p>`;
    const first = (d.streams || []).find((v) => v.embed !== false);
    if (first && !tvNow) playYT(first.id, first.title);   // start the first live
  },

  async sportmatch() {
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    view.innerHTML = `<a class="back-link" href="#sportrecap">← Résumé sport</a><div id="sm"><div class="skeleton"></div></div>`;
    const d = await api(`/api/sportrecap/match?path=${encodeURIComponent(q.get("p") || "")}&id=${encodeURIComponent(q.get("id") || "")}`);
    if (!$("#sm")) return;
    if (d.error || !d.teams?.length) { $("#sm").innerHTML = `<div class="empty">Résumé introuvable pour ce match.</div>`; return; }
    const [h, a] = d.teams;
    const team = (t) => `<div class="sm-team${t.winner ? " win" : ""}">${t.logo ? `<img src="${esc(t.logo)}" alt="" referrerpolicy="no-referrer">` : ""}<b>${esc(t.name)}</b></div>`;
    $("#sm").innerHTML = `<div class="sm-head"><span class="kicker">${esc(d.league)}${d.venue ? " · " + esc(d.venue) : ""}</span>
        <div class="sm-score">${team(h)}<div class="sm-num">${esc(h.score)}<i>–</i>${esc(a.score)}</div>${team(a)}</div><small>${esc(d.status)}</small></div>` +
      (d.photos?.length ? `<div class="sm-photos">${d.photos.map((u) => `<img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`).join("")}</div>` : "") +
      (d.key?.length ? `<h2>Les moments clés</h2><ol class="sm-key">${d.key.map((k) => `<li><span class="sm-t">${esc(k.t)}</span><b>${esc(k.kind)}</b> ${esc(k.who)}${k.team ? ` <small>${esc(k.team)}</small>` : ""}</li>`).join("")}</ol>` : "") +
      (d.videos?.length || d.yt?.length ? `<h2>En vidéo</h2><div class="sm-vids">${(d.videos || []).map((v) => `<figure><video controls preload="none" playsinline poster="${esc(v.thumb)}" src="${esc(v.src)}"></video><figcaption>${esc(v.title)}</figcaption></figure>`).join("")}</div>
        ${d.yt?.length ? `<div class="tv-stage media-stage"><div class="tv-hint">Résumé YouTube</div></div><div class="vid-grid">${d.yt.map(videoCard).join("")}</div>` : ""}` : "") +
      (d.blocks?.length ? `<h2>Le récit du match <small>l'essentiel en gras</small></h2>${d.headline ? `<h3 class="sm-hl">${esc(d.headline)}</h3>` : ""}<div class="reader-body sm-story">${d.blocks.map((b) => `<p>${rdText(b)}</p>`).join("")}</div>` : "") +
      (d.fr_articles?.length ? `<h2>Dans la presse française</h2><div class="rc-news">${d.fr_articles.map((x) =>
        `<a class="art-card rc-art" href="${esc(x.link)}">${x.image ? `<img src="${esc(x.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}<div><b>${esc(x.title)}</b><small>${esc(x.source_name || x.source || "")}</small></div></a>`).join("")}</div>` : "");
  },

  async sportrecap() {
    const date = new Date().toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
    view.innerHTML = `<h1>Résumé <em>sport</em></h1><p class="lead">Ce qu'il faut retenir des dernières 24 h, ${esc(date)} : les résultats, les résumés vidéo, l'actu, et ce qui passe ce soir.</p>
      <div class="tv-stage media-stage"><div class="tv-hint">Choisis un résumé vidéo</div></div><div id="rc"><div class="skeleton"></div></div>`;
    syncTvDock();
    const d = await api("/api/sportrecap");
    if (!$("#rc")) return;
    if (d.error) { $("#rc").innerHTML = `<div class="empty">Le résumé ne répond pas pour l'instant (${esc(d.error)}).</div>`; return; }
    const res = Object.entries(d.results || {});
    $("#rc").innerHTML =
      (d.headline ? `<div class="padel-banner rc-head"><span class="live-badge">À RETENIR</span><b>${esc(d.headline)}</b></div>` : "") +
      (res.length ? `<h2>Les résultats</h2><div class="rc-grid">${res.map(([k, ms]) => `<div class="panel rc-sport"><b>${k === "amical" ? "⚽ Matchs amicaux" : `${SPORT_ICO[k] || "🏟️"} ${esc(SPORT_NAME[k] || k)}`}</b>
        <ul>${ms.slice(0, 6).map((m) => m.path ? `<li><a class="rc-link" href="#sportmatch?p=${encodeURIComponent(m.path)}&id=${encodeURIComponent(m.id)}"><span>${esc(m.text)}</span><small>${esc(m.league)} · voir le résumé →</small></a></li>`
          : `<li><span>${esc(m.text)}</span><small>${esc(m.league)}</small></li>`).join("")}</ul></div>`).join("")}</div>`
        : `<div class="empty">Pas encore de gros résultat dans les dernières 24 h.</div>`) +
      (d.videos?.length ? `<h2>Résumés vidéo</h2><div class="vid-grid">${d.videos.map(videoCard).join("")}</div>` : "") +
      (d.tonight?.length ? `<h2>Ce soir à la télé</h2><div class="epg">${d.tonight.map(epgRow).join("")}</div>` : "") +
      (d.articles?.length ? `<h2>L'actu sport <small>L'Équipe, RMC Sport, franceinfo</small></h2><div class="rc-news">${d.articles.slice(0, 20).map((a) =>
        `<a class="art-card rc-art" href="${esc(a.link)}">${a.image ? `<img src="${esc(a.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}<div><b>${esc(a.title)}</b><small>${esc(a.source_name || a.source || "")} · ${esc(timeAgo(new Date(a.ts * 1000).toISOString()))}</small></div></a>`).join("")}</div>` : "");
  },

  async ai() {
    view.innerHTML = `<h1>Récap <em>IA</em></h1><p class="lead">Ton récap personnel de l'IA, écrit pour toi par Claude : les nouveautés, comment ça marche, avec quoi, et ce que les gens en font.</p>
      <div id="ai"><div class="skeleton"></div></div>`;
    const d = await api("/api/ai");
    const rc = d.recap || {};
    if (rc.sections) {
      $("#ai").innerHTML = `<article class="recap">
        <div class="recap-head"><span class="kicker">Semaine du ${esc(rc.date || "")}</span><h2 class="recap-title">${esc(rc.title || "")}</h2><p class="recap-intro">${esc(rc.intro || "")}</p></div>
        ${rc.sections.map((s) => recapSection(s, rc)).join("")}
        ${rc.sources?.length ? `<details class="recap-sources"><summary>Sources (${rc.sources.length})</summary><ul>${rc.sources.map((s) => `<li>${esc(s.name)}</li>`).join("")}</ul></details>` : ""}
      </article>`;
      return;
    }
    // no recap written yet: fall back to the filtered AI headlines (they open in the in-app reader)
    const ago = (ts) => { if (!ts) return ""; const m = Math.round((Date.now() / 1000 - ts) / 60); return m < 60 ? `${Math.max(m, 1)} min` : m < 1440 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`; };
    const card = (a, big) => `<a class="art-card${big ? " lead-story" : ""}${a.image ? "" : " noimg"}" href="${esc(a.link)}" target="_blank" rel="noopener">
        ${a.image ? `<div class="art-img"><img src="${esc(a.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.remove()"></div>` : ""}
        <div class="art-body"><div class="art-meta"><b>${esc(a.source_name)}</b><span>${esc(a.section)}</span><span>${ago(a.ts)}</span></div>
        <h3>${esc(a.title)}</h3>${a.summary ? `<p>${esc(a.summary)}</p>` : ""}</div></a>`;
    const arts = d.articles || [];
    const lead = arts.find((a) => a.image);
    const labs = arts.filter((a) => a.section === "Lab" || a.section === "Open source");
    const press = arts.filter((a) => a !== lead && !labs.includes(a));
    $("#ai").innerHTML = `<div class="empty">Ton premier récap est en cours de rédaction — en attendant, voici les titres IA du moment.</div>` + (lead ? card(lead, true) : "") +
      `<h2>From the labs <small>OpenAI · DeepMind · Hugging Face</small></h2><div class="news-grid">${labs.slice(0, 9).map((a) => card(a)).join("")}</div>` +
      `<h2>In the press</h2><div class="news-grid">${press.slice(0, 30).map((a) => card(a)).join("")}</div>`;
  },

  async journal() {
    view.innerHTML = `<h1>Le <em>Journal</em></h1><p class="lead">L'essentiel de l'actu à gauche, tous les articles à droite — mis à jour en continu.</p>
      <form class="news-search" id="nw-search" role="search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        <input id="nw-q" type="search" placeholder="Rechercher dans les infos : un nom, un pays, un sujet…" autocomplete="off"></form>
      <div class="journal-cols"><aside class="essentials" id="nw-ess"></aside>
        <div><div class="filters" id="nw-chips"></div><div id="nw"><div class="skeleton"></div></div></div></div>`;
    const d = await api("/api/news");
    let src = store.get("hub-news-src", "all"), q = "";
    const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    const agoE = (ts) => { if (!ts) return ""; const m = Math.round((Date.now() / 1000 - ts) / 60); return m < 60 ? `il y a ${Math.max(m, 1)} min` : `il y a ${Math.round(m / 60)} h`; };
    $("#nw-ess").innerHTML = `<div class="ess-head"><span class="kicker">L'essentiel</span><span class="ess-time">${new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span></div>` +
      ((d.essentials || []).map((s, i) => `<a class="ess art-card" href="${esc(s.link)}">
        <span class="ess-n">${String(i + 1).padStart(2, "0")}</span>
        <div><h3>${esc(s.title)}</h3>${s.summary ? `<p>${esc(s.summary)}</p>` : ""}
        <div class="ess-meta">${s.count} journaux · ${esc(s.sources.slice(0, 3).join(", "))}${s.sources.length > 3 ? "…" : ""} · ${agoE(s.ts)}</div></div></a>`).join("")
        || `<p class="lead small">Pas encore assez d'articles pour un récap.</p>`);
    const ago = (ts) => { if (!ts) return ""; const m = Math.round((Date.now() / 1000 - ts) / 60); return m < 60 ? `${Math.max(m, 1)} min` : m < 1440 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`; };
    const card = (a, big) => `<a class="art-card${big ? " lead-story" : ""}${a.image ? "" : " noimg"}" href="${esc(a.link)}" target="_blank" rel="noopener">
        ${a.image ? `<div class="art-img"><img src="${esc(a.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.remove()"></div>` : ""}
        <div class="art-body"><div class="art-meta"><b>${esc(a.source_name)}</b><span>${esc(a.section)}</span><span>${ago(a.ts)}</span></div>
        <h3>${esc(a.title)}</h3>${a.summary ? `<p>${esc(a.summary)}</p>` : ""}</div></a>`;
    const draw = () => {
      store.set("hub-news-src", src);
      $("#nw-chips").innerHTML = [`<button class="chip${src === "all" ? " on" : ""}" data-s="all">À la une</button>`,
        ...d.sources.filter((s) => d.items.some((i) => i.source === s.key)).map((s) => `<button class="chip${src === s.key ? " on" : ""}" data-s="${s.key}">${esc(s.name)}</button>`)].join("");
      let items = src === "all" ? d.items : d.items.filter((i) => i.source === src);
      if (q) {   // search: every word must appear in the title or summary (accents ignored)
        const words = norm(q).split(/\s+/).filter(Boolean);
        items = items.filter((i) => { const t = norm(`${i.title} ${i.summary} ${i.source_name}`); return words.every((w) => t.includes(w)); });
        $("#nw").innerHTML = items.length ? `<p class="lead small">${items.length} article${items.length > 1 ? "s" : ""} pour « ${esc(q)} »</p><div class="news-grid">${items.slice(0, 80).map((a) => card(a, false)).join("")}</div>`
          : `<div class="empty">Aucun article sur « ${esc(q)} » en ce moment.</div>`;
        return;
      }
      if (src === "all") {   // front page: no more than 4 stories per paper, so one source doesn't flood it
        const per = {}; items = items.filter((i) => (per[i.source] = (per[i.source] || 0) + 1) <= 4);
      }
      const [first, ...rest] = items;
      const leadIdx = first && first.image ? 0 : items.findIndex((i) => i.image);
      const lead = leadIdx >= 0 ? items[leadIdx] : null;
      const others = items.filter((_, i) => i !== leadIdx);
      $("#nw").innerHTML = !items.length ? `<div class="empty">No headlines right now.</div>` :
        `${lead ? card(lead, true) : ""}<div class="news-grid">${others.slice(0, 60).map((a) => card(a, false)).join("")}</div>`;
    };
    $("#nw-chips").onclick = (e) => { const b = e.target.closest(".chip"); if (b) { src = b.dataset.s; draw(); } };
    let t; $("#nw-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { q = e.target.value.trim(); draw(); }, 200); };
    $("#nw-search").onsubmit = (e) => e.preventDefault();
    draw();
  },

  async tv() {
    view.innerHTML = `<h1>Live <em>TV</em></h1><p class="lead">Free channels from official broadcasters — series, news, kids, sport. No account, no subscription.</p><div id="onair"></div>
      <div class="tv-stage media-stage" id="tv-stage"><div class="tv-hint">Pick a channel below</div></div>
      <div class="filters" id="tv-chips"></div><div class="tv-grid" id="tv-grid"><div class="skeleton"></div></div>`;
    syncTvDock();
    const d = await api("/api/tv/channels");
    let group = store.get("hub-tv-group", d.groups[0]);
    if (!d.groups.includes(group)) group = d.groups[0];
    const draw = () => {
      store.set("hub-tv-group", group);
      $("#tv-chips").innerHTML = d.groups.map((g) => `<button class="chip${g === group ? " on" : ""}" data-g="${esc(g)}">${esc(g)} <small>${d.channels.filter((c) => c.group === g).length}</small></button>`).join("");
      $("#tv-grid").innerHTML = d.channels.filter((c) => c.group === group).map((c) => `
        <a class="ch${tvNow && tvNow.id === c.id ? " on" : ""}" href="#tv" data-ch="${c.id}" title="${esc(c.name)}">
          <div class="ch-logo">${c.logo ? `<img src="${esc(c.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'),{textContent:'${esc(c.name.slice(0, 2).toUpperCase())}'}))">` : `<span>${esc(c.name.slice(0, 2).toUpperCase())}</span>`}</div>
          <div class="ch-name">${esc(c.name.replace(/ by Pluto TV$/, ""))}${c.height >= 720 ? ` <span class="hd">${c.height >= 1080 ? "FULL HD" : "HD"}</span>` : ""}</div><div class="ch-sub">${/Pluto/.test(c.name) ? "Pluto TV" : esc(c.group)}</div></a>`).join("");
    };
    $("#tv-chips").onclick = (e) => { const b = e.target.closest(".chip"); if (b) { group = b.dataset.g; draw(); } };
    draw();
    if (!tvNow) { const first = d.channels.find((c) => c.group === group); if (first) playTV(store.get("hub-tv-last", first.id)); }
  },

  async watch() {
    view.innerHTML = `<h1>Watch</h1><p class="lead">Films and series on demand — pause, resume, watch whenever you want.</p><div id="w"><div class="skeleton"></div></div>`;
    const [d] = await Promise.all([api("/api/watch"), loadCatalog()]);
    const free = CATALOG.entries.filter((e) => ["tv-replay", "live-channels", "films", "documentaries"].includes(e.category));
    // Netflix-style rows: one per genre that has at least 2 films
    const byGenre = {};
    (d.movies || []).forEach((m) => (m.genres || []).forEach((g) => (byGenre[g] = byGenre[g] || []).push(m)));
    const genreRows = Object.entries(byGenre).filter(([, l]) => l.length >= 2).sort((a, b) => b[1].length - a[1].length).slice(0, 6)
      .map(([g, l]) => row(g, l)).join("");
    $("#w").innerHTML =
      row("Continue watching", d.resume) +
      row(`All films`, d.movies, {}, EMPTY_VIDEO) +
      row("Series", d.series) +
      genreRows +
      `<h2>Louis de Funès <small>where to watch legally</small></h2><div class="tiles"><a class="tile nf-tile" href="https://www.netflix.com/search?q=louis%20de%20fun%C3%A8s" target="_blank" rel="noopener"><div class="ico nf-ico">N</div><div><b>On your Netflix</b><span>Search his films in your account</span></div></a><a class="tile" href="https://www.justwatch.com/fr/personne/louis-de-funes" target="_blank" rel="noopener"><div class="ico">${ICON.film}</div><div><b>Where is each film?</b><span>JustWatch: free replays, Netflix, Prime, rental…</span></div></a></div>` +
      `<h2>More to watch</h2><div class="tiles"><a class="tile nf-tile" href="https://www.netflix.com/browse" target="_blank" rel="noopener">
        <div class="ico nf-ico">N</div><div><b>Netflix</b><span>Your Netflix account, opens in a new tab</span></div></a>
        <a class="tile" href="${appLink("jellyfin")}"><div class="ico">${ICON.film}</div><div><b>Films & séries</b><span>Your Jellyfin library</span></div></a><a class="tile" href="#tv"><div class="ico">${ICON.tv}</div><div><b>Live TV</b><span>Free channels: series, news, kids, sport</span></div></a></div>` +
      `<h2>Free TV, films & documentaries <small><a href="#discover">see all →</a></small></h2><div class="cards">${free.map(entryCard).join("")}</div>`;
  },

  async listen() {
    view.innerHTML = `<h1>Listen</h1><p class="lead">Your music on Navidrome, live radio, podcasts and free streaming services.</p><div id="l"><div class="skeleton"></div></div>`;
    const [d] = await Promise.all([api("/api/listen"), loadCatalog()]);
    const radios = [...CATALOG.radios, ...(d.radios || []).filter((r) => !CATALOG.radios.some((c) => c.url === r.streamUrl))];
    const music = CATALOG.entries.filter((e) => e.category === "music");
    const pods = CATALOG.entries.filter((e) => e.category === "podcasts");
    const hitRadios = radios.filter((r) => /rap|hip|hits|pop|dance/i.test(r.genre || ""));
    $("#l").innerHTML =
      `<h2>Rap & pop radio <small>live hits</small></h2><div class="radios">${hitRadios.map(radioButton).join("")}</div>` +
      `<h2>Live radio <small>${radios.length} stations · official free streams</small></h2><div class="radios">${radios.map(radioButton).join("")}</div>` +
      row("Recently played", d.recent, { square: true }) +
      row("Most played", d.frequent, { square: true }) +
      (d.random.length ? `<h2>Shuffle your library <small><a href="${appLink("navidrome", "/app/#/album/random")}">open in Navidrome →</a></small></h2><div class="row">${d.random.map((i) => poster(i, { square: true })).join("")}</div>` : `<h2>Your music</h2>${EMPTY_MUSIC}`) +
      `<h2>Podcasts <small><a href="${appLink("audiobookshelf")}">open Audiobookshelf →</a></small></h2><div class="cards">${pods.map(entryCard).join("")}</div>` +
      `<h2>Free streaming services</h2><div class="cards">${music.map(entryCard).join("")}</div>`;
  },

  async discover() {
    await loadCatalog();
    const cats = Object.keys(CATALOG.categories).filter((c) => !CATALOG.learn_categories.includes(c));
    view.innerHTML = `<h1>Discover</h1><p class="lead">Official, free and legal services available in ${esc(CATALOG.region)}. No subscriptions.</p><div id="catalog"></div>`;
    catalogBrowser("discover", cats);
  },

  async learn() {
    await loadCatalog();
    view.innerHTML = `<h1>Learn</h1><p class="lead">Free courses, lectures and science channels. Save the ones you follow with ☆.</p><div id="catalog"></div>`;
    catalogBrowser("learn", CATALOG.learn_categories);
  },

  async organizer() {
    view.innerHTML = `<h1>Organize</h1>
      <p class="lead">Drop files in <code>C:\\Media\\_Inbox</code>. The organizer sorts, renames, flags duplicates and refreshes your libraries. <b>It never deletes anything.</b></p>
      <div class="toolbar"><button class="btn ghost" id="dry">Preview (dry run)</button><button class="btn" id="live">Organize now</button><span class="lead" id="omode"></span></div>
      <div id="o"><div class="skeleton" style="margin-top:20px"></div></div>`;
    const draw = async (report) => {
      const [h, q, last] = await Promise.all([api("/api/organizer/health"), api("/api/organizer/queues"),
        report ? Promise.resolve(report) : api("/api/organizer/report")]);
      report = last;
      $("#omode").textContent = h.error ? "⚠ organizer offline" : `Automatic mode: ${h.mode} · every ${h.interval_minutes} min`;
      const items = report.items || [];
      const counts = report.counts || {};
      const queue = (title, list, cls) => `<h2>${title} <small>${list.length}</small></h2>` + (list.length
        ? `<div class="panel"><table><tr><th>File</th><th>Reason</th></tr>${list.slice(0, 200).map((f) =>
            `<tr><td><code>${esc(f.path)}</code></td><td><span class="badge ${cls}">${cls}</span> ${esc(f.reason)}</td></tr>`).join("")}</table></div>`
        : `<div class="empty">Empty.</div>`);
      $("#o").innerHTML = (report.run_id ? `
        <h2>Last run <small>${esc(report.started)} · ${report.dry_run ? "preview only, nothing moved" : "files moved"} · TMDb ${esc(report.tmdb)}</small></h2>
        <div class="stats">${["organized", "duplicate", "review", "waiting", "error"].map((k) =>
          `<div class="stat"><b>${counts[k] || 0}</b><span>${k}</span></div>`).join("")}</div>
        ${items.length ? `<div class="panel"><table><tr><th>Status</th><th>From</th><th>To / reason</th></tr>${items.slice(0, 300).map((i) =>
          `<tr><td><span class="badge ${i.action}">${i.action}</span></td><td><code>${esc(i.src)}</code></td>
           <td>${i.dst ? `<code>${esc(i.dst)}</code><br>` : ""}<small class="lead">${esc(i.reason)}</small></td></tr>`).join("")}</table></div>`
          : `<div class="empty">The inbox was empty. 🎉</div>`}` : `<div class="empty">No run yet.</div>`) +
        queue("Needs review (_Review)", q.review || [], "review") +
        queue("Suspected duplicates (_Duplicates)", q.duplicates || [], "duplicate") +
        `<p class="lead" style="margin-top:16px">Files in <code>_Review</code>: rename them (e.g. <code>Title (Year).mkv</code>) and put them back in <code>_Inbox</code>. Files in <code>_Duplicates</code>: decide yourself whether to keep or delete them.</p>`;
    };
    const run = async (dry) => {
      $("#dry").disabled = $("#live").disabled = true;
      $(dry ? "#dry" : "#live").textContent = "Running…";
      const r = await api("/api/organizer/run", { method: "POST", body: JSON.stringify({ dry_run: dry }) });
      $("#dry").disabled = $("#live").disabled = false;
      $("#dry").textContent = "Preview (dry run)"; $("#live").textContent = "Organize now";
      await draw(r.error || r.status === "busy" ? null : r);
    };
    $("#dry").onclick = () => run(true);
    $("#live").onclick = () => run(false);
    await draw();
  },

  async offline() {
    const host = (() => { try { return new URL(CONFIG.lan_url).hostname; } catch { return location.hostname; } })();
    const apps = [
      { name: "Streamyfin", what: "Films & séries", icon: "https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/e1/9e/5d/e19e5d72-57b0-180c-d58b-bd972801f633/icon-ios-liquid-glass-0-0-1x_U007epad-0-1-sRGB-85-220.png/512x512bb.jpg",
        store: "https://apps.apple.com/fr/app/streamyfin/id6593660679", server: `https://${host}:8096`,
        steps: ["Installe Streamyfin et ouvre-la.", "« Server URL » : colle l'adresse ci-dessous, puis Connect.", "Identifiant HP + ton mot de passe.", "Ouvre un film ou un épisode → bouton Télécharger (flèche ↓). Il est ensuite dans « Downloads », même sans réseau."] },
      { name: "Amperfy", what: "Musique", icon: "https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/f5/3d/7c/f53d7c35-05c6-4b5b-51fb-e8a8e59f8d32/AmperfyAppIcon-0-0-1x_U007epad-0-0-0-1-0-sRGB-85-220.png/512x512bb.jpg",
        store: "https://apps.apple.com/fr/app/amperfy-music/id1530145038", server: `https://${host}:4533`,
        steps: ["Installe Amperfy et ouvre-la.", "« Server URL » : colle l'adresse ci-dessous.", "Username HP + ton mot de passe → Login.", "Sur un album ou une playlist : ⋯ → Download. La musique reste sur l'iPhone, sans réseau."] },
      { name: "ShelfPlayer", what: "Livres audio & podcasts", icon: "https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/2b/c8/8e/2bc88e4a-d864-459f-06c7-9beb5e06cfe5/ShelfPlayer-0-0-1x_U007epad-0-0-0-1-0-sRGB-85-220.png/512x512bb.jpg",
        store: "https://apps.apple.com/fr/app/shelfplayer-livres-audio/id6475221163", server: `https://${host}:13378`,
        steps: ["Installe ShelfPlayer et ouvre-la.", "Ajoute un serveur : colle l'adresse ci-dessous.", "HP + ton mot de passe.", "Sur un livre ou un épisode : Télécharger. Parfait pour le métro ou l'avion."] },
    ];
    view.innerHTML = `<h1>Hors <em>connexion</em></h1><p class="lead">Pour l'avion, le métro ou la campagne : ces apps iPhone gratuites téléchargent <b>ton</b> contenu depuis ton serveur, et le lisent ensuite sans réseau. Fais les réglages une fois, avec Tailscale activé.</p>
      <div class="off-grid">${apps.map((a) => `<section class="off-card">
        <div class="off-head"><img src="${esc(a.icon)}" alt=""><div><span class="kicker">${esc(a.what)}</span><h2>${esc(a.name)}</h2></div><span class="tag cost">Gratuit</span></div>
        <ol class="steps">${a.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
        <div class="off-server"><code>${esc(a.server)}</code><button class="btn ghost copy" data-copy="${esc(a.server)}">Copier</button></div>
        <a class="btn" href="${esc(a.store)}" target="_blank" rel="noopener">Ouvrir dans l'App Store</a></section>`).join("")}</div>
      <p class="lead small" style="margin-top:22px">Pourquoi pas eSound ou les apps « YouTube hors-ligne » ? Elles téléchargent la musique de YouTube, ce que YouTube et les artistes n'autorisent pas — et ces apps disparaissent souvent de l'App Store. Ici, tout vient de ton propre serveur.</p>`;
    view.querySelectorAll(".copy").forEach((b) => b.onclick = async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copié ✓"; } catch { b.textContent = "Sélectionne et copie"; }
      setTimeout(() => (b.textContent = "Copier"), 2000);
    });
  },

  async phone() {
    const lan = CONFIG.lan_url || `${location.protocol}//${location.host}`;
    view.innerHTML = `<h1>Install the app</h1><p class="lead">Use Media Hub like a real app, on this PC and on your phone.</p>
      <div class="install-grid">
        <section class="panel">
          <h2 style="margin-top:0">💻 On this PC</h2>
          ${installPrompt ? `<button class="btn big" id="install-btn">⬇ Install Media Hub</button>` :
            isStandalone() ? `<p>✅ You are already using the installed app.</p>` :
            `<p>In Chrome or Edge, click the <b>install icon</b> at the right end of the address bar (a small screen with an arrow), then <b>Install</b>.</p>`}
          <p class="lead small">It opens in its own window, with its own icon on the desktop and in the Start menu.</p>
        </section>
        <section class="panel">
          <h2 style="margin-top:0">📱 On your phone</h2>
          <div class="qr" id="qr"></div>
          <ol class="steps">
            <li>Phone on the <b>same Wi-Fi</b> as this PC (and this PC's Wi-Fi set to <b>Private network</b>).</li>
            <li>Scan the code with the camera, or open <code>${esc(lan)}</code>.</li>
            <li><b>Android (Chrome):</b> ⋮ menu → <b>Add to home screen</b>. <b>iPhone (Safari):</b> Share ⬆ → <b>Add to Home Screen</b>.</li>
          </ol>
        </section>
      </div>`;
    if ($("#install-btn")) $("#install-btn").onclick = async () => { installPrompt.prompt(); await installPrompt.userChoice; installPrompt = null; pages.phone(); };
    if (window.QRCode) new QRCode($("#qr"), { text: lan, width: 180, height: 180, colorDark: "#0a0b10", colorLight: "#ffffff" });
    else $("#qr").innerHTML = `<code>${esc(lan)}</code>`;
  },

  async status() {
    view.innerHTML = `<h1>Status</h1><div id="s"><div class="skeleton"></div></div>`;
    const s = await api("/api/status");
    const hints = {
      jellyfin: "Create an API key in Jellyfin → Dashboard → API Keys, then set JELLYFIN_API_KEY in .env",
      navidrome: "Set NAVIDROME_USER / NAVIDROME_PASSWORD in .env",
      audiobookshelf: "Copy your API token from Audiobookshelf → Settings → Users → your user, into ABS_API_TOKEN",
      organizer: "",
    };
    $("#s").innerHTML = `<div class="panel"><table><tr><th>Service</th><th>Running</th><th>Connected to Hub</th><th></th></tr>
      ${Object.entries(s).map(([k, v]) => `<tr><td><b>${k}</b></td>
        <td><span class="badge ${v.up ? "up" : "down"}">${v.up ? "up" : "down"}</span></td>
        <td><span class="badge ${v.configured ? "up" : "warn"}">${v.configured ? "yes" : "not configured"}</span></td>
        <td><small class="lead">${v.configured ? "" : esc(hints[k])}</small></td></tr>`).join("")}</table></div>
      <h2>Open a service</h2>${serviceTiles()}
      <p class="lead" style="margin-top:20px">From another device on your Wi-Fi, open <code>http://${esc(location.host)}</code>.</p>`;
  },

  // "Note Task": one section, two tabs (Tasks / Notes)
  notetask() { return pages.tasks(); },

  async tasks() {
    const list = taskList();
    const shop = list === "shopping";
    view.innerHTML = `${ntHead("tasks")}
      <div class="nt-lists">${[["todo", "To do"], ["shopping", "Shopping"]].map(([k, l]) =>
        `<button class="chip${k === list ? " on" : ""}" data-list="${k}">${l}<small id="cnt-${k}"></small></button>`).join("")}</div>
      <div id="push-box"></div>
      <form class="task-add" id="task-add">
        <div class="task-add-row">
          <input id="task-text" placeholder="${shop ? "Add an item: milk, bread…" : "Add a task…"}" autocomplete="off" maxlength="500" enterkeyhint="done">
          ${shop ? "" : `<button type="button" class="icon-btn clock-toggle" id="add-clock" aria-label="Add an alarm (optional)" title="Alarm (optional)">${ICON_CLOCK}</button>`}
          <button class="btn accent">Add</button>
        </div>
        <div class="add-alarm" id="add-alarm" hidden>
          <label class="chip at-time">Alarm at <input type="time" id="add-time"></label>
          <label class="chip daily"><input type="checkbox" id="add-daily"> Every day</label>
          <small class="lead">Optional. You get a notification if it's still not done.</small>
        </div>
      </form>
      <div id="task-list"><div class="skeleton"></div></div>`;
    if (!shop) pushBox();
    $("#add-clock")?.addEventListener("click", () => {
      const box = $("#add-alarm"); box.hidden = !box.hidden;
      $("#add-clock").classList.toggle("open", !box.hidden);
      if (!box.hidden) {
        if (!$("#add-time").value) { const t = new Date(Date.now() + 3600e3); $("#add-time").value = `${String(t.getHours()).padStart(2, "0")}:00`; }
        if (pushSupported() && Notification.permission === "default") enablePush().then(pushBox).catch(() => {});
      }
    });
    view.querySelectorAll("[data-list]").forEach((b) => b.onclick = () => { store.set("hub-task-list", b.dataset.list); pages.tasks(); });
    $("#task-add").onsubmit = async (e) => {
      e.preventDefault();
      const inp = $("#task-text"), text = inp.value.trim();
      if (!text) return;
      const body = { text, list };
      const alarm = $("#add-alarm");
      if (alarm && !alarm.hidden && $("#add-time").value) {
        body.at = nextAt($("#add-time").value);
        if ($("#add-daily").checked) body.repeat = "daily";
      }
      inp.value = "";
      if (alarm) { alarm.hidden = true; $("#add-clock").classList.remove("open"); $("#add-daily").checked = false; }
      const r = await api("/api/tasks", { method: "POST", body: JSON.stringify(body) });
      if (r.detail || r.error) toast(r.detail || r.error);
      else if (body.at) toast(`Added, alarm ${body.repeat ? "every day at " + hhmm(body.at) : fmtDue(body.at)}`);
      renderTasks();
      inp.focus();
    };
    renderTasks();
  },

  async notes() {
    noteFlush();
    const today = localDay(new Date());
    let day = new URLSearchParams(location.hash.split("?")[1] || "").get("d") || today;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || day > today) day = today;
    view.innerHTML = `${ntHead("notes")}
      <div class="note-head">
        <a class="icon-btn" href="#notes?d=${shiftDay(day, -1)}" aria-label="Previous day">‹</a>
        <div class="note-day"><b>${esc(dayLabel(day, today))}</b><small id="note-state"></small></div>
        <a class="icon-btn" href="#notes?d=${shiftDay(day, 1)}" aria-label="Next day"${day >= today ? ' style="visibility:hidden"' : ""}>›</a>
        ${day !== today ? `<a class="btn ghost" href="#notes">Today</a>` : ""}
      </div>
      <textarea id="note" class="note" placeholder="Write anything: ideas, what happened today, a list…" disabled></textarea>
      <div id="note-days"></div>`;
    const [n, list] = await Promise.all([api(`/api/notes/${day}`), api("/api/notes")]);
    const ta = $("#note");
    if (!ta) return;
    ta.value = n.body || ""; ta.disabled = false;
    const state = $("#note-state");
    state.textContent = n.updated ? `saved ${new Date(n.updated * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "";
    let timer = null, dirty = false;
    const save = async () => {
      clearTimeout(timer);
      if (!dirty) return;
      dirty = false; state.textContent = "saving…";
      const r = await api(`/api/notes/${day}`, { method: "PUT", body: JSON.stringify({ body: ta.value }) });
      state.textContent = r.ok ? "saved" : "not saved, check the connection";
      if (!r.ok) dirty = true;
    };
    ta.oninput = () => { dirty = true; state.textContent = "…"; clearTimeout(timer); timer = setTimeout(save, 700); };
    ta.onblur = save;
    noteFlush = save;
    const others = (list.days || []).filter((d) => d.day !== day);
    $("#note-days").innerHTML = others.length ? `<h2>Earlier notes <small>${others.length}</small></h2><div class="note-list">${others.map((d) => `
      <a class="note-card" href="#notes?d=${esc(d.day)}"><b>${esc(dayLabel(d.day, today))}</b><span>${esc(d.preview)}</span></a>`).join("")}</div>` : "";
  },

  async search(q) {
    view.innerHTML = `<h1>Results for “${esc(q)}”</h1><div id="r"><div class="skeleton"></div></div>`;
    const [d] = await Promise.all([api(`/api/search?q=${encodeURIComponent(q)}`), loadCatalog()]);
    const any = d.jellyfin.length || d.navidrome.length || d.catalog.length;
    $("#r").innerHTML = (!any ? `<div class="empty" style="margin-top:14px">No matches in your library or the free catalog.</div>` : "") +
      row("Movies & TV", d.jellyfin) + row("Music", d.navidrome, { square: true }) +
      (d.catalog.length ? `<h2>Free & legal sites <small>${d.catalog.length}</small></h2><div class="cards">${d.catalog.map(entryCard).join("")}</div>` : "");
  },
};

/* ------------------------------------------------------------ Note Task: tasks, reminders, notes */
const ntHead = (cur) => `<h1>Note Task</h1><div class="nt-tabs">
  <a href="#tasks" class="${cur === "tasks" ? "on" : ""}">Tasks</a><a href="#notes" class="${cur === "notes" ? "on" : ""}">Notes</a></div>`;
const ICON_CLOCK = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="13" r="7"/><path d="M11 9.5V13l2.5 1.5"/><path d="M19 2v5M16.5 4.5h5"/></svg>`;
const fmtDue = (t) => {
  const d = new Date(t * 1000), now = new Date(), tm = new Date(now);
  tm.setDate(now.getDate() + 1);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return time;
  if (d.toDateString() === tm.toDateString()) return `tomorrow ${time}`;
  return `${d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} ${time}`;
};
const inMin = (t) => { const m = Math.round((t * 1000 - Date.now()) / 60000); return m < 60 ? `in ${Math.max(m, 1)} min` : m < 1440 ? `in ${Math.round(m / 60)} h` : ""; };
const REMIND_PRESETS = [["15 min", 15], ["30 min", 30], ["1 h", 60], ["2 h", 120], ["3 h", 180]];
const taskList = () => (store.get("hub-task-list", "todo") === "shopping" ? "shopping" : "todo");
const nextAt = (hm) => {   // "10:00" = today at 10:00, or tomorrow if that time has passed
  const [h, m] = hm.split(":").map(Number), t = new Date();
  t.setHours(h, m, 0, 0);
  if (t <= new Date()) t.setDate(t.getDate() + 1);
  return t.getTime() / 1000;
};
const hhmm = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const isMissed = (r, t) => r.sent === 1 && !r.repeat && !t.done && Date.now() / 1000 - r.due < 86400;
let remindOpen = null, editing = null;
async function renderTasks() {
  if (!$("#task-list")) return;
  const list = taskList();
  const d = await api("/api/tasks");
  const box = $("#task-list");
  if (!box) return;
  const all = d.tasks || [];
  for (const k of ["todo", "shopping"]) {
    const n = all.filter((t) => t.list === k && !t.done).length, el = $(`#cnt-${k}`);
    if (el) el.textContent = n ? ` ${n}` : "";
  }
  const tasks = all.filter((t) => (t.list || "todo") === list), open = tasks.filter((t) => !t.done), done = tasks.filter((t) => t.done);
  const chip = (r, t) => {
    if (r.sent === 0) return `<span class="rem-chip${r.repeat ? " daily" : ""}">⏰ ${r.repeat ? `every day ${esc(hhmm(r.due))}` : `${esc(fmtDue(r.due))} <small>${esc(inMin(r.due))}</small>`}<button data-rdel="${r.id}" aria-label="Remove this alarm">×</button></span>`;
    if (isMissed(r, t)) return `<span class="rem-chip missed">⏰ missed ${esc(hhmm(r.due))}<button data-rdel="${r.id}" aria-label="Dismiss">×</button></span>`;
    return "";
  };
  const menu = (id) => `<div class="remind-menu"><small>Alarm: notify me if it's still not done at…</small>
    <label class="chip at-time">At <input type="time" data-remtime="${id}" aria-label="Alarm time"></label>
    <label class="chip daily"><input type="checkbox" id="rem-daily-${id}"> Every day</label>
    <small>…or in</small>
    ${REMIND_PRESETS.map(([l, m]) => `<button class="chip" data-rem="${id}" data-min="${m}">${l}</button>`).join("")}
    <button class="chip" data-rem="${id}" data-at="tonight">Tonight 20:00</button>
    <button class="chip" data-rem="${id}" data-at="tomorrow">Tomorrow 9:00</button>
    <label class="chip custom">Pick a date <input type="datetime-local" data-remat="${id}"></label></div>`;
  const item = (t) => `<li class="task${t.done ? " done" : ""}${t.reminders.some((r) => isMissed(r, t)) ? " late" : ""}" data-id="${t.id}">
    <button class="tick" data-tick="${t.id}" data-done="${t.done ? 1 : 0}" aria-label="${t.done ? "Mark as not done" : "Mark as done"}"></button>
    <div class="task-body">${editing === t.id
      ? `<input class="task-edit" data-edit="${t.id}" value="${esc(t.text)}" maxlength="500" enterkeyhint="done">`
      : `<span class="task-text" data-etext="${t.id}" title="Tap to edit">${esc(t.text)}</span>`}
      ${t.done ? "" : `<div class="rems">${t.reminders.map((r) => chip(r, t)).join("")}</div>`}
      ${!t.done && remindOpen === t.id ? menu(t.id) : ""}</div>
    ${t.done || list === "shopping" ? `<button class="icon-btn small" data-del="${t.id}" aria-label="Delete">✕</button>`
      : `<button class="icon-btn small plus clock${remindOpen === t.id ? " open" : ""}" data-plus="${t.id}" aria-label="Set an alarm">${ICON_CLOCK}</button>`}</li>`;
  const emptyMsg = list === "shopping" ? "The shopping list is empty." : "Nothing to do. Add a task above.";
  box.innerHTML = (open.length ? `<ul class="tasks">${open.map(item).join("")}</ul>` : `<div class="empty">${emptyMsg}</div>`) +
    (done.length ? `<h2>${list === "shopping" ? "In the cart" : "Done"} <small>${done.length} · <a href="#" id="clear-done">clear</a></small></h2><ul class="tasks">${done.map(item).join("")}</ul>` : "");
  $("#clear-done")?.addEventListener("click", async (e) => {
    e.preventDefault();
    await Promise.all(done.map((t) => api(`/api/tasks/${t.id}`, { method: "DELETE" })));
    renderTasks();
  });
  const ed = box.querySelector(".task-edit");
  if (ed) {
    ed.focus(); ed.setSelectionRange(ed.value.length, ed.value.length);
    const save = async () => {
      if (editing === null) return;
      const id = editing; editing = null;
      const text = ed.value.trim();
      if (text) await api(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ text }) });
      renderTasks();
    };
    ed.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } else if (e.key === "Escape") { editing = null; renderTasks(); } };
    ed.onblur = save;
  }
}
async function addReminder(id, body) {
  const r = await api(`/api/tasks/${id}/reminders`, { method: "POST", body: JSON.stringify(body) });
  if (r.detail || r.error) toast(r.detail || r.error);
  else {
    const last = (r.reminders || []).reduce((a, x) => (!a || x.id > a.id ? x : a), null);   // newest = highest id
    if (last) toast(`Alarm set: ${last.repeat ? "every day at " + hhmm(last.due) : fmtDue(last.due)}`);
  }
  remindOpen = null;
  renderTasks();
}
document.addEventListener("click", async (e) => {
  if (!e.target.closest("#task-list")) return;
  const et = e.target.closest("[data-etext]");
  if (et) { editing = Number(et.dataset.etext); remindOpen = null; renderTasks(); return; }
  const b = e.target.closest("button");
  if (!b) return;
  const d = b.dataset;
  if (d.tick) {
    const done = d.done !== "1";
    b.closest(".task").classList.toggle("done", done);
    if (done && navigator.vibrate) navigator.vibrate(15);
    await api(`/api/tasks/${d.tick}`, { method: "PATCH", body: JSON.stringify({ done }) });
    setTimeout(renderTasks, done ? 350 : 0);   // let the tick animation play before the task moves to "Done"
  } else if (d.plus) {
    const id = Number(d.plus);
    remindOpen = remindOpen === id ? null : id;
    renderTasks();
    // first time: ask for notification permission right inside this tap (required on iPhone)
    if (pushSupported() && Notification.permission === "default") enablePush().then(pushBox).catch(() => {});
  } else if (d.rem) {
    let body;
    if (d.min) body = { minutes: Number(d.min) };
    else {
      const t = new Date();
      if (d.at === "tomorrow") { t.setDate(t.getDate() + 1); t.setHours(9, 0, 0, 0); }
      else { t.setHours(20, 0, 0, 0); if (t <= new Date()) t.setDate(t.getDate() + 1); }
      body = { at: t.getTime() / 1000 };
    }
    addReminder(d.rem, body);
  } else if (d.rdel) {
    await api(`/api/reminders/${d.rdel}`, { method: "DELETE" });
    renderTasks();
  } else if (d.del) {
    await api(`/api/tasks/${d.del}`, { method: "DELETE" });
    renderTasks();
  }
});
document.addEventListener("change", (e) => {
  const i = e.target.closest("[data-remat]");
  if (i && i.value) addReminder(i.dataset.remat, { at: new Date(i.value).getTime() / 1000 });
  const tm = e.target.closest("[data-remtime]");
  if (tm && tm.value) {
    const daily = $(`#rem-daily-${tm.dataset.remtime}`)?.checked;
    addReminder(tm.dataset.remtime, { at: nextAt(tm.value), ...(daily ? { repeat: "daily" } : {}) });
  }
});

/* ------------------------------------------------------------ accounts: login screen + Account page */
let ME = null, authShown = false;
async function showLogin() {
  if (authShown) return;
  authShown = true;
  const st = await (await fetch("/api/auth/me")).json().catch(() => ({}));
  const setup = st.needs_setup;
  let box = $("#auth");
  if (!box) { box = document.createElement("div"); box.id = "auth"; document.body.appendChild(box); }
  box.innerHTML = `<div class="auth-card">
    <div class="auth-logo">Media <i>Hub</i></div>
    ${setup && !st.setup_allowed ? `<p class="lead">The hub isn't set up yet. Open it from the PC first.</p>` : `
    <h1>${setup ? "Create your account" : "Sign in"}</h1>
    <p class="lead small">${setup ? "This is the main account: only it can add accounts for others." : "Each account has its own tasks, notes and reminders."}</p>
    <form id="auth-form">
      <input name="name" placeholder="Name" autocomplete="username" autocapitalize="none" required maxlength="40">
      <input name="password" type="password" placeholder="Password${setup ? " (6+ characters)" : ""}" autocomplete="${setup ? "new-password" : "current-password"}" required>
      <button class="btn accent big">${setup ? "Create" : "Sign in"}</button><small id="auth-err" class="auth-err"></small>
    </form>`}</div>`;
  document.body.classList.add("locked");
  $("#auth-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target, body = JSON.stringify({ name: f.name.value, password: f.password.value });
    const r = await fetch(setup ? "/api/auth/setup" : "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body });
    if (r.ok) { location.hash = "#home"; location.reload(); return; }
    const d = await r.json().catch(() => ({}));
    $("#auth-err").textContent = d.detail || "Something went wrong.";
  });
}

pages.account = async () => {
  const me = (await api("/api/auth/me")).user || {};
  view.innerHTML = `<h1>Account</h1><p class="lead">Signed in as <b>${esc(me.name || "")}</b>${me.admin ? " · main account" : ""}.</p>
    <div class="acc-grid">
      <form class="panel acc" id="pw-form"><b>Change password</b>
        <input name="old" type="password" placeholder="Current password" autocomplete="current-password" required>
        <input name="new" type="password" placeholder="New password (6+ characters)" autocomplete="new-password" required>
        <button class="btn">Save</button><small class="auth-err" id="pw-err"></small></form>
      <div class="panel acc"><b>Sign out</b><p class="lead small">On this device only.</p><button class="btn ghost" id="logout">Sign out</button></div>
    </div>
    ${me.admin ? `<h2>Share the hub</h2>
    <div class="panel acc share-box"><b>Link to send</b>
      <div class="share-row"><input id="share-url" readonly value="${esc(CONFIG.lan_url || location.origin)}"><button class="btn accent" id="share-copy">Copy</button></div>
      <p class="lead small">Send this link with the person's name and password (create their account below). Nothing to install:
        on iPhone, open it in Safari, then <b>Share → Add to Home Screen</b>. Works from anywhere, 7:00–22:00 (the PC sleeps at night).</p>
      ${navigator.share ? `<button class="btn ghost" id="share-native">Share…</button>` : ""}</div>
    <h2>Accounts <small>only you can see this</small></h2>
    <div class="acc-grid"><div class="panel acc"><ul class="acc-users" id="acc-users"></ul></div>
      <form class="panel acc" id="add-user"><b>Add an account</b>
        <input name="name" placeholder="Name" required maxlength="40" autocapitalize="none">
        <input name="password" type="text" placeholder="Password for them (6+ characters)" required autocomplete="off">
        <button class="btn accent">Add account</button><small class="auth-err" id="add-err"></small>
        <p class="lead small">They get their own tasks, notes and notifications. Give them the name and password.</p></form></div>` : ""}`;
  $("#logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.reload(); };
  $("#pw-form").onsubmit = async (e) => {
    e.preventDefault();
    const r = await api("/api/auth/password", { method: "POST", body: JSON.stringify({ old: e.target.old.value, new: e.target.new.value }) });
    $("#pw-err").textContent = r.ok ? "" : r.detail || r.error;
    if (r.ok) { e.target.reset(); toast("Password changed"); }
  };
  if (!me.admin) return;
  $("#share-copy").onclick = async () => {
    const u = $("#share-url").value;
    try { await navigator.clipboard.writeText(u); } catch { $("#share-url").select(); document.execCommand("copy"); }
    toast("Link copied");
  };
  $("#share-native")?.addEventListener("click", () => navigator.share({ title: "Media Hub", url: $("#share-url").value }).catch(() => {}));
  let USERS = [], TABS = [], openTabs = null;
  const countLabel = (u) => `${TABS.length - (u.hidden || []).length}/${TABS.length} onglets`;
  const users = async () => {
    const d = await api("/api/auth/users");
    USERS = d.users || []; TABS = d.tabs || [];
    $("#acc-users").innerHTML = USERS.map((u) => `<li${openTabs === u.id ? ` class="open"` : ""}><div class="acc-row"><span class="acc-av">${esc(u.name[0].toUpperCase())}</span><b>${esc(u.name)}</b>
      ${u.admin ? `<small>main account · tout</small>` : `<button class="btn ghost small acc-tabs-btn" data-utabs="${u.id}">Onglets <span class="acc-count">${countLabel(u)}</span></button>
      <button class="icon-btn small" data-udel="${u.id}" data-uname="${esc(u.name)}" aria-label="Delete account">✕</button>`}</div>
      ${!u.admin && openTabs === u.id ? `<div class="acc-tabs" data-tabs-of="${u.id}"><p class="lead small">Coche les onglets que <b>${esc(u.name)}</b> peut ouvrir. Enregistré tout de suite.</p>
        ${TABS.map((t) => `<label class="acc-tab"><input type="checkbox" value="${esc(t.key)}" data-label="${esc(t.label)}"${(u.hidden || []).includes(t.key) ? "" : " checked"}><span>${esc(t.label)}</span></label>`).join("")}</div>` : ""}</li>`).join("");
  };

  users();
  $("#acc-users").onclick = async (e) => {
    const t = e.target.closest("[data-utabs]");
    if (t) { openTabs = openTabs === +t.dataset.utabs ? null : +t.dataset.utabs; return users(); }
    const b = e.target.closest("[data-udel]"); if (!b) return;
    if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Delete?"; b.classList.add("danger"); return; }   // tap twice to delete
    await api(`/api/auth/users/${b.dataset.udel}`, { method: "DELETE" });
    toast(`${b.dataset.uname}'s account deleted`); users();
  };
  $("#acc-users").onchange = async (e) => {
    const box = e.target.closest("[data-tabs-of]"); if (!box) return;
    const hidden = [...box.querySelectorAll("input[type=checkbox]")].filter((c) => !c.checked).map((c) => c.value);
    const r = await api(`/api/auth/users/${box.dataset.tabsOf}/tabs`, { method: "PUT", body: JSON.stringify({ hidden }) });
    if (r.ok) { const u = USERS.find((x) => x.id === +box.dataset.tabsOf); if (u) u.hidden = r.hidden; toast(e.target.checked ? `${e.target.dataset.label} activé` : `${e.target.dataset.label} retiré`); }
    else toast(r.detail || r.error || "Erreur");
    box.closest("li").querySelector(".acc-count").textContent = countLabel(USERS.find((x) => x.id === +box.dataset.tabsOf));
  };
  $("#add-user").onsubmit = async (e) => {
    e.preventDefault();
    const r = await api("/api/auth/users", { method: "POST", body: JSON.stringify({ name: e.target.name.value, password: e.target.password.value }) });
    $("#add-err").textContent = r.ok ? "" : r.detail || r.error;
    if (r.ok) { toast(`Account ${e.target.name.value} created`); e.target.reset(); users(); }
  };
};

/* ---- push notifications (reminders reach the phone even when the app is closed) */
const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const urlB64 = (s) => { const b = atob((s + "=".repeat((4 - s.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(b, (c) => c.charCodeAt(0)); };
async function enablePush() {
  if (!pushSupported()) return "unsupported";
  const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
  if (perm !== "granted") return perm;
  const reg = await navigator.serviceWorker.ready;
  const { key } = await api("/api/push/key");
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlB64(key) });
  await api("/api/push/subscribe", { method: "POST", body: JSON.stringify(sub.toJSON()) });
  return "granted";
}
function pushBox() {
  const box = $("#push-box");
  if (!box) return;
  if (pushSupported() && Notification.permission === "granted") {
    enablePush().catch(() => {});   // keeps this device registered on the server
    box.innerHTML = `<p class="lead small push-ok">🔔 Notifications are on for this device · <a href="#" id="push-test">send a test</a></p>`;
    $("#push-test").onclick = async (e) => {
      e.preventDefault();
      const r = await api("/api/push/test", { method: "POST" });
      toast(r.reached ? "Test sent. Check your notifications" : "No device reached yet");
    };
    return;
  }
  if (!pushSupported() || (isIOS && !isStandalone())) {
    box.innerHTML = `<div class="panel push-help"><b>Get reminders on your iPhone</b><p class="lead small">With Tailscale on, open
      <code>${esc(CONFIG.lan_url || location.origin)}</code> in Safari, tap <b>Share → Add to Home Screen</b>, open Media Hub from that icon,
      then come back here and turn notifications on.</p></div>`;
    return;
  }
  if (Notification.permission === "denied") {
    box.innerHTML = `<div class="panel push-help"><p class="lead small">Notifications are blocked for Media Hub. Allow them in Settings → Notifications → Media Hub.</p></div>`;
    return;
  }
  box.innerHTML = `<div class="panel push-help"><b>Turn on reminders</b><p class="lead small">Allow notifications once, so reminders reach this device even when the app is closed.</p>
    <button class="btn accent" id="push-on">Turn on notifications</button></div>`;
  $("#push-on").onclick = async () => {
    const r = await enablePush().catch((err) => { toast(err.message); return "error"; });
    if (r === "granted") toast("Notifications on");
    pushBox();
  };
}

/* ---- notes: one page per day, saved automatically */
let noteFlush = () => {};
const localDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const shiftDay = (day, n) => { const d = new Date(`${day}T12:00:00`); d.setDate(d.getDate() + n); return localDay(d); };
function dayLabel(day, today) {
  const d = new Date(`${day}T12:00:00`);
  const long = d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  return day === today ? `Today · ${long}` : day === shiftDay(today, -1) ? `Yesterday · ${long}` : long;
}
window.addEventListener("hashchange", () => noteFlush());
document.addEventListener("visibilitychange", () => { if (document.hidden) noteFlush(); });

/* ---- tabs the main account turned off for this person: hidden in the menu, and the page can't be opened */
const can = (tab) => !(ME?.hidden || []).includes(tab);
function applyTabs() {
  document.querySelectorAll("#nav a[data-page], #nav a[data-tab]").forEach((a) => { a.hidden = !can(a.dataset.tab || a.dataset.page); });
  const APP_TAB = { jellyfin: "watch", navidrome: "listen", audiobookshelf: "listen" };
  document.querySelectorAll("#service-links a[data-app]").forEach((a) => { a.hidden = !can(APP_TAB[a.dataset.app]); });
  document.querySelectorAll("#nav .nav-label").forEach((l) => {   // a section with nothing left in it disappears too
    let n = l.nextElementSibling, any = false;
    while (n && !n.classList.contains("nav-label")) { if (n.tagName === "A" && !n.hidden) any = true; n = n.nextElementSibling; }
    l.hidden = !any;
  });
}

/* ------------------------------------------------------------ router */
async function route() {
  const [name, query] = location.hash.slice(1).split("?");
  if (name.startsWith("app/")) {
    const ok = openApp(name.slice(4), new URLSearchParams(query || "").get("p"));
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === location.hash));
    if (ok) { syncTvDock(); return; }
  }
  closeApps();
  let page = pages[name] ? name : name === "padel" ? "sport" : "home";
  if (!can(page === "tasks" || page === "notes" ? "notetask" : page)) page = "home";
  const navPage = page === "tasks" || page === "notes" ? "notetask" : page === "sportmatch" ? "sportrecap" : page;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === navPage));
  try {
    if (page === "search") await pages.search(new URLSearchParams(query).get("q") || "");
    else await pages[page]();
  } catch (err) {
    view.innerHTML = `<div class="empty">Something went wrong loading this page: ${esc(err.message)}</div>`;
  }
  window.scrollTo(0, 0);
  if ((page === "tv" || page === "home") && can("tv")) onAirBox();
  syncTvDock();
  setTimeout(() => { syncTvDock(); }, 800);   // re-align once the page entrance animation has settled
}

$("#search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (q) location.hash = `search?q=${encodeURIComponent(q)}`;
});
$("#theme").onclick = () => {
  const root = document.documentElement;
  const cur = root.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  root.dataset.theme = cur === "dark" ? "light" : "dark";
  try { localStorage.setItem("hub-theme", root.dataset.theme); } catch { /* private mode */ }
};
if (!document.documentElement.dataset.theme) document.documentElement.dataset.theme = "dark";   // dark by default

/* ------------------------------------------------------------ motion */
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
// cards fly in as they scroll into view, one after the other
const io = "IntersectionObserver" in window ? new IntersectionObserver((list) => {
  list.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
}, { rootMargin: "0px 0px -40px 0px" }) : null;
function enterView() { view.classList.remove("enter"); void view.offsetWidth; view.classList.add("enter"); }
window.addEventListener("hashchange", enterView);
function animateView() {
  if (calm || !io) return;
  document.querySelectorAll(".row, .grid, .radios, .cards, .tiles, .stats").forEach((group) => {
    [...group.children].forEach((el, i) => {
      if (el.classList.contains("in") || el.classList.contains("fx")) return;
      el.classList.add("fx"); el.style.setProperty("--i", Math.min(i, 14)); io.observe(el);
    });
  });
}
new MutationObserver((muts) => {
  if (muts.every((m) => [...m.addedNodes].every((n) => n.classList?.contains("ripple")))) return;
  requestAnimationFrame(animateView);
}).observe(view, { childList: true, subtree: true });
enterView();
// hero title: words rise one after another (the only "showy" motion, on the one element that deserves it)
function splitWords(el) {
  if (!el || calm) return;
  el.innerHTML = el.textContent.split(/(\s+)/).map((w, i) => /\s+/.test(w) ? w : `<span class="w" style="--w:${i / 2}">${esc(w)}</span>`).join("");
}

window.addEventListener("hashchange", route);
/* ---- auto-refresh: news-type pages reload their content on their own (only when the app is visible and you are
   at the top of the page, so it never jumps while you read or watch), and the app updates itself when a new version is deployed */
const LIVE_PAGES = { journal: 10, ai: 30, home: 15, sport: 1, sportrecap: 15, listen: 30 };   // minutes
let lastRender = Date.now();
window.addEventListener("hashchange", () => { lastRender = Date.now(); });
setInterval(() => {
  const page = location.hash.slice(1).split("?")[0] || "home";
  const every = LIVE_PAGES[page];
  if (!every || document.hidden || window.scrollY > 300 || Date.now() - lastRender < every * 60000) return;
  if (document.body.classList.contains("reading") || document.activeElement?.tagName === "INPUT" || $("#nw-q")?.value) return;   // never interrupt reading or a search
  lastRender = Date.now();
  pages[page]?.();
}, 60000);
document.addEventListener("visibilitychange", () => {   // coming back to the app after a while = fresh page
  const page = location.hash.slice(1).split("?")[0] || "home";
  if (!document.hidden && LIVE_PAGES[page] && Date.now() - lastRender > LIVE_PAGES[page] * 60000) { lastRender = Date.now(); pages[page]?.(); }
});
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (!tvNow && audio.paused) location.reload(); });
  setInterval(() => navigator.serviceWorker.getRegistration().then((r) => r?.update()), 3600000);
}

/* ---- sport live alert: red LIVE badge in the menu + banner on the home page, checked every 3 minutes */
async function checkSport() {
  if (!ME || !can("sport")) return;
  const p = await api("/api/sport/live");
  const n = (p.streams || []).length + (p.big_live || []).length + (p.tv_free || []).length;
  document.querySelector('#nav a[data-page="sport"]')?.classList.toggle("is-live", n > 0);
  const b = $("#sport-banner"); if (!b) return;
  const g = p.big_live?.[0];
  const first = p.tv_free?.[0] ? `${p.tv_free[0].title} · ${p.tv_free[0].channel}` : g ? `${g.home.full} ${g.home.score}–${g.away.score} ${g.away.full}` : p.streams?.[0]?.title || "";
  b.innerHTML = n ? `<a class="padel-banner" href="#sport"><span class="live-badge">● LIVE</span>
    <b>Sport : ${n} en direct</b><span>${esc(first)}</span><span class="go">${ICON.arrow}</span></a>` : "";
}
setInterval(checkSport, 180000);

/* ---- phone menu: ☰ button top-left opens the full menu as a side panel */
const setNav = (open) => { document.body.classList.toggle("nav-open", open); $("#menu-btn")?.setAttribute("aria-expanded", open); };
$("#menu-btn")?.addEventListener("click", () => setNav(!document.body.classList.contains("nav-open")));
$("#nav-backdrop")?.addEventListener("click", () => setNav(false));
document.querySelector(".sidebar")?.addEventListener("click", (e) => { if (e.target.closest("a")) setNav(false); });
window.addEventListener("hashchange", () => setNav(false));

/* ---- installable app (PWA) */
let installPrompt = null, CONFIG = {};
const isStandalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone;
addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; if (location.hash === "#phone") pages.phone(); });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

api("/api/config").then((c) => { CONFIG = c || {}; if (c.ports) PORTS = c.ports; }).finally(async () => {
  $("#service-links").innerHTML = SERVICES.map(([id, name]) => `<a href="${appLink(id)}" data-app="${id}">▸ ${name}</a>`).join("");
  const st = await fetch("/api/auth/me").then((r) => r.json()).catch(() => ({}));
  if (!st.user) return showLogin();
  ME = st.user;
  const acc = $("#nav-account span"); if (acc) acc.textContent = ME.name;
  applyTabs();
  route();
});
