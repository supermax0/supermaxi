/* Shared presentation adapters. Existing controls, forms and data stay in place. */
(function () {
  'use strict';
  if (!document.body.classList.contains('finora-unified')) return;

  var components = {
    'fu-card': '.card,.enhanced-card,.premium-card,.fd-table-card,.ofd-table-card,.fd-detail-section,.fd-form-section,.ins-card,.ins-panel,.mnt-card,.tr-card,.fa-card,.rc-panel,.rc-filter-shell,.finance-table-wrap,.finance-schedule,.rs-card,.rs-table-wrap,.pl-card,.settings-section-card,.settings-hub-card,.settings-status-card,.admin-card,.epw-card,.template-card,.advisor-panel,.report-section,.chart-box,.archive-table-wrap,.dr-filter-card,.dr-table-card,.cr-card,.inv-add-card,.inv-modal-card,.pos-panel,.quick-panel,.quick-cashier,.quick-products,.mobile-app-card,.pos-card,.quick-card,.ma-card,.settings-card,.settings-panel,.activity-cat-panel,.ed-detail-card,.ed-perm-card,.ed-id-card,.fm-panel,.exec-card,.bank-card,.credit-card,.health-card,.chart-panel,.alerts-card,.live-panel,.notes-template-card,.notes-templates-card,.notes-modal-card,.notes-draw-card,.notes-assistant-card,.ai-chat-card,.ai-plan-panel,.template-selection-card,.template-option-card,.preview-panel,.fm-set-panel,.check-card,.detail-card,.panel',
    'fu-stat': '.fd-kpi,.finora-stat-card,.finora-wide-card,.ins-stat,.mnt-kpi,.fa-kpi,.rs-kpi,.stat-card,.stat-box,.finance-stat,.rc-sum-card,.inv-box,.kpi-card,.exec-kpi,.ma-stat,.detail-stat,.ai-chat-hero-stat',
    'fu-toolbar': '.fd-toolbar,.ofd-toolbar,.admin-toolbar,.finance-toolbar,.rc-toolbar,.pl-head,.tr-filters,.fa-filters,.rs-filters,.inv-add-toolbar,.archive-actions,.report-actions,.dr-filter-actions',
    'fu-tabs': '.fd-tabs,.ofd-tabs,.finance-tabs,.ins-nav,.fa-nav,.rs-nav,.mnt-tabs,.settings-subnav,.notes-filters,.fm-tabs,.ma-subnav',
    'fu-primary': '.fd-btn--primary,.fd-btn--purple,.fd-btn--accent,.fd-btn--rose,.ofd-btn--primary,.ofd-btn--purple,.ofd-btn--accent,.ofd-btn--rose,.btn-primary,.btn.primary,.settings-btn-primary,.finance-primary,.pl-primary,.mnt-btn-primary,.fa-btn-primary,.tr-btn.primary,.rs-btn-primary,.ins-btn:not(.ghost):not(.danger):not(.secondary),.rc-btn-primary,.inv-btn-primary,.notes-primary,.notes-main-btn,.quick-primary,.pos-primary,.pos-btn-primary,.ws-btn-primary,.fm-primary:not(.fm-ghost),.btn-submit-primary,.ma-btn-primary,.advisor-btn,.pos-btn-add,.ed-pos-new-btn,.quick-btn:not(.cancel):not(.secondary):not(.success)',
    'fu-secondary': '.fd-btn:not(.fd-btn--primary):not(.fd-btn--purple):not(.fd-btn--accent):not(.fd-btn--rose):not(.fd-btn--danger),.ofd-btn:not(.ofd-btn--primary):not(.ofd-btn--purple):not(.ofd-btn--accent):not(.ofd-btn--rose):not(.ofd-btn--danger),.btn-secondary,.btn-ghost,.settings-btn-secondary,.finance-secondary,.pl-muted,.fa-btn-secondary,.ins-btn.ghost,.tr-btn:not(.primary),.rs-btn-secondary,.archive-btn:not(.primary)',
    'fu-danger': '.btn-danger,.fd-btn--danger,.ofd-btn--danger,.finance-danger,.ins-btn.danger,.ws-btn-danger,.pos-btn-danger',
    'fu-control': '.fd-btn,.ofd-btn,.btn,.settings-btn,.finance-primary,.finance-secondary,.finance-danger,.pl-btn,.mnt-btn,.mnt-tab-btn,.fa-btn,.tr-btn,.rs-btn,.ins-btn,.rc-btn,.inv-btn,.archive-btn,.report-btn,.cr-btn,.notes-main-btn,.pos-btn,.ws-btn,.fm-primary,.quick-btn,.ma-btn,.advisor-btn,.btn-submit-primary,.ed-pos-new-btn',
    'fu-scroll-table': '.workspace-table-scroll,.tr-table-wrap,.mnt-table-wrap,.archive-table-wrap,.finance-table-wrap,.pl-table-wrap,.rc-table-wrap,.cr-table-wrap,.dr-table-wrap'
  };

  function mark(root) {
    Object.keys(components).forEach(function (name) {
      if (root.matches && root.matches(components[name])) root.classList.add(name);
      if (root.querySelectorAll) root.querySelectorAll(components[name]).forEach(function (node) { node.classList.add(name); });
    });
  }

  function cleanTitle(text) {
    return String(text || '').replace(/\s+/g, ' ').trim();
  }

  function pageTitle() {
    var title = cleanTitle(document.title).replace(/\s*[—|–]\s*Finora.*$/i, '');
    if (title && !/^finora$/i.test(title)) return title;
    var exact = Array.from(document.querySelectorAll('.menu a[href]')).find(function (link) {
      return link.pathname.replace(/\/$/, '') === location.pathname.replace(/\/$/, '');
    });
    return exact ? cleanTitle(exact.textContent) : cleanTitle(document.querySelector('.topbar .page-title')?.textContent) || 'فينورا';
  }

  function header() {
    var scope = document.querySelector('main.page-main') || document.body;
    if (document.querySelector('#finoraDesktopHome')) {
      var home = document.querySelector('.desktop-home-header');
      if (home) home.classList.add('fu-home-header');
      return;
    }
    var compact = document.querySelector('.pos-header,.pos-topbar,.quick-pos-topbar,.ws-toolbar,.ed-top,.fm-header,.notes-library-head,.users-list-header,.sales-ai-pane-title,body.finora-audit #root main > header');
    var candidate = compact || scope.querySelector('.fd-header,.ofd-header,.settings-page-header,.admin-page-header,.finance-heading,.ins-dashboard-hero,.ins-heading,.rc-hero,.cr-hero,.dr-header,.archive-head,.exec-top-controls,.pl-head,.quick-hero,.ma-page-head');
    // Drawers and report previews must never become the page's heading.
    if (candidate && candidate.closest('dialog,.modal,.fd-drawer,[hidden]')) candidate = null;
    if (!candidate) {
      candidate = document.createElement('header');
      candidate.className = 'fu-page-header fu-generated-header';
      var title = document.createElement('h1');
      title.textContent = pageTitle();
      candidate.appendChild(title);
      var container = Array.from(scope.children).find(function (node) {
        return node.matches('div,section,article,main') && !node.matches('.modal,.loading-overlay,.toast-container,[hidden]') && getComputedStyle(node).position !== 'fixed';
      });
      var layout = container && getComputedStyle(container);
      if (layout && (layout.display === 'grid' || (layout.display === 'flex' && layout.flexDirection !== 'column'))) {
        scope.insertBefore(candidate, container);
      } else { (container || scope).prepend(candidate); }
    } else {
      candidate.classList.add(compact ? 'fu-compact-header' : 'fu-page-header');
    }
    var heading = candidate.querySelector('h1,h2,h3,.fd-title,.ofd-title,.admin-page-header__title,.pos-title,.ws-title');
    if (!heading && !compact) {
      heading = document.createElement('h1');
      heading.textContent = pageTitle();
      (candidate.querySelector('.admin-page-header__meta') || candidate).prepend(heading);
    }
    if (heading) heading.classList.add('fu-title');
    var subtitle = candidate.querySelector('p,.fd-subtitle,.ofd-subtitle,.admin-page-header__subtitle');
    if (subtitle) subtitle.classList.add('fu-subtitle');
    document.body.dataset.workspaceHeader = 'ready';
  }

  function start() {
    header();
    mark(document.body);
    document.body.dataset.workspaceDesign = 'finora-v1';

    // Newly opened drawers and asynchronously rendered cards share the same styles.
    var queued = new Set();
    var pending = false;
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) { if (node.nodeType === 1) queued.add(node); });
      });
      if (pending || !queued.size) return;
      pending = true;
      requestAnimationFrame(function () {
        queued.forEach(function (node) { if (node.isConnected) mark(node); });
        queued.clear();
        pending = false;
      });
    }).observe(document.body, { childList: true, subtree: true });
  }
  var appRoot = document.querySelector('body.finora-audit #root');
  if (appRoot && !appRoot.children.length) {
    var mount = new MutationObserver(function () {
      if (appRoot.children.length) { mount.disconnect(); start(); }
    });
    mount.observe(appRoot, { childList: true });
  } else { start(); }
})();
