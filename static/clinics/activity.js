/**
 * Finora Clinics — Activity log page
 */
(() => {
  function localToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function fmtClock(iso) {
    if (!iso) return "";
    return window.FinoraTime.time(iso) || window.FinoraTime.dateTime(iso);
  }

  function dayKey(iso) {
    return String(iso || "").slice(0, 10);
  }

  function dayLabel(iso) {
    const key = dayKey(iso);
    if (!key) return "";
    const today = localToday();
    const y = new Date();
    y.setDate(y.getDate() - 1);
    const yesterday = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, "0")}-${String(y.getDate()).padStart(2, "0")}`;
    if (key === today) return "اليوم";
    if (key === yesterday) return "أمس";
    return key;
  }

  function skeleton() {
    return `
      <div class="cx-act">
        <div class="cx-skeleton-block" style="height:88px;border-radius:18px"></div>
        <div class="cx-skeleton-block" style="height:520px;border-radius:18px;margin-top:12px"></div>
      </div>`;
  }

  function groupRows(rows) {
    const groups = [];
    const index = {};
    (rows || []).forEach((row) => {
      const key = dayKey(row.created_at) || "—";
      if (!index[key]) {
        index[key] = { key, label: dayLabel(row.created_at), items: [] };
        groups.push(index[key]);
      }
      index[key].items.push(row);
    });
    return groups;
  }

  function itemHtml(row, ctx) {
    const body = `
      <time>${ctx.esc(fmtClock(row.created_at))}</time>
      <i class="fa ${row.icon || "fa-circle-dot"}"></i>
      <div>
        <span>${ctx.esc(row.summary)}</span>
        <small>
          ${row.entity_type_label ? ctx.esc(row.entity_type_label) : ""}
          ${row.actor_name ? ` · ${ctx.esc(row.actor_name)}` : ""}
        </small>
      </div>`;
    if (row.href) {
      return `<a class="cx-activity__item cx-activity__item--link" href="${ctx.esc(row.href)}">${body}</a>`;
    }
    return `<div class="cx-activity__item">${body}</div>`;
  }

  function buildHtml(data, state, ctx) {
    const groups = groupRows(data.items || []);
    const types = data.entity_types || [];
    return `
      <div class="cx-act">
        <header class="cx-act__head">
          <div>
            <h1>سجل النشاط</h1>
            <p>كل إجراءات العيادة في مكان واحد — بحث، تصفية، وتصفح كامل السجل.</p>
          </div>
          <strong class="cx-act__count">${Number(data.total || 0).toLocaleString("en-IQ")} حدث</strong>
        </header>
        <div class="cx-act__filters">
          <label class="cx-act__search">
            <i class="fa fa-magnifying-glass"></i>
            <input type="search" class="cx-input" id="cxActQ" value="${ctx.esc(state.q)}" placeholder="ابحث في ملخص النشاط…">
          </label>
          <select class="cx-select" id="cxActType">
            <option value="">كل الأنواع</option>
            ${types
              .map(
                (t) =>
                  `<option value="${ctx.esc(t.key)}" ${state.entityType === t.key ? "selected" : ""}>${ctx.esc(t.label)}</option>`
              )
              .join("")}
          </select>
          <input type="date" class="cx-input" id="cxActFrom" value="${ctx.esc(state.dateFrom)}" title="من تاريخ">
          <input type="date" class="cx-input" id="cxActTo" value="${ctx.esc(state.dateTo)}" title="إلى تاريخ">
        </div>
        <article class="cx-card cx-act__card">
          ${
            groups.length
              ? groups
                  .map(
                    (g) => `
            <section class="cx-act__group">
              <h2>${ctx.esc(g.label)}</h2>
              <div class="cx-activity">
                ${g.items.map((row) => itemHtml(row, ctx)).join("")}
              </div>
            </section>`
                  )
                  .join("")
              : `<div class="cx-empty">لا يوجد نشاط مطابق</div>`
          }
          <footer class="cx-act__pager">
            <span>صفحة ${data.page || 1} من ${data.pages || 1}</span>
            <div>
              <button type="button" class="cx-btn cx-btn--sm" id="cxActPrev" ${Number(data.page || 1) <= 1 ? "disabled" : ""}>السابق</button>
              <button type="button" class="cx-btn cx-btn--sm" id="cxActNext" ${Number(data.page || 1) >= Number(data.pages || 1) ? "disabled" : ""}>التالي</button>
            </div>
          </footer>
        </article>
      </div>`;
  }

  function bind(root, state, ctx) {
    const q = root.querySelector("#cxActQ");
    if (q) {
      q.oninput = () => {
        clearTimeout(q._t);
        q._t = setTimeout(() => {
          state.q = q.value.trim();
          state.page = 1;
          ctx.refresh();
        }, 280);
      };
    }
    root.querySelector("#cxActType")?.addEventListener("change", (e) => {
      state.entityType = e.target.value;
      state.page = 1;
      ctx.refresh();
    });
    root.querySelector("#cxActFrom")?.addEventListener("change", (e) => {
      state.dateFrom = e.target.value;
      state.page = 1;
      ctx.refresh();
    });
    root.querySelector("#cxActTo")?.addEventListener("change", (e) => {
      state.dateTo = e.target.value;
      state.page = 1;
      ctx.refresh();
    });
    root.querySelector("#cxActPrev")?.addEventListener("click", () => {
      state.page = Math.max(1, (state.page || 1) - 1);
      ctx.refresh();
    });
    root.querySelector("#cxActNext")?.addEventListener("click", () => {
      state.page = (state.page || 1) + 1;
      ctx.refresh();
    });
  }

  async function render(appState, root, helpers) {
    const state = appState.activity || (appState.activity = { q: "", entityType: "", dateFrom: "", dateTo: "", page: 1 });
    root.innerHTML = skeleton();
    try {
      const qs = new URLSearchParams({ page: String(state.page || 1), per_page: "40" });
      if (state.q) qs.set("q", state.q);
      if (state.entityType) qs.set("entity_type", state.entityType);
      if (state.dateFrom) qs.set("date_from", state.dateFrom);
      if (state.dateTo) qs.set("date_to", state.dateTo);
      const data = await helpers.api(`/clinics/api/activity?${qs}`);
      const ctx = { ...helpers, refresh: () => render(appState, root, helpers) };
      root.innerHTML = buildHtml(data, state, ctx);
      bind(root, state, ctx);
    } catch (err) {
      root.innerHTML = `<div class="cx-empty">تعذر تحميل سجل النشاط: ${helpers.esc(err.message || String(err))}</div>`;
    }
  }

  window.ClinicsActivity = { render };
})();
