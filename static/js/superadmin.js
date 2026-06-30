(function () {
  "use strict";

  var sidebar = document.getElementById("saSidebar");
  var backdrop = document.getElementById("saSidebarBackdrop");
  var toggle = document.getElementById("saMenuToggle");

  function openSidebar() {
    sidebar?.classList.add("open");
    backdrop?.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeSidebar() {
    sidebar?.classList.remove("open");
    backdrop?.classList.remove("open");
    document.body.style.overflow = "";
  }

  toggle?.addEventListener("click", function () {
    if (sidebar?.classList.contains("open")) closeSidebar();
    else openSidebar();
  });

  backdrop?.addEventListener("click", closeSidebar);

  document.querySelectorAll(".sa-nav .nav-link").forEach(function (link) {
    link.addEventListener("click", function () {
      if (window.innerWidth <= 1024) closeSidebar();
    });
  });

  var btn = document.getElementById("systemUpdateBtn");
  if (btn) {
    btn.addEventListener("click", function () {
      if (btn.disabled) return;
      if (!confirm("رفع التغييرات إلى GitHub وتحديث VPS؟")) return;
      btn.disabled = true;
      btn.classList.add("updating");
      fetch("/admin/system-update", {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
      })
        .then(function (r) {
          var ct = (r.headers.get("Content-Type") || "").toLowerCase();
          if (ct.indexOf("application/json") === -1) {
            return r.text().then(function () {
              throw new Error("الخادم أعاد استجابة غير متوقعة.");
            });
          }
          return r.json();
        })
        .then(function (data) {
          btn.disabled = false;
          btn.classList.remove("updating");
          if (data && data.status === "success") {
            alert(data.message || "تم التحديث بنجاح.");
          } else {
            alert("خطأ: " + (data && data.message ? data.message : "فشل التحديث"));
          }
        })
        .catch(function (err) {
          btn.disabled = false;
          btn.classList.remove("updating");
          alert(err && err.message ? err.message : "خطأ في الاتصال.");
        });
    });
  }
})();
