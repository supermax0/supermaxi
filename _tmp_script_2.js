
    // ======================================================
    // SIDEBAR – RTL OFF-CANVAS (MODULAR)
    // Technical: Desktop = sidebar position:fixed; right:0; content margin-right.
    // Mobile = transform:translate3d(100%,0,0) closed, (0,0,0) open; GPU-friendly.
    // Overlay via .app.sidebar-open::before; body overflow hidden when open;
    // fast-tap guard (320ms) avoids double-open on iOS; single ESC handler.
    // ======================================================
    (function () {
      var sidebarLastClose = 0;
      var SIDEBAR_FAST_TAP_MS = 320;

      window.collapseDesktopSidebar = function () {
        var app = document.querySelector(".app");
        if (!app || window.innerWidth <= 900) return;
        app.classList.add("sidebar-desktop-hidden");
        try {
          localStorage.setItem("sidebarDesktopHidden", "1");
        } catch (e) {}
      };

      window.toggleSidebar = function () {
        var sidebar = document.getElementById("sidebar");
        var app = document.querySelector(".app");
        if (!sidebar) return;
        if (window.innerWidth <= 900) {
          if (sidebar.classList.contains("show")) {
            closeSidebar();
          } else {
            openSidebar();
          }
          return;
        }
        if (!app) return;
        app.classList.toggle("sidebar-desktop-hidden");
        try {
          localStorage.setItem(
            "sidebarDesktopHidden",
            app.classList.contains("sidebar-desktop-hidden") ? "1" : "0"
          );
        } catch (e) {}
      };

      window.openSidebar = function () {
        var sidebar = document.getElementById("sidebar");
        var app = document.querySelector(".app");
        if (!sidebar) return;
        /* Guard: avoid re-open on fast double-tap (e.g. iPhone) */
        if (Date.now() - sidebarLastClose < SIDEBAR_FAST_TAP_MS) return;
        sidebar.classList.add("show");
        if (app) app.classList.add("sidebar-open");
        document.body.style.overflow = "hidden";
        document.body.setAttribute("data-sidebar-open", "1");
        document.addEventListener("click", closeSidebarOnOutsideClick, true);
        document.addEventListener("touchstart", closeSidebarOnOutsideClick, { passive: true, capture: true });
      };

      window.closeSidebar = function () {
        var sidebar = document.getElementById("sidebar");
        var app = document.querySelector(".app");
        if (!sidebar) return;
        sidebar.classList.remove("show");
        if (app) app.classList.remove("sidebar-open");
        document.body.style.overflow = "";
        document.body.removeAttribute("data-sidebar-open");
        sidebarLastClose = Date.now();
        document.removeEventListener("click", closeSidebarOnOutsideClick, true);
        document.removeEventListener("touchstart", closeSidebarOnOutsideClick, true);
      };

      try {
        if (localStorage.getItem("sidebarDesktopHidden") === "1" && window.innerWidth > 900) {
          var appInit = document.querySelector(".app");
          if (appInit) appInit.classList.add("sidebar-desktop-hidden");
        }
      } catch (e) {}

      window.addEventListener("resize", function () {
        if (window.innerWidth <= 900) {
          var appR = document.querySelector(".app");
          if (appR) appR.classList.remove("sidebar-desktop-hidden");
        }
      });

      function closeSidebarOnOutsideClick(e) {
        var sidebar = document.getElementById("sidebar");
        var toggle = document.querySelector(".toggle");
        if (!sidebar || !toggle) return;
        var target = e.target;
        if (!sidebar.contains(target) && !toggle.contains(target)) closeSidebar();
      }
    })();

    // Escape closes sidebar (single handler)
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var sidebar = document.getElementById("sidebar");
        if (sidebar && sidebar.classList.contains("show")) closeSidebar();
      }
    });

    // على الموبايل: إغلاق السايدبار فقط عند الضغط على رابط فعلي (a)، وليس عند الضغط على زر فتح القائمة الفرعية (الطلبات)
    document.querySelector(".menu")?.addEventListener("click", function (e) {
      if (window.innerWidth > 900) return;
      var target = e.target;
      while (target && target !== this) {
        if (target.tagName === "A" && target.getAttribute("href")) {
          closeSidebar();
          return;
        }
        if (target.classList && target.classList.contains("menu-group-header")) return;
        target = target.parentElement;
      }
    });

    // ======================================================
    // TOAST NOTIFICATIONS
    // ======================================================
    function showToast(message, type = "info", duration = 3000, options) {
      if (typeof duration === "object" && duration !== null) {
        options = duration;
        duration = options.duration != null ? options.duration : 3000;
      }
      options = options || {};

      const container = document.getElementById("toastContainer");
      if (!container) return;

      if (!options.silent && options.sound !== false && typeof window.playNotificationSound === "function") {
        window.playNotificationSound(type, options);
      }

      const toast = document.createElement("div");
      toast.className = `toast ${type}`;

      const icons = {
        success: "fa-check-circle",
        error: "fa-exclamation-circle",
        warning: "fa-exclamation-triangle",
        info: "fa-info-circle",
        order: "fa-bell"
      };

      toast.innerHTML = `
    <i class="fa ${icons[type] || icons.info}"></i>
    <span class="toast-message">${message}</span>
    <button class="toast-close" onclick="this.parentElement.remove()">×</button>
  `;

      container.appendChild(toast);

      // Auto remove after duration
      setTimeout(() => {
        toast.classList.add("fade-out");
        setTimeout(() => toast.remove(), 300);
      }, duration);

      return toast;
    }

    // Make toast function globally available
    window.showToast = showToast;

    function finoraConfirmImpact(options) {
      options = options || {};
      return new Promise(function (resolve) {
        var overlay = document.createElement("div");
        overlay.className = "finora-confirm-overlay";
        var tone = options.tone === "danger" ? "danger" : "warning";
        var impact = Array.isArray(options.impact) ? options.impact : [];
        overlay.innerHTML = `
          <div class="finora-confirm-dialog is-${tone}" role="dialog" aria-modal="true" aria-label="${options.title || "تأكيد الإجراء"}">
            <div class="finora-confirm-head">
              <div class="finora-confirm-icon"><i class="fa ${tone === "danger" ? "fa-triangle-exclamation" : "fa-circle-info"}"></i></div>
              <div>
                <h3 class="finora-confirm-title">${options.title || "تأكيد الإجراء"}</h3>
                <p class="finora-confirm-message">${options.message || "يرجى مراجعة الأثر قبل المتابعة."}</p>
              </div>
            </div>
            ${impact.length ? `<div class="finora-impact-list">${impact.map(function (item) {
              return `<div class="finora-impact-item"><i class="fa fa-check"></i><span>${item}</span></div>`;
            }).join("")}</div>` : ""}
            <div class="finora-confirm-actions">
              <button type="button" class="finora-confirm-cancel">${options.cancelText || "إلغاء"}</button>
              <button type="button" class="finora-confirm-confirm">${options.confirmText || "تأكيد"}</button>
            </div>
          </div>
        `;
        function escHandler(e) {
          if (e.key === "Escape" && document.body.contains(overlay)) {
            close(false);
          }
        }
        function close(value) {
          document.removeEventListener("keydown", escHandler);
          overlay.remove();
          resolve(value);
        }
        overlay.addEventListener("click", function (e) {
          if (e.target === overlay) close(false);
        });
        overlay.querySelector(".finora-confirm-cancel").addEventListener("click", function () { close(false); });
        overlay.querySelector(".finora-confirm-confirm").addEventListener("click", function () { close(true); });
        document.addEventListener("keydown", escHandler);
        document.body.appendChild(overlay);
        overlay.querySelector(".finora-confirm-cancel").focus();
      });
    }

    window.finoraConfirmImpact = finoraConfirmImpact;

    // ======================================================
    // THEME TOGGLE (Dark/Light) — localStorage + prefers-color-scheme
    // ======================================================
    (function () {
      var btn = document.getElementById("themeToggleBtn");
      if (!btn) return;

      function currentTheme() {
        return document.documentElement.getAttribute("data-theme") || "dark";
      }

      function setTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        try { localStorage.setItem("theme", theme); } catch (e) { }
        var icon = btn.querySelector("i");
        if (icon) icon.className = theme === "light" ? "fa fa-sun" : "fa fa-moon";
      }

      // init icon
      setTheme(currentTheme());

      btn.addEventListener("click", function () {
        setTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    })();

    // ======================================================
    // LOADING OVERLAY
    // ======================================================
    function showLoading() {
      const overlay = document.getElementById("loadingOverlay");
      if (overlay) overlay.classList.add("show");
    }

    function hideLoading() {
      const overlay = document.getElementById("loadingOverlay");
      if (overlay) overlay.classList.remove("show");
    }

    window.showLoading = showLoading;
    window.hideLoading = hideLoading;

    // ======================================================
    // ACTIVE MENU ITEM
    // ======================================================
    document.addEventListener("DOMContentLoaded", function () {
      const currentPath = window.location.pathname;
      const menuLinks = document.querySelectorAll(".menu a");

      menuLinks.forEach(link => {
        const href = link.getAttribute("href");
        if (currentPath === href || (href !== "/" && currentPath.startsWith(href))) {
          link.classList.add("active");
        }
      });
    });

    // ======================================================
    // SMOOTH SCROLL TO TOP
    // ======================================================
    function scrollToTop() {
      window.scrollTo({
        top: 0,
        behavior: "smooth"
      });
    }

    // ======================================================
    // KEYBOARD SHORTCUTS
    // ======================================================
    document.addEventListener("keydown", function (e) {
      // Ctrl/Cmd + K to focus search (if exists)
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        const searchInput = document.querySelector("input[type='search'], input[placeholder*='بحث'], input[placeholder*='Search']");
        if (searchInput) {
          searchInput.focus();
        }
      }
    });

    // ======================================================
    // AUTO-HIDE TOASTS ON MOBILE
    // ======================================================
    if (window.innerWidth <= 900) {
      const style = document.createElement("style");
      style.textContent = `
    .toast-container {
      bottom: 20px;
      top: auto;
    }
  `;
      document.head.appendChild(style);
    }

    // ======================================================
    // PROFILE MODAL LOGIC
    // ======================================================
    window.openProfileModal = function () {
      const modal = document.getElementById("profileModal");
      if (modal) {
        syncNotificationSoundToggle();
        modal.style.display = "flex";
      }
    };

    function syncNotificationSoundToggle() {
      var toggle = document.getElementById("notificationSoundToggle");
      var label = document.getElementById("notificationSoundLabel");
      var status = document.getElementById("notificationSoundStatus");
      if (!toggle) return;
      var enabled = typeof window.finoraNotificationSoundEnabled === "function"
        ? window.finoraNotificationSoundEnabled()
        : true;
      toggle.classList.toggle("active", enabled);
      if (label) label.textContent = "صوت الإشعارات";
      if (status) status.textContent = enabled ? "مفعّل" : "متوقف";
    }

    window.toggleNotificationSound = function (el) {
      var enabled = typeof window.finoraNotificationSoundEnabled === "function"
        ? window.finoraNotificationSoundEnabled()
        : true;
      if (typeof window.finoraSetNotificationSound === "function") {
        window.finoraSetNotificationSound(!enabled);
      }
      syncNotificationSoundToggle();
      if (!enabled && typeof window.playNotificationSound === "function") {
        window.playNotificationSound("success", { soundType: "success" });
      }
    };

    document.addEventListener("finora:notification-sound-changed", syncNotificationSoundToggle);

    window.closeProfileModal = function () {
      const modal = document.getElementById("profileModal");
      if (modal) modal.style.display = "none";
    };

    window.setProfileTheme = function (theme, el) {
      const group = el.closest('[data-setting-group="theme"]');
      if (group) {
        group.querySelectorAll('.setting-item').forEach(function (item) {
          item.classList.remove('active');
        });
      }
      el.classList.add('active');

      // Apply theme
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem("theme", theme);

      // Sync with topbar toggle
      const btn = document.getElementById("themeToggleBtn");
      if (btn) {
        const icon = btn.querySelector("i");
        if (icon) icon.className = theme === "light" ? "fa fa-sun" : "fa fa-moon";
      }

      // Save to DB
      fetch('/employees/profile/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme: theme })
      });
    };

    window.setProfileLang = function (lang, el) {
      const group = el.closest('[data-setting-group="lang"]');
      if (group) {
        group.querySelectorAll('.setting-item').forEach(function (item) {
          item.classList.remove('active');
        });
      }
      el.classList.add('active');

      // Save to DB
      fetch('/employees/profile/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: lang })
      }).then(() => {
        // Reload to apply changes globally (Jinja needs to re-render with new session lang)
        window.location.reload();
      });
    };

    window.saveProfileChanges = function () {
      const nameInput = document.getElementById("profileNameInput");
      const newName = nameInput.value.trim();

      if (!newName) {
        showToast("يرجى إدخال الاسم", "error");
        return;
      }

      fetch('/employees/profile/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName })
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            showToast("تم تحديث الملف الشخصي بنجاح", "success");

            // Update header
            const headerName = document.getElementById("headerUserName");
            if (headerName) headerName.textContent = newName;

            const modalTitle = document.getElementById("modalUserNameTitle");
            if (modalTitle) modalTitle.textContent = newName;

            // Update avatar initials if no image
            const modalAvatar = document.getElementById("modalAvatar");
            if (modalAvatar && !modalAvatar.querySelector('img')) {
              modalAvatar.textContent = newName.charAt(0).toUpperCase();
            }

            const headerAvatar = document.getElementById("headerAvatar");
            if (headerAvatar && !headerAvatar.querySelector('img')) {
              headerAvatar.textContent = newName.charAt(0).toUpperCase();
            }

            closeProfileModal();
          } else {
            showToast(data.error || "فشل التحديث", "error");
          }
        });
    };

    window.uploadProfilePic = function (input) {
      if (!input.files || !input.files[0]) return;

      const formData = new FormData();
      formData.append('file', input.files[0]);

      showToast("جاري رفع الصورة...", "info");

      fetch('/employees/profile/upload', {
        method: 'POST',
        body: formData
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            showToast("تم تغيير الصورة بنجاح", "success");

            // Update avatars
            const modalAvatar = document.getElementById("modalAvatar");
            const headerAvatar = document.getElementById("headerAvatar");
            const picUrl = '/' + data.profile_pic;

            const imgHtml = `<img src="${picUrl}" style="width:100%;height:100%;border-radius:50%;object-fit:cover;">`;

            if (modalAvatar) {
              modalAvatar.innerHTML = `<img src="${picUrl}">`;
            }
            if (headerAvatar) {
              headerAvatar.innerHTML = imgHtml;
            }
          } else {
            showToast(data.error || "فشل رفع الصورة", "error");
          }
        });
    };

    // ======================================================
    // UPDATE UNREAD MESSAGES COUNT
    // ======================================================
    function updateMessagesBadge() {
      fetch('/messages/unread-count')
        .then(r => {
          if (!r.ok) {
            throw new Error('Network response was not ok');
          }
          return r.json();
        })
        .then(data => {
          const badge = document.getElementById('messagesBadge');
          if (badge) {
            if (data.unread_count > 0) {
              badge.textContent = data.unread_count;
              badge.style.display = 'inline-flex';
            } else {
              badge.style.display = 'none';
            }
          }
        })
        .catch(error => {
          // إخفاء الأخطاء الصامتة - الخادم غير متاح
          // Silently ignore connection errors
          if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
            // فقط سجل الأخطاء غير المتعلقة بالاتصال
            // Only log non-connection errors
            console.error('Error updating messages badge:', error);
          }
        });
    }

    // Update badge on page load
    document.addEventListener('DOMContentLoaded', function () {
      updateMessagesBadge();
      // Update every 10 seconds
      setInterval(updateMessagesBadge, 10000);
    });
  