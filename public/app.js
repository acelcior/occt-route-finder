const form = document.getElementById("route-form");
const fromInput = document.getElementById("from");
const toInput = document.getElementById("to");
const modeSelect = document.getElementById("mode");
const whenField = document.getElementById("when-field");
const whenInput = document.getElementById("when");
const accessSelect = document.getElementById("access");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const alertsEl = document.getElementById("alerts");
const metaEl = document.getElementById("meta");
const submitBtn = document.getElementById("submit-btn");
const themeToggle = document.getElementById("theme-toggle");
const clockEl = document.getElementById("clock");

const ETA_URL = "https://binghamtonupublic.etaspot.net/";
let entries = []; // [{name, aliases}]

/* ---------- theme + clock ---------- */
function applyTheme(dark) {
  document.documentElement.classList.toggle("dark-mode", dark);
  themeToggle.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  themeToggle.setAttribute("aria-pressed", String(dark));
}
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) { /* private mode */ }
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved ? saved === "dark" : prefersDark);
}
themeToggle.addEventListener("click", () => {
  const dark = !document.documentElement.classList.contains("dark-mode");
  applyTheme(dark);
  try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch (e) { /* ignore */ }
});

function updateClock() {
  const now = new Date();
  const h = now.getHours();
  const m = now.getMinutes().toString().padStart(2, "0");
  clockEl.textContent = `Now: ${now.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} · ${h % 12 || 12}:${m} ${h >= 12 ? "PM" : "AM"}`;
}
updateClock();
setInterval(updateClock, 15000);

