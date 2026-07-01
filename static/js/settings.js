(function () {
  "use strict";

  function initSettingsNav() {
    var nav = document.getElementById("settingsNav");
    var backdrop = document.getElementById("settingsNavBackdrop");
    var toggle = document.getElementById("settingsNavToggle");
    if (!nav) return;

    function openNav() {
      nav.classList.add("is-open");
      if (backdrop) backdrop.classList.add("is-open");
      document.body.style.overflow = "hidden";
    }

    function closeNav() {
      nav.classList.remove("is-open");
      if (backdrop) backdrop.classList.remove("is-open");
      document.body.style.overflow = "";
    }

    if (toggle) {
      toggle.addEventListener("click", function () {
        if (nav.classList.contains("is-open")) closeNav();
        else openNav();
      });
    }

    if (backdrop) {
      backdrop.addEventListener("click", closeNav);
    }

    nav.querySelectorAll(".settings-nav-item").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.innerWidth <= 900) closeNav();
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeNav();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSettingsNav);
  } else {
    initSettingsNav();
  }
})();
