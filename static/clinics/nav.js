/* Clinics role-aware navigation — Phase UX */
(() => {
  const HREF = {
    dashboard: "/clinics/",
    activity: "/clinics/activity",
    reception: "/clinics/reception",
    appointments: "/clinics/appointments",
    queue: "/clinics/queue",
    display: "/clinics/display",
    patients: "/clinics/patients",
    visits: "/clinics/visits",
    doctor: "/clinics/doctor",
    clinical: "/clinics/clinical",
    labs: "/clinics/labs",
    radiology: "/clinics/radiology",
    procedures: "/clinics/procedures",
    followups: "/clinics/followups",
    billing: "/clinics/billing",
    expenses: "/clinics/expenses",
    cash: "/clinics/cash",
    settlements: "/clinics/settlements",
    inventory: "/clinics/inventory",
    purchases: "/clinics/purchases",
    suppliers: "/clinics/suppliers",
    doctors: "/clinics/staff",
    specialties: "/clinics/specialties",
    schedules: "/clinics/schedules",
    services: "/clinics/services",
    rooms: "/clinics/rooms",
    attachments: "/clinics/attachments",
    communications: "/clinics/communications",
    reports: "/clinics/reports",
    settings: "/clinics/settings",
  };

  const MOBILE_META = {
    dashboard: { icon: "fa-house-medical", label: "الرئيسية" },
    reception: { icon: "fa-desktop", label: "استقبال" },
    appointments: { icon: "fa-calendar-check", label: "مواعيد" },
    visits: { icon: "fa-notes-medical", label: "زيارات" },
    doctor: { icon: "fa-stethoscope", label: "معاينة" },
    patients: { icon: "fa-user-injured", label: "مرضى" },
    clinical: { icon: "fa-folder-medical", label: "سجل" },
    billing: { icon: "fa-file-invoice-dollar", label: "مالية" },
  };

  function initials(name) {
    const parts = String(name || "م").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "م";
    return ((parts[0][0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] || "" : "")).toUpperCase();
  }

  function applyUser(user) {
    if (!user || !user.name) return;
    const name = user.name;
    const role = user.role_label || user.role || "موظف";
    const av = initials(name);
    const setText = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };
    setText("cxUserName", name);
    setText("cxUserNamePanel", name);
    setText("cxSidebarUserName", name);
    setText("cxUserRole", role);
    setText("cxUserRolePanel", role);
    setText("cxSidebarUserRole", role);
    ["cxUserAvatar", "cxUserAvatarLarge", "cxSidebarUserAvatar"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (user.avatar) {
        el.style.backgroundImage = `url(${user.avatar})`;
        el.style.backgroundSize = "cover";
        el.style.backgroundPosition = "center";
        el.textContent = "";
      } else {
        el.style.backgroundImage = "";
        el.textContent = av;
      }
    });
  }

  function applyNav(nav) {
    if (!nav || !nav.items) return;
    const items = nav.items;
    document.querySelectorAll("[data-nav-key]").forEach((el) => {
      const key = el.getAttribute("data-nav-key");
      const show = !!items[key];
      el.hidden = !show;
      el.classList.toggle("cx-nav-hidden", !show);
      if (!show) el.setAttribute("aria-hidden", "true");
      else el.removeAttribute("aria-hidden");
    });

    document.querySelectorAll(".cx-sidebar__group").forEach((group) => {
      const visibleLinks = Array.from(group.querySelectorAll("[data-nav-key]")).filter((el) => !el.hidden);
      group.hidden = visibleLinks.length === 0;
      const label = group.querySelector(".cx-sidebar__label");
      const key = label?.textContent?.trim() || "";
      const defaults = nav.groups_default_collapsed || [];
      const hasActive = !!group.querySelector(".cx-sidebar__link.active:not([hidden])");
      if (!hasActive && defaults.includes(key) && !group.classList.contains("is-collapsed")) {
        const stored = sessionStorage.getItem(`cx-nav-${key}`);
        if (stored !== "open") group.classList.add("is-collapsed");
      }
    });

    const topbar = nav.topbar || {};
    document.querySelectorAll("[data-topbar-key]").forEach((el) => {
      const key = el.getAttribute("data-topbar-key");
      el.hidden = !topbar[key];
    });

    const mobile = document.querySelector(".cx-mobile-nav");
    if (mobile && Array.isArray(nav.mobile)) {
      const menuBtn = mobile.querySelector("#cxMobileMenuOpen");
      const page = document.querySelector(".cx-shell")?.dataset?.clinicsPage || "";
      mobile.querySelectorAll("[data-mobile-key]").forEach((el) => el.remove());
      nav.mobile.slice(0, 4).forEach((key) => {
        const meta = MOBILE_META[key] || { icon: "fa-circle", label: key };
        const a = document.createElement("a");
        a.href = HREF[key] || "/clinics/";
        a.className = "cx-mobile-nav__item";
        a.setAttribute("data-mobile-key", key);
        const active =
          (key === "dashboard" && page === "dashboard") ||
          (key === "patients" && (page === "patients" || page === "patient_detail")) ||
          (key === "visits" && page === "visits") ||
          (key === "doctor" && page === "doctor") ||
          page === key;
        if (active) a.classList.add("active");
        a.innerHTML = `<i class="fa ${meta.icon}"></i><span>${meta.label}</span>`;
        if (menuBtn) mobile.insertBefore(a, menuBtn);
        else mobile.appendChild(a);
      });
      // Hide legacy hardcoded items that lack data-mobile-key after rebuild
      mobile.querySelectorAll(".cx-mobile-nav__item:not([data-mobile-key]):not(#cxMobileMenuOpen)").forEach((el) => {
        el.hidden = true;
      });
    }

    document.documentElement.dataset.cxPersona = nav.persona || "";
  }

  window.ClinicsNav = { apply: applyNav, applyUser, HREF };

  document.addEventListener("clinics:bootstrap", (event) => {
    const detail = event.detail || {};
    applyNav(detail.nav || detail);
    applyUser(detail.user || detail.nav?.user);
  });
})();
