const form = document.getElementById("route-form");
const fromInput = document.getElementById("from");
const toInput = document.getElementById("to");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const submitBtn = document.getElementById("submit-btn");

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
          ? `<ul>${opt.stops_between.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`
          : "<p>No intermediate stops.</p>";

      return `
      <article class="route">
        <h3>Option ${idx + 1}: ${escapeHtml(opt.route_name)}</h3>
        <p>Walk <strong>${Math.round(opt.walk_to_stop_m)}m</strong> to <strong>${escapeHtml(opt.boarding_stop)}</strong></p>
        <p>Depart: <strong>${escapeHtml(opt.departure_time)}</strong></p>
        <p>Get off at <strong>${escapeHtml(opt.destination_stop)}</strong></p>
        <p>Arrive: <strong>${escapeHtml(opt.arrival_time)}</strong></p>
        <p>Walk <strong>${Math.round(opt.walk_from_stop_m)}m</strong> to destination</p>
        <details>
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

