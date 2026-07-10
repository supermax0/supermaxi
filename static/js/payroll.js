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
        const dueBadge = r.is_due
          ? '<span class="payroll-badge due">مستحق</span>'
          : '<span class="payroll-badge">مجدول</span>';
        let action = "";
        if (r.kind === "commission" && r.is_due) {
          action = `<button type="button" class="payroll-btn small primary" data-settle-commission="${r.payee_id}">سداد</button>`;
        } else if (r.kind === "salary" && r.is_due) {
          action = `<button type="button" class="payroll-btn small primary" data-pay-salary="${r.payee_type}:${r.payee_id}">صرف</button>`;
        } else if (r.kind === "salary") {
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

  function renderCommission(rows) {
    const body = document.getElementById("commissionTableBody");
    if (!rows || !rows.length) {
      body.innerHTML = '<tr><td colspan="5" class="empty">لا توجد عمولات معلّقة</td></tr>';
      return;
    }
    body.innerHTML = rows
      .map(
        (r) => `<tr>
          <td>${r.employee_name}</td>
          <td>${r.orders}</td>
          <td>${fmt(r.commission_rate)} د.ع</td>
          <td>${fmt(r.amount)} د.ع</td>
          <td>
            <button type="button" class="payroll-btn small secondary" data-view-commission="${r.employee_id}">التفاصيل</button>
            <button type="button" class="payroll-btn small primary" data-settle-commission="${r.employee_id}">سداد</button>
          </td>
        </tr>`
      )
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
    const data = await api("/payroll/api/dashboard");
    dashboard = data;
    setSummary(data);
    renderDue(data.due_rows || []);
    renderCommission(data.commission_employees || []);
    renderSchedule(data.schedule_rows || []);
  }

  async function settleCommission(employeeId) {
    const tid = treasuryId();
    if (!tid) {
      toast("اختر حساب الخزينة", false);
      return;
    }
    if (!confirm("تأكيد سداد كل العمولات المعلّقة لهذا الموظف؟")) return;
    try {
      const res = await api("/payroll/api/settle-commission", {
        method: "POST",
        body: JSON.stringify({ employee_id: employeeId, treasury_account_id: tid }),
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
    try {
      const data = await api(`/payroll/api/commission/${employeeId}`);
      modalEmployeeId = employeeId;
      document.getElementById("commissionModalTitle").textContent =
        `عمولات ${data.employee_name} (${data.order_count} طلب)`;
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
        : '<tr><td colspan="4" class="empty">لا توجد أسطر</td></tr>';
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
      });
    });
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
    loadDashboard()
      .then(() => loadHistory())
      .catch((e) => toast(e.message, false));
  });
})();
