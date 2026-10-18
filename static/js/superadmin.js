(function () {
  "use strict";

  var sidebar = document.getElementById("saSidebar");
  var backdrop = document.getElementById("saSidebarBackdrop");
  var toggles = Array.prototype.slice.call(document.querySelectorAll("[data-sidebar-toggle]"));

  function syncSidebarState(isOpen) {
    toggles.forEach(function (button) {
      button.setAttribute("aria-expanded", isOpen ? "true" : "false");
      var icon = button.querySelector("i");
      if (icon && button.id === "saMenuToggle") icon.className = isOpen ? "fas fa-xmark" : "fas fa-bars";
    });
  }

  function openSidebar() {
    sidebar?.classList.add("open");
    backdrop?.classList.add("open");
    document.body.classList.add("sa-sidebar-open");
    syncSidebarState(true);
  }

  function closeSidebar() {
    sidebar?.classList.remove("open");
    backdrop?.classList.remove("open");
    document.body.classList.remove("sa-sidebar-open");
    syncSidebarState(false);
  }

  toggles.forEach(function (toggle) {
    toggle.addEventListener("click", function () {
      if (sidebar?.classList.contains("open")) closeSidebar();
      else openSidebar();
    });
  });

  backdrop?.addEventListener("click", closeSidebar);

  document.querySelectorAll(".sa-nav .nav-link").forEach(function (link) {
    link.addEventListener("click", function () {
      if (window.innerWidth <= 1024) closeSidebar();
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && sidebar?.classList.contains("open")) {
      closeSidebar();
      document.getElementById("saMenuToggle")?.focus();
    }
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth > 1024 && sidebar?.classList.contains("open")) closeSidebar();
  });

  // Keep wide data tables inside their cards on phones instead of widening the whole page.
  document.querySelectorAll(".sa-content table").forEach(function (table) {
    var parent = table.parentElement;
    var emptyCell = table.querySelector("tbody tr:only-child td[colspan]");
    if (emptyCell && parent) parent.classList.add("sa-empty-table");
    if (!parent || parent.matches(".sa-responsive-table, .table-card, .table-wrap, .data-table-wrap, .dashboard-table-wrap, [style*='overflow-x']")) return;
    var wrapper = document.createElement("div");
    wrapper.className = "sa-responsive-table";
    wrapper.setAttribute("role", "region");
    wrapper.setAttribute("aria-label", "جدول قابل للتمرير أفقياً");
    wrapper.tabIndex = 0;
    parent.insertBefore(wrapper, table);
    wrapper.appendChild(table);
  });

  var themeToggle = document.getElementById("saThemeToggle");
  var themeIcon = themeToggle && themeToggle.querySelector("i");

  function syncThemeButton() {
    var isDark = document.documentElement.dataset.theme === "dark";
    if (themeIcon) themeIcon.className = isDark ? "fas fa-sun" : "fas fa-moon";
    if (themeToggle) {
      themeToggle.setAttribute("aria-label", isDark ? "تفعيل الوضع الفاتح" : "تفعيل الوضع الداكن");
      themeToggle.setAttribute("title", isDark ? "تفعيل الوضع الفاتح" : "تفعيل الوضع الداكن");
    }
  }

  syncThemeButton();
  themeToggle?.addEventListener("click", function () {
    var nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nextTheme;
    try { localStorage.setItem("finora-superadmin-theme", nextTheme); } catch (error) {}
    syncThemeButton();
  });

  // Global command palette — familiar fast navigation used by modern admin systems.
  var commandDialog = document.getElementById("saCommandPalette");
  var commandSearch = document.getElementById("saCommandSearch");
  var commandEmpty = document.getElementById("saCommandEmpty");
  var commandRecent = document.getElementById("saCommandRecent");
  var commandCompanies = document.getElementById("saCommandCompanies");
  var commandCompanySection = document.getElementById("saCommandCompanySection");
  var commandCompanyLoading = document.getElementById("saCommandCompanyLoading");
  var commandTriggers = Array.prototype.slice.call(document.querySelectorAll("[data-command-trigger]"));
  var activeCommandIndex = 0;
  var lastCommandTrigger = null;
  var recentStorageKey = "finora-superadmin-recent-pages";
  var favoriteCompaniesStorageKey = "finora-superadmin-favorite-companies";
  var companySearchTimer = null;
  var companySearchController = null;
  var lastCompanyResults = [];

  function normalizeCommandText(value) {
    return String(value || "")
      .toLocaleLowerCase("ar")
      .normalize("NFKD")
      .replace(/[\u064B-\u065F\u0670]/g, "")
      .replace(/[أإآ]/g, "ا")
      .replace(/ة/g, "ه")
      .trim();
  }

  function commandItems() {
    return Array.prototype.slice.call(commandDialog?.querySelectorAll("[data-command]") || []);
  }

  function visibleCommandItems() {
    return commandItems().filter(function (item) {
      return !item.hidden && !item.closest("[data-command-section]")?.hidden;
    });
  }

  function highlightCommand(index) {
    var items = visibleCommandItems();
    if (!items.length) return;
    activeCommandIndex = ((index % items.length) + items.length) % items.length;
    commandItems().forEach(function (item) {
      item.classList.remove("is-selected");
      item.removeAttribute("aria-selected");
    });
    var selected = items[activeCommandIndex];
    selected.classList.add("is-selected");
    selected.setAttribute("aria-selected", "true");
    selected.scrollIntoView({ block: "nearest" });
  }

  function updateCommandEmptyState() {
    if (!commandEmpty) return;
    var isLoading = commandCompanyLoading && !commandCompanyLoading.hidden;
    commandEmpty.hidden = isLoading || visibleCommandItems().length !== 0;
  }

  function filterCommands(value) {
    var query = normalizeCommandText(value);
    var visibleCount = 0;
    commandDialog?.querySelectorAll("[data-command-section]").forEach(function (section) {
      var sectionCount = 0;
      section.querySelectorAll("[data-command]").forEach(function (item) {
        var haystack = normalizeCommandText(
          (item.dataset.commandLabel || item.textContent) + " " + (item.dataset.commandKeywords || "")
        );
        var matches = !query || haystack.indexOf(query) !== -1;
        item.hidden = !matches;
        if (matches) sectionCount += 1;
      });
      section.hidden = sectionCount === 0;
      visibleCount += sectionCount;
    });
    activeCommandIndex = 0;
    updateCommandEmptyState();
    highlightCommand(0);
  }

  function readFavoriteCompanies() {
    try {
      var value = JSON.parse(localStorage.getItem(favoriteCompaniesStorageKey) || "[]");
      return Array.isArray(value) ? value.filter(function (slug) { return typeof slug === "string"; }).slice(0, 20) : [];
    } catch (error) {
      return [];
    }
  }

  function saveFavoriteCompanies(companies) {
    try { localStorage.setItem(favoriteCompaniesStorageKey, JSON.stringify(companies.slice(0, 20))); } catch (error) {}
  }

  function tenantManagementUrl(slug, tab) {
    return "/superadmin/tenants?company=" + encodeURIComponent(slug) + "&tab=" + encodeURIComponent(tab || "overview");
  }

  function makeCompanyQuickLink(slug, tab, icon, label) {
    var link = document.createElement("a");
    link.className = "sa-company-quick-link";
    link.href = tenantManagementUrl(slug, tab);
    link.title = label;
    link.setAttribute("aria-label", label);
    link.innerHTML = '<i class="fas ' + icon + '" aria-hidden="true"></i>';
    return link;
  }

  function renderCompanyResults(companies) {
    if (!commandCompanies || !commandCompanySection) return;
    commandCompanies.textContent = "";
    lastCompanyResults = Array.isArray(companies) ? companies.slice() : [];
    var favorites = readFavoriteCompanies();
    var favoriteSet = new Set(favorites);
    var sortedCompanies = lastCompanyResults.slice().sort(function (a, b) {
      return Number(favoriteSet.has(b.slug)) - Number(favoriteSet.has(a.slug));
    });

    sortedCompanies.forEach(function (company) {
      var row = document.createElement("div");
      row.className = "sa-company-command-row";

      var link = document.createElement("a");
      link.href = tenantManagementUrl(company.slug, "overview");
      link.className = "sa-command-item sa-company-command-main";
      link.dataset.command = "";
      link.dataset.commandLabel = company.name || company.slug;
      link.dataset.commandKeywords = [company.slug, company.plan_name, company.business_type_label, company.status_label, "شركة مزايا اشتراك"].join(" ");

      var icon = document.createElement("span");
      icon.className = "sa-command-item-icon blue";
      icon.innerHTML = '<i class="fas fa-building" aria-hidden="true"></i>';
      var copy = document.createElement("span");
      var name = document.createElement("b");
      name.textContent = company.name || company.slug;
      var meta = document.createElement("small");
      meta.textContent = (company.plan_name && company.plan_name !== "—" ? company.plan_name + " · " : "") +
        (company.business_type_label || "شركة عامة") + " · ينتهي " + (company.subscription_end_date || "—") + " · " + company.slug;
      copy.appendChild(name);
      copy.appendChild(meta);
      var status = document.createElement("span");
      status.className = "sa-company-status " + (company.status_key || "expired");
      status.textContent = company.status_label || "—";
      link.appendChild(icon);
      link.appendChild(copy);
      link.appendChild(status);

      var actions = document.createElement("span");
      actions.className = "sa-company-command-actions";
      var favorite = document.createElement("button");
      favorite.type = "button";
      favorite.className = "sa-company-favorite" + (favoriteSet.has(company.slug) ? " is-favorite" : "");
      favorite.title = favoriteSet.has(company.slug) ? "إزالة من الشركات المفضلة" : "إضافة إلى الشركات المفضلة";
      favorite.setAttribute("aria-label", favorite.title);
      favorite.setAttribute("aria-pressed", favoriteSet.has(company.slug) ? "true" : "false");
      favorite.innerHTML = '<i class="' + (favoriteSet.has(company.slug) ? "fas" : "far") + ' fa-star" aria-hidden="true"></i>';
      favorite.addEventListener("click", function () {
        var current = readFavoriteCompanies().filter(function (slug) { return slug !== company.slug; });
        if (!favorite.classList.contains("is-favorite")) current.unshift(company.slug);
        saveFavoriteCompanies(current);
        renderCompanyResults(lastCompanyResults);
        filterCommands(commandSearch?.value || "");
      });
      actions.appendChild(favorite);
      actions.appendChild(makeCompanyQuickLink(company.slug, "subscription", "fa-crown", "فتح اشتراك " + company.name));
      actions.appendChild(makeCompanyQuickLink(company.slug, "features", "fa-toggle-on", "فتح مزايا " + company.name));
      row.appendChild(link);
      row.appendChild(actions);
      commandCompanies.appendChild(row);
    });

    commandCompanySection.hidden = sortedCompanies.length === 0;
    updateCommandEmptyState();
    highlightCommand(0);
  }

  function searchCompanies(value) {
    if (!commandCompanies || !commandCompanySection) return;
    if (companySearchController) companySearchController.abort();
    companySearchController = typeof AbortController === "function" ? new AbortController() : null;
    commandCompanySection.hidden = false;
    if (commandCompanyLoading) commandCompanyLoading.hidden = false;
    commandCompanies.textContent = "";
    updateCommandEmptyState();
    var url = "/superadmin/tenants/search?q=" + encodeURIComponent(String(value || "").trim()) + "&limit=8";
    fetch(url, companySearchController ? { signal: companySearchController.signal } : undefined)
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (commandCompanyLoading) commandCompanyLoading.hidden = true;
        renderCompanyResults(data && data.ok ? data.companies : []);
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") return;
        if (commandCompanyLoading) commandCompanyLoading.hidden = true;
        renderCompanyResults([]);
      });
  }

  function scheduleCompanySearch(value) {
    window.clearTimeout(companySearchTimer);
    companySearchTimer = window.setTimeout(function () { searchCompanies(value); }, 180);
  }

  function readRecentPages() {
    try {
      var value = JSON.parse(localStorage.getItem(recentStorageKey) || "[]");
      return Array.isArray(value) ? value.filter(function (item) {
        return item && /^\/superadmin(?:\/|$)/.test(item.href || "") && typeof item.label === "string";
      }).slice(0, 4) : [];
    } catch (error) {
      return [];
    }
  }

  function saveCurrentPageToRecent() {
    var path = window.location.pathname;
    if (!/^\/superadmin(?:\/|$)/.test(path) || path === "/superadmin/login") return;
    var titleNode = document.querySelector(".page-title");
    var label = (titleNode && titleNode.textContent || document.title || "صفحة Superadmin").trim();
    var recent = readRecentPages().filter(function (item) { return item.href !== path; });
    recent.unshift({ href: path, label: label.slice(0, 80) });
    try { localStorage.setItem(recentStorageKey, JSON.stringify(recent.slice(0, 4))); } catch (error) {}
  }

  function renderRecentPages() {
    if (!commandRecent) return;
    commandRecent.textContent = "";
    var recent = readRecentPages();
    recent.forEach(function (item) {
      var link = document.createElement("a");
      link.href = item.href;
      link.className = "sa-command-item";
      link.dataset.command = "";
      link.dataset.commandLabel = item.label;
      link.dataset.commandKeywords = "حديث مؤخرا recent";
      var icon = document.createElement("span");
      icon.className = "sa-command-item-icon blue";
      icon.innerHTML = '<i class="fas fa-clock-rotate-left" aria-hidden="true"></i>';
      var copy = document.createElement("span");
      var name = document.createElement("b");
      name.textContent = item.label;
      var meta = document.createElement("small");
      meta.textContent = item.href;
      copy.appendChild(name);
      copy.appendChild(meta);
      link.appendChild(icon);
      link.appendChild(copy);
      commandRecent.appendChild(link);
    });
    var section = commandRecent.closest("[data-command-section]");
    if (section) section.hidden = recent.length === 0;
  }

  function openCommandPalette(trigger) {
    if (!commandDialog) return;
    lastCommandTrigger = trigger || document.activeElement;
    renderRecentPages();
    commandSearch.value = "";
    filterCommands("");
    searchCompanies("");
    if (typeof commandDialog.showModal === "function") commandDialog.showModal();
    else commandDialog.setAttribute("open", "");
    document.body.classList.add("sa-command-open");
    window.setTimeout(function () { commandSearch?.focus(); }, 20);
  }

  function closeCommandPalette() {
    if (!commandDialog?.open) return;
    if (typeof commandDialog.close === "function") commandDialog.close();
    else commandDialog.removeAttribute("open");
  }

  saveCurrentPageToRecent();
  renderRecentPages();

  commandTriggers.forEach(function (trigger) {
    trigger.addEventListener("click", function () { openCommandPalette(trigger); });
  });

  document.querySelectorAll("[data-command-close]").forEach(function (button) {
    button.addEventListener("click", closeCommandPalette);
  });

  commandDialog?.addEventListener("close", function () {
    document.body.classList.remove("sa-command-open");
    if (lastCommandTrigger && typeof lastCommandTrigger.focus === "function") lastCommandTrigger.focus();
  });

  commandDialog?.addEventListener("cancel", function () {
    document.body.classList.remove("sa-command-open");
  });

  commandDialog?.addEventListener("click", function (event) {
    if (event.target === commandDialog) closeCommandPalette();
  });

  commandDialog?.querySelectorAll("[data-command-action]").forEach(function (item) {
    item.addEventListener("click", function () {
      var action = item.dataset.commandAction;
      if (action === "theme") {
        themeToggle?.click();
        closeCommandPalette();
      } else if (action === "reload") {
        window.location.reload();
      }
    });
  });

  commandSearch?.addEventListener("input", function () {
    filterCommands(commandSearch.value);
    scheduleCompanySearch(commandSearch.value);
  });
  commandSearch?.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeCommandPalette();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      highlightCommand(activeCommandIndex + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Enter") {
      var selected = visibleCommandItems()[activeCommandIndex];
      if (selected) {
        event.preventDefault();
        selected.click();
      }
    }
  });

  var goSequenceActive = false;
  var goSequenceTimer = null;
  var goShortcuts = {
    d: "/superadmin/",
    r: "/superadmin/requests",
    t: "/superadmin/tenants",
    p: "/superadmin/plans",
    l: "/superadmin/landing",
  };

  document.addEventListener("keydown", function (event) {
    var target = event.target;
    var isTyping = target && (target.matches("input, textarea, select") || target.isContentEditable);
    if (event.key === "Escape" && commandDialog?.open) {
      event.preventDefault();
      closeCommandPalette();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (commandDialog?.open) closeCommandPalette();
      else openCommandPalette(document.querySelector("[data-command-trigger]"));
      return;
    }
    if (!isTyping && event.key === "/" && !commandDialog?.open) {
      event.preventDefault();
      openCommandPalette(document.querySelector("[data-command-trigger]"));
      return;
    }
    if (isTyping || commandDialog?.open || event.ctrlKey || event.metaKey || event.altKey) return;
    var key = event.key.toLowerCase();
    if (goSequenceActive && goShortcuts[key]) {
      event.preventDefault();
      window.location.href = goShortcuts[key];
      goSequenceActive = false;
      window.clearTimeout(goSequenceTimer);
    } else if (key === "g") {
      goSequenceActive = true;
      window.clearTimeout(goSequenceTimer);
      goSequenceTimer = window.setTimeout(function () { goSequenceActive = false; }, 1200);
    } else {
      goSequenceActive = false;
    }
  });

  var btn = document.getElementById("systemUpdateBtn");
  if (btn) {
    btn.addEventListener("click", function () {
      if (btn.disabled) return;
      if (!confirm("رفع التغييرات إلى GitHub وتحديث VPS؟")) return;
      btn.disabled = true;
      btn.classList.add("updating");
      fetch("/admin/system-update", {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
      })
        .then(function (r) {
          var ct = (r.headers.get("Content-Type") || "").toLowerCase();
          if (ct.indexOf("application/json") === -1) {
            return r.text().then(function () {
              throw new Error("الخادم أعاد استجابة غير متوقعة.");
            });
          }
          return r.json();
        })
        .then(function (data) {
          btn.disabled = false;
          btn.classList.remove("updating");
          if (data && data.status === "success") {
            alert(data.message || "تم التحديث بنجاح.");
          } else {
            alert("خطأ: " + (data && data.message ? data.message : "فشل التحديث"));
          }
        })
        .catch(function (err) {
          btn.disabled = false;
          btn.classList.remove("updating");
          alert(err && err.message ? err.message : "خطأ في الاتصال.");
        });
    });
  }
})();
