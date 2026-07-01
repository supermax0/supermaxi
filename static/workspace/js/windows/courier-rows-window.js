const CourierRowsWindow = {
  _filters: ["all", "matched", "review", "unmatched", "duplicate"],
  _labels: {
    all: "الكل",
    matched: "مطابق",
    review: "مراجعة",
    unmatched: "غير مطابق",
    duplicate: "مكرر",
  },

  render(container, spec, handlers = {}) {
    const p = spec.props || {};
    container.innerHTML = `
      <div class="ws-courier-rows">
        <div class="ws-courier-row-filters"></div>
        <div class="ws-courier-rows-loading">جاري تحميل الصفوف...</div>
        <div class="ws-courier-rows-table-wrap"></div>
      </div>`;
    const filterEl = container.querySelector(".ws-courier-row-filters");
    const current = p.filter || "all";
    this._filters.forEach((f) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `ws-btn ws-btn-ghost ws-courier-filter${f === current ? " active" : ""}`;
      btn.textContent = this._labels[f];
      btn.dataset.filter = f;
      btn.addEventListener("click", () => {
        if (handlers.onFilter) handlers.onFilter(f);
      });
      filterEl.appendChild(btn);
    });
    if (p.rows) {
      this._renderTable(container, p.rows);
    } else if (p.analysisId && handlers.loadRows) {
      handlers.loadRows(p.analysisId, current);
    }
  },

  _renderTable(container, rows) {
    const loading = container.querySelector(".ws-courier-rows-loading");
    const wrap = container.querySelector(".ws-courier-rows-table-wrap");
    if (loading) loading.style.display = "none";
    if (!rows.length) {
      wrap.innerHTML = "<p>لا توجد صفوف</p>";
      return;
    }
    const table = document.createElement("table");
    table.className = "ws-courier-table";
    table.innerHTML = `<thead><tr>
      <th>#</th><th>رقم الطلب</th><th>العميل</th><th>المبلغ</th><th>أجور</th><th>الصافي</th><th>المطابقة</th><th>النتيجة</th>
    </tr></thead>`;
    const tbody = document.createElement("tbody");
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${r.row_index}</td>
        <td>${r.normalized_order_number || r.raw_order_number || "—"}</td>
        <td>${r.customer_name || "—"}</td>
        <td>${this._fmt(r.collected_amount)}</td>
        <td>${this._fmt(r.delivery_fee)}</td>
        <td>${this._fmt(r.net_amount)}</td>
        <td><span class="ws-courier-status ws-courier-status-${r.match_status}">${r.match_status}</span></td>
        <td>${(r.match_score || 0).toFixed(0)}%</td>`;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.innerHTML = "";
    wrap.appendChild(table);
  },

  _fmt(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString("ar-IQ");
  },

  showRows(container, rows) {
    this._renderTable(container, rows || []);
  },
};

window.CourierRowsWindow = CourierRowsWindow;
