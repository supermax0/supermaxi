(function () {
  "use strict";

  const fmt = (n) => Number(n || 0).toLocaleString("ar-IQ");
  let dashboard = null;
  let modalEmployeeId = null;

  function treasuryId() {
    const el = document.getElementById("treasuryAccount");
    return el ? parseInt(el.value, 10) : null;
  }

  function toast(msg, ok) {
    if (window.showToast) {
      window.showToast(msg, ok ? "success" : "error");
      return;
    }
    alert(msg);
  }

  async function api(url, options) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || data.message || "حدث خطأ");
    }
    return data;
  }

  function setSummary(data) {
    document.getElementById("summarySalaryDue").textContent = fmt(data.total_salary_due);
    document.getElementById("summaryCommissionDue").textContent = fmt(data.total_commission_due);
    document.getElementById("summaryTotalDue").textContent = fmt(data.total_due);
  }

  function initCommissionMonth() {
    const input = document.getElementById("commissionMonth");
    if (!input || input.value) return;
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    input.value = `${y}-${m}`;
  }

  function getCommissionPeriod() {
    const input = document.getElementById("commissionMonth");
    if (!input || !input.value) return null;
    const [year, month] = input.value.split("-").map((v) => parseInt(v, 10));
    if (!year || !month || month < 1 || month > 12) return null;
    return { year, month };
  }

  function formatPeriodLabel(year, month) {
    try {
      const d = new Date(year, month - 1, 1);
      return d.toLocaleDateString("ar-IQ", { year: "numeric", month: "long" });
    } catch (e) {
      return `${year}-${String(month).padStart(2, "0")}`;
    }
  }

  function requireCommissionPeriod() {
    const period = getCommissionPeriod();
    if (!period) {
      toast("اختر شهر السداد أولاً", false);
      const input = document.getElementById("commissionMonth");
      if (input) input.focus();
      return null;
    }
    return period;
  }

  function renderDue(rows) {
    const body = document.getElementById("dueTableBody");
    if (!rows || !rows.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty">لا توجد مستحقات حالياً</td></tr>';
      return;
    }
    body.innerHTML = rows
      .map((r) => {
        const kindLabel = r.kind === "commission" ? "عمولة" : "راتب";
        const typeLabel = r.payee_type === "delivery_agent" ? "مندوب" : "موظف";
        const dueBadge = r.paid_in_current_cycle
          ? '<span class="payroll-badge paid">تم الصرف</span>'
          : r.is_due
            ? '<span class="payroll-badge due">مستحق</span>'
            : '<span class="payroll-badge">مجدول</span>';
        let action = "";
        if (r.kind === "commission" && r.is_due) {
          action = `<button type="button" class="payroll-btn small primary" data-settle-commission="${r.payee_id}">سداد</button>`;
        } else if (r.kind === "salary" && r.is_due) {
          action = `<button type="button" class="payroll-btn small primary" data-pay-salary="${r.payee_type}:${r.payee_id}">صرف</button>`;
        } else if (r.kind === "salary" && r.can_pay_manually !== false) {
          action = `<button type="button" class="payroll-btn small secondary" data-pay-salary-manual="${r.payee_type}:${r.payee_id}">صرف يدوي</button>`;
        }
        return `<tr>
          <td>${r.name}</td>
          <td>${typeLabel} — ${kindLabel}</td>
          <td>${r.schedule_label || "—"}</td>
          <td>${fmt(r.amount)} د.ع</td>
          <td>${r.next_pay_date || "—"} ${dueBadge}</td>
          <td>${action}</td>
        </tr>`;
      })
      .join("");
  }

  function renderCommission(rows, period) {
    const body = document.getElementById("commissionTableBody");
    const summary = document.getElementById("commissionMonthSummary");
    const periodLabel = period ? formatPeriodLabel(period.year, period.month) : "";

    if (summary) {
      if (!period) {
        summary.textContent = "اختر الشهر لعرض العمولات المعلّقة";
      } else if (!rows || !rows.length) {
        summary.textContent = `لا توجد عمولات معلّقة في ${periodLabel}`;
      } else {
        const totalOrders = rows.reduce((s, r) => s + Number(r.orders || 0), 0);
        const carriedOrders = rows.reduce((s, r) => s + Number(r.carried_orders || 0), 0);
        const totalAmount = rows.reduce((s, r) => s + Number(r.amount || 0), 0);
        let text = `${periodLabel} — ${rows.length} موظف — ${fmt(totalOrders)} طلب — ${fmt(totalAmount)} د.ع`;
        if (carriedOrders > 0) {
          text += ` (منها ${fmt(carriedOrders)} مرحّل من أشهر سابقة)`;
        }
        summary.textContent = text;
      }
    }

    if (!rows || !rows.length) {
      body.innerHTML = `<tr><td colspan="5" class="empty">${
        period ? "لا توجد عمولات معلّقة لهذا الشهر" : "اختر الشهر ثم اضغط عرض"
      }</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map((r) => {
        const carried = Number(r.carried_orders || 0);
        const ordersCell =
          carried > 0
            ? `${r.orders} <span class="payroll-badge" title="طلبات وصلت بعد أشهر سابقة وكانت جاري شحن">+${carried} مرحّل</span>`
            : `${r.orders}`;
        return `<tr>
          <td>${r.employee_name}</td>
          <td>${ordersCell}</td>
          <td>${fmt(r.commission_rate)} د.ع</td>
          <td>${fmt(r.amount)} د.ع</td>
          <td>
            <button type="button" class="payroll-btn small secondary" data-view-commission="${r.employee_id}">التفاصيل</button>
            <button type="button" class="payroll-btn small primary" data-settle-commission="${r.employee_id}">سداد الشهر</button>
          </td>
        </tr>`;
      })
      .join("");
  }

  function renderSchedule(rows) {
    const body = document.getElementById("scheduleTableBody");
    if (!rows || !rows.length) {
      body.innerHTML = '<tr><td colspan="4" class="empty">لا توجد جداول رواتب</td></tr>';
      return;
    }
    body.innerHTML = rows
      .map(
        (r) => `<tr>
          <td>${r.name}</td>
          <td>${r.schedule_label}</td>
          <td>${fmt(r.amount)} د.ع</td>
          <td>${r.next_pay_date || "—"}</td>
        </tr>`
      )
      .join("");
  }

  async function loadHistory() {
    const body = document.getElementById("historyTableBody");
    try {
      const data = await api("/payroll/api/history");
      const rows = data.rows || [];
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="5" class="empty">لا يوجد سجل مدفوعات</td></tr>';
        return;
      }
      body.innerHTML = rows
        .map((r) => {
          const exp = r.expense_id
            ? `<a href="/expenses">#${r.expense_id}</a>`
            : "—";
          const date = r.paid_at ? r.paid_at.slice(0, 16).replace("T", " ") : "—";
          return `<tr>
            <td>${date}</td>
            <td>${r.payee_name}</td>
            <td>${r.payment_kind_label}</td>
            <td>${fmt(r.amount)} د.ع</td>
            <td>${exp}</td>
          </tr>`;
        })
        .join("");
    } catch (e) {
      body.innerHTML = `<tr><td colspan="5" class="empty">${e.message}</td></tr>`;
    }
  }

  async function loadDashboard() {
    const period = getCommissionPeriod();
    let url = "/payroll/api/dashboard";
    if (period) {
      url += `?year=${period.year}&month=${period.month}`;
    }
    const data = await api(url);
    dashboard = data;
    setSummary(data);
    renderDue(data.due_rows || []);
    renderCommission(data.commission_employees || [], period);
    renderSchedule(data.schedule_rows || []);
  }

  async function settleCommission(employeeId) {
    const tid = treasuryId();
    if (!tid) {
      toast("اختر حساب الخزينة", false);
      return;
    }
    const period = requireCommissionPeriod();
    if (!period) return;
    const label = formatPeriodLabel(period.year, period.month);
    if (
      !confirm(
        `تأكيد سداد عمولات ${label} لهذا الموظف؟\n(يشمل طلبات الشهر + المرحّلة من جاري شحن أشهر سابقة بعد وصولها)`
      )
    )
      return;
    try {
      const res = await api("/payroll/api/settle-commission", {
        method: "POST",
        body: JSON.stringify({
          employee_id: employeeId,
          treasury_account_id: tid,
          year: period.year,
          month: period.month,
        }),
      });
      toast(res.message || "تم السداد", true);
      closeModal();
      await loadDashboard();
      await loadHistory();
    } catch (e) {
      toast(e.message, false);
    }
  }

  async function paySalary(payeeType, payeeId, manual) {
    const tid = treasuryId();
    if (!tid) {
      toast("اختر حساب الخزينة", false);
      return;
    }
    const label = manual ? "صرف يدوي للراتب؟" : "صرف الراتب المستحق؟";
    if (!confirm(label)) return;
    try {
      const res = await api("/payroll/api/pay-salary", {
        method: "POST",
        body: JSON.stringify({
          payee_type: payeeType,
          payee_id: payeeId,
          treasury_account_id: tid,
          manual: !!manual,
        }),
      });
      toast(res.message || "تم الصرف", true);
      await loadDashboard();
      await loadHistory();
    } catch (e) {
      toast(e.message, false);
    }
  }

  async function processDue() {
    const tid = treasuryId();
    if (!tid) {
      toast("اختر حساب الخزينة", false);
      return;
    }
    if (!confirm("صرف كل الرواتب المستحقة اليوم من الخزينة؟")) return;
    try {
      const res = await api("/payroll/api/process-due", {
        method: "POST",
        body: JSON.stringify({ treasury_account_id: tid }),
      });
      let msg = res.message || "تم";
      if (res.skipped_count) {
        msg += ` — تعذر صرف ${res.skipped_count}`;
      }
      toast(msg, true);
      await loadDashboard();
      await loadHistory();
    } catch (e) {
      toast(e.message, false);
    }
  }

  function openModal() {
    document.getElementById("commissionModal").hidden = false;
  }

  function closeModal() {
    document.getElementById("commissionModal").hidden = true;
    modalEmployeeId = null;
  }

  async function viewCommission(employeeId) {
    const period = requireCommissionPeriod();
    if (!period) return;
    try {
      const data = await api(
        `/payroll/api/commission/${employeeId}?year=${period.year}&month=${period.month}`
      );
      modalEmployeeId = employeeId;
      const label = formatPeriodLabel(period.year, period.month);
      document.getElementById("commissionModalTitle").textContent =
        `عمولات ${data.employee_name} — ${label} (${data.order_count} طلب)`;
      const settleBtn = document.getElementById("btnSettleFromModal");
      if (settleBtn) settleBtn.textContent = `سداد ${label}`;
      const body = document.getElementById("commissionLinesBody");
      const lines = data.lines || [];
      body.innerHTML = lines.length
        ? lines
            .map(
              (l) => `<tr>
                <td><code>${l.code}</code></td>
                <td>#${l.invoice_id}</td>
                <td>${l.customer_name || "—"}</td>
                <td>${fmt(l.amount)} د.ع</td>
              </tr>`
            )
            .join("")
        : '<tr><td colspan="4" class="empty">لا توجد أسطر لهذا الشهر</td></tr>';
      openModal();
    } catch (e) {
      toast(e.message, false);
    }
  }

  function bindTabs() {
    document.querySelectorAll(".payroll-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".payroll-tab").forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".payroll-panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        const id = tab.getAttribute("data-tab");
        const panel = document.getElementById(
          "panel" + id.charAt(0).toUpperCase() + id.slice(1)
        );
        if (panel) panel.classList.add("active");
        if (id === "history") loadHistory();
        if (id === "statement") initStatementMonth();
        if (id === "commission") {
          initCommissionMonth();
          loadDashboard().catch((e) => toast(e.message, false));
        }
      });
    });
  }

  // ==================== Monthly Orders Statement ====================
  let lastStatementData = null;

  function initStatementMonth() {
    const input = document.getElementById("statementMonth");
    if (!input || input.value) return;
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    input.value = `${y}-${m}`;
  }

  function getStatementPeriod() {
    const input = document.getElementById("statementMonth");
    if (!input || !input.value) {
      const now = new Date();
      return { year: now.getFullYear(), month: now.getMonth() + 1 };
    }
    const [year, month] = input.value.split("-").map((v) => parseInt(v, 10));
    return { year, month };
  }

  function formatStatementPeriodLabel(year, month) {
    return formatPeriodLabel(year, month);
  }

  function renderStatement(data) {
    lastStatementData = data;
    const body = document.getElementById("statementTableBody");
    const foot = document.getElementById("statementTableFoot");
    const summary = document.getElementById("statementSummary");
    const noteEl = document.getElementById("statementNote");
    const rows = data.rows || [];
    const totals = data.totals || {};

    if (noteEl && data.note) noteEl.textContent = data.note;

    if (summary) {
      summary.textContent = rows.length
        ? `${data.title || `طلبات شهر ${data.month}`} — ${rows.length} موظف — كلي: ${fmt(
            totals.total_orders
          )} | واصل: ${fmt(totals.delivered_orders)} | راجع/ملغي: ${fmt(
            totals.returned_orders
          )} | جاري: ${fmt(totals.pending_orders)} | عمولة الواصل: ${fmt(totals.total_amount)} د.ع`
        : `لا توجد طلبات في ${data.title || `شهر ${data.month}`}`;
    }

    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="8" class="empty">لا توجد طلبات في هذا الشهر</td></tr>';
      if (foot) foot.innerHTML = "";
      return;
    }

    body.innerHTML = rows
      .map(
        (r, i) => `<tr>
          <td>${i + 1}</td>
          <td><strong>${r.employee_name}</strong></td>
          <td>${fmt(r.total_orders)}</td>
          <td>${fmt(r.delivered_orders)}</td>
          <td>${fmt(r.returned_orders)}</td>
          <td>${fmt(r.pending_orders)}${
            r.carried_pending
              ? ` <span class="payroll-badge" title="مرحّل من أشهر سابقة">+${fmt(r.carried_pending)} مرحّل</span>`
              : ""
          }</td>
          <td>${fmt(r.total_amount)} د.ع</td>
          <td dir="ltr">${r.transfer_number || "—"}</td>
        </tr>`
      )
      .join("");

    if (foot) {
      foot.innerHTML = `<tr>
        <td colspan="2">الإجمالي</td>
        <td>${fmt(totals.total_orders)}</td>
        <td>${fmt(totals.delivered_orders)}</td>
        <td>${fmt(totals.returned_orders)}</td>
        <td>${fmt(totals.pending_orders)}</td>
        <td>${fmt(totals.total_amount)} د.ع</td>
        <td></td>
      </tr>`;
    }
  }

  async function loadStatement() {
    const { year, month } = getStatementPeriod();
    try {
      const data = await api(`/payroll/api/monthly-statement?year=${year}&month=${month}`);
      renderStatement(data);
    } catch (e) {
      toast(e.message, false);
    }
  }

  function printStatement() {
    if (!lastStatementData || !(lastStatementData.rows || []).length) {
      toast("اعرض الكشف أولاً ثم اطبع", false);
      return;
    }

    const data = lastStatementData;
    const totals = data.totals || {};
    const titleEl = document.getElementById("pspTitle");
    const periodEl = document.getElementById("pspPeriod");
    const printedAtEl = document.getElementById("pspPrintedAt");
    const summaryEl = document.getElementById("pspSummary");
    const noteEl = document.getElementById("pspNote");
    const bodyEl = document.getElementById("pspBody");
    const footEl = document.getElementById("pspFoot");
    if (!bodyEl) return;

    if (titleEl) titleEl.textContent = data.title || `طلبات شهر ${data.month}`;
    if (periodEl) periodEl.textContent = formatStatementPeriodLabel(data.year, data.month);
    if (printedAtEl) printedAtEl.textContent = new Date().toLocaleString("ar-IQ");
    if (summaryEl) {
      summaryEl.textContent = `الموظفون: ${(data.rows || []).length} — الكلي: ${fmt(
        totals.total_orders
      )} — الواصل: ${fmt(totals.delivered_orders)} — الراجع/الملغي: ${fmt(
        totals.returned_orders
      )} — الجاري: ${fmt(totals.pending_orders)} — عمولة الواصل: ${fmt(
        totals.total_amount
      )} د.ع`;
    }
    if (noteEl) noteEl.textContent = data.note || "";

    bodyEl.innerHTML = (data.rows || [])
      .map(
        (r, i) => `<tr>
          <td class="psp-col-index">${i + 1}</td>
          <td class="psp-col-name">${r.employee_name}</td>
          <td class="psp-col-num">${fmt(r.total_orders)}</td>
          <td class="psp-col-num">${fmt(r.delivered_orders)}</td>
          <td class="psp-col-num">${fmt(r.returned_orders)}</td>
          <td class="psp-col-num">${fmt(r.pending_orders)}</td>
          <td class="psp-col-amount">${fmt(r.total_amount)} د.ع</td>
          <td class="psp-col-transfer">${r.transfer_number || "—"}</td>
        </tr>`
      )
      .join("");

    if (footEl) {
      footEl.innerHTML = `<tr>
        <td colspan="2">الإجمالي</td>
        <td class="psp-col-num">${fmt(totals.total_orders)}</td>
        <td class="psp-col-num">${fmt(totals.delivered_orders)}</td>
        <td class="psp-col-num">${fmt(totals.returned_orders)}</td>
        <td class="psp-col-num">${fmt(totals.pending_orders)}</td>
        <td class="psp-col-amount">${fmt(totals.total_amount)} د.ع</td>
        <td></td>
      </tr>`;
    }

    requestAnimationFrame(() => window.print());
  }

  function bindActions() {
    document.getElementById("btnRefresh").addEventListener("click", () => {
      loadDashboard().catch((e) => toast(e.message, false));
    });
    document.getElementById("btnProcessDue").addEventListener("click", processDue);
    document.getElementById("btnSettleFromModal").addEventListener("click", () => {
      if (modalEmployeeId) settleCommission(modalEmployeeId);
    });
    document.querySelectorAll("[data-close-modal]").forEach((el) => {
      el.addEventListener("click", closeModal);
    });

    const btnLoad = document.getElementById("btnLoadStatement");
    const btnPrint = document.getElementById("btnPrintStatement");
    if (btnLoad) btnLoad.addEventListener("click", () => loadStatement());
    if (btnPrint) btnPrint.addEventListener("click", printStatement);

    const btnLoadCommission = document.getElementById("btnLoadCommission");
    const commissionMonth = document.getElementById("commissionMonth");
    if (btnLoadCommission) {
      btnLoadCommission.addEventListener("click", () => {
        loadDashboard().catch((e) => toast(e.message, false));
      });
    }
    if (commissionMonth) {
      commissionMonth.addEventListener("change", () => {
        loadDashboard().catch((e) => toast(e.message, false));
      });
    }

    document.body.addEventListener("click", (e) => {
      const settle = e.target.closest("[data-settle-commission]");
      if (settle) {
        settleCommission(parseInt(settle.getAttribute("data-settle-commission"), 10));
        return;
      }
      const view = e.target.closest("[data-view-commission]");
      if (view) {
        viewCommission(parseInt(view.getAttribute("data-view-commission"), 10));
        return;
      }
      const pay = e.target.closest("[data-pay-salary]");
      if (pay) {
        const [t, id] = pay.getAttribute("data-pay-salary").split(":");
        paySalary(t, parseInt(id, 10), false);
        return;
      }
      const payManual = e.target.closest("[data-pay-salary-manual]");
      if (payManual) {
        const [t, id] = payManual.getAttribute("data-pay-salary-manual").split(":");
        paySalary(t, parseInt(id, 10), true);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindTabs();
    bindActions();
    initStatementMonth();
    initCommissionMonth();
    loadDashboard()
      .then(() => loadHistory())
      .catch((e) => toast(e.message, false));
  });
})();
