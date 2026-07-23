const FLOOD_INTERVAL_SEC = 5 * 60;

function statusOf(s) { return s.flood_risk; }
function labelOf(s) { return s.label; }

function buildStationCard(s) {
  const card = document.createElement("div");
  card.className = "station-card";

  const h3 = document.createElement("h3");
  const nameSpan = document.createElement("span");
  nameSpan.textContent = s.label;
  const badge = document.createElement("span");
  badge.className = `status-badge status-${s.flood_risk}`;
  badge.textContent = s.flood_risk;
  h3.append(nameSpan, badge);
  card.appendChild(h3);

  const updated = document.createElement("div");
  updated.className = "updated-line";
  updated.style.margin = "0 0 0.4rem";
  updated.textContent = s.last_updated ? `Updated ${formatAge(s.last_updated)}` : "No readings yet";
  card.appendChild(updated);

  const dl = document.createElement("dl");
  dl.className = "reading-grid";
  const rows = [
    ["Soil moisture", s.soil_sensor_installed ? fmt(s.soil_moisture_pct, 0, "%") : "not installed"],
    ["Rain rate", fmt(s.rain_rate_in_hr, 2, " in/hr")],
    ["Rain today", fmt(s.rain_daily_in, 2, " in")],
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
  reason.textContent = s.flood_risk_reason;
  card.appendChild(reason);

  return card;
}

async function refreshFlood() {
  try {
    const flood = await fetchJSON("/data/flood.json");
    showStaleBanner(flood.updated, FLOOD_INTERVAL_SEC, "flood readings");
    document.getElementById("flood-updated").textContent = `Last updated: ${formatAge(flood.updated)}`;

    const indicator = document.getElementById("overall-indicator");
    indicator.textContent = "";
    const dot = document.createElement("div");
    dot.className = `dot status-${flood.overall_flood_risk}`;
    const label = document.createElement("div");
    label.className = "label";
    label.textContent = `Overall flood risk: ${flood.overall_flood_risk}`;
    indicator.append(dot, label);

    renderNodeMap(document.getElementById("node-map"), flood.stations, statusOf, labelOf);

    const grid = document.getElementById("station-grid");
    grid.textContent = "";
    flood.stations.forEach((s) => grid.appendChild(buildStationCard(s)));
  } catch (e) {
    document.getElementById("station-grid").textContent = "Live flood data is currently unavailable.";
    console.error(e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  refreshFlood();
  setInterval(refreshFlood, 60000);
});
