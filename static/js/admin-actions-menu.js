(function () {
  'use strict';

  const MENU_CLASS = 'admin-actions-menu';
  const TRIGGER_SELECTOR = '[data-compact-actions-trigger], .admin-actions-trigger, .ship-actions-trigger';
  const WRAP_SELECTOR = '[data-compact-actions]';
  const SOURCE_SELECTOR = '.compact-actions-source';
  const DANGER_MATCH = '.danger, .action-btn-delete, .btn-outline-danger, .btn-danger, .is-danger';

  let menuEl = null;
  let activeTrigger = null;

  function ensureMenu() {
    if (menuEl) return menuEl;
    menuEl = document.createElement('div');
    menuEl.className = MENU_CLASS;
    menuEl.id = 'adminActionsMenu';
    menuEl.setAttribute('role', 'menu');
    menuEl.hidden = true;
    document.body.appendChild(menuEl);
    return menuEl;
  }

  function closeMenu() {
    const menu = menuEl || document.getElementById('adminActionsMenu');
    if (menu) menu.hidden = true;
    if (activeTrigger) {
      activeTrigger.setAttribute('aria-expanded', 'false');
      activeTrigger = null;
    }
  }

  function positionMenu(trigger) {
    const menu = ensureMenu();
    const rect = trigger.getBoundingClientRect();
    const gap = 6;
    const viewportPad = 8;

    menu.hidden = false;
    menu.style.visibility = 'hidden';
    menu.style.left = '0px';
    menu.style.top = '0px';

    const menuRect = menu.getBoundingClientRect();
    let left = rect.right - menuRect.width;
    let top = rect.bottom + gap;

    if (left < viewportPad) left = viewportPad;
    if (left + menuRect.width > window.innerWidth - viewportPad) {
      left = Math.max(viewportPad, window.innerWidth - menuRect.width - viewportPad);
    }
    if (top + menuRect.height > window.innerHeight - viewportPad) {
      top = rect.top - menuRect.height - gap;
    }
    if (top < viewportPad) top = viewportPad;

    menu.style.left = Math.round(left) + 'px';
    menu.style.top = Math.round(top) + 'px';
    menu.style.visibility = '';
  }

  function getActionLabel(el) {
    const title = (el.getAttribute('title') || '').trim();
    if (title) return title;
    const spans = el.querySelectorAll('span');
    if (spans.length >= 2) return spans[spans.length - 1].textContent.trim();
    if (spans.length === 1) return spans[0].textContent.trim();
    return (el.textContent || '').trim();
  }

  function getActionIconHtml(el) {
    const icon = el.querySelector('i');
    if (icon) {
      return `<i class="${icon.className}" aria-hidden="true"></i>`;
    }
    const spans = el.querySelectorAll('span');
    if (spans.length >= 2) {
      const emoji = spans[0].textContent.trim();
      if (emoji) return `<span class="compact-actions-emoji" aria-hidden="true">${emoji}</span>`;
    }
    return '<i class="fas fa-circle" aria-hidden="true" style="font-size:6px;opacity:.35"></i>';
  }

  function isDangerAction(el) {
    return el.matches(DANGER_MATCH);
  }

  function buildMenuFromSource(source) {
    const menu = ensureMenu();
    menu.innerHTML = '';
    const items = Array.from(source.children).filter((el) => el.nodeType === 1);
    let insertedSep = false;

    items.forEach((sourceEl, index) => {
      const danger = isDangerAction(sourceEl);
      if (danger && !insertedSep && index > 0) {
        const sep = document.createElement('div');
        sep.className = 'admin-actions-menu-sep';
        sep.setAttribute('role', 'separator');
        menu.appendChild(sep);
        insertedSep = true;
      }

      const label = getActionLabel(sourceEl);
      const isLink = sourceEl.tagName === 'A';
      const item = document.createElement(isLink ? 'a' : 'button');
      item.className = 'admin-actions-menu-item' + (danger ? ' is-danger' : '');
      item.setAttribute('role', 'menuitem');
      if (!isLink) item.type = 'button';
      item.innerHTML = `${getActionIconHtml(sourceEl)}<span>${label}</span>`;

      if (isLink) {
        item.href = sourceEl.href;
        if (sourceEl.target) item.target = sourceEl.target;
        if (sourceEl.rel) item.rel = sourceEl.rel;
        item.addEventListener('click', () => closeMenu());
      } else {
        item.addEventListener('click', (event) => {
          event.preventDefault();
          closeMenu();
          sourceEl.click();
        });
      }

      menu.appendChild(item);
    });
  }

  function openMenu(trigger) {
    const wrap = trigger.closest(WRAP_SELECTOR);
    if (!wrap) return;
    const source = wrap.querySelector(SOURCE_SELECTOR);
    if (!source || !source.children.length) return;

    if (activeTrigger === trigger && menuEl && !menuEl.hidden) {
      closeMenu();
      return;
    }

    closeMenu();
    buildMenuFromSource(source);
    activeTrigger = trigger;
    trigger.setAttribute('aria-expanded', 'true');
    positionMenu(trigger);
  }

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest ? event.target.closest(TRIGGER_SELECTOR) : null;
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      openMenu(trigger);
      return;
    }
    if (menuEl && !menuEl.hidden && !menuEl.contains(event.target)) {
      closeMenu();
    }
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenu();
  });

  window.addEventListener('resize', closeMenu);
  window.addEventListener('scroll', closeMenu, true);

  window.AdminActionsMenu = { close: closeMenu };
})();
