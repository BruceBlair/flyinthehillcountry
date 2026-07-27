const FLOOD_INTERVAL_SEC = 5 * 60;

function statusOf(s) { return s.flood_risk; }
function labelOf(s) { return s.label; }
function kindOf(s) { return s.kind || "native"; }

function buildGaugeCard(g) {
  const card = document.createElement("div");
  card.className = "station-card";

  const h3 = document.createElement("h3");
  const nameSpan = document.createElement("span");
  nameSpan.textContent = g.name;
  const badge = document.createElement("span");
  badge.className = "status-badge status-unknown";
  badge.textContent = `${g.distance_mi} mi`;
  h3.append(nameSpan, badge);
  card.appendChild(h3);

  const updated = document.createElement("div");
  updated.className = "updated-line";
  updated.style.margin = "0 0 0.4rem";
  updated.textContent = g.last_updated ? `Updated ${formatAge(g.last_updated)}` : "No reading";
  card.appendChild(updated);

  const dl = document.createElement("dl");
  dl.className = "reading-grid";
  const rows = [
    ["Gage height", fmt(g.gage_height_ft, 2, " ft")],
    ["Discharge", fmt(g.discharge_cfs, 1, " ft³/s")],
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
  reason.textContent = `USGS site ${g.site_no}`;
  card.appendChild(reason);

  return card;
}

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

    const merged = flood.stations.map((s) => ({ ...s, kind: "native" }));
    let gauges = [];
    try {
      const gaugeData = await fetchJSON("/data/external-flood-gauges.json");
      gauges = gaugeData.gauges || [];
      gauges.forEach((g) => merged.push({
        lat: g.lat,
        lon: g.lon,
        kind: "gauge",
        flood_risk: "unknown",
        label: `USGS gauge: ${g.name} (${g.distance_mi} mi)`,
      }));
    } catch (e) { /* external-flood-gauges.json is optional — map still works without it */ }

    renderNodeMap(document.getElementById("node-map"), merged, statusOf, labelOf, kindOf);

    const grid = document.getElementById("station-grid");
    grid.textContent = "";
    flood.stations.forEach((s) => grid.appendChild(buildStationCard(s)));

    const gaugeGrid = document.getElementById("gauge-grid");
    if (gaugeGrid) {
      gaugeGrid.textContent = "";
      gauges.forEach((g) => gaugeGrid.appendChild(buildGaugeCard(g)));
    }
  } catch (e) {
    document.getElementById("station-grid").textContent = "Live flood data is currently unavailable.";
    console.error(e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  refreshFlood();
  setInterval(refreshFlood, 60000);
});
