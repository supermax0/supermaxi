/**
 * Finora Clinics — shared finance UI primitives
 */
(() => {
  const PAYMENT_METHODS = {
    cash: "نقدي",
    card: "بطاقة",
    transfer: "تحويل",
    zain: "زين كاش",
    electronic: "دفع إلكتروني",
    other: "أخرى",
  };

  const QUICK_DATES = [
    { id: "today", label: "اليوم" },
    { id: "yesterday", label: "أمس" },
    { id: "week", label: "آخر 7 أيام" },
    { id: "month", label: "هذا الشهر" },
    { id: "last_month", label: "الشهر الماضي" },
    { id: "custom", label: "فترة مخصصة" },
  ];

  // Local calendar date as YYYY-MM-DD. NEVER toISOString() for "today": that converts to UTC, which is a
  // different calendar day than the local one for several hours around local midnight (e.g. AST, UTC+3).
  function localDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function shiftDate(base, days) {
    const d = new Date(base + "T12:00:00");
    d.setDate(d.getDate() + days);
    return localDateStr(d);
  }

  function resolveDateRange(quick, day, from, to) {
    const today = localDateStr(new Date());
    if (quick === "today") return { from: today, to: today, fetchAll: false, day: today };
    if (quick === "yesterday") {
      const y = shiftDate(today, -1);
      return { from: y, to: y, fetchAll: false, day: y };
    }
    if (quick === "week") return { from: shiftDate(today, -6), to: today, fetchAll: true, day: "" };
    if (quick === "month") {
      const d = new Date();
      const f = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
      return { from: f, to: today, fetchAll: true, day: "" };
    }
    if (quick === "last_month") {
      const d = new Date();
      d.setDate(1);
      d.setMonth(d.getMonth() - 1);
      const f = d.toISOString().slice(0, 10);
      d.setMonth(d.getMonth() + 1);
      d.setDate(0);
      const t = d.toISOString().slice(0, 10);
      return { from: f, to: t, fetchAll: true, day: "" };
    }
    if (from && to) return { from, to, fetchAll: true, day: "" };
    return { from: day || today, to: day || today, fetchAll: false, day: day || today };
  }

  function inRange(dateStr, from, to) {
    if (!dateStr) return true;
    if (from && dateStr < from) return false;
    if (to && dateStr > to) return false;
    return true;
  }

  function activeFilterCount(state, keys) {
    let n = 0;
    keys.forEach((k) => {
      if (state[k]) n += 1;
    });
    return n;
  }

  function headerHtml(ctx, opts) {
    const actBtns = (opts.actions || [])
      .map((a) => {
        let cls = "cx-btn";
        if (a.primary === true) cls += " cx-btn--primary";
        else if (a.primary === false || opts.actionsRow) cls += " cx-btn--ghost";
        return `<button type="button" class="${cls}" id="${ctx.esc(a.id)}"${a.finoraAction ? ` data-finora-action="${ctx.esc(a.finoraAction)}"` : ""}>${a.icon ? `<i class="fa ${a.icon}"></i> ` : ""}${ctx.esc(a.label)}</button>`;
      })
      .join("");
    return `
      <header class="cx-fin-header${opts.actionsRow ? " cx-fin-header--stacked" : ""}">
        <div class="cx-fin-header__main">
          <div class="cx-fin-header__copy">
            ${opts.kicker ? `<span class="cx-fin-kicker">${ctx.esc(opts.kicker)}</span>` : `<nav class="cx-fin-breadcrumb">${opts.breadcrumb || "المالية"}</nav>`}
            <h1>${ctx.esc(opts.title)}</h1>
            <p>${ctx.esc(opts.desc || "")}</p>
          </div>
          <div class="cx-fin-header__icon"><i class="fa ${opts.icon || "fa-coins"}"></i></div>
        </div>
        ${opts.actionsRow ? "" : `<div class="cx-fin-header__acts">${actBtns}</div>`}
      </header>
      ${opts.actionsRow ? `<section class="cx-fin-actions-row">${actBtns}</section>` : ""}`;
  }

  function kpisHtml(cards) {
    return cards
      .map(
        (c) => `
      <article class="cx-fin-kpi cx-fin-kpi--${c.theme || "teal"}" title="${c.tip || ""}">
        <div class="cx-fin-kpi__top">
          <span>${c.label}</span>
          <i class="fa ${c.icon || "fa-chart-line"}"></i>
        </div>
        <div class="cx-fin-kpi__val">
          <strong>${c.value}</strong>
          ${c.unit ? `<small>${c.unit}</small>` : ""}
        </div>
        ${c.sub ? `<em>${c.sub}</em>` : ""}
      </article>`
      )
      .join("");
  }

  function filtersShell(ctx, inner, extraInner, state, extraKeys) {
    const n = activeFilterCount(state, extraKeys || []);
    return `
      <div class="cx-fin-filters">
        <div class="cx-fin-filters__quick">
          ${QUICK_DATES.map(
            (q) =>
              `<button type="button" class="cx-fin-qdate ${state.quickDate === q.id ? "is-active" : ""}" data-qdate="${q.id}">${q.label}</button>`
          ).join("")}
        </div>
        <div class="cx-fin-filters__row">${inner}</div>
        <div class="cx-fin-filters__tools">
          <button type="button" class="cx-btn cx-btn--ghost" id="cxFinMore"><i class="fa fa-sliders"></i> <span>فلاتر متقدمة${n ? ` (${n})` : ""}</span></button>
          <button type="button" class="cx-btn cx-btn--ghost" id="cxFinReset">مسح</button>
          <button type="button" class="cx-btn cx-btn--ghost cx-fin-refresh" id="cxFinRefresh" aria-label="تحديث"><i class="fa fa-rotate"></i></button>
        </div>
        <div class="cx-fin-extra" id="cxFinExtra" ${state.extraOpen ? "" : "hidden"}>${extraInner || ""}</div>
        ${state.quickDate === "custom" ? `
        <div class="cx-fin-custom-range">
          <input type="date" class="cx-select" id="cxFinFrom" value="${ctx.esc(state.from || "")}">
          <span>إلى</span>
          <input type="date" class="cx-select" id="cxFinTo" value="${ctx.esc(state.to || "")}">
        </div>` : ""}
      </div>`;
  }

  function emptyHtml(msg, btnLabel, btnId, opts) {
    const o = opts || {};
    return `
      <div class="cx-fin-empty">
        <div class="cx-fin-empty__icon"><i class="fa ${o.icon || "fa-folder-open"}"></i></div>
        <h3>${msg}</h3>
        ${o.sub ? `<p>${o.sub}</p>` : ""}
        ${btnLabel ? `<button type="button" class="cx-btn cx-btn--primary" id="${btnId}"><i class="fa fa-plus"></i> ${btnLabel}</button>` : ""}
      </div>`;
  }

  function skeletonKpis(n = 5) {
    return `<div class="cx-fin-kpis">${Array(n)
      .fill('<div class="cx-skeleton-block" style="height:76px;border-radius:14px"></div>')
      .join("")}</div>`;
  }

  function tableCard(html, pager) {
    return `<article class="cx-fin-table-card"><div class="cx-table-wrap">${html}</div>${pager || ""}</article>`;
  }

  function pagerHtml(ctx, pg) {
    return `
      <div class="cx-fin-pager">
        <span>عرض ${pg.from || 0}-${pg.to || 0} من ${pg.total || 0}</span>
        <div class="cx-fin-pager__nav">
          <button type="button" class="cx-btn cx-btn--sm" id="cxFinPrev" ${pg.page <= 1 ? "disabled" : ""}>السابق</button>
          <span>${pg.page || 1} / ${pg.pages || 1}</span>
          <button type="button" class="cx-btn cx-btn--sm" id="cxFinNext" ${pg.page >= pg.pages ? "disabled" : ""}>التالي</button>
        </div>
      </div>`;
  }

  function paginate(rows, page, perPage) {
    const total = rows.length;
    const pages = Math.max(1, Math.ceil(total / perPage));
    const p = Math.min(Math.max(1, page), pages);
    const start = (p - 1) * perPage;
    return {
      items: rows.slice(start, start + perPage),
      pagination: {
        page: p,
        per_page: perPage,
        total,
        pages,
        from: total ? start + 1 : 0,
        to: Math.min(start + perPage, total),
      },
    };
  }

  function bindFilterChrome(ctx, onApply, paintFn) {
    const root = ctx.root;
    const repaint = paintFn || (() => {});
    root.querySelectorAll("[data-qdate]").forEach((btn) => {
      btn.onclick = async () => {
        ctx.state.quickDate = btn.dataset.qdate;
        if (ctx.state.quickDate !== "custom") await onApply();
        else repaint(ctx);
      };
    });
    root.querySelector("#cxFinMore")?.addEventListener("click", () => {
      ctx.state.extraOpen = !ctx.state.extraOpen;
      repaint(ctx);
    });
    root.querySelector("#cxFinReset")?.addEventListener("click", async () => {
      ctx.state.q = "";
      ctx.state.status = "";
      ctx.state.method = "";
      ctx.state.doctor_id = "";
      ctx.state.category = "";
      ctx.state.extraOpen = false;
      ctx.state.quickDate = ctx.state.defaultQuickDate || "today";
      ctx.state.page = 1;
      await onApply();
    });
    root.querySelector("#cxFinRefresh")?.addEventListener("click", onApply);
    ["cxFinFrom", "cxFinTo"].forEach((id) => {
      const el = root.querySelector(`#${id}`);
      if (el) el.onchange = onApply;
    });
  }

  window.FinoraFinanceUI = {
    PAYMENT_METHODS,
    resolveDateRange,
    localDateStr,
    inRange,
    headerHtml,
    kpisHtml,
    filtersShell,
    emptyHtml,
    skeletonKpis,
    tableCard,
    pagerHtml,
    paginate,
    bindFilterChrome,
  };
})();
