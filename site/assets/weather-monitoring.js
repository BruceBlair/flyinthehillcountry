const NODES_INTERVAL_SEC = 5 * 60;
const FORECAST_INTERVAL_SEC = 30 * 60;

function buildStationCard(node) {
  const card = document.createElement("div");
  card.className = "station-card";

  const h3 = document.createElement("h3");
  const nameSpan = document.createElement("span");
  nameSpan.textContent = node.label;
  const badge = document.createElement("span");
  badge.className = `status-badge status-${node.status}`;
  badge.textContent = node.status;
  h3.append(nameSpan, badge);
  card.appendChild(h3);

  const updated = document.createElement("div");
  updated.className = "updated-line";
  updated.style.margin = "0 0 0.4rem";
  updated.textContent = node.current && node.current.timestamp
    ? `Updated ${formatAge(node.current.timestamp)}`
    : "No readings yet";
  card.appendChild(updated);

  const dl = document.createElement("dl");
  dl.className = "reading-grid";
  const c = node.current || {};
  const rows = [
    ["Temp", fmt(c.temp_f, 1, "°F")],
    ["Humidity", fmt(c.humidity_pct, 0, "%")],
    ["Pressure", fmt(c.pressure_msl_inhg, 2, " inHg")],
    ["Wind", fmt(c.wind_speed_mph, 1, " mph")],
    ["Gust", fmt(c.wind_gust_mph, 1, " mph")],
    ["Wind dir", fmt(c.wind_dir_deg, 0, "°")],
    ["Rain rate", fmt(c.rain_rate_in_hr, 2, " in/hr")],
    ["Rain today", fmt(c.rain_daily_in, 2, " in")],
    ["Battery", fmt(c.battery_pct, 0, "%")],
  ];
  rows.forEach(([label, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.append(dt, dd);
  });
  card.appendChild(dl);

  if (node.current && (c.temp_f === null || c.wind_speed_mph === null)) {
    const note = document.createElement("p");
    note.className = "reason";
    note.textContent = "Some fields unavailable — sensor or integration issue at this station, not necessarily calm/missing conditions.";
    card.appendChild(note);
  }

  return card;
}

function appendForecastPeriods(strip, periods) {
  periods.slice(0, 8).forEach((p) => {
    const el = document.createElement("div");
    el.className = "forecast-period";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = p.name;
    const img = document.createElement("img");
    img.src = p.icon;
    img.alt = p.short;
    img.loading = "lazy";
    const temp = document.createElement("div");
    temp.textContent = `${p.temp_f}°F`;
    const short = document.createElement("div");
    short.textContent = p.short;
    el.append(name, img, temp, short);
    strip.appendChild(el);
  });
}

function mapKindOf(n) { return n.kind || "native"; }
function mapStatusOf(n) { return n.status || "unknown"; }
function mapLabelOf(n) { return n.label; }

async function refreshNodes() {
  try {
    const nodes = await fetchJSON("/data/nodes.json");
    showStaleBanner(nodes.updated, NODES_INTERVAL_SEC, "sensor readings");
    document.getElementById("nodes-updated").textContent = `Last updated: ${formatAge(nodes.updated)}`;

    const merged = nodes.nodes.map((n) => ({ ...n, kind: "native" }));

    try {
      const ext = await fetchJSON("/data/external-stations.json");
      ext.stations
        .filter((s) => s.approx_lat != null && s.approx_lon != null)
        .forEach((s) => merged.push({
          lat: s.approx_lat,
          lon: s.approx_lon,
          kind: "external",
          status: s.temp_f != null ? "active" : "offline",
          label: `Regional station (${s.network === "wunderground" ? "WU" : s.network}) — ${s.distance_mi != null ? s.distance_mi + " mi" : "distance unknown"}`,
        }));
    } catch (e) { /* external-stations.json is optional — map still works without it */ }

    try {
      const pref = await fetchJSON("/data/preferred-locations.json");
      pref.locations.forEach((p) => merged.push({
        lat: p.lat,
        lon: p.lon,
        kind: "preferred",
        status: "unknown",
        label: `Proposed: ${p.label}`,
      }));
    } catch (e) { /* preferred-locations.json is optional — map still works without it */ }

    const mapEl = document.getElementById("node-map");
    renderNodeMap(mapEl, merged, mapStatusOf, mapLabelOf, mapKindOf);

    const grid = document.getElementById("station-grid");
    grid.textContent = "";
    nodes.nodes.forEach((n) => grid.appendChild(buildStationCard(n)));
  } catch (e) {
    document.getElementById("station-grid").textContent = "Live station data is currently unavailable.";
    console.error(e);
  }
}

async function refreshForecast() {
  try {
    const forecast = await fetchJSON("/data/forecast.json");
    document.getElementById("forecast-updated").textContent = `Forecast last updated: ${formatAge(forecast.updated)} (source: ${forecast.source})`;
    const strip = document.getElementById("forecast-strip");
    strip.textContent = "";
    appendForecastPeriods(strip, forecast.periods);
  } catch (e) {
    console.error(e);
  }
}

function initWeather() {
  refreshNodes();
  refreshForecast();
  setInterval(refreshNodes, 60000);
  setInterval(refreshForecast, 5 * 60000);
}

document.addEventListener("DOMContentLoaded", initWeather);
