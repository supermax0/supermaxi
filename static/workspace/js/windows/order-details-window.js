const OrderDetailsWindow = {
  _esc(value) {
    const node = document.createElement("div");
    node.textContent = value == null || value === "" ? "—" : String(value);
    return node.innerHTML;
  },

  _money(value) {
    const amount = Number(value || 0);
    return `${amount.toLocaleString("en-US")} د.ع`;
  },

  _date(value) {
    if (!value) return "—";
    const parsed = new Date(String(value).replace(" ", "T"));
    if (Number.isNaN(parsed.getTime())) return this._esc(value);
    return parsed.toLocaleString("ar-IQ", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  },

  _field(label, value, extraClass = "") {
    return `<div class="ws-order-field ${extraClass}"><span>${this._esc(label)}</span><strong>${this._esc(value)}</strong></div>`;
  },

  _skeleton(orderId, phase, message) {
    const stages = [
      ["details", "بيانات الطلب"],
      ["finance", "الحركات المالية"],
      ["history", "سجل الحركات"],
    ];
    const ranks = { locating: 0, details: 1, finance: 2, history: 3, complete: 4 };
    const rank = ranks[phase] || 0;
    return `
      <div class="ws-order-loading" data-phase="${this._esc(phase)}">
        <div class="ws-order-loading-orbit"><span>${this._esc(orderId)}</span></div>
        <strong>${this._esc(message || "LEON يبحث في بيانات الطلب...")}</strong>
        <div class="ws-order-load-stages">
          ${stages.map(([key, label], index) => `
            <div class="ws-order-load-stage ${rank > index ? "is-done" : rank === index ? "is-active" : ""}">
              <i>${rank > index ? "✓" : index + 1}</i><span>${label}</span>
            </div>`).join("")}
        </div>
        <div class="ws-order-skeleton"><i></i><i></i><i></i><i></i></div>
      </div>`;
  },

  render(container, spec) {
    const props = spec.props || {};
    const phase = props.phase || "locating";
    const orderId = props.orderId || "—";
    if (props.error) {
      container.innerHTML = `
        <div class="ws-order-error">
          <span>!</span><strong>تعذّر فتح الطلب #${this._esc(orderId)}</strong>
          <p>${this._esc(props.error)}</p>
        </div>`;
      return;
    }
    if (!props.details) {
      container.innerHTML = this._skeleton(orderId, phase, props.message);
      return;
    }

    const data = props.details || {};
    const order = data.order || {};
    const summary = data.financial_summary || {};
    const movements = data.financial_movements || [];
    const history = props.history || [];
    const barcodes = Array.isArray(order.shipping_barcodes) && order.shipping_barcodes.length
      ? order.shipping_barcodes.join(" • ")
      : (order.shipping_barcode || "—");
    const paid = Number(summary.paid_amount ?? order.paid_amount ?? 0);
    const total = Number(summary.order_total ?? order.total ?? 0);
    const remaining = Number(summary.remaining_amount ?? Math.max(0, total - paid));
    const paymentClass = remaining <= 0 ? "is-paid" : paid > 0 ? "is-partial" : "is-unpaid";
    const paymentLabel = remaining <= 0 ? "مسدد بالكامل" : paid > 0 ? "مسدد جزئياً" : "غير مسدد";

    container.innerHTML = `
      <article class="ws-order-details" data-phase="${this._esc(phase)}">
        <section class="ws-order-hero ws-order-reveal" style="--reveal-index:0">
          <div>
            <span class="ws-order-kicker">LEON · ORDER INTELLIGENCE</span>
            <h3>الطلب #${this._esc(order.id || orderId)}</h3>
            <p>${this._esc(order.customer)} · ${this._esc(order.city)}</p>
          </div>
          <div class="ws-order-badges">
            <span>${this._esc(order.status)}</span>
            <span class="${paymentClass}">${paymentLabel}</span>
          </div>
        </section>

        <section class="ws-order-money-grid ws-order-reveal" style="--reveal-index:1">
          <div><span>قيمة الطلب</span><strong>${this._money(total)}</strong></div>
          <div><span>المدفوع</span><strong>${this._money(paid)}</strong></div>
          <div class="${remaining > 0 ? "has-remaining" : "is-clear"}"><span>المتبقي</span><strong>${this._money(remaining)}</strong></div>
        </section>

        <section class="ws-order-section ws-order-reveal" style="--reveal-index:2">
          <header><h4>بيانات الزبون والطلب</h4><span>معلومات مباشرة من النظام</span></header>
          <div class="ws-order-field-grid">
            ${this._field("الزبون", order.customer)}
            ${this._field("الهاتف الأول", order.phone, "is-ltr")}
            ${this._field("الهاتف الثاني", order.phone2, "is-ltr")}
            ${this._field("المحافظة", order.city)}
            ${this._field("العنوان", order.address, "is-wide")}
            ${this._field("الموظف", order.employee)}
            ${this._field("تاريخ الإنشاء", this._date(order.created_at))}
            ${this._field("الفرع", order.branch_name)}
          </div>
        </section>

        <section class="ws-order-section ws-order-reveal" style="--reveal-index:3">
          <header><h4>الشحن والباركود</h4><span>${this._esc(order.shipping_status || "—")}</span></header>
          <div class="ws-order-field-grid">
            ${this._field("شركة النقل", order.shipping_company)}
            ${this._field("باركودات النقل", barcodes, "is-wide is-ltr")}
          </div>
        </section>

        <section class="ws-order-section ws-order-reveal" style="--reveal-index:4">
          <header><h4>أصناف الطلب</h4><span>${(data.items || []).length} صنف</span></header>
          <div class="ws-order-items">
            ${(data.items || []).length ? (data.items || []).map((item, index) => `
              <div class="ws-order-item" style="--item-index:${index}">
                <div><strong>${this._esc(item.name)}</strong><span>الكمية ${this._esc(item.qty)}</span></div>
                <div><span>${this._money(item.price)}</span><strong>${this._money(item.total)}</strong></div>
              </div>`).join("") : `<p class="ws-order-empty">لا توجد أصناف ظاهرة لهذا الطلب.</p>`}
          </div>
        </section>

        <section class="ws-order-section ws-order-finance ws-order-reveal" style="--reveal-index:5">
          <header><h4>الحركات المالية</h4><span>${movements.length} حركة · الصافي ${this._money(summary.net_ledger_amount || 0)}</span></header>
          <div class="ws-order-timeline">
            ${movements.length ? movements.map((movement, index) => {
              const amount = Number(movement.amount_delta || 0);
              return `<div class="ws-order-timeline-row ${amount < 0 ? "is-reversal" : "is-collection"}" style="--item-index:${index}">
                <i></i>
                <div><strong>${amount < 0 ? "عكس/تخفيض دفعة" : "تسجيل دفعة"}</strong><span>${this._esc(movement.treasury_account || movement.payment_method || "الحساب الافتراضي")}</span><small>${this._esc(movement.note || movement.source_module || "حركة تسديد")}</small></div>
                <div><b>${amount > 0 ? "+" : ""}${this._money(amount)}</b><time>${this._date(movement.recorded_at)}</time></div>
              </div>`;
            }).join("") : `<p class="ws-order-empty">لا توجد قيود دفع مسجلة على هذا الطلب.</p>`}
          </div>
        </section>

        <section class="ws-order-section ws-order-history ws-order-reveal" style="--reveal-index:6">
          <header><h4>سجل حركات الطلب</h4><span>${history.length} حدث</span></header>
          ${phase !== "complete" && !history.length ? this._skeleton(orderId, "history", "أجمع سجل التغييرات الآن...") : `
            <div class="ws-order-timeline">
              ${history.length ? history.slice(0, 80).map((event, index) => `
                <div class="ws-order-timeline-row is-history" style="--item-index:${index}">
                  <i></i><div><strong>${this._esc(event.movement)}</strong><span>${this._esc(event.employee)}</span><small>${this._esc(event.details)}</small></div>
                  <time>${this._date(event.created_at)}</time>
                </div>`).join("") : `<p class="ws-order-empty">لا توجد حركات إضافية.</p>`}
            </div>`}
        </section>

        ${order.note ? `<section class="ws-order-note ws-order-reveal" style="--reveal-index:7"><strong>ملاحظة الطلب</strong><p>${this._esc(order.note)}</p></section>` : ""}
        <footer class="ws-order-actions ws-order-reveal" style="--reveal-index:8">
          ${order.invoice_url ? `<a href="${this._esc(order.invoice_url)}" target="_blank" rel="noopener">فتح الفاتورة</a>` : ""}
          <button type="button" data-order-scroll-top>العودة للأعلى</button>
        </footer>
      </article>`;

    container.querySelector("[data-order-scroll-top]")?.addEventListener("click", () => {
      container.scrollTo({ top: 0, behavior: "smooth" });
    });
  },
};

window.OrderDetailsWindow = OrderDetailsWindow;
