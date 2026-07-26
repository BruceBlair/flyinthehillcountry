// Shared helpers for live-data demo pages (weather/flood/flight/wildlife).
// No external dependencies — every demo page fetches its own /data/*.json
// and renders with these small utilities.

async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

function ageSeconds(isoString) {
  if (!isoString) return null;
  return (Date.now() - new Date(isoString).getTime()) / 1000;
}

function formatAge(isoString) {
  const secs = ageSeconds(isoString);
  if (secs === null) return "no data yet";
  if (secs < 90) return `${Math.round(secs)}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

// A page is "stale" if its data is older than 2x the expected push
// interval (spec §6). Pass the cron interval in seconds.
function isStale(isoString, expectedIntervalSec) {
  const secs = ageSeconds(isoString);
  return secs === null || secs > expectedIntervalSec * 2;
}

function showStaleBanner(updatedIso, expectedIntervalSec, label) {
  const banner = document.getElementById("stale-banner");
  if (!banner) return;
  if (isStale(updatedIso, expectedIntervalSec)) {
    banner.textContent = `Data may be out of date — ${label || "last update"}: ${formatAge(updatedIso)}. The page shows the most recent reading it has, but a network or sensor issue may be delaying updates.`;
    banner.classList.add("show");
  } else {
    banner.classList.remove("show");
  }
}

function fmt(value, decimals, unit) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(decimals)}${unit || ""}`;
}

// Renders lat/lon nodes onto a simple local-projection map (no tiles, no
// external map library — the 3 GTN stations sit within about half a mile
// of each other, so a small equirectangular approximation centered on
// their centroid is all that's needed to show relative position).
function renderNodeMap(container, nodes, statusOf, labelOf, kindOf) {
  container.innerHTML = "";
  if (!nodes.length) return;
  kindOf = kindOf || (() => "native");

  // The map's scale is set by "native"/"preferred" nodes only (property
  // scale, ~half a mile across) — "external" nodes (regional WU stations,
  // up to ~20 miles out) are clamped to the map edge in their true direction
  // instead of expanding the box, so one distant regional station doesn't
  // collapse the tightly-clustered native pins into a single blob.
  const scaleNodes = nodes.filter((n) => kindOf(n) !== "external");
  const boxNodes = scaleNodes.length ? scaleNodes : nodes;

  const lats = boxNodes.map((n) => n.lat);
  const centerLat = (Math.max(...lats) + Math.min(...lats)) / 2;
  const cosLat = Math.cos((centerLat * Math.PI) / 180);

  const xs = boxNodes.map((n) => n.lon * cosLat);
  const ys = boxNodes.map((n) => n.lat);
  const pad = 0.15; // fractional padding so pins aren't flush with the edge
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1e-6);
  const spanY = Math.max(maxY - minY, 1e-6);

  nodes.forEach((n) => {
    const x = n.lon * cosLat;
    const y = n.lat;
    let px = pad * 100 + ((x - minX) / spanX) * (100 - 2 * pad * 100);
    let py = (1 - pad) * 100 - ((y - minY) / spanY) * (100 - 2 * pad * 100);
    px = Math.min(97, Math.max(3, px));
    py = Math.min(97, Math.max(3, py));

    const pin = document.createElement("div");
    pin.className = `node-pin status-${statusOf(n)} kind-${kindOf(n)}`;
    pin.style.left = `${px}%`;
    pin.style.top = `${py}%`;
    pin.dataset.label = labelOf(n);
    pin.title = labelOf(n);
    container.appendChild(pin);
  });
}
