"use strict";

/* ------------------------------------------------------------ helpers */
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await r.json().catch(() => ({}));
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
  $("#apps-tabs").innerHTML = Object.keys(APP_HOME).map((k) =>
    `<a href="${appLink(k)}" class="${k === service ? "on" : ""}${frames[k] ? " live" : ""}">${APP_NAME[k]}</a>`).join("") +
    `<button class="apps-reload" id="apps-reload" title="Back to the start of this app">⟲</button>`;
  $("#apps-reload").onclick = () => { f.src = serviceUrl(service, APP_HOME[service]); };
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
  return `<a class="poster${square ? " square" : ""}" href="${esc(href)}"${item.service ? "" : ' target="_blank" rel="noopener"'} title="${esc(item.title)}">
    <div class="art"><div class="fallback">${initial}</div>
      <img src="${esc(item.image)}" alt="" loading="lazy" onerror="this.remove()">${prog}</div>
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
  sp: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><circle cx="12" cy="12" r="10"/><path d="M7 9.5c3.5-1 7.5-.6 10.5 1.2M7.6 12.8c2.8-.8 6-.4 8.4 1M8.3 15.9c2.2-.6 4.5-.3 6.3.8"/></svg>`,
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
  audio.src = url; playingUrl = url;
  audio.volume = Number($("#vol").value);
  audio.play().catch(() => { $("#now-sub").textContent = "Could not start the stream"; });
  $("#now-name").textContent = name; $("#now-sub").textContent = `Live · ${genre || "radio"}`;
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
$("#stop").onclick = () => { audio.pause(); audio.removeAttribute("src"); audio.load(); playingUrl = null; player.classList.remove("show"); markPlaying(); };
document.addEventListener("click", (e) => {
  const r = e.target.closest(".radio"); if (r) playRadio(r.dataset.name, r.dataset.url, r.dataset.genre);
});
const hue = (s) => [...String(s)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
const radioButton = (r) => `<button class="radio${playingUrl === (r.url || r.streamUrl) && !audio.paused ? " playing" : ""}" style="--h:${hue(r.name)}" data-name="${esc(r.name)}" data-url="${esc(r.url || r.streamUrl)}" data-genre="${esc(r.genre || "")}">
  <div class="dot">${esc(r.name.replace(/[^\p{L}\p{N}]/gu, "").slice(0, 3).toUpperCase())}</div><div class="rt"><b>${esc(r.name)}</b><small>${esc(r.genre || "Internet radio")}</small></div><span class="eq"><i></i><i></i><i></i></span></button>`;
audio.addEventListener("play", () => {
  // the radio and Spotify share the speakers: pausing the radio is enough, Spotify has its own button
  const n = $("#now-name").textContent; $("#now-art").style.setProperty("--h", hue(n));
});

/* ------------------------------------------------------------ live TV (persistent player, like the Spotify dock) */
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
      <video id="tv-video" controls autoplay playsinline></video><div class="tv-msg" id="tv-msg"></div>`;
    $("#tv-x").onclick = () => { tvHls?.destroy(); tvHls = null; tvNow = null; tvDock.innerHTML = ""; syncTvDock(); markTv(); };
  }
  if (!audio.paused) $("#stop").click();   // one sound at a time
  $("#tv-name").textContent = r.name; $("#tv-msg").textContent = "Loading…"; $("#tv-msg").hidden = false;
  const v = $("#tv-video");
  v.onplaying = () => { $("#tv-msg").hidden = true; };
  tvHls?.destroy(); tvHls = null;
  if (window.Hls && Hls.isSupported()) {
    // best picture: start at the highest quality and never cap it to the player size
    tvHls = new Hls({ lowLatencyMode: false, backBufferLength: 30, capLevelToPlayerSize: false, abrEwmaDefaultEstimate: 12e6, startLevel: -1 });
    tvHls.on(Hls.Events.MANIFEST_PARSED, (_, data) => { if (data.levels?.length > 1) { tvHls.startLevel = data.levels.length - 1; tvHls.nextLevel = data.levels.length - 1; } });
    tvHls.on(Hls.Events.ERROR, (_, e) => { if (e.fatal) { $("#tv-msg").hidden = false; $("#tv-msg").textContent = "This channel is off the air right now — try another one."; } });
    tvHls.loadSource(r.src); tvHls.attachMedia(v);
  } else { v.src = r.src; }   // Safari / iPhone play HLS natively
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
  tvDock.innerHTML = `<div class="dock-bar tv-bar"><a href="#videos"><b>▶</b> <span>${esc(title)}</span></a><button id="tv-x" title="Close">✕</button></div>
    <iframe class="yt-frame" src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(vid)}?autoplay=1&rel=0&modestbranding=1"
      allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen title="${esc(title)}"></iframe>`;
  $("#tv-x").onclick = () => { tvNow = null; tvDock.innerHTML = ""; syncTvDock(); markTv(); };
  syncTvDock(); markTv();
}
document.addEventListener("click", (e) => {
  const v = e.target.closest(".vid"); if (!v) return;
  e.preventDefault(); playYT(v.dataset.yt, v.dataset.title);
  $(".media-stage")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
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
      (r.blocks || []).map((b) => b.t === "p" ? `<p>${esc(b.x)}</p>` : b.t === "li" ? `<p class="li">• ${esc(b.x)}</p>` : b.t === "blockquote" ? `<blockquote>${esc(b.x)}</blockquote>` : `<h3>${esc(b.x)}</h3>`).join("")}
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
const videoCard = (v) => `<a class="vid${tvNow && tvNow.yt === v.id ? " on" : ""}" href="https://www.youtube.com/watch?v=${esc(v.id)}" data-yt="${esc(v.id)}" data-title="${esc(v.title)}">
  <div class="vid-thumb"><img src="${esc(v.thumb)}" alt="" loading="lazy"><span class="vid-play">${ICON.play}</span></div>
  <div class="vid-t">${esc(v.title)}</div><div class="vid-s">${esc(v.channel)} · ${timeAgo(v.published)}${v.views ? ` · ${fmtViews(v.views)}` : ""}</div></a>`;
document.addEventListener("click", (e) => { const c = e.target.closest(".ch"); if (c) { e.preventDefault(); playTV(+c.dataset.ch); $("#tv-stage")?.scrollIntoView({ behavior: "smooth", block: "nearest" }); } });

/* ------------------------------------------------------------ spotify (official embedded player) */
const SPOTIFY_TYPES = ["track", "album", "playlist", "artist", "episode", "show"];
function parseSpotify(input) {
  const s = String(input || "").trim();
  let m = s.match(/^spotify:(\w+):([A-Za-z0-9]+)$/);
  if (!m) m = s.match(/open\.spotify\.com\/(?:intl-[a-z-]+\/)?(\w+)\/([A-Za-z0-9]+)/);
  return m && SPOTIFY_TYPES.includes(m[1]) ? `${m[1]}/${m[2]}` : null;
}
const spotifyFrame = (path, height = 452) =>
  `<iframe class="sp-frame" src="https://open.spotify.com/embed/${esc(path)}?utm_source=generator&theme=0" height="${height}"
    allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy" title="Spotify player"></iframe>`;
