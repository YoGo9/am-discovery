/* =========================================================
   AM Discovery — Router and bootstrap
   ========================================================= */

"use strict";

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
// The paginated list pages remember where you were. Leaving one (to an artist
// page, say) stashes its scroll offset; coming back re-renders the same page
// number and filters and scrolls you back down to the tile you clicked.
const SCROLL_MEMORY_ROUTES = new Set(["#/", "#/all"]);
let _activeRoute = null;

// Scrolls back to the offset remembered for `hash` once `rendered` settles.
function restoreScroll(hash, rendered) {
  const y = state.scrollMemory[hash] || 0;
  const go = () => { window.scrollTo({ top: y, behavior: "auto" }); };
  Promise.resolve(rendered).then(go, go);
}

function route(hash) {
  hash = hash || "#/";
  const main = $("main-content");

  // Stash the outgoing page's offset before the render blows the DOM away.
  // Also covers re-rendering the current page in place (e.g. after a watch
  // toggle), which would otherwise restore a stale offset.
  if (_activeRoute && SCROLL_MEMORY_ROUTES.has(_activeRoute)) {
    state.scrollMemory[_activeRoute] = window.scrollY;
  }
  _activeRoute = hash;

  // Highlight nav
  document.querySelectorAll(".nav-link").forEach(a => {
    const page = a.dataset.page;
    const active =
      (page === "releases"  && (hash === "#/" || hash.startsWith("#/releases"))) ||
      (page === "all"       && hash === "#/all") ||
      (page === "watchlist" && hash === "#/watchlist") ||
      (page === "admin"     && hash.startsWith("#/admin")) ||
      (page === "settings"  && hash === "#/settings");
    a.classList.toggle("active", active);
  });

  if (hash === "#/all") {
    document.title = "All Albums — AM Discovery";
    restoreScroll(hash, renderAllReleases(
      main,
      state.allReleasesPage,
      state.allReleasesQuery,
      state.allReleasesStorefront,
      state.allReleasesWatchedOnly,
      state.allReleasesTypeFilter,
    ));
  } else if (hash === "#/watchlist") {
    document.title = "Artist Watchlist — AM Discovery";
    const sortFilter = WatchlistPrefs.getSortFilter();
    renderWatchlist(main, "", "", sortFilter, state.watchlistPage);
  } else if (hash === "#/settings") {
    document.title = "Settings — AM Discovery";
    renderSettings(main);
  } else if (hash.startsWith("#/admin")) {
    document.title = "MB Admin — AM Discovery";
    const tab = hash.slice("#/admin".length).replace(/^\//, "") || "";
    renderAdmin(main, tab || null);
  } else if (hash.startsWith("#/artist/")) {
    document.title = "Artist — AM Discovery";
    const artistId = hash.slice("#/artist/".length);
    renderArtist(main, artistId);
  } else {
    document.title = "New Releases — AM Discovery";
    restoreScroll(hash, renderNewReleases(
      main,
      state.currentPage,
      state.currentQuery,
      state.currentStorefront,
      state.currentWatchedOnly,
    ));
  }
}

// ---------------------------------------------------------------------------
// Feature flags
// ---------------------------------------------------------------------------
// Fetched once at bootstrap (before the initial route) so the Admin nav link
// and #/admin route agree from the first paint. Settings saves keep it in
// sync afterwards (see page-settings.js).
async function applyMbScanFeatureFlag() {
  try {
    const cfg = await API.get("/api/system/config");
    state.mbScanEnabled = cfg.mb_scan_enabled !== false;
  } catch {
    state.mbScanEnabled = true;
  }
  const navAdmin = $("nav-admin");
  if (navAdmin) navAdmin.style.display = state.mbScanEnabled ? "" : "none";
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  // Routing
  window.addEventListener("hashchange", () => route(location.hash));
  // Re-route on nav click when the hash isn't changing (e.g. clicking "New
  // Releases" while already on that page) — otherwise hashchange does it, and
  // routing here too would double-render and clobber the stashed scroll offset.
  // Modified clicks are left alone so ⌘/Ctrl-click still opens a new tab.
  document.querySelectorAll(".nav-link").forEach(a => {
    a.addEventListener("click", e => {
      if (isModifiedClick(e)) return;
      const href = a.getAttribute("href");
      if ((location.hash || "#/") !== href) return;
      e.preventDefault();
      route(href);
    });
  });

  // Refresh button
  $("btn-refresh").addEventListener("click", triggerRefresh);

  // Modal close
  $("modal-close").addEventListener("click", closeModal);
  $("modal-overlay").addEventListener("click", e => {
    if (e.target === $("modal-overlay")) closeModal();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") closeModal();
  });

  // Metadata source widget
  initMetaSourceWidget();

  // Sidebar expand/collapse for small screens
  function expandSidebar() {
    $("sidebar").classList.add("expanded");
    $("sidebar-backdrop").classList.add("active");
  }
  function collapseSidebar() {
    $("sidebar").classList.remove("expanded");
    $("sidebar-backdrop").classList.remove("active");
  }
  $("sidebar-expand-btn").addEventListener("click", () => {
    $("sidebar").classList.contains("expanded") ? collapseSidebar() : expandSidebar();
  });
  $("sidebar-src-badge").addEventListener("click", expandSidebar);
  $("status-card").addEventListener("click", expandSidebar);
  $("sidebar-backdrop").addEventListener("click", collapseSidebar);

  // Initial status poll
  refreshStatus();
  setInterval(refreshStatus, 10000);

  // Gate the Admin nav link/route before the first render so a bookmarked
  // #/admin URL doesn't flash the page before redirecting away.
  await applyMbScanFeatureFlag();

  // Initial route
  route(location.hash || "#/");
});
