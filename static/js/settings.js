(function () {
  "use strict";

  function initSubnavScrollHint() {
    document.querySelectorAll(".settings-subnav-wrap").forEach(function (wrap) {
      var nav = wrap.querySelector(".settings-subnav");
      if (!nav) return;
      function updateHint() {
        var maxScroll = nav.scrollWidth - nav.clientWidth;
        var pos = Math.abs(nav.scrollLeft);
        var atStart = pos <= 2;
        var atEnd = maxScroll <= 2 || pos >= maxScroll - 2;
        wrap.style.setProperty("--subnav-fade-start", atStart ? "0" : "1");
        wrap.style.setProperty("--subnav-fade-end", atEnd ? "0" : "1");
      }
      nav.addEventListener("scroll", updateHint, { passive: true });
      window.addEventListener("resize", updateHint, { passive: true });
      updateHint();
    });
  }

  function initInnerTabs() {
    document.querySelectorAll("[data-settings-tabs]").forEach(function (root) {
      var tabs = root.querySelectorAll(".settings-inner-tab");
      var panels = root.querySelectorAll(".settings-inner-panel");
      tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
          var target = tab.getAttribute("data-tab");
          tabs.forEach(function (t) { t.classList.remove("active"); });
          panels.forEach(function (p) {
            p.classList.toggle("active", p.getAttribute("data-tab-panel") === target);
          });
          tab.classList.add("active");
        });
      });
    });
  }

  function initStickyBar() {
    if (document.querySelector(".settings-sticky-bar")) {
      document.body.classList.add("settings-has-sticky-bar");
    }
  }

  window.settingsFetchJson = function (url, options) {
    return fetch(url, options || {}).then(function (r) {
      return r.json().then(function (data) {
        return { ok: r.ok, status: r.status, data: data };
      });
    });
  };

  window.settingsSave = function (opts) {
    var btn = opts.button;
    if (btn) btn.disabled = true;
    return settingsFetchJson(opts.url, {
      method: opts.method || "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, opts.headers || {}),
      body: JSON.stringify(opts.payload || {}),
    })
      .then(function (res) {
        if (btn) btn.disabled = false;
        if (res.ok && res.data && res.data.success !== false) {
          if (typeof showToast === "function") {
            showToast(opts.successMessage || "تم الحفظ بنجاح", "success");
          }
          if (opts.onSuccess) opts.onSuccess(res.data);
          return res.data;
        }
        if (typeof showToast === "function") {
          showToast((res.data && res.data.error) || opts.errorMessage || "حدث خطأ أثناء الحفظ", "error");
        }
        if (opts.onError) opts.onError(res.data);
        return null;
      })
      .catch(function () {
        if (btn) btn.disabled = false;
        if (typeof showToast === "function") {
          showToast(opts.networkError || "خطأ في الاتصال بالخادم", "error");
        }
        if (opts.onError) opts.onError(null);
        return null;
      });
  };

  window.openSettingsModal = function (id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    var focusable = modal.querySelector("input, button, select, textarea, [tabindex]");
    if (focusable) focusable.focus();
  };

  window.closeSettingsModal = function (id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  };

  function initModals() {
    document.querySelectorAll(".settings-modal-backdrop").forEach(function (backdrop) {
      backdrop.addEventListener("click", function (e) {
        if (e.target === backdrop) {
          closeSettingsModal(backdrop.id);
        }
      });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      document.querySelectorAll(".settings-modal-backdrop.is-open").forEach(function (modal) {
        closeSettingsModal(modal.id);
      });
    });
  }

  function initMobileSubnav() {
    var select = document.getElementById("settingsSubnavMobile");
    if (!select) return;
    select.addEventListener("change", function () {
      var url = select.value;
      if (url && url !== window.location.pathname) {
        window.location.href = url;
      }
    });
  }

  function init() {
    initSubnavScrollHint();
    initStickyBar();
    initModals();
    initInnerTabs();
    initMobileSubnav();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
