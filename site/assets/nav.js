// Shared header/nav/footer, injected into every page at load time.
// Contract: each page sets <body data-nav-id="..."> matching one of the
// `id` values below, and includes two empty containers:
//   <div id="site-header"></div>  (near top of <body>)
//   <div id="site-footer"></div>  (near bottom of <body>)

const NAV_ITEMS = [
  { id: "demos", label: "Demo Applications", href: "/demos/" },
  { id: "photo-sales", label: "Photo Sales", href: "/photo-sales.html" },
  { id: "investors", label: "Investors", href: "/investors.html" },
  { id: "about", label: "About Us", href: "/about.html" },
];

function renderHeader(activeId) {
  const links = NAV_ITEMS.map((item) => {
    const activeClass = item.id === activeId ? " active" : "";
    return `<a href="${item.href}" class="${activeClass.trim()}">${item.label}</a>`;
  }).join("\n");

  return `
    <header class="site-header">
      <div class="site-header-inner">
        <a href="/" class="brand">HITHC &middot; Ground Truth Network</a>
        <nav>${links}</nav>
      </div>
    </header>
  `;
}

// Analytics config — fill in once accounts exist, tracking activates
// site-wide automatically since every page loads this file.
const ANALYTICS = {
  ga4MeasurementId: "G-HLK9H7WMX9",
  cfBeaconToken: "9111ae5effef4491b2f1ae0d24af5dfa",
};

function loadAnalytics() {
  if (ANALYTICS.ga4MeasurementId) {
    const gtagSrc = document.createElement("script");
    gtagSrc.async = true;
    gtagSrc.src = `https://www.googletagmanager.com/gtag/js?id=${ANALYTICS.ga4MeasurementId}`;
    document.head.appendChild(gtagSrc);

    window.dataLayer = window.dataLayer || [];
    function gtag() { window.dataLayer.push(arguments); }
    gtag("js", new Date());
    gtag("config", ANALYTICS.ga4MeasurementId);
  }

  if (ANALYTICS.cfBeaconToken) {
    const beacon = document.createElement("script");
    beacon.type = "module";
    beacon.src = "https://static.cloudflareinsights.com/beacon.min.js";
    beacon.setAttribute("data-cf-beacon", JSON.stringify({ token: ANALYTICS.cfBeaconToken }));
    document.head.appendChild(beacon);
  }
}

function renderFooter() {
  const year = new Date().getFullYear();
  return `
    <footer class="site-footer">
      <p>&copy; ${year} High in the Hill Country LLC &middot; <a href="/">senselayer.io</a></p>
    </footer>
  `;
}

document.addEventListener("DOMContentLoaded", () => {
  loadAnalytics();
  const activeId = document.body.dataset.navId || "";
  const headerMount = document.getElementById("site-header");
  const footerMount = document.getElementById("site-footer");
  if (headerMount) headerMount.innerHTML = renderHeader(activeId);
  if (footerMount) footerMount.innerHTML = renderFooter();
});
