const form = document.getElementById("route-form");
const fromInput = document.getElementById("from");
const toInput = document.getElementById("to");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const submitBtn = document.getElementById("submit-btn");
const themeToggle = document.getElementById("theme-toggle");
const clockEl = document.getElementById("clock");

let allStops = [];

function initTheme() {
  const saved = localStorage.getItem("theme");
  if (saved === "light") {
    document.documentElement.classList.remove("dark-mode");
    themeToggle.textContent = "🌙";
    themeToggle.setAttribute("aria-label", "Switch to dark mode");
  } else {
    document.documentElement.classList.add("dark-mode");
    themeToggle.textContent = "☀️";
    themeToggle.setAttribute("aria-label", "Switch to light mode");
  }
}

themeToggle.addEventListener("click", () => {
  const isDark = document.documentElement.classList.toggle("dark-mode");
  localStorage.setItem("theme", isDark ? "dark" : "light");
  themeToggle.textContent = isDark ? "☀️" : "🌙";
  themeToggle.setAttribute(
    "aria-label",
    isDark ? "Switch to light mode" : "Switch to dark mode"
  );
});

function updateClock() {
  const now = new Date();
  const hours = now.getHours();
  const minutes = now.getMinutes().toString().padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  const displayHours = hours % 12 || 12;
  clockEl.textContent = `Current time: ${displayHours}:${minutes} ${ampm}`;
}

updateClock();
setInterval(updateClock, 1000);

async function loadStops() {
  try {
    const res = await fetch("/api/stops");
    const data = await res.json();
    allStops = data.stops || [];
  } catch (err) {
    console.error("Failed to load stops:", err);
    allStops = [];
  }
}

function filterStops(query) {
  if (!query) return [];
  const lower = query.toLowerCase();
  return allStops.filter((stop) => stop.toLowerCase().includes(lower)).slice(0, 8);
}

function showSuggestions(input, suggestionsList) {
  const query = input.value.trim();
  const matches = filterStops(query);

  suggestionsList.innerHTML = "";
  if (matches.length > 0) {
    suggestionsList.classList.add("active");
    matches.forEach((stop) => {
      const li = document.createElement("li");
      li.textContent = stop;
      li.addEventListener("click", () => {
        input.value = stop;
        suggestionsList.classList.remove("active");
      });
      suggestionsList.appendChild(li);
    });
  } else {
    suggestionsList.classList.remove("active");
  }
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

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderOptions(options) {
  resultsEl.innerHTML = options
    .map((opt, idx) => {
      const between =
        opt.stops_between.length > 0
          ? `<ul class="between-stops">${opt.stops_between
              .map((s) => `<li>${escapeHtml(s)}</li>`)
              .join("")}</ul>`
          : '<p class="between-empty">No intermediate stops on this segment.</p>';

      const tripDuration =
        opt.trip_duration_minutes != null
          ? `<p class="meta-line"><span class="meta-label">Ride time</span> ~${opt.trip_duration_minutes} min</p>`
          : "";

      return `
      <article class="route-card">
        <div class="route-card__head">
          <span class="route-card__badge">Option ${idx + 1}</span>
          <h2 class="route-card__title">${escapeHtml(opt.route_name)}</h2>
        </div>

        <div class="route-card__block">
          <span class="step-label">Board here</span>
          <p class="step-value">${escapeHtml(opt.boarding_stop)}</p>
          <p class="step-sub">About <strong>${Math.round(opt.walk_to_stop_m)} m</strong> walk from your start</p>
        </div>

        <div class="route-card__times">
          <div>
            <span class="time-label">Depart</span>
            <span class="time-value">${escapeHtml(opt.departure_time)}</span>
          </div>
          <div>
            <span class="time-label">Arrive</span>
            <span class="time-value">${escapeHtml(opt.arrival_time)}</span>
          </div>
        </div>
        ${tripDuration}

        <div class="route-card__block route-card__block--exit">
          <span class="step-label">Get off here</span>
          <p class="step-value get-off-stop">${escapeHtml(opt.destination_stop)}</p>
          <p class="step-sub">Then <strong>${Math.round(opt.walk_from_stop_m)} m</strong> walk to your destination</p>
        </div>

        <details class="route-details">
          <summary>Stops in between</summary>
          ${between}
        </details>
      </article>`;
    })
    .join("");
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const origin = fromInput.value.trim();
  const destination = toInput.value.trim();
  if (!origin || !destination) {
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
      body: JSON.stringify({ origin, destination }),
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || "Failed to fetch routes.");
    }

    statusEl.textContent = `${data.options.length} route option(s) found.`;
    statusEl.className = "status status--ok";
    renderOptions(data.options);
  } catch (err) {
    statusEl.textContent = err.message || "Unexpected error.";
    statusEl.className = "status status--error";
  } finally {
    submitBtn.disabled = false;
  }
});

initTheme();
loadStops();
