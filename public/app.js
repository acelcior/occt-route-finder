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
let allStops = [];

/* ---------- theme + clock ---------- */
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) { /* private mode */ }
  const dark = saved !== "light";
  document.documentElement.classList.toggle("dark-mode", dark);
  themeToggle.textContent = dark ? "☀️" : "🌙";
  themeToggle.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
}
themeToggle.addEventListener("click", () => {
  const isDark = document.documentElement.classList.toggle("dark-mode");
  try { localStorage.setItem("theme", isDark ? "dark" : "light"); } catch (e) { /* ignore */ }
  themeToggle.textContent = isDark ? "☀️" : "🌙";
  themeToggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
});

function updateClock() {
  const now = new Date();
  const h = now.getHours();
  const m = now.getMinutes().toString().padStart(2, "0");
  clockEl.textContent = `Current time: ${h % 12 || 12}:${m} ${h >= 12 ? "PM" : "AM"}`;
}
updateClock();
setInterval(updateClock, 1000);

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
function stampText(stamp, estimated) {
  const t = `${estimated ? "~" : ""}${stamp.text}`;
  return stamp.same_day ? t : `${t} <span class="day">${escapeHtml(stamp.day)}</span>`;
}
function timeText(stop) {
  return `${stop.estimated ? "~" : ""}${escapeHtml(stop.time)}`;
}

/* ---------- autocomplete ---------- */
async function loadStops() {
  try {
    const res = await fetch("/api/stops");
    const data = await res.json();
    allStops = data.stops || [];
  } catch (err) {
    allStops = [];
  }
}
function showSuggestions(input, list) {
  const q = input.value.trim().toLowerCase();
  const matches = q ? allStops.filter((s) => s.toLowerCase().includes(q)).slice(0, 8) : [];
  list.innerHTML = "";
  list.classList.toggle("active", matches.length > 0);
  matches.forEach((stop) => {
    const li = document.createElement("li");
    li.setAttribute("role", "option");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = stop;
    btn.addEventListener("click", () => {
      input.value = stop;
      list.classList.remove("active");
      input.focus();
    });
    li.appendChild(btn);
    list.appendChild(li);
  });
}
const fromSuggestions = document.getElementById("from-suggestions");
const toSuggestions = document.getElementById("to-suggestions");
fromInput.addEventListener("input", () => showSuggestions(fromInput, fromSuggestions));
toInput.addEventListener("input", () => showSuggestions(toInput, toSuggestions));
document.addEventListener("click", (e) => {
  if (!e.target.closest(".autocomplete-wrapper")) {
    fromSuggestions.classList.remove("active");
    toSuggestions.classList.remove("active");
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    fromSuggestions.classList.remove("active");
    toSuggestions.classList.remove("active");
  }
});

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
  (alerts || []).forEach((a) => items.push(`<p class="alert alert--service">⚠️ ${escapeHtml(a)}</p>`));
  (warnings || []).forEach((w) => {
    const text = w.replace(/^[a-z_]+:\s*/, "");
    items.push(`<p class="alert">ℹ️ ${escapeHtml(text)}</p>`);
  });
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
      `Schedule: <strong>${escapeHtml(m.dataset.label)}</strong> · OCCT pages checked ${escapeHtml(fetchedText)} · ` +
      `Today: ${escapeHtml(m.today.profile)} service (${escapeHtml(m.today.status)})` +
      ` · <a href="https://occtransport.org/news.html" target="_blank" rel="noopener">OCCT news</a>` +
      ` · <a href="${ETA_URL}" target="_blank" rel="noopener">Live buses</a>`;
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
    return `<li class="leg leg--walk">🚶 ${kind} <strong>${leg.minutes} min</strong> (${leg.meters} m) to <strong>${escapeHtml(leg.to)}</strong></li>`;
  }
  const between = leg.stops.slice(1, -1);
  const stopsHtml = between.length
    ? `<details class="route-details"><summary>${between.length} stop${between.length === 1 ? "" : "s"} in between</summary>
         <ul class="between-stops">${between.map((s) => `<li>${escapeHtml(s.name)} <span class="t-muted">${timeText(s)}</span></li>`).join("")}</ul>
       </details>`
    : "";
  const badge = leg.late_nite ? '<span class="route-badge route-badge--late">Late Nite</span>' : "";
  const dir = [leg.direction_label, leg.headsign].filter(Boolean).join(" · ");
  const note = leg.note ? `<p class="leg__note">${escapeHtml(leg.note)}</p>` : "";
  return `<li class="leg leg--ride">
    <div class="leg__line">🚌 <strong>${escapeHtml(leg.line_name)}</strong> ${badge}<span class="leg__dir">${escapeHtml(dir)}</span></div>
    <div class="leg__stop"><span class="step-label">Board</span> <strong>${escapeHtml(leg.board.name)}</strong> at <strong class="time-value">${timeText(leg.board)}</strong></div>
    <div class="leg__stop leg__stop--off"><span class="step-label">Get off</span> <strong>${escapeHtml(leg.alight.name)}</strong> at <strong class="time-value">${timeText(leg.alight)}</strong> <span class="t-muted">(${leg.ride_minutes} min ride)</span></div>
    ${note}${stopsHtml}
  </li>`;
}

function renderJourney(j, idx) {
  const badges = [];
  if (j.walk_only) badges.push('<span class="route-badge">Walk only</span>');
  if (j.late_nite) badges.push('<span class="route-badge route-badge--late">Late Nite</span>');
  if (j.has_estimates) badges.push('<span class="route-badge route-badge--est" title="Times marked ~ are estimated between published timepoints">~ estimated</span>');
  const xfer = j.transfers === 0 ? "direct" : `${j.transfers} transfer${j.transfers === 1 ? "" : "s"}`;
  return `<article class="route-card journey">
    <div class="route-card__head">
      <span class="route-card__badge">Option ${idx + 1}</span>${badges.join("")}
    </div>
    <div class="journey__times">
      <span class="time-value">${stampText(j.depart, false)}</span> <span class="arrow">→</span>
      <span class="time-value">${stampText(j.arrive, false)}</span>
    </div>
    <p class="meta-line">${j.duration_min} min · ${xfer} · ${j.walk_min} min walking</p>
    <ol class="legs">${j.legs.map(renderLeg).join("")}</ol>
  </article>`;
}

function renderUntimed(u) {
  return `<article class="route-card untimed">
    <div class="route-card__head"><span class="route-badge">No timetable</span>
      <h2 class="route-card__title">${escapeHtml(u.line_name)} — ${escapeHtml(u.service)}</h2></div>
    <p class="meta-line">Runs continuously ${escapeHtml(u.hours)}, ${escapeHtml(u.days.join("–").replace(/^Mon–.*Fri$/, "Mon–Fri"))}.
      Board at <strong>${escapeHtml(u.board)}</strong> (${u.walk_to_min} min walk), get off at <strong>${escapeHtml(u.alight)}</strong> (${u.walk_from_min} min walk).</p>
    <p class="step-sub">${escapeHtml(u.note)} <a href="${ETA_URL}" target="_blank" rel="noopener">Open ETA Transit</a></p>
  </article>`;
}

function renderResults(data) {
  const parts = [];
  if (data.message) parts.push(`<div class="ranking-note" role="note"><p>${escapeHtml(data.message)}</p></div>`);
  parts.push(...data.journeys.map(renderJourney));
  parts.push(...(data.untimed_services || []).map(renderUntimed));
  if (data.journeys.some((j) => j.has_estimates)) {
    parts.push('<p class="legend">Times marked <strong>~</strong> are estimated between the timepoints OCCT publishes.</p>');
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
