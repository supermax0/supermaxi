/**
 * Finora contextual help — auto-bind data-help + mobile tap + overflow-safe positioning
 */
(function () {
  'use strict';

  var FIELDS = {};
  try {
    var el = document.getElementById('finora-help-fields');
    if (el && el.textContent) FIELDS = JSON.parse(el.textContent);
  } catch (e) { /* ignore */ }

  function createIcon(text) {
    var span = document.createElement('span');
    span.className = 'finora-help';
    span.setAttribute('role', 'button');
    span.setAttribute('tabindex', '0');
    span.setAttribute('aria-label', 'مساعدة');
    span.textContent = '?';
    var tip = document.createElement('span');
    tip.className = 'finora-help__tip';
    tip.textContent = text;
    span.appendChild(tip);
    return span;
  }

  function positionFixedTip(icon, tip) {
    var rect = icon.getBoundingClientRect();
    tip.classList.add('finora-help__tip--fixed');
    var tipRect = tip.getBoundingClientRect();
    var top = rect.top - tipRect.height - 8;
    var left = rect.left + rect.width / 2 - tipRect.width / 2;
    if (left < 8) left = 8;
    if (left + tipRect.width > window.innerWidth - 8) {
      left = window.innerWidth - tipRect.width - 8;
    }
    if (top < 8) {
      top = rect.bottom + 8;
    }
    tip.style.top = top + 'px';
    tip.style.left = left + 'px';
  }

  function clearFixedTip(tip) {
    tip.classList.remove('finora-help__tip--fixed');
    tip.style.top = '';
    tip.style.left = '';
  }

  function bindOverflowFix(icon) {
    var tip = icon.querySelector('.finora-help__tip');
    if (!tip) return;
    icon.addEventListener('mouseenter', function () {
      requestAnimationFrame(function () {
        positionFixedTip(icon, tip);
      });
    });
    icon.addEventListener('mouseleave', function () {
      if (!icon.classList.contains('is-open')) clearFixedTip(tip);
    });
  }

  var openIcon = null;

  function closeOpen() {
    if (!openIcon) return;
    openIcon.classList.remove('is-open');
    var tip = openIcon.querySelector('.finora-help__tip');
    if (tip) clearFixedTip(tip);
    openIcon = null;
  }

  function toggleIcon(icon) {
    if (openIcon === icon) {
      closeOpen();
      return;
    }
    closeOpen();
    icon.classList.add('is-open');
    openIcon = icon;
    var tip = icon.querySelector('.finora-help__tip');
    if (tip) {
      requestAnimationFrame(function () {
        positionFixedTip(icon, tip);
      });
    }
  }

  function bindTap(icon) {
    icon.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggleIcon(icon);
    });
    icon.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggleIcon(icon);
      }
    });
  }

  document.addEventListener('click', function (e) {
    if (openIcon && !openIcon.contains(e.target)) closeOpen();
  });

  function attachIcon(node, icon) {
    var tag = node.tagName ? node.tagName.toLowerCase() : '';
    if (tag === 'select' || tag === 'input' || tag === 'textarea') {
      if (node.parentNode) {
        node.parentNode.insertBefore(icon, node.nextSibling);
      }
    } else {
      node.appendChild(icon);
    }
    bindOverflowFix(icon);
    bindTap(icon);
  }

  function initDataHelp() {
    document.querySelectorAll('[data-help]').forEach(function (node) {
      if (node.classList.contains('finora-help') || node.querySelector('.finora-help')) return;
      var key = node.getAttribute('data-help');
      var text = node.getAttribute('data-help-text') || FIELDS[key] || '';
      if (!text) return;
      var icon = createIcon(text);
      attachIcon(node, icon);
    });
  }

  function initExisting() {
    document.querySelectorAll('.finora-help').forEach(function (icon) {
      bindOverflowFix(icon);
      bindTap(icon);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initDataHelp();
      initExisting();
    });
  } else {
    initDataHelp();
    initExisting();
  }
})();
