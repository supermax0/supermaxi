const EmployeePerformanceWindow = {
  _escape(value) {
    const node = document.createElement("span");
    node.textContent = String(value ?? "");
    return node.innerHTML;
  },

  _number(value) {
    return Number(value || 0).toLocaleString("ar-IQ");
  },

  _money(value) {
    return `${this._number(value)} د.ع`;
  },

  _score(row, topSales) {
    const orders = Number(row.orders || 0);
    const sales = Number(row.total_sales || 0);
    const collected = Number(row.collected || 0);
    const issues = Number(row.returned || 0) + Number(row.canceled || 0);
    if (!orders && !sales && !issues) return 0;
    const collection = sales > 0 ? Math.min(1, collected / sales) : 0;
    const quality = Math.max(0, 1 - issues / Math.max(orders + issues, 1));
    const contribution = topSales > 0 ? Math.min(1, sales / topSales) : 0;
    return Math.round((collection * 0.4 + quality * 0.25 + contribution * 0.35) * 100);
  },

  _detailMarkup(row, topSales) {
    if (!row) {
      return `<div class="ws-emp-detail-empty"><span>👤</span><strong>اختر موظفاً</strong><p>اضغط على أي صف لمشاهدة تفاصيل الأداء.</p></div>`;
    }
    const name = this._escape(row.name || "غير محدد");
    const role = this._escape(row.role || "بدون مسمى وظيفي");
    const branch = this._escape(row.branch || "كل الفروع");
    const score = this._score(row, topSales);
    const sales = Number(row.total_sales || 0);
    const collected = Number(row.collected || 0);
    const collection = sales > 0 ? Math.min(100, Math.round((collected / sales) * 100)) : 0;
    const issues = Number(row.returned || 0) + Number(row.canceled || 0);
    const orders = Number(row.orders || 0);
    const quality = Math.max(0, Math.round((1 - issues / Math.max(orders + issues, 1)) * 100));
    return `
      <div class="ws-emp-detail-head">
        <span class="ws-emp-avatar is-large">${name.charAt(0) || "م"}</span>
        <div><strong>${name}</strong><span>${role} · ${branch}</span></div>
        <b class="${row.is_active === false ? "is-off" : "is-on"}">${row.is_active === false ? "متوقف" : "نشط"}</b>
      </div>
      <div class="ws-emp-detail-money">
        <span>إجمالي المبيعات</span>
        <strong>${this._money(sales)}</strong>
      </div>
      <div class="ws-emp-detail-stats">
        <div><strong>${this._number(row.orders)}</strong><span>طلب</span></div>
        <div><strong>${this._number(row.returned)}</strong><span>مرتجع</span></div>
        <div><strong>${this._number(row.canceled)}</strong><span>ملغي</span></div>
      </div>
      <div class="ws-emp-meters">
        <div><span><b>التقييم العام</b><em>${score}%</em></span><i><u style="width:${score}%"></u></i></div>
        <div><span><b>نسبة التحصيل</b><em>${collection}%</em></span><i><u style="width:${collection}%"></u></i></div>
        <div><span><b>جودة الطلبات</b><em>${quality}%</em></span><i><u style="width:${quality}%"></u></i></div>
      </div>`;
  },

  render(container, spec) {
    const data = spec.props?.data || {};
    const rows = Array.isArray(data.performance) ? data.performance : [];
    const topSales = Math.max(...rows.map((row) => Number(row.total_sales || 0)), 0);
    const totalOrders = rows.reduce((sum, row) => sum + Number(row.orders || 0), 0);
    const totalSales = rows.reduce((sum, row) => sum + Number(row.total_sales || 0), 0);
    const totalCollected = rows.reduce((sum, row) => sum + Number(row.collected || 0), 0);
    const totalIssues = rows.reduce((sum, row) => sum + Number(row.returned || 0) + Number(row.canceled || 0), 0);
    const activeCount = rows.filter((row) => row.is_active !== false).length;
    const collectionRate = totalSales > 0 ? Math.min(100, Math.round((totalCollected / totalSales) * 100)) : 0;
    const zeroCount = Array.isArray(data.zero_order_employees) ? data.zero_order_employees.length : 0;
    const topRows = rows.filter((row) => Number(row.total_sales || 0) > 0).slice(0, 4);
    const period = this._escape(data.period || "آخر 30 يوماً");
    const esc = (value) => this._escape(value);

    const rowMarkup = rows.map((row, index) => {
      const score = this._score(row, topSales);
      const issues = Number(row.returned || 0) + Number(row.canceled || 0);
      const statusClass = row.is_active === false ? "is-off" : (!Number(row.orders || 0) ? "is-idle" : "is-on");
      const statusText = row.is_active === false ? "متوقف" : (!Number(row.orders || 0) ? "بدون نشاط" : "نشط");
      return `
        <tr tabindex="0" data-employee-index="${index}" data-search="${esc(`${row.name || ""} ${row.role || ""} ${row.branch || ""}`.toLowerCase())}" data-state="${statusClass}">
          <td><div class="ws-emp-person"><span class="ws-emp-avatar">${esc((row.name || "م").charAt(0))}</span><div><strong>${esc(row.name || "غير محدد")}</strong><span>${esc(row.role || "بدون مسمى")}</span></div></div></td>
          <td><span class="ws-emp-branch">${esc(row.branch || "غير محدد")}</span></td>
          <td><strong>${this._number(row.orders)}</strong></td>
          <td><strong>${this._money(row.total_sales)}</strong><small>المحصّل ${this._money(row.collected)}</small></td>
          <td><span class="ws-emp-issue ${issues ? "has-issue" : ""}">${issues ? `${this._number(issues)} حركة` : "سليم"}</span></td>
          <td><div class="ws-emp-score"><span><i style="width:${score}%"></i></span><b>${score}%</b></div></td>
          <td><span class="ws-emp-state ${statusClass}"><i></i>${statusText}</span></td>
        </tr>`;
    }).join("");

    const topMarkup = topRows.length ? topRows.map((row, index) => {
      const percent = topSales > 0 ? Math.max(8, Math.round((Number(row.total_sales || 0) / topSales) * 100)) : 0;
      return `<div class="ws-emp-rank"><span>${index + 1}</span><div><b>${esc(row.name || "غير محدد")}</b><i><u style="width:${percent}%"></u></i></div><strong>${this._money(row.total_sales)}</strong></div>`;
    }).join("") : `<p class="ws-emp-empty-note">لا توجد مبيعات ضمن هذه الفترة.</p>`;

    container.closest(".ws-window")?.classList.add("ws-employee-window");
    container.innerHTML = `
      <div class="ws-employee-dashboard" dir="rtl">
        <header class="ws-emp-hero">
          <div>
            <span class="ws-emp-eyebrow"><i></i> LEON · ذكاء أداء الفريق</span>
            <h2>لوحة أداء الموظفين</h2>
            <p>${period}</p>
          </div>
          <span class="ws-emp-live"><i></i> بيانات مباشرة من النظام</span>
        </header>

        <section class="ws-emp-kpis">
          <article><span class="ws-emp-kpi-icon is-purple">👥</span><div><small>الموظفون النشطون</small><strong>${this._number(activeCount)}</strong><em>من أصل ${this._number(rows.length)}</em></div></article>
          <article><span class="ws-emp-kpi-icon is-blue">▤</span><div><small>إجمالي الطلبات</small><strong>${this._number(totalOrders)}</strong><em>خلال الفترة</em></div></article>
          <article><span class="ws-emp-kpi-icon is-green">د.ع</span><div><small>إجمالي المبيعات</small><strong class="is-money">${this._money(totalSales)}</strong><em>المحصّل ${this._money(totalCollected)}</em></div></article>
          <article><span class="ws-emp-kpi-icon is-orange">↻</span><div><small>المرتجع والملغي</small><strong>${this._number(totalIssues)}</strong><em>${zeroCount} بدون نشاط</em></div></article>
        </section>

        <main class="ws-emp-layout">
          <section class="ws-emp-table-card">
            <div class="ws-emp-card-head">
              <div><h3>تفاصيل الفريق</h3><p><b data-visible-count>${this._number(rows.length)}</b> موظف في النتائج</p></div>
              <div class="ws-emp-tools">
                <label><span>⌕</span><input type="search" placeholder="ابحث بالاسم أو الفرع..." data-employee-search></label>
                <select data-employee-filter aria-label="فلترة الموظفين"><option value="all">جميع الحالات</option><option value="is-on">نشط</option><option value="is-idle">بدون نشاط</option><option value="is-off">متوقف</option></select>
              </div>
            </div>
            <div class="ws-emp-table-wrap">
              <table>
                <thead><tr><th>الموظف</th><th>الفرع</th><th>الطلبات</th><th>المبيعات والتحصيل</th><th>الملاحظات</th><th>الأداء</th><th>الحالة</th></tr></thead>
                <tbody>${rowMarkup || `<tr><td colspan="7" class="ws-emp-no-results">لا توجد بيانات موظفين للفترة المحددة.</td></tr>`}</tbody>
              </table>
              <div class="ws-emp-no-results" data-no-results hidden>لا توجد نتائج مطابقة للبحث.</div>
            </div>
          </section>

          <aside class="ws-emp-side">
            <section class="ws-emp-card ws-emp-health">
              <div class="ws-emp-card-title"><div><h3>صحة التحصيل</h3><p>المبالغ المحصلة من المبيعات</p></div><span>هذا الشهر</span></div>
              <div class="ws-emp-ring" style="--ring-value:${collectionRate * 3.6}deg"><div><strong>${collectionRate}%</strong><span>نسبة التحصيل</span></div></div>
              <div class="ws-emp-health-row"><span><i class="is-green"></i>مُحصّل <b>${this._money(totalCollected)}</b></span><span><i class="is-soft"></i>متبقٍ <b>${this._money(Math.max(0, totalSales - totalCollected))}</b></span></div>
            </section>
            <section class="ws-emp-card ws-emp-top"><div class="ws-emp-card-title"><div><h3>الأعلى أداءً</h3><p>بحسب قيمة المبيعات</p></div><span>TOP ${topRows.length}</span></div>${topMarkup}</section>
            <section class="ws-emp-card ws-emp-detail" data-employee-detail>${this._detailMarkup(rows[0], topSales)}</section>
          </aside>
        </main>
      </div>`;

    const search = container.querySelector("[data-employee-search]");
    const filter = container.querySelector("[data-employee-filter]");
    const tableRows = [...container.querySelectorAll("tbody tr[data-employee-index]")];
    const visibleCount = container.querySelector("[data-visible-count]");
    const noResults = container.querySelector("[data-no-results]");
    const detail = container.querySelector("[data-employee-detail]");

    const applyFilters = () => {
      const query = (search?.value || "").trim().toLowerCase();
      const state = filter?.value || "all";
      let count = 0;
      tableRows.forEach((row) => {
        const visible = (!query || row.dataset.search.includes(query)) && (state === "all" || row.dataset.state === state);
        row.hidden = !visible;
        if (visible) count += 1;
      });
      if (visibleCount) visibleCount.textContent = this._number(count);
      if (noResults) noResults.hidden = count !== 0;
    };

    const selectEmployee = (row) => {
      tableRows.forEach((item) => item.classList.toggle("is-selected", item === row));
      const selected = rows[Number(row.dataset.employeeIndex)];
      if (detail) detail.innerHTML = this._detailMarkup(selected, topSales);
    };
    tableRows.forEach((row, index) => {
      row.addEventListener("click", () => selectEmployee(row));
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectEmployee(row);
        }
      });
      if (index === 0) row.classList.add("is-selected");
    });
    search?.addEventListener("input", applyFilters);
    filter?.addEventListener("change", applyFilters);
  },
};

window.EmployeePerformanceWindow = EmployeePerformanceWindow;
