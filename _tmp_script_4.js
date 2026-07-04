
    // MOBILE BOTTOM NAVIGATION REMOVED
    (function () {

      // Get current page path
      function getCurrentPage() {
        const path = window.location.pathname;
        if (path === '/' || path === '/index') return 'home';
        if (path.startsWith('/orders')) return 'orders';
        if (path.startsWith('/reports')) return 'reports';
        if (path.startsWith('/agents')) return 'agents';
        if (path.startsWith('/messages')) return 'messages';
        return null;
      }

      // Set active nav item
      function setActiveNavItem() {
        const currentPage = getCurrentPage();
        if (!currentPage) return;

        const navItems = document.querySelectorAll('.mobile-bottom-nav .nav-item');
        navItems.forEach(item => {
          if (item.getAttribute('data-page') === currentPage) {
            item.classList.add('active');
          } else {
            item.classList.remove('active');
          }
        });
      }

      // Update messages badge from existing badge
      function updateMobileMessagesBadge() {
        const desktopBadge = document.getElementById('messagesBadge');
        const mobileBadge = document.getElementById('mobileMessagesBadge');

        if (desktopBadge && mobileBadge) {
          const count = desktopBadge.textContent.trim();
          if (count && parseInt(count) > 0) {
            mobileBadge.textContent = count;
            mobileBadge.style.display = 'flex';
          } else {
            mobileBadge.style.display = 'none';
          }
        }
      }

      // Handle navigation clicks
      function handleNavClick(e) {
        const navItem = e.currentTarget;
        const href = navItem.getAttribute('href');

        // Add active class immediately for better UX
        document.querySelectorAll('.mobile-bottom-nav .nav-item').forEach(item => {
          item.classList.remove('active');
        });
        navItem.classList.add('active');

        // If it's the same page, prevent navigation
        if (href === window.location.pathname) {
          e.preventDefault();
          return false;
        }

        // Add loading state
        navItem.style.opacity = '0.6';
        setTimeout(() => {
          navItem.style.opacity = '1';
        }, 300);
      }

      // Initialize on DOM ready
      function initMobileNav() {
        // Only initialize on mobile devices
        if (window.innerWidth >= 768) {
          return;
        }

        const mobileNav = document.getElementById('mobileBottomNav');
        if (!mobileNav) return;

        // Set active item
        setActiveNavItem();

        // Update messages badge
        updateMobileMessagesBadge();

        // Add click handlers
        const navItems = mobileNav.querySelectorAll('.nav-item');
        navItems.forEach(item => {
          item.addEventListener('click', handleNavClick);
        });

        // Watch for badge updates
        const observer = new MutationObserver(updateMobileMessagesBadge);
        const desktopBadge = document.getElementById('messagesBadge');
        if (desktopBadge) {
          observer.observe(desktopBadge, {
            childList: true,
            characterData: true,
            subtree: true
          });
        }

        // Update on window resize
        let resizeTimer;
        window.addEventListener('resize', function () {
          clearTimeout(resizeTimer);
          resizeTimer = setTimeout(function () {
            if (window.innerWidth < 768) {
              setActiveNavItem();
            }
          }, 250);
        });
      }

      // Run on DOM ready
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initMobileNav);
      } else {
        initMobileNav();
      }

      // Also run after a short delay to ensure all elements are loaded
      setTimeout(initMobileNav, 100);
    })();
  