/* The Spotify iframe lives OUTSIDE #view, so changing page never destroys it (= music keeps playing).
   On the Spotify page it is laid over the #sp-player placeholder; elsewhere it shrinks to a mini player. */
const dock = $("#sp-dock");
let dockPath = null;
function syncDock() {
  if (!dockPath) { dock.hidden = true; return; }
  dock.hidden = false;
  const ph = $("#sp-player");
  if (ph) {
    const r = ph.getBoundingClientRect();
    dock.classList.add("big"); dock.classList.remove("mini");
    Object.assign(dock.style, { top: `${r.top}px`, left: `${r.left}px`, width: `${r.width}px`, height: `${r.height}px` });
  } else {
    dock.classList.add("mini"); dock.classList.remove("big");
    dock.style.cssText = "";
  }
}
addEventListener("scroll", () => requestAnimationFrame(syncDock), { passive: true });
addEventListener("resize", () => requestAnimationFrame(syncDock));
function playSpotify(path) {
  store.set("hub-spotify", path);
  if (path !== dockPath) {
    dockPath = path;
    dock.innerHTML = `<div class="dock-bar"><a href="#spotify" title="Open Spotify page">♫ Spotify</a><button id="dock-x" title="Close the player">✕</button></div>${spotifyFrame(path)}`;
    $("#dock-x").onclick = () => { dockPath = null; dock.innerHTML = ""; syncDock(); };
  }
  syncDock();
  const app = $("#sp-app");
  if (app) app.href = `spotify:${path.replace("/", ":")}`;
  document.querySelectorAll(".sp-card").forEach((c) => c.classList.toggle("on", c.dataset.sp === path));
}
document.addEventListener("click", (e) => {
  const c = e.target.closest(".sp-card"); if (!c) return;
  e.preventDefault(); playSpotify(c.dataset.sp);
  $("#sp-player")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

/* ------------------------------------------------------------ pages */
const EMPTY_VIDEO = `<div class="empty">Nothing here yet. Drop video files into <code>C:\\Media\\_Inbox</code> (or its <code>Movies</code>, <code>TV</code>, <code>Documentaries</code>, <code>Education</code>, <code>Personal</code> sub-folders) and the organizer files them into Jellyfin. A good legal start: the public-domain films on <a href="#discover">Discover</a>.</div>`;
const EMPTY_MUSIC = `<div class="empty">No local music yet. Put albums in <code>C:\\Media\\_Inbox\\Music</code>. Free, legal sources: Jamendo, Free Music Archive, Bandcamp free downloads.</div>`;

const pages = {
  async home() {
    const hour = new Date().getHours();
    const greet = hour < 5 ? "Late night" : hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    const date = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
    view.innerHTML = `<section class="hero plain" id="hero"><div class="hero-txt">
        <span class="kicker">${esc(date)}</span><h1>${greet}.</h1>
        <p>Films, live TV, music, radio, Spotify and books — one place, yours.</p></div></section>
      <div id="home-rows"><div class="skeleton" style="margin-top:28px"></div></div>`;
    const [d] = await Promise.all([api("/api/home"), loadCatalog()]);
    const favs = CATALOG.entries.filter((e) => FAVS.has(e.id));

    // hero: a rotating mix of what's fresh — padel live, news, your channels (the British trio first), AI, trending
    const [pd, nw, ytc, yta, tr] = await Promise.all([api("/api/padel"), api("/api/news"),
      api("/api/yt/feed?cat=" + encodeURIComponent("Clarkson, Hammond & May")), api("/api/yt/feed"), api("/api/yt/trending")]);
    const ytSlide = (v, kicker) => v && { kind: "yt", kicker, title: v.title, text: `${v.channel}${v.published ? " · " + timeAgo(v.published) : ""}`, img: `https://i.ytimg.com/vi/${v.id}/maxresdefault.jpg`, yt: v.id };
    const ess = (nw.essentials || []).filter((s) => s.image);
    const notIn = (cat) => (yta.videos || []).find((v) => !(ytc.videos || []).some((x) => x.id === v.id) && v.channel && !/top gear|grand tour|drivetribe/i.test(v.channel));
    const feats = [
      pd.live?.[0] && { kind: "padel", kicker: "Padel · LIVE", title: pd.live[0].title, text: `${pd.live.length} match${pd.live.length > 1 ? "es" : ""} en direct — ${pd.live[0].channel}`, img: pd.live[0].thumb.replace("hqdefault", "maxresdefault"), href: "#padel" },
      ess[0] && { kind: "news", kicker: `À la une · ${ess[0].count} journaux`, title: ess[0].title, text: ess[0].summary, img: ess[0].image, link: ess[0].link },
      ytSlide((ytc.videos || [])[0], "Clarkson, Hammond & May"),
      ess[1] && { kind: "news", kicker: `Actu · ${ess[1].count} journaux`, title: ess[1].title, text: ess[1].summary, img: ess[1].image, link: ess[1].link },
      ytSlide(notIn(), "Tes chaînes"),
      ytSlide((tr.videos || [])[0], "Tendance en France"),
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
        const btn = f.kind === "yt" ? `<a class="btn big vid" href="#" data-yt="${esc(f.yt)}" data-title="${esc(f.title)}">${ICON.play} Regarder</a>`
          : f.kind === "news" ? `<a class="btn big art-card" href="${esc(f.link)}">Lire</a>`
          : `<a class="btn big" href="${f.href}">${ICON.play} Voir le direct</a>`;
        const more = f.kind === "yt" ? `<a class="btn big ghost" href="#videos">Toutes les vidéos</a>` : f.kind === "news" ? `<a class="btn big ghost" href="#journal">Le Journal</a>` : "";
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

    const R = CATALOG.radios.length, P = (CATALOG.spotify_playlists || []).length;
    api("/api/tv/channels").then((t) => { const el = $("#tv-count"); if (el && t.channels) el.firstChild.textContent = t.channels.length; });
    checkPadel();
    api("/api/weekly").then((w) => {
      const box = $("#weekly"); if (!box || !w.items || !w.items.length) return;
      box.innerHTML = `<h2>This week <small>${esc(w.week || "")} · curated by Claude</small></h2>${w.headline ? `<p class="lead">${esc(w.headline)}</p>` : ""}
        <ol class="weekly">${w.items.map((i) => `<li><span class="tag">${esc(i.kind || "")}</span><div><b>${i.link ? `<a href="${esc(i.link)}" target="_blank" rel="noopener">${esc(i.title)}</a>` : esc(i.title)}</b><p>${esc(i.text || "")}</p></div></li>`).join("")}</ol>`;
    });
    $("#home-rows").innerHTML =
      `<div class="bento">
        <a class="big tv-cell" href="#tv"><span class="eyebrow">Live TV</span>
          <div><div class="num" id="tv-count">—<small>channels</small></div><b>Films, series, news & kids — free, no account.</b></div><span class="go">${ICON.arrow}</span></a>
        <a class="sp-cell" href="#spotify"><span class="eyebrow">Spotify</span><div><div class="num">${P}<small>playlists</small></div><b>Top 50 France & more</b></div><span class="go">${ICON.arrow}</span></a>
        <a href="#listen"><span class="eyebrow">Radio</span><div><div class="num">${R}<small>stations</small></div><b>NRJ, Skyrock, FIP…</b></div><span class="go">${ICON.arrow}</span></a>
      </div>` +
      `<div id="padel-banner"></div><div id="weekly"></div>` +
      `<h2>On air <small><a href="#listen">all stations</a></small></h2><div class="radios strip">${CATALOG.radios.slice(0, 8).map(radioButton).join("")}</div>` +
      row("Continue watching", d.resume) +
      row("Recently added", d.latest, {}, EMPTY_VIDEO) +
      row("Recently played music", d.recent_albums, { square: true }) +
      row("New albums", d.new_albums, { square: true }) +
      row("New podcast episodes", d.podcasts, { square: true }) +
      (favs.length ? `<h2>Your favorite free sites <small>${favs.length}</small></h2><div class="cards">${favs.map(entryCard).join("")}</div>`
        : `<h2>Free & legal streaming</h2><div class="empty">Browse <a href="#discover">Discover</a> and <a href="#learn">Learn</a> and tap ☆ to pin your favorite free services here.</div>`) +
      `<h2>Your apps</h2>${serviceTiles()}`;
  },

  async padel() {
    view.innerHTML = `<h1>Padel</h1><p class="lead">Live matches from Premier Padel, the FIP and the padel channels you follow — detected automatically, played right here.</p>
      <div class="tv-stage media-stage"><div class="tv-hint">No match playing</div></div><div id="pd"><div class="skeleton"></div></div>`;
    syncTvDock();
    const [p, f] = await Promise.all([api("/api/padel"), api("/api/yt/feed?cat=Padel")]);
    const liveCard = (v) => `<a class="vid live-vid" href="https://www.youtube.com/watch?v=${esc(v.id)}" data-yt="${esc(v.id)}" data-title="${esc(v.title)}">
      <div class="vid-thumb"><img src="${esc(v.thumb)}" alt="" loading="lazy"><span class="live-badge">● LIVE</span><span class="vid-play">${ICON.play}</span></div>
      <div class="vid-t">${esc(v.title)}</div><div class="vid-s">${esc(v.channel)}</div></a>`;
    const when = (iso) => new Date(iso).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" });
    $("#pd").innerHTML =
      (p.live?.length ? `<h2>Live now <small>${p.live.length} match${p.live.length > 1 ? "es" : ""}</small></h2><div class="vid-grid">${p.live.map(liveCard).join("")}</div>`
        : `<h2>Live now</h2><div class="empty">No padel match live right now. Upcoming matches are listed below — this page checks every 5 minutes.</div>`) +
      (p.upcoming?.length ? `<h2>Coming up</h2><ol class="weekly">${p.upcoming.map((u) => `<li><div><b><a href="https://www.youtube.com/watch?v=${esc(u.id)}" target="_blank" rel="noopener">${esc(u.title)}</a></b><p>${esc(when(u.start))} · ${esc(u.channel)}</p></div></li>`).join("")}</ol>` : "") +
      `<h2>Replays & full matches</h2><div class="vid-grid">${(f.videos || []).slice(0, 24).map(videoCard).join("")}</div>` +
      `<h2>More sport on Live TV</h2><div class="tiles"><a class="tile" href="#tv"><div class="ico">${ICON.tv}</div><div><b>Sport channels</b><span>Red Bull TV, FIFA+, Tennis Channel, DAZN…</span></div></a></div>`;
    if (p.live?.length && !tvNow) playYT(p.live[0].id, p.live[0].title);   // start the first live court
  },

  async videos() {
    view.innerHTML = `<h1>Your <em>videos</em></h1><p class="lead">The latest from the YouTube channels you follow — no ads in the feed, no algorithm, plays right here.</p>
      <div class="tv-stage media-stage"><div class="tv-hint">Pick a video below</div></div>
      <div class="filters" id="yt-chips"></div>
      <form class="yt-add" id="yt-add"><input placeholder="Add a channel: paste its link or @name (e.g. @HugoDecrypte)" autocomplete="off"><button class="btn">Follow</button><small id="yt-err"></small></form>
      <div class="vid-grid" id="yt-grid"><div class="skeleton"></div></div>`;
    syncTvDock();
    let chans = (await api("/api/yt/channels")).channels || [];
    let cur = store.get("hub-yt-ch", ""), cat = store.get("hub-yt-cat", "");
    let extra = store.get("hub-yt-extra-cats", []);   // filters created by the user that have no channel yet
    const cats = () => [...new Set([...chans.map((c) => c.cat || "My channels"), ...extra])];
    const draw = async () => {
      store.set("hub-yt-ch", cur); store.set("hub-yt-cat", cat);
      $("#yt-chips").innerHTML = `<button class="chip${!cat && !cur ? " on" : ""}" data-k="">For you · mix</button><button class="chip trend-chip${cat === "__trending" ? " on" : ""}" data-k="__trending">Trending in France</button>` +
        cats().filter((k) => k !== "__trending").map((k) => `<button class="chip${cat === k && !cur ? " on" : ""}" data-k="${esc(k)}">${esc(k)}</button>`).join("") +
        `<button class="chip add-chip" id="yt-newcat">+ New filter</button><span style="width:100%"></span>` +
        chans.filter((c) => cat && (c.cat || "My channels") === cat).map((c) =>
        `<span class="chip ch-chip${cur === c.id ? " on" : ""}" data-c="${esc(c.id)}">${c.avatar ? `<img src="${esc(c.avatar)}" alt="">` : ""}${esc(c.title)}<button class="x" data-rm="${esc(c.id)}" title="Unfollow">✕</button></span>`).join("");
      $("#yt-grid").innerHTML = `<div class="skeleton"></div>`;
      $("#yt-add input").placeholder = cat ? `Add a channel to “${cat}”: paste its link or @name` : "Add a channel: paste its link or @name (pick a filter first to file it there)";
      let f;
      if (!cat && !cur) {   // "Latest" = everything mixed: all your channels (AI, padel, self-improvement, the trio…) + a trending video every 4
        const [mine, tr] = await Promise.all([api("/api/yt/feed"), api("/api/yt/trending")]);
        const out = [], t = [...(tr.videos || [])];
        (mine.videos || []).forEach((v, i) => { out.push(v); if (i % 3 === 2 && t.length) out.push(t.shift()); });
        f = { videos: out };
      } else f = cat === "__trending" && !cur ? await api("/api/yt/trending") : await api(`/api/yt/feed?${cur ? `ch=${encodeURIComponent(cur)}` : `cat=${encodeURIComponent(cat)}`}`);
      $("#yt-grid").innerHTML = (f.videos || []).map(videoCard).join("") ||
        `<div class="empty">${cat && !chans.some((c) => c.cat === cat) ? `“${esc(cat)}” is empty — add a channel to it with the box above.` : "No videos yet."}</div>`;
    };
    $("#yt-chips").onclick = async (e) => {
      if (e.target.closest("#yt-newcat")) {
        const chip = e.target.closest("#yt-newcat");
        chip.outerHTML = `<form class="chip add-chip" id="yt-newcat-form"><input placeholder="Filter name" maxlength="40" autofocus></form>`;
        const form = $("#yt-newcat-form"), inp = form.querySelector("input"); inp.focus();
        form.onsubmit = (ev) => { ev.preventDefault(); const n = inp.value.trim(); if (n) { extra = [...new Set([...extra, n])]; store.set("hub-yt-extra-cats", extra); cat = n; cur = ""; } draw(); };
        inp.onblur = () => form.requestSubmit();
        return;
      }
      const rm = e.target.closest("[data-rm]");
      if (rm) { e.stopPropagation(); await api(`/api/yt/channels/${rm.dataset.rm}`, { method: "DELETE" }); chans = chans.filter((c) => c.id !== rm.dataset.rm); if (cur === rm.dataset.rm) cur = ""; return draw(); }
      const k = e.target.closest("[data-k]"); if (k) { cat = k.dataset.k; cur = ""; return draw(); }
      const c = e.target.closest("[data-c]"); if (c) { cur = c.dataset.c; draw(); }
    };
    $("#yt-add").onsubmit = async (e) => {
      e.preventDefault(); const inp = e.target.querySelector("input"); $("#yt-err").textContent = "Looking for the channel…";
      const r = await api("/api/yt/channels", { method: "POST", body: JSON.stringify({ ref: inp.value, cat: cat || "My channels" }) });
      if (r.detail || r.error) { $("#yt-err").textContent = r.detail || r.error; return; }
      $("#yt-err").textContent = ""; inp.value = ""; if (!chans.some((c) => c.id === r.id)) chans.unshift(r); cur = r.id; draw();
    };
    if (cat && cat !== "__trending" && !cats().includes(cat)) cat = "";
    draw();
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
    view.innerHTML = `<h1>Live <em>TV</em></h1><p class="lead">Free channels from official broadcasters — films, series, news, kids. No account, no subscription.</p>
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

  async spotify() {
    view.innerHTML = `<h1>Spotify</h1><p class="lead">The official Spotify player, inside your hub. Log in once at
      <a href="https://open.spotify.com" target="_blank" rel="noopener"><b>open.spotify.com</b></a> in this browser to hear full tracks.</p>
      <div class="sp-top">
        <div class="sp-player" id="sp-player"></div>
        <div class="sp-side">
          <form class="sp-paste" id="sp-form"><label for="sp-url">Play anything from Spotify</label>
            <input id="sp-url" placeholder="Paste a Spotify link (song, album, artist, playlist, podcast)…" autocomplete="off">
            <button class="btn sp">Play</button><small id="sp-err"></small></form>
          <a class="tile" id="sp-app" href="spotify:"><div class="ico sp-ico">${ICON.sp}</div><div><b>Open in the Spotify app</b><span>Your installed app, same music</span></div></a>
          <p class="lead small">Tip: in the Spotify app, <b>Share → Copy link</b> on any song, then paste it here.</p>
        </div>
      </div>
      <div id="sp-lists"><div class="skeleton" style="margin-top:24px"></div></div>`;
    playSpotify(dockPath || store.get("hub-spotify", "playlist/37i9dQZEVXbIPWwFssbupI"));   // reuse the live player if any
    const d = await api("/api/spotify");
    const lists = d.playlists || [];
    const spCard = (p) => `
      <a class="poster square sp-card" href="https://open.spotify.com/playlist/${esc(p.id)}" data-sp="playlist/${esc(p.id)}" title="${esc(p.name)}">
        <div class="art"><div class="fallback">♫</div><img src="${esc(p.image)}" alt="" onerror="this.remove()"><span class="play-badge">▶</span></div>
        <div class="t">${esc(p.name)}</div><div class="s">${esc(p.mood)}</div></a>`;
    $("#sp-lists").innerHTML = `<div id="sp-mine"></div><h2>Picked for you <small>${lists.length} playlists</small></h2><div class="grid">${lists.map(spCard).join("")}</div>`;
    // the user's own playlists (needs a one-time connection)
    const [acc, mine] = await Promise.all([api("/api/spotify/account"), api("/api/spotify/mine")]);
    if (mine.connected) {
      $("#sp-mine").innerHTML = `<h2>Your playlists <small>${esc(mine.name || "")} · <a href="#" id="sp-out">disconnect</a></small></h2>
        <div class="grid">${mine.playlists.map(spCard).join("") || `<div class="empty">No playlists on this account yet.</div>`}</div>`;
      $("#sp-out").onclick = async (e) => { e.preventDefault(); await api("/api/spotify/logout", { method: "POST" }); pages.spotify(); };
    } else {
      $("#sp-mine").innerHTML = `<h2>Your playlists <small>connect once</small></h2>
        <div class="panel sp-connect">${acc.client_id ? `
          <p>Last step: allow Media Hub to read your playlists.</p><a class="btn sp" href="/api/spotify/login">Connect my Spotify account</a>
          <button class="btn ghost" id="sp-reset">Change Client ID</button>` : `
          <ol class="steps">
            <li>Open <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noopener"><b>developer.spotify.com/dashboard</b></a> and log in with your Spotify account.</li>
            <li><b>Create app</b> — name: <code>Media Hub</code>, description: <code>personal</code>, Redirect URI: <code>${esc(acc.redirect_uri)}</code> (click <b>Add</b>), tick <b>Web API</b>, then <b>Save</b>.</li>
            <li>In the app's <b>Settings</b>, copy the <b>Client ID</b> and paste it here:</li>
          </ol>
          <form id="sp-cid" class="sp-cid"><input placeholder="Client ID (32 characters)" maxlength="32" autocomplete="off"><button class="btn sp">Save</button><small id="sp-cid-err"></small></form>`}
        </div>`;
      $("#sp-reset")?.addEventListener("click", async () => { await api("/api/spotify/client", { method: "POST", body: JSON.stringify({ client_id: "" }) }); pages.spotify(); });
      $("#sp-cid")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const r = await api("/api/spotify/client", { method: "POST", body: JSON.stringify({ client_id: e.target.querySelector("input").value }) });
        if (r.error || r.detail) $("#sp-cid-err").textContent = r.detail || r.error; else pages.spotify();
      });
    }
    const cur = store.get("hub-spotify", "");
    document.querySelectorAll(".sp-card").forEach((c) => c.classList.toggle("on", c.dataset.sp === cur));
    $("#sp-form").onsubmit = (e) => {
      e.preventDefault();
      const p = parseSpotify($("#sp-url").value);
      $("#sp-err").textContent = p ? "" : "That doesn't look like a Spotify link.";
      if (p) { playSpotify(p); $("#sp-url").value = ""; }
    };
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
      `<h2>Louis de Funès <small>where to watch legally</small></h2><div class="tiles"><a class="tile nf-tile" href="https://www.netflix.com/search?q=louis%20de%20fun%C3%A8s" target="_blank" rel="noopener"><div class="ico nf-ico">N</div><div><b>On your Netflix</b><span>Search his films in your account</span></div></a><a class="tile" href="https://www.justwatch.com/fr/personne/louis-de-funes" target="_blank" rel="noopener"><div class="ico">${ICON.film}</div><div><b>Where is each film?</b><span>JustWatch: free replays, Netflix, Prime, rental…</span></div></a><a class="tile" href="#videos"><div class="ico">${ICON.play}</div><div><b>Archives & extracts</b><span>Gaumont + INA Stars, in your Videos</span></div></a></div>` +
      `<h2>More to watch</h2><div class="tiles"><a class="tile nf-tile" href="https://www.netflix.com/browse" target="_blank" rel="noopener">
        <div class="ico nf-ico">N</div><div><b>Netflix</b><span>Your Netflix account, opens in a new tab</span></div></a>
        <a class="tile" href="${appLink("jellyfin")}"><div class="ico">${ICON.film}</div><div><b>Films & séries</b><span>Your Jellyfin library</span></div></a><a class="tile" href="#tv"><div class="ico">${ICON.tv}</div><div><b>Live TV</b><span>Free channels: films, series, news, kids</span></div></a></div>` +
      `<h2>Free TV, films & documentaries <small><a href="#discover">see all →</a></small></h2><div class="cards">${free.map(entryCard).join("")}</div>`;
  },

  async listen() {
    view.innerHTML = `<h1>Listen</h1><p class="lead">Your music on Navidrome, live radio, podcasts and free streaming services.</p><div id="l"><div class="skeleton"></div></div>`;
    const [d] = await Promise.all([api("/api/listen"), loadCatalog()]);
    const radios = [...CATALOG.radios, ...(d.radios || []).filter((r) => !CATALOG.radios.some((c) => c.url === r.streamUrl))];
    const music = CATALOG.entries.filter((e) => e.category === "music");
    const pods = CATALOG.entries.filter((e) => e.category === "podcasts");
    $("#l").innerHTML =
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

  async search(q) {
    view.innerHTML = `<h1>Results for “${esc(q)}”</h1><div id="r"><div class="skeleton"></div></div>`;
    const [d] = await Promise.all([api(`/api/search?q=${encodeURIComponent(q)}`), loadCatalog()]);
    const any = d.jellyfin.length || d.navidrome.length || d.catalog.length;
    const sp = `<a class="tile sp-search" href="https://open.spotify.com/search/${encodeURIComponent(q)}" target="_blank" rel="noopener">
      <div class="ico sp-ico">♫</div><div><b>Search “${esc(q)}” on Spotify</b><span>Copy the link of what you find, then paste it on the Spotify page</span></div></a>`;
    $("#r").innerHTML = sp + (!any ? `<div class="empty" style="margin-top:14px">No matches in your library or the free catalog.</div>` : "") +
      row("Movies & TV", d.jellyfin) + row("Music", d.navidrome, { square: true }) +
      (d.catalog.length ? `<h2>Free & legal sites <small>${d.catalog.length}</small></h2><div class="cards">${d.catalog.map(entryCard).join("")}</div>` : "");
  },
};

/* ------------------------------------------------------------ router */
async function route() {
  const [name, query] = location.hash.slice(1).split("?");
  if (name.startsWith("app/")) {
    const ok = openApp(name.slice(4), new URLSearchParams(query || "").get("p"));
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === location.hash));
    if (ok) { syncDock(); syncTvDock(); return; }
  }
  closeApps();
  const page = pages[name] ? name : "home";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  try {
    if (page === "search") await pages.search(new URLSearchParams(query).get("q") || "");
    else await pages[page]();
  } catch (err) {
    view.innerHTML = `<div class="empty">Something went wrong loading this page: ${esc(err.message)}</div>`;
  }
  window.scrollTo(0, 0);
  syncDock(); syncTvDock();
  setTimeout(() => { syncDock(); syncTvDock(); }, 800);   // re-align once the page entrance animation has settled
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
const LIVE_PAGES = { journal: 10, ai: 30, home: 15, padel: 5, videos: 30, listen: 30 };   // minutes
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
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (!tvNow && !dockPath && audio.paused) location.reload(); });
  setInterval(() => navigator.serviceWorker.getRegistration().then((r) => r?.update()), 3600000);
}

/* ---- padel live alert: red LIVE badge in the menu + banner on the home page, checked every 5 minutes */
let PADEL_LIVE = [];
async function checkPadel() {
  const p = await api("/api/padel");
  PADEL_LIVE = p.live || [];
  const a = document.querySelector('#nav a[data-page="padel"]');
  if (a) a.classList.toggle("is-live", PADEL_LIVE.length > 0);
  const b = $("#padel-banner");
  if (b) b.innerHTML = PADEL_LIVE.length ? `<a class="padel-banner" href="#padel"><span class="live-badge">● LIVE</span>
    <b>Padel: ${PADEL_LIVE.length} match${PADEL_LIVE.length > 1 ? "es" : ""} live</b><span>${esc(PADEL_LIVE[0].title)}</span><span class="go">${ICON.arrow}</span></a>` : "";
}
checkPadel(); setInterval(checkPadel, 300000);

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

api("/api/config").then((c) => { CONFIG = c || {}; if (c.ports) PORTS = c.ports; }).finally(() => {
  $("#service-links").innerHTML = SERVICES.map(([id, name]) => `<a href="${appLink(id)}" data-app="${id}">▸ ${name}</a>`).join("");
  route();
});
