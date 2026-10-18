/* ======================================================
   FINORA UI — shared behaviour for pages built on finora-ui.css
   (popovers, pager, layout tiers for AG Grid, detail panel,
   drawers, number formatting). Pages call FinoraUI.* helpers.
====================================================== */
(function (global) {
  "use strict";

  const FinoraUI = {};

  FinoraUI.esc = function (value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  };

  FinoraUI.num = function (value) {
    return (Math.round(Number(value) || 0)).toLocaleString("en-US");
  };

  FinoraUI.money = function (value) {
    return '<span dir="ltr">' + FinoraUI.num(value) + " د.ع</span>";
  };

  FinoraUI.blank = function (value) {
    const v = value === null || value === undefined ? "" : String(value).trim();
    return !v || v === "—" || v === "-" || v === "---";
  };

  FinoraUI.dash = function (value) {
    return FinoraUI.blank(value) ? '<span class="fd-muted">—</span>' : FinoraUI.esc(value);
  };

  FinoraUI.toast = function (message, type) {
    if (typeof global.showToast === "function") return global.showToast(message, type || "info");
    // eslint-disable-next-line no-alert
    alert(message);
  };

  // ---- Popovers: [data-fd-pop="id"] toggles #id, [data-fd-pop-close] closes ----
  let openPop = null;

  FinoraUI.closePop = function () {
    if (!openPop) return;
    openPop.hidden = true;
    const trigger = document.querySelector('[data-fd-pop="' + openPop.id + '"]');
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    openPop = null;
  };

  FinoraUI.openPop = function (pop) {
    FinoraUI.closePop();
    pop.hidden = false;
    openPop = pop;
    const trigger = document.querySelector('[data-fd-pop="' + pop.id + '"]');
    if (trigger) trigger.setAttribute("aria-expanded", "true");
  };

  FinoraUI.isPopOpen = function () {
    return !!openPop;
  };

  document.addEventListener("click", function (event) {
    const t = event.target;
    if (!t || !t.closest) return;
    const trigger = t.closest("[data-fd-pop]");
    if (trigger) {
      const pop = document.getElementById(trigger.getAttribute("data-fd-pop"));
      if (!pop) return;
      if (openPop === pop) FinoraUI.closePop();
      else FinoraUI.openPop(pop);
      return;
    }
    if (t.closest("[data-fd-pop-close]")) FinoraUI.closePop();
    else if (openPop && !t.closest(".fd-pop")) FinoraUI.closePop();
  });

  // ---- Pager markup (0-based pages) ----
  FinoraUI.pagerHtml = function (current, pages, attr) {
    const chevron = d => '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
    const spread = global.matchMedia("(max-width: 600px)").matches ? 1 : 2;
    const win = spread * 2 + 1;
    let start = Math.max(0, current - spread);
    let end = Math.min(pages - 1, current + spread);
    if (end - start + 1 < win) {
      if (start === 0) end = Math.min(pages - 1, win - 1);
      else start = Math.max(0, end - win + 1);
    }
    const list = [];
    if (start > 0) { list.push(0); if (start > 1) list.push("…"); }
    for (let i = start; i <= end; i++) list.push(i);
    if (end < pages - 1) { if (end < pages - 2) list.push("…"); list.push(pages - 1); }
    let html = '<button type="button" class="fd-page fd-page--nav" ' + attr + '="prev" aria-label="السابقة"' + (current <= 0 ? " disabled" : "") + ">" + chevron("m9 6 6 6-6 6") + "</button>";
    list.forEach(p => {
      html += p === "…"
        ? '<span class="fd-page-gap">…</span>'
        : '<button type="button" class="fd-page' + (p === current ? " active" : "") + '" ' + attr + '="' + p + '"' + (p === current ? ' aria-current="page"' : "") + ">" + FinoraUI.num(p + 1) + "</button>";
    });
    html += '<button type="button" class="fd-page fd-page--nav" ' + attr + '="next" aria-label="التالية"' + (current >= pages - 1 ? " disabled" : "") + ">" + chevron("m15 6-6 6 6 6") + "</button>";
    return html;
  };

  /**
   * AG Grid page: custom pager, page size, layout tiers and card mode.
   * opts: { gridEl, wrapEl, pagerEl, rangeEl, sizeEl, sizeKey, unit,
   *         tiers: [{mode, minWidth, hidden: [colIds]}], cardCol, alwaysHidden,
   *         rowHeight, cardRowHeight, onLayout }
   */
  FinoraUI.gridPage = function (opts) {
    const sizes = [10, 25, 50, 100];
    const page = { api: null, mode: null };

    page.readSize = function () {
      try {
        const saved = parseInt(localStorage.getItem(opts.sizeKey), 10);
        if (sizes.includes(saved)) return saved;
      } catch (e) { /* storage unavailable */ }
      return 25;
    };

    page.tier = function () {
      const width = opts.wrapEl && opts.wrapEl.clientWidth ? opts.wrapEl.clientWidth : global.innerWidth;
      return opts.tiers.find(t => width >= t.minWidth) || null;
    };

    page.layoutMode = function () {
      const tier = page.tier();
      return tier ? tier.mode : "card";
    };

    page.gridOptions = function (extra) {
      const mode = page.layoutMode();
      return Object.assign({
        pagination: true,
        suppressPaginationPanel: true,
        paginationPageSize: page.readSize(),
        paginationPageSizeSelector: sizes,
        includeHiddenColumnsInQuickFilter: true,
        enableRtl: true,
        animateRows: false,
        suppressCellFocus: true,
        getRowHeight: () => (page.layoutMode() === "card" ? (opts.cardRowHeight || 120) : (opts.rowHeight || 72)),
        headerHeight: mode === "card" ? 46 : 58,
        domLayout: mode === "card" ? "autoHeight" : "normal",
        onPaginationChanged: () => page.renderPager()
      }, extra || {});
    };

    page.fitHeight = function () {
      if (!opts.gridEl) return;
      if (page.layoutMode() === "card") {
        opts.gridEl.style.height = "";
        return;
      }
      const footer = opts.pagerEl ? opts.pagerEl.closest(".fd-footer") : null;
      const footerHeight = footer ? footer.offsetHeight + 14 : 0;
      const top = opts.gridEl.getBoundingClientRect().top + global.scrollY;
      opts.gridEl.style.height = Math.max(520, global.innerHeight - top - footerHeight - 18) + "px";
    };

    page.applyLayout = function () {
      const api = page.api;
      if (!api) return;
      const mode = page.layoutMode();
      page.mode = mode;
      const all = api.getColumns().map(c => c.getColId());
      const always = opts.alwaysHidden || [];
      let visible;
      if (mode === "card") {
        visible = all.filter(id => id === opts.cardCol || (opts.cardKeep || []).includes(id));
      } else {
        const hidden = page.tier().hidden.concat([opts.cardCol], always);
        visible = all.filter(id => !hidden.includes(id));
      }
      api.setColumnsVisible(all.filter(id => visible.includes(id)), true);
      api.setColumnsVisible(all.filter(id => !visible.includes(id)), false);
      const root = document.getElementById("fdPage");
      if (root) root.classList.toggle("fd--cards", mode === "card");
      api.setGridOption("domLayout", mode === "card" ? "autoHeight" : "normal");
      api.setGridOption("headerHeight", mode === "card" ? 46 : 58);
      api.resetRowHeights();
      page.fitHeight();
      page.renderPager();
      if (opts.onLayout) opts.onLayout(mode);
    };

    page.renderPager = function () {
      const api = page.api;
      if (!api) return;
      const size = api.paginationGetPageSize();
      const total = api.paginationGetRowCount();
      const pages = Math.max(1, api.paginationGetTotalPages());
      const current = Math.min(api.paginationGetCurrentPage(), pages - 1);
      const from = total ? current * size + 1 : 0;
      if (opts.rangeEl) {
        opts.rangeEl.innerHTML = "عرض " + FinoraUI.num(from) + "–" + FinoraUI.num(Math.min(total, (current + 1) * size)) +
          " من <b>" + FinoraUI.num(total) + "</b> " + (opts.unit || "");
      }
      if (opts.pagerEl) opts.pagerEl.innerHTML = FinoraUI.pagerHtml(current, pages, "data-fd-grid-page");
    };

    page.attach = function (api) {
      page.api = api;
      page.applyLayout();
      if (opts.pagerEl) {
        opts.pagerEl.addEventListener("click", event => {
          const btn = event.target.closest("[data-fd-grid-page]");
          if (!btn || btn.disabled) return;
          const v = btn.getAttribute("data-fd-grid-page");
          if (v === "prev") api.paginationGoToPreviousPage();
          else if (v === "next") api.paginationGoToNextPage();
          else api.paginationGoToPage(parseInt(v, 10) || 0);
        });
      }
      if (opts.sizeEl) {
        opts.sizeEl.value = String(page.readSize());
        opts.sizeEl.addEventListener("change", () => {
          const size = parseInt(opts.sizeEl.value, 10);
          if (!sizes.includes(size)) return;
          api.setGridOption("paginationPageSize", size);
          try { localStorage.setItem(opts.sizeKey, String(size)); } catch (e) { /* storage unavailable */ }
        });
      }
      if (global.ResizeObserver && opts.wrapEl) {
        new ResizeObserver(() => {
          if (page.layoutMode() !== page.mode) page.applyLayout();
        }).observe(opts.wrapEl);
      }
      global.addEventListener("resize", () => {
        page.fitHeight();
        page.renderPager();
      });
    };

    return page;
  };

  // ---- Side panels (detail / drawer): Esc closes the top-most one ----
  FinoraUI.show = function (el) { if (el) el.hidden = false; };
  FinoraUI.hide = function (el) { if (el) el.hidden = true; };

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (openPop) { FinoraUI.closePop(); return; }
    const drawer = document.querySelector("#fdPage .fd-drawer:not([hidden])");
    if (drawer) { drawer.hidden = true; return; }
    const detail = document.querySelector("#fdPage .fd-detail:not([hidden])");
    if (detail) detail.hidden = true;
  });

  global.FinoraUI = FinoraUI;
})(window);
