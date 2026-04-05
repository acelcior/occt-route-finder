const form = document.getElementById("route-form");
const fromInput = document.getElementById("from");
const toInput = document.getElementById("to");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const submitBtn = document.getElementById("submit-btn");
const themeToggle = document.getElementById("theme-toggle");
const clockEl = document.getElementById("clock");

let allStops = [];

// ============================================
// DARK MODE
// ============================================
function initTheme() {
  const isDark = localStorage.getItem("theme") === "dark";
  if (isDark) {
    document.documentElement.classList.add("dark-mode");
    themeToggle.textContent = "☀️";
  }
}

themeToggle.addEventListener("click", () => {
  const isDark = document.documentElement.classList.toggle("dark-mode");
  localStorage.setItem("theme", isDark ? "dark" : "light");
  themeToggle.textContent = isDark ? "☀️" : "🌙";
});

// ============================================
// REAL-TIME CLOCK
// ============================================
function updateClock() {
  const now = new Date();
  const hours = now.getHours();
  const minutes = now.getMinutes().toString().padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  const displayHours = hours % 12 || 12; // Convert 0 to 12 for 12 AM
  clockEl.textContent = `Current time: ${displayHours}:${minutes} ${ampm}`;
}

updateClock();
setInterval(updateClock, 1000);

// ============================================
// AUTOCOMPLETE
// ============================================
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

  suggestionsList.innerHTML = '';
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

// Close suggestions when clicking outside
document.addEventListener("click", (e) => {
  if (!e.target.closest(".autocomplete-wrapper")) {
    fromSuggestions.classList.remove("active");
    toSuggestions.classList.remove("active");
  }
});

// ============================================
// HTML ESCAPING
// ============================================
function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// ============================================
// RENDER RESULTS
// ============================================
function renderOptions(options) {
  resultsEl.innerHTML = options
    .map((opt, idx) => {
      const between =
        opt.stops_between.length > 0
          ? `<ul>${opt.stops_between.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`
          : "<p>No intermediate stops.</p>";

      const tripDuration = opt.trip_duration_minutes
        ? `<p><strong>Travel time:</strong> ${opt.trip_duration_minutes} minutes</p>`
        : "";

      return `
      <article class="route">
        <h3>Option ${idx + 1}: ${escapeHtml(opt.route_name)}</h3>
        <p>Walk <strong>${Math.round(opt.walk_to_stop_m)}m</strong> to <strong>${escapeHtml(opt.boarding_stop)}</strong></p>
        <div class="route-meta">
          <div>
            <strong>Depart:</strong> ${escapeHtml(opt.departure_time)}
          </div>
          <div>
            <strong>Arrive:</strong> ${escapeHtml(opt.arrival_time)}
          </div>
        </div>
        ${tripDuration}
        <p>Get off at <strong>${escapeHtml(opt.destination_stop)}</strong></p>
        <p>Walk <strong>${Math.round(opt.walk_from_stop_m)}m</strong> to destination</p>
        <details>
          <summary>Stops in between</summary>
          ${between}
        </details>
      </article>`;
    })
    .join("");
}

// ============================================
// FORM SUBMISSION
// ============================================
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const origin = fromInput.value.trim();
  const destination = toInput.value.trim();
  if (!origin || !destination) {
    statusEl.textContent = "Please enter both From and To.";
    statusEl.className = "status error";
    return;
  }

  submitBtn.disabled = true;
  statusEl.className = "status";
  statusEl.textContent = "Finding routes...";
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

    statusEl.textContent = `Found ${data.options.length} route option(s).`;
    renderOptions(data.options);
  } catch (err) {
    statusEl.textContent = err.message || "Unexpected error.";
    statusEl.className = "status error";
  } finally {
    submitBtn.disabled = false;
  }
});

// ============================================
// INITIALIZATION
// ============================================
initTheme();
loadStops();

