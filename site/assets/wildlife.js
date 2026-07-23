const WILDLIFE_INTERVAL_SEC = 30 * 60;
let allSpecies = [];

function buildHeatmap(hourly) {
  const wrap = document.createElement("div");
  wrap.className = "heatmap";
  const max = Math.max(...hourly, 1);
  hourly.forEach((count) => {
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.height = `${Math.max((count / max) * 100, 3)}%`;
    bar.title = `${count} detections`;
    wrap.appendChild(bar);
  });
  return wrap;
}

function buildSpeciesCard(s) {
  const card = document.createElement("div");
  card.className = "species-card";

  if (s.representative_photo) {
    const img = document.createElement("img");
    img.className = "species-photo";
    img.src = s.representative_photo;
    img.alt = s.species;
    img.loading = "lazy";
    card.appendChild(img);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = "species-photo-placeholder";
    placeholder.textContent = "Photo not yet curated";
    card.appendChild(placeholder);
  }

  const body = document.createElement("div");
  body.className = "body";

  const h3 = document.createElement("h3");
  h3.textContent = s.species;
  if (s.gone_quiet) {
    const flag = document.createElement("span");
    flag.className = "quiet-flag";
    flag.textContent = "GONE QUIET";
    h3.appendChild(flag);
  }
  body.appendChild(h3);

  if (s.scientific_name) {
    const sci = document.createElement("p");
    sci.className = "sci-name";
    sci.textContent = s.scientific_name;
    body.appendChild(sci);
  }

  if (s.family || s.conservation_status) {
    const p = document.createElement("p");
    p.className = "meta";
    p.textContent = [s.family, s.conservation_status].filter(Boolean).join(" · ");
    body.appendChild(p);
  }

  const seen = document.createElement("p");
  seen.className = "meta";
  seen.textContent = `First identified ${s.first_identified} · Last seen ${s.last_seen}`;
  body.appendChild(seen);

  const pop = document.createElement("p");
  pop.className = "meta";
  pop.textContent = s.population_estimate;
  body.appendChild(pop);

  const count = document.createElement("p");
  count.className = "meta";
  count.textContent = `${s.total_detections.toLocaleString()} total detections`;
  body.appendChild(count);

  const heatLabel = document.createElement("p");
  heatLabel.className = "meta";
  heatLabel.style.marginBottom = "0.1rem";
  heatLabel.textContent = "Activity by hour of day (midnight → 11pm)";
  body.appendChild(heatLabel);
  body.appendChild(buildHeatmap(s.hourly_activity));

  card.appendChild(body);
  return card;
}

function renderSpecies(list) {
  const grid = document.getElementById("species-grid");
  grid.textContent = "";
  if (!list.length) {
    grid.textContent = "No species match that search.";
    return;
  }
  list.forEach((s) => grid.appendChild(buildSpeciesCard(s)));
}

async function refreshWildlife() {
  try {
    const wildlife = await fetchJSON("/data/wildlife-species.json");
    showStaleBanner(wildlife.updated, WILDLIFE_INTERVAL_SEC, "wildlife summary");
    document.getElementById("wildlife-updated").textContent =
      `Last updated: ${formatAge(wildlife.updated)} · ${wildlife.species_count} species identified`;

    allSpecies = wildlife.species;
    renderSpecies(allSpecies);
  } catch (e) {
    document.getElementById("species-grid").textContent = "Live wildlife data is currently unavailable.";
    console.error(e);
  }
}

function applyFilters() {
  const q = document.getElementById("species-search").value.trim().toLowerCase();
  const quietOnly = document.getElementById("quiet-only").checked;
  let list = allSpecies;
  if (q) {
    list = list.filter((s) => s.species.toLowerCase().includes(q)
      || (s.scientific_name || "").toLowerCase().includes(q));
  }
  if (quietOnly) {
    list = list.filter((s) => s.gone_quiet);
  }
  renderSpecies(list);
}

document.addEventListener("DOMContentLoaded", () => {
  refreshWildlife();
  setInterval(refreshWildlife, 5 * 60000);

  document.getElementById("species-search").addEventListener("input", applyFilters);
  document.getElementById("quiet-only").addEventListener("change", applyFilters);
});