/* ---------- helpers ---------- */
function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function localIsoMinutes(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
function stampText(stamp) {
  return stamp.same_day
    ? escapeHtml(stamp.text)
    : `${escapeHtml(stamp.text)} <span class="day">${escapeHtml(stamp.day)}</span>`;
}
function timeText(stop) {
  return `${stop.estimated ? "~" : ""}${escapeHtml(stop.time)}`;
}

/* ---------- autocomplete ---------- */
const norm = (s) => s.toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim();
const wordStart = (hay, q) => hay.split(" ").some((w) => w.startsWith(q));

// Lower rank = better. "union" → University Union (word start) beats a mid-word hit;
// alias hits ("Union University", "UU") still surface, labelled with what matched.
function rankEntry(q, e) {
  const nn = norm(e.name);
  if (nn.startsWith(q)) return [0, null];
  if (wordStart(nn, q)) return [1, null];
  if (nn.includes(q)) return [2, null];
  const qw = q.split(" ");
  if (qw.length > 1 && qw.every((w) => wordStart(nn, w))) return [3, null];
  for (const a of e.aliases) {
    const na = norm(a);
    if (na === q || na.startsWith(q) || wordStart(na, q)) return [4, a];
    if (na.includes(q)) return [5, a];
  }
  return null;
}
function matchEntries(query) {
  const q = norm(query);
  if (!q) return [];
  const scored = [];
  for (const e of entries) {
    const r = rankEntry(q, e);
    if (r) scored.push({ rank: r[0], via: r[1], e });
  }
  scored.sort((a, b) => a.rank - b.rank || a.e.name.length - b.e.name.length || a.e.name.localeCompare(b.e.name));
  return scored.slice(0, 8);
}
function highlight(name, query) {
  const i = name.toLowerCase().indexOf(query.toLowerCase());
  if (i < 0 || !query) return escapeHtml(name);
  return `${escapeHtml(name.slice(0, i))}<mark>${escapeHtml(name.slice(i, i + query.length))}</mark>${escapeHtml(name.slice(i + query.length))}`;
}

async function loadStops() {
  try {
    const res = await fetch("/api/stops");
    const data = await res.json();
    entries = Array.isArray(data.entries) ? data.entries : (data.stops || []).map((name) => ({ name, aliases: [] }));
  } catch (err) {
    entries = [];
  }
}

function setupAutocomplete(input, list) {
  let items = [];
  let active = -1;

  function close() {
    list.classList.remove("active");
    list.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    items = [];
    active = -1;
  }
  function pick(i) {
    if (i < 0 || i >= items.length) return;
    input.value = items[i].e.name;
    close();
  }
  function render() {
    const q = input.value.trim();
    items = matchEntries(q);
    active = -1;
    list.innerHTML = "";
    if (!items.length) { close(); return; }
    items.forEach((it, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.id = `${list.id}-${i}`;
      li.setAttribute("aria-selected", "false");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.tabIndex = -1;
      btn.innerHTML = `<span>${highlight(it.e.name, q)}</span>` +
        (it.via ? `<span class="sugg-alias">also called <b>${escapeHtml(it.via)}</b></span>` : "");
      btn.addEventListener("mousedown", (e) => { e.preventDefault(); pick(i); });
      li.appendChild(btn);
      list.appendChild(li);
    });
    list.classList.add("active");
    input.setAttribute("aria-expanded", "true");
  }
  function setActive(i) {
    active = i;
    [...list.children].forEach((li, k) => li.setAttribute("aria-selected", String(k === i)));
    if (i >= 0) {
      input.setAttribute("aria-activedescendant", list.children[i].id);
      list.children[i].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  input.addEventListener("input", render);
  input.addEventListener("focus", () => { if (input.value.trim()) render(); });
  input.addEventListener("keydown", (e) => {
    const open = list.classList.contains("active") && items.length > 0;
    if (e.key === "ArrowDown" && open) { e.preventDefault(); setActive((active + 1) % items.length); }
    else if (e.key === "ArrowUp" && open) { e.preventDefault(); setActive((active - 1 + items.length) % items.length); }
    else if (e.key === "Enter" && open) {
      // Enter completes the suggestion (highlighted one, else the best match)
      // instead of submitting a half-typed name.
      const exact = items.some((it) => it.e.name.toLowerCase() === input.value.trim().toLowerCase());
      if (active >= 0 || !exact) { e.preventDefault(); pick(active >= 0 ? active : 0); }
      else close();
    }
    else if (e.key === "Tab" && open) { pick(active >= 0 ? active : 0); }
    else if (e.key === "Escape") { close(); }
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
}
setupAutocomplete(fromInput, document.getElementById("from-suggestions"));
setupAutocomplete(toInput, document.getElementById("to-suggestions"));

/* ---------- mode / time controls ---------- */
function syncModeUI() {
  const needsTime = modeSelect.value !== "now";
  whenField.hidden = !needsTime;
  if (needsTime && !whenInput.value) whenInput.value = localIsoMinutes(new Date());
}
modeSelect.addEventListener("change", syncModeUI);

/* ---------- meta + alerts ---------- */
function renderBanners(warnings, alerts) {
  const items = [];
  (alerts || []).forEach((a) => items.push(`<p>⚠️ ${escapeHtml(a)}</p>`));
  (warnings || []).forEach((w) => items.push(`<p class="alert--info">ℹ️ ${escapeHtml(w.replace(/^[a-z_]+:\s*/, ""))}</p>`));
  alertsEl.innerHTML = items.join("");
  alertsEl.hidden = items.length === 0;
}
async function loadMeta() {
  try {
    const res = await fetch("/api/meta");
    const m = await res.json();
    const fetched = m.dataset.fetched_at ? new Date(m.dataset.fetched_at) : null;
    const fetchedText = fetched
      ? fetched.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
      : "unknown";
    metaEl.innerHTML =
      `Schedule: ${escapeHtml(m.dataset.label)} · OCCT pages checked ${escapeHtml(fetchedText)} · ` +
      `Today: ${escapeHtml(m.today.profile)} service (${escapeHtml(m.today.status)})`;
    renderBanners(m.warnings, m.alerts);
  } catch (err) {
    metaEl.textContent = "Schedule information unavailable.";
  }
}

/* ---------- rendering ---------- */
function renderLeg(leg) {
  if (leg.type === "walk") {
    if (leg.minutes === 0) return "";
    const kind = leg.transfer ? "Transfer: walk" : "Walk";
    return `<li class="leg leg--walk">🚶 ${kind} <b>${leg.minutes} min</b> (${leg.meters} m) to <b>${escapeHtml(leg.to)}</b></li>`;
  }
  const between = leg.stops.slice(1, -1);
  const stopsHtml = between.length
    ? `<details class="route-details"><summary>${between.length} stop${between.length === 1 ? "" : "s"} in between</summary>
         <ul class="between-stops">${between.map((s) => `<li>${escapeHtml(s.name)} <span class="t-muted">${timeText(s)}</span></li>`).join("")}</ul>
       </details>`
    : "";
  const badge = leg.late_nite ? '<span class="chip chip-eve">Late Nite</span>' : "";
  const dir = [leg.direction_label, leg.headsign].filter(Boolean).join(" · ");
  const note = leg.note ? `<p class="leg__note">${escapeHtml(leg.note)}</p>` : "";
  return `<li class="leg leg--ride">
    <div class="leg__line">🚌 <b>${escapeHtml(leg.line_name)}</b> ${badge}<span class="leg__dir">${escapeHtml(dir)}</span></div>
    <div class="leg__stop">Board <b>${escapeHtml(leg.board.name)}</b> at <span class="time">${timeText(leg.board)}</span></div>
    <div class="leg__stop leg__stop--off">Get off <b>${escapeHtml(leg.alight.name)}</b> at <span class="time">${timeText(leg.alight)}</span> <span class="t-muted">(${leg.ride_minutes} min ride)</span></div>
    ${note}${stopsHtml}
  </li>`;
}

function renderJourney(j, idx) {
  const chips = [];
  if (j.walk_only) chips.push('<span class="chip chip-int">Walk only</span>');
  else if (j.transfers === 0) chips.push('<span class="chip chip-run">Direct</span>');
  else chips.push(`<span class="chip chip-off">${j.transfers} transfer${j.transfers === 1 ? "" : "s"}</span>`);
  if (j.late_nite) chips.push('<span class="chip chip-eve">Late Nite</span>');
  if (j.has_estimates) chips.push('<span class="chip chip-off" title="Times marked ~ are estimated between published timepoints">~ estimated</span>');
  return `<article class="box journey">
    <div class="box-head"><h2>Option ${idx + 1}</h2><div class="chips">${chips.join("")}</div></div>
    <div class="box-body">
      <div class="journey-times">
        <span>${stampText(j.depart)}</span><span class="arrow">→</span><span>${stampText(j.arrive)}</span>
      </div>
      <p class="journey-meta">${j.duration_min} min total · ${j.walk_min} min walking</p>
      <ol class="legs">${j.legs.map(renderLeg).join("")}</ol>
    </div>
  </article>`;
}

function renderUntimed(u) {
  const days = u.days.length === 5 ? "Mon–Fri" : u.days.join(", ");
  return `<article class="box untimed">
    <div class="box-head"><h2>${escapeHtml(u.line_name)} — ${escapeHtml(u.service)}</h2><div class="chips"><span class="chip chip-off">No timetable</span></div></div>
    <div class="box-body">
      <p>Runs continuously <b>${escapeHtml(u.hours)}</b>, ${escapeHtml(days)}. Board at <b>${escapeHtml(u.board)}</b> (${u.walk_to_min} min walk), get off at <b>${escapeHtml(u.alight)}</b> (${u.walk_from_min} min walk).</p>
      <p class="t-muted" style="margin-top:6px">${escapeHtml(u.note)} <a href="${ETA_URL}" target="_blank" rel="noopener">Open ETA Transit</a></p>
    </div>
  </article>`;
}

function renderResults(data) {
  const parts = [];
  if (data.message) parts.push(`<div class="notice-box">${escapeHtml(data.message)}</div>`);
  parts.push(...data.journeys.map(renderJourney));
  parts.push(...(data.untimed_services || []).map(renderUntimed));
  if (data.journeys.some((j) => j.has_estimates)) {
    parts.push('<p class="legend">Times marked <b>~</b> are estimated between the timepoints OCCT publishes.</p>');
  }
  resultsEl.innerHTML = parts.join("");
}

/* ---------- query ---------- */
function currentQuery() {
  const q = {
    origin: fromInput.value.trim(),
    destination: toInput.value.trim(),
    mode: modeSelect.value,
    access_m: Number(accessSelect.value),
  };
  if (q.mode !== "now" && whenInput.value) q.when = whenInput.value;
  return q;
}
function syncUrl(q) {
  const p = new URLSearchParams({ from: q.origin, to: q.destination, mode: q.mode, access_m: String(q.access_m) });
  if (q.when) p.set("when", q.when);
  history.replaceState(null, "", `?${p.toString()}`);
}
function loadFromUrl() {
  const p = new URLSearchParams(location.search);
  if (!p.get("from") || !p.get("to")) return false;
  fromInput.value = p.get("from").slice(0, 120);
  toInput.value = p.get("to").slice(0, 120);
  if (["now", "depart", "arrive"].includes(p.get("mode"))) modeSelect.value = p.get("mode");
  if (p.get("when")) whenInput.value = p.get("when");
  if ([...accessSelect.options].some((o) => o.value === p.get("access_m"))) accessSelect.value = p.get("access_m");
  syncModeUI();
  return true;
}

async function runQuery() {
  const q = currentQuery();
  if (!q.origin || !q.destination) {
    statusEl.textContent = "Please enter both From and To.";
    statusEl.className = "status status--error";
    return;
  }
  submitBtn.disabled = true;
  statusEl.className = "status";
  statusEl.textContent = "Finding routes…";
  resultsEl.innerHTML = "";
  try {
    const res = await fetch("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(q),
    });
    const data = await res.json();
    if (!res.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
      throw new Error(detail || "Failed to fetch routes.");
    }
    if (!Array.isArray(data.journeys)) {
      // An old copy of this page talking to a newer API (or vice versa).
      throw new Error("This page is out of date — reload it to get the latest planner.");
    }
    syncUrl(q);
    const n = data.journeys.length;
    const resolved = `${data.origin.resolved} → ${data.destination.resolved}`;
    statusEl.textContent = n
      ? `${n} option${n === 1 ? "" : "s"} for ${resolved}, earliest arrival first.`
      : `No timed options for ${resolved}.`;
    statusEl.className = n ? "status status--ok" : "status status--error";
    renderBanners(data.warnings, data.alerts);
    renderResults(data);
  } catch (err) {
    statusEl.textContent = err.message || "Unexpected error.";
    statusEl.className = "status status--error";
  } finally {
    submitBtn.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  runQuery();
});

initTheme();
syncModeUI();
loadStops();
loadMeta().then(() => {
  if (loadFromUrl()) runQuery();
});
