(function () {
  "use strict";
  const nav = document.querySelector("[data-organized-navigation]");
  if (!nav) return;
  const english = nav.dataset.navLanguage === "en";
  const storageKey = "finora.navigation.v2." + nav.dataset.navStorageKey;
  let preferences;
  try {
    preferences = JSON.parse(localStorage.getItem(storageKey) || "{}");
  } catch (error) {
    preferences = {};
  }
  if (!preferences || typeof preferences !== "object" || Array.isArray(preferences)) preferences = {};
  const favorites = new Set(Array.isArray(preferences.favorites) ? preferences.favorites : []);
  const opened = preferences.opened && typeof preferences.opened === "object" && !Array.isArray(preferences.opened) ? preferences.opened : {};
  const sections = Array.from(nav.querySelectorAll("[data-nav-section]"));
  const items = Array.from(nav.querySelectorAll("[data-nav-item]"));
  const search = nav.querySelector("[data-nav-search]");
  const clearSearch = nav.querySelector("[data-nav-clear]");
  const searchStatus = nav.querySelector("[data-nav-search-status]");
  const favoriteSection = nav.querySelector("[data-nav-favorites]");
  const favoriteLinks = nav.querySelector("[data-nav-favorite-links]");
  const logo = nav.closest(".sidebar")?.querySelector(".brand-logo");
  if (logo) {
    logo.addEventListener("error", function () { logo.hidden = true; });
    if (logo.complete && !logo.naturalWidth) logo.hidden = true;
  }
  // Select one destination by the longest complete path segment.
  function markCurrentPage() {
    const current = window.location.pathname.replace(/\/+$/, "") || "/";
    let best = null;
    let bestLength = -1;
    items.forEach(function (item) {
      const anchor = item.querySelector("a");
      let path;
      try {
        const url = new URL(anchor.getAttribute("href"), window.location.href);
        if (url.origin !== window.location.origin || !["http:", "https:"].includes(url.protocol)) return;
        path = url.pathname.replace(/\/+$/, "") || "/";
      } catch (error) { return; }
      if ((current === path || (path !== "/" && current.startsWith(path + "/"))) && path.length > bestLength) {
        best = item;
        bestLength = path.length;
      }
    });
    items.forEach(function (item) {
      const active = item === best;
      const anchor = item.querySelector("a");
      item.classList.toggle("is-current", active);
      anchor.classList.toggle("active", active);
      if (active) anchor.setAttribute("aria-current", "page");
      else anchor.removeAttribute("aria-current");
    });
  }
  function save() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ favorites: Array.from(favorites), opened }));
    } catch (error) {
      // Browsing remains usable when storage is unavailable; preferences stay in memory.
      nav.dataset.preferencesStorage = "unavailable";
    }
  }
  function paintFavorites() {
    favoriteLinks.replaceChildren();
    items.forEach(function (item) {
      const button = item.querySelector("[data-nav-pin]");
      if (!button) return;
      const pinned = favorites.has(button.dataset.navPin);
      button.setAttribute("aria-pressed", String(pinned));
      button.setAttribute("aria-label", (english ? (pinned ? "Unpin " : "Pin ") : (pinned ? "إلغاء تثبيت " : "تثبيت ")) + item.querySelector("a").textContent.trim());
      button.querySelector("i").className = pinned ? "fa-solid fa-star" : "fa-regular fa-star";
      if (pinned) {
        const clone = item.querySelector("a").cloneNode(true);
        clone.removeAttribute("id");
        clone.querySelectorAll("[id]").forEach(function (element) { element.removeAttribute("id"); });
        favoriteLinks.appendChild(clone);
      }
    });
    favoriteSection.hidden = favoriteLinks.children.length === 0;
    const favoriteCount = nav.querySelector("[data-nav-favorite-count]");
    if (favoriteCount) favoriteCount.textContent = String(favoriteLinks.children.length);
  }
  function normalized(value) {
    return value.normalize("NFKD").replace(/[\u064b-\u065f]/g, "").toLocaleLowerCase().trim();
  }
  function filter() {
    const query = normalized(search.value);
    let count = 0;
    sections.forEach(function (section) {
      let visible = 0;
      section.querySelectorAll("[data-nav-item]").forEach(function (item) {
        const anchor = item.querySelector("a");
        const matches = !query || normalized(anchor.textContent + " " + anchor.getAttribute("href") + " " + (item.dataset.navSearchTerms || "")).includes(query);
        item.hidden = !matches;
        if (matches) visible++;
      });
      section.hidden = visible === 0;
      const badge = section.querySelector("[data-nav-section-count]");
      if (badge) badge.textContent = String(visible);
      count += visible;
      section.open = query ? visible > 0 : section.dataset.currentSection === "true" || !!opened[section.dataset.navSection];
    });
    favoriteSection.hidden = !!query || favoriteLinks.children.length === 0;
    nav.querySelector("[data-nav-empty]").hidden = count !== 0;
    if (clearSearch) clearSearch.hidden = !query;
    if (searchStatus) searchStatus.textContent = query ? count + (english ? " results" : " نتيجة") : "";
  }
  sections.forEach(function (section) {
    section.dataset.currentSection = String(section.open);
    section.open = section.open || !!opened[section.dataset.navSection];
    section.addEventListener("toggle", function () {
      if (!search.value.trim() && !section.hidden) {
        opened[section.dataset.navSection] = section.open;
        save();
      }
    });
  });
  nav.addEventListener("click", function (event) {
    const button = event.target.closest("[data-nav-pin]");
    if (!button || !nav.contains(button)) return;
    const key = button.dataset.navPin;
    if (favorites.has(key)) favorites.delete(key);
    else favorites.add(key);
    save();
    paintFavorites();
  });
  search.addEventListener("input", filter);
  clearSearch?.addEventListener("click", function () {
    search.value = "";
    filter();
    search.focus();
  });
  search.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && search.value) {
      event.preventDefault();
      event.stopPropagation();
      search.value = "";
      filter();
    }
  });
  markCurrentPage();
  paintFavorites();
})();
