/* Global UI micro-interactions for Publisher templates */
(function () {
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("sidebarOverlay");
    const toggleBtn = document.getElementById("sidebarToggle");

    function closeSidebar() {
        if (!sidebar || !overlay) return;
        sidebar.classList.remove("mobile-open");
        overlay.classList.remove("active");
    }

    function openSidebar() {
        if (!sidebar || !overlay) return;
        sidebar.classList.add("mobile-open");
        overlay.classList.add("active");
    }

    if (toggleBtn) {
        toggleBtn.addEventListener("click", function () {
            if (!sidebar || !overlay) return;
            if (sidebar.classList.contains("mobile-open")) closeSidebar();
            else openSidebar();
        });
    }

    if (overlay) {
        overlay.addEventListener("click", closeSidebar);
    }

    document.addEventListener("click", function (event) {
        const target = event.target;
        const btn = target && target.closest ? target.closest("[data-ripple], .btn") : null;
        if (!btn) return;

        const rect = btn.getBoundingClientRect();
        const ripple = document.createElement("span");
        ripple.className = "ripple";
        ripple.style.left = (event.clientX - rect.left) + "px";
        ripple.style.top = (event.clientY - rect.top) + "px";
        btn.appendChild(ripple);
        window.setTimeout(function () {
            ripple.remove();
        }, 450);
    });
})();
