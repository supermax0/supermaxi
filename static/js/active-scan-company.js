(function (global) {
  "use strict";

  function toast(message, type) {
    if (typeof global.showToast === "function") {
      global.showToast(message, type || "success");
      return;
    }
    try { console.log(message); } catch (_) {}
  }

  function setActiveScanCompany(id, name) {
    if (!global.FinoraBarcode || typeof global.FinoraBarcode.setActiveShippingCompany !== "function") {
      toast("تعذر تعيين شركة المسح", "error");
      return;
    }
    global.FinoraBarcode.setActiveShippingCompany(id, name || "");
    refreshActiveScanUI();
    toast("تم تعيين " + (name || "") + " كشركة مسح", "success");
  }

  function clearActiveScanCompany() {
    if (global.FinoraBarcode && typeof global.FinoraBarcode.clearActiveShippingCompany === "function") {
      global.FinoraBarcode.clearActiveShippingCompany();
    }
    refreshActiveScanUI();
    toast("تم إلغاء شركة المسح", "success");
  }

  function refreshActiveScanUI() {
    var badge = document.getElementById("activeScanCompanyBadge");
    var active = global.FinoraBarcode && global.FinoraBarcode.getActiveShippingCompany
      ? global.FinoraBarcode.getActiveShippingCompany()
      : null;

    document.querySelectorAll("#companiesTable tbody tr[data-company-id], .ship-m-card[data-company-id]").forEach(function (el) {
      var isActive = !!(active && String(el.getAttribute("data-company-id")) === String(active.id));
      el.classList.toggle("is-active-scan", isActive);
    });

    if (!badge) return;

    if (active) {
      badge.classList.add("is-set");
      badge.textContent = "";
      var label = document.createElement("span");
      label.textContent = "شركة المسح: " + (active.name || "");
      badge.appendChild(label);
      var clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.title = "إلغاء";
      clearBtn.textContent = "✕";
      clearBtn.addEventListener("click", clearActiveScanCompany);
      badge.appendChild(clearBtn);
    } else {
      badge.classList.remove("is-set");
      badge.textContent = "لم تحدد شركة مسح — اختر من الإجراءات";
    }
  }

  function onClick(e) {
    var btn = e.target && e.target.closest ? e.target.closest("[data-set-active-scan]") : null;
    if (!btn) return;
    e.preventDefault();
    var wrap = btn.closest("[data-company-id]");
    var id = btn.getAttribute("data-company-id") || (wrap && wrap.getAttribute("data-company-id"));
    var name = btn.getAttribute("data-company-name") || (wrap && wrap.getAttribute("data-company-name")) || "";
    var parsed = parseInt(id, 10);
    if (!parsed) return;
    setActiveScanCompany(parsed, name);
  }

  document.addEventListener("click", onClick);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", refreshActiveScanUI);
  } else {
    refreshActiveScanUI();
  }

  global.setActiveScanCompany = setActiveScanCompany;
  global.clearActiveScanCompany = clearActiveScanCompany;
  global.refreshActiveScanUI = refreshActiveScanUI;
})(window);
