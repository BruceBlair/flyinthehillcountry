const FLIGHT_INTERVAL_SEC = 5 * 60;

function statusOf(s) { return s.status; }
function labelOf(s) { return s.label; }

function buildStationCard(s) {
  const card = document.createElement("div");
  card.className = "station-card";

  const h3 = document.createElement("h3");
  const nameSpan = document.createElement("span");
  nameSpan.textContent = s.label;
  const badge = document.createElement("span");
  badge.className = `status-badge status-${s.status}`;
  badge.textContent = s.status;
  h3.append(nameSpan, badge);
  card.appendChild(h3);

  const dl = document.createElement("dl");
  dl.className = "reading-grid";
  const rows = [
    ["Sustained wind", fmt(s.wind_speed_mph, 1, " mph")],
    ["Gust", fmt(s.wind_gust_mph, 1, " mph")],
    ["Direction", fmt(s.wind_dir_deg, 0, "°")],
  ];
  rows.forEach(([label, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.append(dt, dd);
  });
  card.appendChild(dl);

  const reason = document.createElement("p");
  reason.className = "reason";
  reason.textContent = s.reason;
  card.appendChild(reason);

  return card;
}

async function refreshFlight() {
  try {
    const flight = await fetchJSON("/data/flight-conditions.json");
    showStaleBanner(flight.updated, FLIGHT_INTERVAL_SEC, "wind readings");
    document.getElementById("flight-updated").textContent = `Last updated: ${formatAge(flight.updated)}`;

    const indicator = document.getElementById("overall-indicator");
    indicator.textContent = "";
    const dot = document.createElement("div");
    dot.className = `dot status-${flight.overall_status}`;
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = `Overall: ${flight.overall_status}`;
    indicator.append(dot, label);

    renderNodeMap(document.getElementById("node-map"), flight.stations, statusOf, labelOf);

    const grid = document.getElementById("station-grid");
    grid.textContent = "";
    flight.stations.forEach((s) => grid.appendChild(buildStationCard(s)));

    const t = flight.thresholds_mph;
    document.getElementById("thresholds").textContent =
      `Thresholds — no-go: gust ≥ ${t.gust_no_go} mph or sustained ≥ ${t.sustained_no_go} mph; `
      + `caution: gust ≥ ${t.gust_caution} mph or sustained ≥ ${t.sustained_caution} mph.`;
  } catch (e) {
    document.getElementById("station-grid").textContent = "Live wind data is currently unavailable.";
    console.error(e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  refreshFlight();
  setInterval(refreshFlight, 60000);
});
