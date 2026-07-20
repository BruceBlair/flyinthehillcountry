// Photo Sales gallery: renders a thumbnail grid from /photos/manifest.json
// and a click-through lightbox. Loads /photos/full/<file>.jpg on demand.

async function initGallery() {
  const grid = document.getElementById("photo-grid");
  if (!grid) return;

  const res = await fetch("/photos/manifest.json");
  const photos = await res.json();

  photos.forEach((p, i) => {
    const link = document.createElement("a");
    link.href = "#";
    link.className = "photo-thumb";
    link.dataset.index = String(i);

    const img = document.createElement("img");
    img.src = `/photos/thumb/${p.file}.jpg`;
    img.alt = `${p.category} — Ground Truth Network`;
    img.loading = "lazy";

    const tag = document.createElement("span");
    tag.className = "photo-tag";
    tag.textContent = p.category;

    link.append(img, tag);
    grid.appendChild(link);
  });

  const lightbox = document.createElement("div");
  lightbox.className = "lightbox";
  lightbox.innerHTML = `
    <button class="lightbox-close" aria-label="Close">&times;</button>
    <button class="lightbox-prev" aria-label="Previous">&lsaquo;</button>
    <img class="lightbox-img" src="" alt="" />
    <button class="lightbox-next" aria-label="Next">&rsaquo;</button>
  `;
  document.body.appendChild(lightbox);

  const imgEl = lightbox.querySelector(".lightbox-img");
  let current = 0;

  function show(index) {
    current = (index + photos.length) % photos.length;
    imgEl.src = `/photos/full/${photos[current].file}.jpg`;
    imgEl.alt = `${photos[current].category} — Ground Truth Network`;
    lightbox.classList.add("open");
  }

  function close() {
    lightbox.classList.remove("open");
    imgEl.src = "";
  }

  grid.addEventListener("click", (e) => {
    const thumb = e.target.closest(".photo-thumb");
    if (!thumb) return;
    e.preventDefault();
    show(Number(thumb.dataset.index));
  });

  lightbox.querySelector(".lightbox-close").addEventListener("click", close);
  lightbox.querySelector(".lightbox-prev").addEventListener("click", () => show(current - 1));
  lightbox.querySelector(".lightbox-next").addEventListener("click", () => show(current + 1));
  lightbox.addEventListener("click", (e) => {
    if (e.target === lightbox) close();
  });
  document.addEventListener("keydown", (e) => {
    if (!lightbox.classList.contains("open")) return;
    if (e.key === "Escape") close();
    if (e.key === "ArrowLeft") show(current - 1);
    if (e.key === "ArrowRight") show(current + 1);
  });
}

document.addEventListener("DOMContentLoaded", initGallery);
