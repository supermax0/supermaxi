(function () {
  'use strict';

  document.querySelectorAll('.fp-brand img, .fp-app-icon img').forEach(function (logo) {
    function fallback() {
      if (!logo.src.endsWith('/static/images/landing/finora-mark.svg')) logo.src = '/static/images/landing/finora-mark.svg';
    }
    logo.addEventListener('error', fallback);
    if (logo.complete && !logo.naturalWidth) fallback();
  });

  var menu = document.getElementById('fpMenu');
  var mobile = document.getElementById('fpMobileNav');
  function closeMenu() {
    if (!menu || !mobile) return;
    mobile.hidden = true;
    menu.setAttribute('aria-expanded', 'false');
    menu.setAttribute('aria-label', 'فتح قائمة التنقل');
  }
  if (menu && mobile) {
    menu.addEventListener('click', function () {
      mobile.hidden = !mobile.hidden;
      menu.setAttribute('aria-expanded', String(!mobile.hidden));
      menu.setAttribute('aria-label', mobile.hidden ? 'فتح قائمة التنقل' : 'إغلاق قائمة التنقل');
    });
    mobile.querySelectorAll('a').forEach(function (link) { link.addEventListener('click', closeMenu); });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !mobile.hidden) { closeMenu(); menu.focus(); }
    });
    window.matchMedia('(min-width: 851px)').addEventListener('change', closeMenu);
  }

  var tabs = Array.from(document.querySelectorAll('.fp-tabs [role="tab"]'));
  function activate(tab, focus) {
    tabs.forEach(function (item) {
      var selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
      var panel = document.getElementById(item.getAttribute('aria-controls'));
      if (panel) panel.hidden = !selected;
    });
    if (focus) tab.focus();
  }
  tabs.forEach(function (tab, index) {
    tab.addEventListener('click', function () { activate(tab, false); });
    tab.addEventListener('keydown', function (event) {
      var next;
      if (event.key === 'ArrowLeft') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowRight') next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== undefined) { event.preventDefault(); activate(tabs[next], true); }
    });
  });

  var dialog = document.getElementById('fpLightbox');
  var image = document.getElementById('fpLightboxImage');
  var caption = document.getElementById('fpLightboxCaption');
  var previousFocus;
  if (dialog && typeof dialog.showModal === 'function') {
    document.querySelectorAll('[data-lightbox]').forEach(function (link) {
      link.addEventListener('click', function (event) {
        // Preserve native open-in-new-tab and image-link behavior.
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        previousFocus = link;
        image.src = link.href;
        image.alt = link.querySelector('img').alt;
        caption.textContent = image.alt;
        dialog.showModal();
        document.body.style.overflow = 'hidden';
      });
    });
    dialog.querySelector('button').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (event) {
      var rect = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
    });
    dialog.addEventListener('close', function () {
      document.body.style.overflow = '';
      if (previousFocus) previousFocus.focus({ preventScroll: true });
    });
  }
})();
