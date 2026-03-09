/**
 * Social Media Automation Dashboard - Frontend
 * متصل بالـ API الفعلي
 */

(function () {
  'use strict';

  const API_BASE = window.AUTOPOSTER_API_BASE || '';
  const LOGIN_URL = window.AUTOPOSTER_LOGIN_URL || '/login';
  const TOAST_DURATION = 4000;
  const ACCENT = '#00d4ff';
  const MUTED = 'rgba(139, 143, 153, 0.8)';
  const GRID = 'rgba(255,255,255,0.04)';

  function fullUrl(url) {
    if (typeof url !== 'string') return url;
    if (url.startsWith('/') && !url.startsWith('//')) return (API_BASE + url).replace(/\/+/g, '/');
    return url;
  }

  // ----- API و المصادقة -----
  async function apiFetch(url, options = {}) {
    const res = await fetch(fullUrl(url), { ...options, credentials: 'include' });
    if (res.status === 401) {
      window.location.href = LOGIN_URL + '?next=' + encodeURIComponent(window.location.pathname || '/autoposter/');
      return null;
    }
    return res;
  }

  async function checkAuth() {
    const res = await apiFetch('/api/me');
    if (!res || res.status === 401) {
      window.location.href = LOGIN_URL + '?next=' + encodeURIComponent(window.location.pathname || '/autoposter/');
      return false;
    }
    const user = await res.json().catch(() => ({}));
    const nameEl = document.querySelector('.user-name');
    if (nameEl) nameEl.textContent = user.display_name || user.email || 'مدير';
    return true;
  }

  async function loadStats() {
    const res = await apiFetch('/api/stats');
    if (!res || !res.ok) return;
    const data = await res.json();
    const map = {
      'pages_connected': document.querySelector('.stat-card .stat-icon.pages')?.closest('.stat-card')?.querySelector('.stat-value'),
      'posts_published': document.querySelector('.stat-card .stat-icon.posts')?.closest('.stat-card')?.querySelector('.stat-value'),
      'scheduled': document.querySelector('.stat-card .stat-icon.scheduled')?.closest('.stat-card')?.querySelector('.stat-value'),
      'avg_engagement': document.querySelector('.stat-card .stat-icon.engagement')?.closest('.stat-card')?.querySelector('.stat-value'),
    };
    if (map.pages_connected) { map.pages_connected.dataset.count = data.pages_connected; map.pages_connected.textContent = '0'; }
    if (map.posts_published) { map.posts_published.dataset.count = data.posts_published; map.posts_published.textContent = '0'; }
    if (map.scheduled) { map.scheduled.dataset.count = data.scheduled; map.scheduled.textContent = '0'; }
    if (map.avg_engagement) { map.avg_engagement.dataset.count = data.avg_engagement || 0; map.avg_engagement.textContent = '0'; }
    setTimeout(animateStats, 200);
  }

  async function loadPages() {
    const res = await apiFetch('/api/pages');
    if (!res || !res.ok) return;
    const data = await res.json();
    const pages = data.pages || [];
    const tbody = document.getElementById('pagesTableBody');
    const wrap = document.getElementById('pagesSelectWrap');
    if (tbody) {
      tbody.innerHTML = pages.map(p => `
        <tr>
          <td><input type="checkbox" class="page-check"></td>
          <td>${escapeHtml(p.name)}</td>
          <td><code>${escapeHtml(p.id)}</code></td>
          <td><span class="status-badge ${p.status === 'connected' ? 'connected' : 'warning'}">${p.status === 'connected' ? 'متصل' : 'انتهت صلاحية التوكن'}</span></td>
          <td>
            <button class="icon-btn small" type="button" title="إجراءات">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="5" cy="12" r="1.5"></circle>
                <circle cx="12" cy="12" r="1.5"></circle>
                <circle cx="19" cy="12" r="1.5"></circle>
              </svg>
            </button>
          </td>
        </tr>
      `).join('') || `
        <tr>
          <td colspan="5">
            <div class="empty-state small">
              <p>لا توجد صفحات متصلة بعد.</p>
              <button type="button" class="btn btn-primary btn-sm" data-connect-page="1">ربط صفحة فيسبوك</button>
            </div>
          </td>
        </tr>
      `;
    }
    if (wrap) {
      const chips = pages.length
        ? pages.map(p => `<div class="page-chip ${pages.length === 1 ? 'selected' : ''}" data-id="${escapeAttr(p.id)}">${escapeHtml(p.name)}</div>`).join('')
        : '<span class="text-muted">لا توجد صفحات متصلة بعد. اربط صفحة من قسم الصفحات.</span>';
      wrap.innerHTML = chips + '<button type="button" class="link-btn" id="managePagesBtn">إدارة الصفحات</button>';
      wrap.querySelector('#managePagesBtn')?.addEventListener('click', () => showPage('pages'));
      wrap.querySelectorAll('.page-chip').forEach(chip => chip.addEventListener('click', () => {
        chip.classList.toggle('selected');
        updateSelectedPagesSummary();
      }));
      updateSelectedPagesSummary();
    }
  }

  function updateSelectedPagesSummary() {
    const wrap = document.getElementById('pagesSelectWrap');
    if (!wrap) return;
    let summary = wrap.querySelector('.pages-selected-summary');
    if (!summary) {
      summary = document.createElement('div');
      summary.className = 'pages-selected-summary field-help';
      wrap.appendChild(summary);
    }
    const hasPages = wrap.querySelector('.page-chip');
    if (!hasPages) {
      summary.textContent = '';
      return;
    }
    const selectedCount = wrap.querySelectorAll('.page-chip.selected').length;
    if (!selectedCount) {
      summary.textContent = 'لم يتم تحديد أي صفحة بعد.';
    } else if (selectedCount === 1) {
      summary.textContent = 'صفحة واحدة محددة.';
    } else {
      summary.textContent = `${selectedCount} صفحات محددة.`;
    }
  }

  async function loadNotifications() {
    const res = await apiFetch('/api/notifications');
    if (!res || !res.ok) return;
    const data = await res.json();
    const list = data.notifications || [];
    const container = document.getElementById('notifList');
    const badge = document.getElementById('notifBadge');
    const unreadCount = list.filter(n => !n.read).length;
    if (badge) {
      badge.textContent = unreadCount;
      badge.style.display = unreadCount ? '' : 'none';
    }
    if (container) {
      container.innerHTML = list.slice(0, 10).map(n => `
        <li class="notif-item ${n.read ? '' : 'unread'}">
          <span class="notif-dot"></span>
          <div>
            <strong>${escapeHtml(n.title)}</strong>
            <p>${escapeHtml(n.body || '')}</p>
            <time>${formatTime(n.created_at)}</time>
          </div>
        </li>
      `).join('') || '<li class="text-muted">لا توجد إشعارات</li>';
    }
  }

  async function loadScheduled() {
    const res = await apiFetch('/api/scheduled');
    if (!res || !res.ok) return;
    const data = await res.json();
    const list = data.scheduled || [];
    const ul = document.getElementById('scheduledList');
    const empty = document.getElementById('scheduledEmpty');
    if (ul) {
      ul.innerHTML = list.map(p => {
        const typeLabel = { post: 'منشور', story: 'ستوري', reels: 'ريلز' }[p.post_type] || p.post_type || 'منشور';
        return `
        <li class="scheduled-item">
          <div class="scheduled-info">
            <strong>${escapeHtml((p.content || '').slice(0, 50))}${(p.content || '').length > 50 ? '...' : ''}</strong>
            <span>${p.scheduled_at ? formatDateTime(p.scheduled_at) : ''} · ${escapeHtml(p.page_name || '')} · <em>${typeLabel}</em></span>
          </div>
          <div class="scheduled-actions">
            <button class="icon-btn small" title="تعديل">✎</button>
            <button class="icon-btn small" title="حذف">🗑</button>
          </div>
        </li>
      `;
      }).join('');
    }
    if (empty) empty.style.display = list.length ? 'none' : 'block';
  }

  async function loadDrafts() {
    const res = await apiFetch('/api/drafts');
    if (!res || !res.ok) return;
    const data = await res.json();
    const drafts = data.drafts || [];
    const ul = document.getElementById('draftsList');
    if (!ul) return;
    if (!drafts.length) {
      ul.innerHTML = '<li class="text-muted">لا توجد مسودات بعد</li>';
      return;
    }
    window.__AUTOPOSTER_DRAFTS__ = drafts;
    ul.innerHTML = drafts.map(d => `
      <li class="scheduled-item" data-draft-id="${d.id}">
        <div class="scheduled-info">
          <strong>${escapeHtml((d.content || '').slice(0, 50))}${(d.content || '').length > 50 ? '...' : ''}</strong>
          <span>${escapeHtml(d.page_name || '')} · ${d.post_type === 'story' ? 'ستوري' : d.post_type === 'reels' ? 'ريلز' : 'منشور'}</span>
        </div>
        <div class="scheduled-actions">
          <button type="button" class="icon-btn small draft-load-btn">تحميل</button>
        </div>
      </li>
    `).join('');
  }

  let templatesCache = [];

  async function loadTemplates() {
    const res = await apiFetch('/api/templates');
    if (!res || !res.ok) return;
    const data = await res.json();
    const list = data.templates || [];
    templatesCache = list;
    const select = document.getElementById('templateSelect');
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value=\"\">بدون قالب</option>' +
      list.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('');
    if (current) {
      const hasCurrent = list.some(t => String(t.id) === String(current));
      if (hasCurrent) select.value = current;
    }
  }

  function escapeHtml(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }
  function escapeAttr(s) {
    if (s == null) return '';
    return String(s).replace(/"/g, '&quot;');
  }
  function formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diff = (now - d) / 60000;
    if (diff < 1) return 'الآن';
    if (diff < 60) return `منذ ${Math.floor(diff)} د`;
    if (diff < 1440) return `منذ ${Math.floor(diff / 60)} س`;
    return d.toLocaleDateString('ar');
  }
  function formatDateTime(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString('ar', { dateStyle: 'short', timeStyle: 'short' });
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const ok = await checkAuth();
    if (!ok) return;
    loadStats();
    loadPages();
    loadNotifications();
    loadScheduled();
    loadDrafts();
    loadTemplates();
    loadAnalytics();
  });

  async function loadSettings() {
    const res = await apiFetch('/api/settings');
    if (!res || !res.ok) return;
    const data = await res.json();
    const appIdEl = document.getElementById('fbAppId');
    const appSecretEl = document.getElementById('fbAppSecret');
    if (appIdEl) appIdEl.value = data.facebook_app_id || '';
    if (appSecretEl) {
      appSecretEl.value = data.facebook_app_secret_set ? '••••••••' : '';
      appSecretEl.placeholder = data.facebook_app_secret_set ? 'اتركه فارغاً للإبقاء على القيمة الحالية' : 'أدخل سر التطبيق';
    }
  }

  async function loadAnalytics() {
    const res = await apiFetch('/api/analytics');
    if (!res || !res.ok) return;
    const data = await res.json().catch(() => ({}));
    const summaryEl = document.getElementById('analyticsSummary');
    const topEl = document.getElementById('topPostsList');
    if (summaryEl && data.summary) {
      const s = data.summary;
      const byType = s.by_type || {};
      const byPage = s.by_page || [];
      summaryEl.innerHTML = `
        <div class="summary-row">
          <div><strong>إجمالي المنشورات المنشورة:</strong> ${s.total_published || 0}</div>
        </div>
        <div class="summary-row">
          <strong>حسب النوع:</strong>
          <span>منشورات: ${byType.post || 0}</span> ·
          <span>ستوري: ${byType.story || 0}</span> ·
          <span>ريلز: ${byType.reels || 0}</span>
        </div>
        <div class="summary-row">
          <strong>أكثر الصفحات نشاطاً:</strong>
          ${(byPage.length ? byPage.map(p => `<span>${escapeHtml(p.page_name || '')}: ${p.count}</span>`).join(' · ') : 'لا توجد بيانات بعد')}
        </div>
      `;
    }
    if (topEl && Array.isArray(data.top_posts)) {
      const items = data.top_posts;
      topEl.innerHTML = items.length ? items.map((p, idx) => `
        <li>
          <div class="rank">${idx + 1}</div>
          <div>
            <strong>${escapeHtml((p.content || '').slice(0, 80))}</strong>
            <div class="top-post-meta">
              <span>${escapeHtml(p.page_name || '')}</span> ·
              <span>${p.post_type === 'story' ? 'ستوري' : p.post_type === 'reels' ? 'ريلز' : 'منشور'}</span> ·
              <span>${p.published_at ? formatDateTime(p.published_at) : ''}</span>
            </div>
          </div>
        </li>
      `).join('') : '<li class="text-muted">لا توجد بيانات بعد</li>';
    }
  }

  // ----- Navigation -----
  const navItems = document.querySelectorAll('.nav-item[data-page]');
  const pages = document.querySelectorAll('.page');

  function showPage(pageId) {
    pages.forEach(p => {
      p.classList.toggle('active', p.id === `page-${pageId}`);
    });
    navItems.forEach(nav => {
      nav.classList.toggle('active', nav.dataset.page === pageId);
    });
    if (window.innerWidth < 992) {
      document.getElementById('sidebar').classList.remove('open');
    }
    const fab = document.getElementById('fabCreate');
    if (fab) fab.classList.toggle('hidden', pageId === 'create');
  }

  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const page = item.dataset.page;
      if (page && !document.getElementById(`page-${page}`)) return;
      showPage(page);
      if (page === 'dashboard') animateStats();
      if (page === 'analytics') drawAnalyticsCharts();
      if (page === 'settings') loadSettings();
    });
  });

  // Hash navigation
  window.addEventListener('hashchange', () => {
    const hash = (window.location.hash || '#dashboard').slice(1);
    if (hash && document.getElementById(`page-${hash}`)) {
      showPage(hash);
      if (hash === 'settings') loadSettings();
      if (hash === 'analytics') drawAnalyticsCharts();
    }
  });
  if (window.location.hash) {
    const hash = window.location.hash.slice(1);
    if (document.getElementById(`page-${hash}`)) {
      showPage(hash);
      if (hash === 'settings') loadSettings();
    }
  } else {
    const fab = document.getElementById('fabCreate');
    if (fab) fab.classList.remove('hidden');
  }

  const goToCreateFromDashboard = document.getElementById('goToCreateFromDashboard');
  if (goToCreateFromDashboard) {
    goToCreateFromDashboard.addEventListener('click', (e) => {
      e.preventDefault();
      showPage('create');
      window.location.hash = '#create';
    });
  }

  // ----- Sidebar toggle (mobile) -----
  const sidebar = document.getElementById('sidebar');
  const menuBtn = document.getElementById('menuBtn');
  const sidebarToggle = document.getElementById('sidebarToggle');

  if (menuBtn) menuBtn.addEventListener('click', () => sidebar.classList.toggle('open'));
  if (sidebarToggle) sidebarToggle.addEventListener('click', () => sidebar.classList.toggle('open'));

  // ----- Stat counters animation -----
  function animateValue(el, end, duration = 1200, suffix = '') {
    const start = 0;
    const startTime = performance.now();
    const isFloat = typeof end === 'number' && end % 1 !== 0;

    function step(now) {
      const t = Math.min((now - startTime) / duration, 1);
      const ease = 1 - Math.pow(1 - t, 3);
      const current = start + (end - start) * ease;
      el.textContent = isFloat ? current.toFixed(1) : Math.round(current) + suffix;
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function animateStats() {
    document.querySelectorAll('.stat-value[data-count]').forEach(el => {
      const count = el.dataset.count;
      const num = count.includes('.') ? parseFloat(count) : parseInt(count, 10);
      const suffix = count.includes('.') ? '%' : '';
      el.textContent = '0' + suffix;
      animateValue(el, num, 1400, suffix);
    });
  }

  // Run once on load if dashboard is active
  if (document.getElementById('page-dashboard').classList.contains('active')) {
    setTimeout(animateStats, 300);
  }

  // ----- Toasts -----
  function toast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const node = document.createElement('div');
    node.className = `toast ${type}`;
    node.setAttribute('role', 'alert');
    node.textContent = message;
    container.appendChild(node);
    setTimeout(() => {
      node.style.opacity = '0';
      const isRtl = document.documentElement.getAttribute('dir') === 'rtl';
      node.style.transform = isRtl ? 'translateX(-100%)' : 'translateX(100%)';
      setTimeout(() => node.remove(), 300);
    }, TOAST_DURATION);
  }

  // ----- Modal -----
  function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
      modal.hidden = false;
      modal.querySelector('[data-close]')?.focus();
    }
  }

  function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.hidden = true;
  }

  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.close));
  });

  document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('click', (e) => {
      if (e.target === modal || e.target.classList.contains('modal-backdrop')) {
        closeModal(modal.id);
      }
    });
  });

  // ----- Create Post -----
  const postEditor = document.getElementById('postEditor');
  const charCount = document.getElementById('charCount');
  const mediaInput = document.getElementById('mediaInput');
  const dropZone = document.getElementById('dropZone');
  const browseMedia = document.getElementById('browseMedia');
  const mediaPreview = document.getElementById('mediaPreview');
  const postPreview = document.getElementById('postPreview');
  const previewPostBtn = document.getElementById('previewPostBtn');
  const publishBtn = document.getElementById('publishBtn');
  const pageChips = document.querySelectorAll('.page-chip[data-id]');
  const uploadProgress = document.getElementById('uploadProgress');
  const postProgress = document.getElementById('postProgress');
  const postProgressText = document.getElementById('postProgressText');
  const saveDraftBtn = document.getElementById('saveDraftBtn');
  const saveTemplateBtn = document.getElementById('saveTemplateBtn');

  if (postEditor && charCount) {
    postEditor.addEventListener('input', () => {
      const len = postEditor.value.length;
      charCount.textContent = len;
      if (len >= 4500) {
        charCount.style.color = 'var(--warning)';
      } else {
        charCount.style.color = '';
      }
      updatePreview();
    });
  }

  function updatePreview() {
    if (!postPreview) return;
    const text = (postEditor && postEditor.value) || '';
    const media = mediaPreview ? mediaPreview.querySelectorAll('img, video') : [];
    const placeholder = postPreview.querySelector('.preview-placeholder');
    if (!text.trim() && media.length === 0) {
      if (placeholder) placeholder.style.display = 'block';
      const content = postPreview.querySelector('.preview-content');
      const mediaWrap = postPreview.querySelector('.preview-media');
      if (content) content.remove();
      if (mediaWrap) mediaWrap.remove();
      return;
    }
    if (placeholder) placeholder.style.display = 'none';
    let content = postPreview.querySelector('.preview-content');
    if (!content) {
      content = document.createElement('div');
      content.className = 'preview-content';
      postPreview.appendChild(content);
    }
    content.textContent = text || '(لا يوجد نص)';
    let mediaWrap = postPreview.querySelector('.preview-media');
    if (media.length) {
      if (!mediaWrap) {
        mediaWrap = document.createElement('div');
        mediaWrap.className = 'preview-media';
        postPreview.appendChild(mediaWrap);
      }
      mediaWrap.innerHTML = '';
      media.forEach(m => {
        const clone = m.cloneNode(true);
        clone.style.maxWidth = '100%';
        clone.style.maxHeight = '120px';
        mediaWrap.appendChild(clone);
      });
    } else if (mediaWrap) mediaWrap.innerHTML = '';
  }

  if (browseMedia) browseMedia.addEventListener('click', () => mediaInput && mediaInput.click());

  let uploadedMedia = { url: null, type: null };

  if (mediaInput) {
    mediaInput.addEventListener('change', (e) => handleFiles(e.target.files));
  }

  async function handleFiles(files) {
    if (!files || !files.length || !mediaPreview) return;
    const file = files[0];
    const isVideo = file.type.startsWith('video/');
    const fd = new FormData();
    fd.append('file', file);
    if (uploadProgress) uploadProgress.hidden = false;
    const res = await apiFetch('/api/upload', { method: 'POST', body: fd });
    if (uploadProgress) uploadProgress.hidden = true;
    if (!res || !res.ok) {
      const err = await res?.json().catch(() => ({}));
      toast(err?.error || 'فشل رفع الملف', 'error');
      return;
    }
    const data = await res.json();
    uploadedMedia = { url: data.url, type: data.type || (isVideo ? 'video' : 'image') };
    mediaPreview.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'media-preview-item';
    const media = data.type === 'video'
      ? Object.assign(document.createElement('video'), { src: data.url, controls: true, muted: true, style: 'max-width:100%;max-height:160px' })
      : Object.assign(document.createElement('img'), { src: data.url, style: 'max-width:100%;max-height:160px' });
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove-media';
    remove.textContent = '×';
    remove.addEventListener('click', () => {
      wrap.remove();
      uploadedMedia = { url: null, type: null };
      updatePreview();
    });
    wrap.appendChild(media);
    wrap.appendChild(remove);
    mediaPreview.appendChild(wrap);
    updatePreview();
  }

  if (dropZone) {
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      handleFiles(e.dataTransfer.files);
    });
  }

  pageChips.forEach(chip => {
    chip.addEventListener('click', () => {
      chip.classList.toggle('selected');
      updateSelectedPagesSummary();
    });
  });

  if (previewPostBtn) {
    previewPostBtn.addEventListener('click', () => {
      const body = document.getElementById('previewModalBody');
      if (!body) return;
      const text = (postEditor && postEditor.value) || '';
      const media = mediaPreview ? mediaPreview.querySelectorAll('img, video') : [];
      body.innerHTML = '';
      const p = document.createElement('p');
      p.className = 'preview-content';
      p.style.whiteSpace = 'pre-wrap';
      p.textContent = text || '(لا يوجد نص)';
      body.appendChild(p);
      if (media.length) {
        const div = document.createElement('div');
        div.className = 'preview-media';
        div.style.marginTop = '0.75rem';
        media.forEach(m => {
          const clone = m.cloneNode(true);
          clone.style.maxWidth = '100%';
          div.appendChild(clone);
        });
        body.appendChild(div);
      }
      openModal('previewModal');
    });
  }

  function getPostPayload(scheduledAt) {
    const text = (postEditor && postEditor.value) || '';
    const selected = document.querySelectorAll('.page-chip.selected[data-id]');
    const pageIds = Array.from(selected).map(c => c.getAttribute('data-id'));
    const postTypeEl = document.querySelector('input[name="postType"]:checked');
    const postType = (postTypeEl && postTypeEl.value) || 'post';
    const payload = {
      text,
      content: text,
      page_ids: pageIds,
      post_type: postType,
      image_url: uploadedMedia.type === 'image' ? uploadedMedia.url : undefined,
      video_url: uploadedMedia.type === 'video' ? uploadedMedia.url : undefined,
    };
    if (scheduledAt) payload.scheduled_at = scheduledAt;
    return { payload, pageIds, text };
  }

  if (publishBtn) {
    publishBtn.addEventListener('click', async () => {
      const { payload, pageIds, text } = getPostPayload(null);
      if (payload.post_type === 'story' && !payload.image_url && !payload.video_url) {
        toast('الستوري يتطلب صورة أو فيديو', 'warning');
        return;
      }
      if (payload.post_type === 'reels' && !payload.video_url) {
        toast('الريلز يتطلب فيديو', 'warning');
        return;
      }
      if (!text.trim() && !payload.image_url && !payload.video_url) {
        toast('الرجاء إدخال محتوى أو رفع صورة/فيديو', 'warning');
        return;
      }
      if (!pageIds.length) {
        toast('اختر صفحة واحدة على الأقل', 'warning');
        return;
      }

      publishBtn.classList.add('loading');
      publishBtn.disabled = true;
      const origText = publishBtn.querySelector('.btn-text')?.textContent || 'نشر الآن';

      if (postProgress) postProgress.hidden = false;

      const chips = Array.from(document.querySelectorAll('.page-chip[data-id]'));
      for (let i = 0; i < pageIds.length; i++) {
        const pageId = pageIds[i];
        const chip = chips.find(c => c.getAttribute('data-id') === pageId);
        chip?.classList.remove('posted', 'error');
        chip?.classList.add('posting');
        if (postProgressText) {
          postProgressText.textContent = `جاري النشر على الصفحة ${i + 1} من ${pageIds.length}`;
        }
        if (publishBtn.querySelector('.btn-text')) {
          publishBtn.querySelector('.btn-text').textContent = `نشر (${i + 1}/${pageIds.length})`;
        }

        const res = await apiFetch('/api/posts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, page_ids: [pageId] }),
        });
        const data = await res?.json().catch(() => ({}));

        if (res && res.ok && data.success) {
          chip?.classList.remove('posting');
          chip?.classList.add('posted');
        } else {
          chip?.classList.remove('posting');
          chip?.classList.add('error');
          toast(data?.error || 'فشل النشر لصفحة واحدة أو أكثر', 'error');
        }
      }

      publishBtn.classList.remove('loading');
      publishBtn.disabled = false;
      if (publishBtn.querySelector('.btn-text')) {
        publishBtn.querySelector('.btn-text').textContent = origText;
      }
      if (postProgress) postProgress.hidden = true;
      if (postProgressText) postProgressText.textContent = '';

      if (postEditor) postEditor.value = '';
      if (charCount) charCount.textContent = '0';
      if (mediaPreview) mediaPreview.innerHTML = '';
      uploadedMedia = { url: null, type: null };
      updatePreview();
      loadStats();
      loadNotifications();
      loadScheduled();
    });
  }

  const scheduleBtn = document.getElementById('scheduleBtn');
  if (scheduleBtn) {
    scheduleBtn.addEventListener('click', async () => {
      const scheduleAtEl = document.getElementById('scheduleAt');
      const scheduledAtLocal = scheduleAtEl ? scheduleAtEl.value : '';

      // تحويل الوقت المحلي من حقل datetime-local إلى UTC ISO
      let scheduledAtIso = '';
      if (scheduledAtLocal) {
        const d = new Date(scheduledAtLocal);
        if (!isNaN(d.getTime())) {
          scheduledAtIso = d.toISOString();
        }
      }

      const { payload, pageIds, text } = getPostPayload(scheduledAtIso || null);
      if (payload.post_type === 'story' && !payload.image_url && !payload.video_url) {
        toast('الستوري يتطلب صورة أو فيديو', 'warning');
        return;
      }
      if (payload.post_type === 'reels' && !payload.video_url) {
        toast('الريلز يتطلب فيديو', 'warning');
        return;
      }
      if (!text.trim() && !payload.image_url && !payload.video_url) {
        toast('الرجاء إدخال محتوى أو رفع صورة/فيديو', 'warning');
        return;
      }
      if (!pageIds.length) {
        toast('اختر صفحة واحدة على الأقل', 'warning');
        return;
      }
      if (!scheduledAtIso) {
        toast('اختر تاريخ ووقت الجدولة', 'warning');
        return;
      }
      scheduleBtn.classList.add('loading');
      scheduleBtn.disabled = true;

      if (postProgress) postProgress.hidden = false;
      const origText = scheduleBtn.querySelector('.btn-text')?.textContent || 'جدولة المنشور';
      const chips = Array.from(document.querySelectorAll('.page-chip[data-id]'));

      for (let i = 0; i < pageIds.length; i++) {
        const pageId = pageIds[i];
        const chip = chips.find(c => c.getAttribute('data-id') === pageId);
        chip?.classList.remove('posted', 'error');
        chip?.classList.add('posting');
        if (postProgressText) {
          postProgressText.textContent = `جاري جدولة الصفحة ${i + 1} من ${pageIds.length}`;
        }
        if (scheduleBtn.querySelector('.btn-text')) {
          scheduleBtn.querySelector('.btn-text').textContent = `جدولة (${i + 1}/${pageIds.length})`;
        }

        const res = await apiFetch('/api/posts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...payload, page_ids: [pageId], scheduled_at: scheduledAtIso }),
        });
        const data = await res?.json().catch(() => ({}));

        if (res && res.ok && data.success) {
          chip?.classList.remove('posting');
          chip?.classList.add('posted');
        } else {
          chip?.classList.remove('posting');
          chip?.classList.add('error');
          toast(data?.error || 'فشل جدولة إحدى الصفحات', 'error');
        }
      }

      scheduleBtn.classList.remove('loading');
      scheduleBtn.disabled = false;
      if (scheduleBtn.querySelector('.btn-text')) {
        scheduleBtn.querySelector('.btn-text').textContent = origText;
      }
      if (postProgress) postProgress.hidden = true;
      if (postProgressText) postProgressText.textContent = '';

      if (postEditor) postEditor.value = '';
      if (charCount) charCount.textContent = '0';
      if (mediaPreview) mediaPreview.innerHTML = '';
      uploadedMedia = { url: null, type: null };
      if (scheduleAtEl) scheduleAtEl.value = '';
      updatePreview();
      loadScheduled();
      loadStats();
    });
  }

  if (saveDraftBtn) {
    saveDraftBtn.addEventListener('click', async () => {
      const { payload, pageIds, text } = getPostPayload(null);
      if (!text.trim() && !payload.image_url && !payload.video_url) {
        toast('لا يمكن حفظ مسودة بدون محتوى أو وسائط', 'warning');
        return;
      }
      if (!pageIds.length) {
        toast('اختر صفحة واحدة على الأقل للمسودة', 'warning');
        return;
      }
      const res = await apiFetch('/api/drafts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res) return;
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.success) {
        toast('تم حفظ المسودة', 'success');
        loadDrafts();
      } else {
        toast(data.error || 'فشل حفظ المسودة', 'error');
      }
    });
  }

  if (saveTemplateBtn) {
    saveTemplateBtn.addEventListener('click', async () => {
      const { payload, pageIds, text } = getPostPayload(null);
      if (!text.trim() && !payload.image_url && !payload.video_url) {
        toast('لا يمكن حفظ قالب بدون محتوى أو وسائط', 'warning');
        return;
      }
      const name = window.prompt('اسم القالب', 'منشور بدون عنوان');
      if (!name) return;
      const res = await apiFetch('/api/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          content: text,
          post_type: payload.post_type,
          image_url: payload.image_url,
          video_url: payload.video_url,
        }),
      });
      if (!res) return;
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.success) {
        toast('تم حفظ القالب', 'success');
        loadTemplates();
      } else {
        toast(data.error || 'فشل حفظ القالب', 'error');
      }
    });
  }

  const templateSelect = document.getElementById('templateSelect');
  if (templateSelect) {
    templateSelect.addEventListener('change', () => {
      const id = templateSelect.value;
      if (!id) return;
      const tpl = templatesCache.find(t => String(t.id) === String(id));
      if (!tpl) return;
      if (postEditor) {
        postEditor.value = tpl.content || '';
        if (charCount) charCount.textContent = String(postEditor.value.length);
      }
      const radio = document.querySelector(`input[name="postType"][value="${tpl.post_type || 'post'}"]`);
      if (radio) radio.checked = true;

      // تعيين الميديا إن وُجدت في القالب (بدون رفع جديد)
      uploadedMedia = { url: tpl.video_url || tpl.image_url || null, type: tpl.video_url ? 'video' : (tpl.image_url ? 'image' : null) };
      if (mediaPreview) {
        mediaPreview.innerHTML = '';
        if (uploadedMedia.url && uploadedMedia.type) {
          const wrap = document.createElement('div');
          wrap.className = 'media-preview-item';
          const media = uploadedMedia.type === 'video'
            ? Object.assign(document.createElement('video'), { src: uploadedMedia.url, controls: true, muted: true, style: 'max-width:100%;max-height:160px' })
            : Object.assign(document.createElement('img'), { src: uploadedMedia.url, style: 'max-width:100%;max-height:160px' });
          wrap.appendChild(media);
          const remove = document.createElement('button');
          remove.type = 'button';
          remove.className = 'remove-media';
          remove.textContent = '×';
          remove.addEventListener('click', () => {
            wrap.remove();
            uploadedMedia = { url: null, type: null };
            updatePreview();
          });
          wrap.appendChild(remove);
          mediaPreview.appendChild(wrap);
        }
      }
      updatePreview();
      showPage('create');
    });
  }

  // ----- Pages: select all -----
  document.getElementById('selectAllPages')?.addEventListener('change', function() {
    document.querySelectorAll('.page-check').forEach(cb => { cb.checked = this.checked; });
  });

  // ----- Charts (vanilla canvas) -----
  function drawLineChart(canvasId, data, color = ACCENT) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data.length) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = Number(canvas.getAttribute('width')) || 400;
    const h = Number(canvas.getAttribute('height')) || 200;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.scale(dpr, dpr);
    const padding = { top: 20, right: 20, bottom: 28, left: 40 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;
    const max = Math.max(...data);
    const min = Math.min(...data);
    const range = max - min || 1;

    ctx.fillStyle = GRID;
    for (let i = 0; i <= 4; i++) {
      const y = padding.top + (chartH / 4) * i;
      ctx.fillRect(padding.left, y, chartW, 1);
    }
    for (let i = 0; i <= 5; i++) {
      const x = padding.left + (chartW / 5) * i;
      ctx.fillRect(x, padding.top, 1, chartH);
    }

    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    data.forEach((v, i) => {
      const x = padding.left + (chartW / (data.length - 1 || 1)) * i;
      const y = padding.top + chartH - ((v - min) / range) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function drawBarChart(canvasId, data, color = ACCENT) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data.length) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = Number(canvas.getAttribute('width')) || 300;
    const h = Number(canvas.getAttribute('height')) || 200;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.scale(dpr, dpr);
    const padding = { top: 20, right: 20, bottom: 28, left: 40 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;
    const max = Math.max(...data);
    const barW = (chartW / data.length) * 0.6;
    const gap = (chartW / data.length) * 0.2;

    data.forEach((v, i) => {
      const x = padding.left + gap + (chartW / data.length) * i + (chartW / data.length - barW) / 2;
      const barH = max ? (v / max) * chartH : 0;
      const y = padding.top + chartH - barH;
      ctx.fillStyle = color;
      ctx.fillRect(x, y, barW, barH);
    });
  }

  function drawPerformanceChart() {
    const data = [32, 45, 38, 52, 48, 62, 58];
    drawLineChart('perfChart', data, ACCENT);
  }

  function drawAnalyticsCharts() {
    drawLineChart('engagementChart', [20, 34, 28, 45, 52, 48, 60, 55, 70], ACCENT);
    drawBarChart('growthChart', [120, 145, 160, 178, 195], '#00e676');
  }

  const perfCanvas = document.getElementById('perfChart');
  if (perfCanvas && document.getElementById('page-dashboard').classList.contains('active')) {
    setTimeout(drawPerformanceChart, 400);
  }

  // ----- Calendar -----
  let calDate = new Date();
  const calMonthYear = document.getElementById('calMonthYear');
  const calGrid = document.getElementById('calendarGrid');
  const calPrev = document.getElementById('calPrev');
  const calNext = document.getElementById('calNext');

  const DAYS = ['أحد', 'إثن', 'ثلا', 'أرب', 'خمي', 'جمع', 'سبت'];

  function renderCalendar() {
    if (!calGrid || !calMonthYear) return;
    const year = calDate.getFullYear();
    const month = calDate.getMonth();
    calMonthYear.textContent = calDate.toLocaleString('ar', { month: 'long', year: 'numeric' });

    const first = new Date(year, month, 1);
    const last = new Date(year, month + 1, 0);
    const startDay = first.getDay();
    const daysInMonth = last.getDate();
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    calGrid.innerHTML = '';
    DAYS.forEach(d => {
      const cell = document.createElement('div');
      cell.className = 'calendar-cell head';
      cell.textContent = d;
      calGrid.appendChild(cell);
    });

    for (let i = 0; i < startDay; i++) {
      const cell = document.createElement('div');
      cell.className = 'calendar-cell other';
      const prevMonth = new Date(year, month, -startDay + i + 1);
      cell.textContent = prevMonth.getDate();
      calGrid.appendChild(cell);
    }

    const eventDays = [10, 12];
    for (let d = 1; d <= daysInMonth; d++) {
      const cell = document.createElement('div');
      cell.className = 'calendar-cell';
      const dDate = new Date(year, month, d);
      dDate.setHours(0, 0, 0, 0);
      if (dDate.getTime() === today.getTime()) cell.classList.add('today');
      if (eventDays.includes(d)) cell.classList.add('has-event');
      cell.textContent = d;
      calGrid.appendChild(cell);
    }

    const total = startDay + daysInMonth;
    const rest = 42 - total;
    for (let i = 0; i < rest; i++) {
      const cell = document.createElement('div');
      cell.className = 'calendar-cell other';
      cell.textContent = i + 1;
      calGrid.appendChild(cell);
    }
  }

  if (calPrev) calPrev.addEventListener('click', () => { calDate.setMonth(calDate.getMonth() - 1); renderCalendar(); });
  if (calNext) calNext.addEventListener('click', () => { calDate.setMonth(calDate.getMonth() + 1); renderCalendar(); });
  renderCalendar();

  // ----- Scheduled view toggle -----
  document.querySelectorAll('.view-toggle .toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.view-toggle .toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const view = btn.dataset.view;
      const calendarCard = document.getElementById('calendarCard');
      if (calendarCard) calendarCard.style.display = view === 'calendar' ? 'block' : 'none';
    });
  });

  // ----- ربط صفحة فيسبوك وعمليات أخرى بالنقر -----
  document.addEventListener('click', (e) => {
    const connectPageBtn = e.target.closest('#connectPageBtn, [data-connect-page]');
    if (connectPageBtn) {
      e.preventDefault();
      (async () => {
        const res = await apiFetch('/api/facebook/connect');
        if (!res) return;
        const data = await res.json().catch(() => ({}));
        if (data.url) {
          window.location.href = data.url;
        } else {
          toast(data.error || 'لم يتم ضبط تطبيق فيسبوك. أضف FACEBOOK_APP_ID و FACEBOOK_APP_SECRET.', 'warning');
        }
      })();
      return;
    }

    const draftBtn = e.target.closest('.draft-load-btn');
    if (draftBtn) {
      e.preventDefault();
      const li = draftBtn.closest('[data-draft-id]');
      const id = li?.getAttribute('data-draft-id');
      if (!id || !window.__AUTOPOSTER_DRAFTS__) return;
      const d = window.__AUTOPOSTER_DRAFTS__.find(x => String(x.id) === String(id));
      if (!d) return;
      showPage('create');
      if (postEditor) {
        postEditor.value = d.content || '';
        if (charCount) charCount.textContent = String(postEditor.value.length);
      }
      const radio = document.querySelector(`input[name="postType"][value="${d.post_type || 'post'}"]`);
      if (radio) radio.checked = true;

      // تحديد الصفحة
      document.querySelectorAll('.page-chip.selected').forEach(chip => chip.classList.remove('selected'));
      if (d.page_id) {
        const chip = document.querySelector(`.page-chip[data-id="${CSS.escape(String(d.page_id))}"]`);
        chip?.classList.add('selected');
      }

      // تعيين الميديا من المسودة (إن وجدت)
      uploadedMedia = { url: d.video_url || d.image_url || null, type: d.video_url ? 'video' : (d.image_url ? 'image' : null) };
      if (mediaPreview) {
        mediaPreview.innerHTML = '';
        if (uploadedMedia.url && uploadedMedia.type) {
          const wrap = document.createElement('div');
          wrap.className = 'media-preview-item';
          const media = uploadedMedia.type === 'video'
            ? Object.assign(document.createElement('video'), { src: uploadedMedia.url, controls: true, muted: true, style: 'max-width:100%;max-height:160px' })
            : Object.assign(document.createElement('img'), { src: uploadedMedia.url, style: 'max-width:100%;max-height:160px' });
          const remove = document.createElement('button');
          remove.type = 'button';
          remove.className = 'remove-media';
          remove.textContent = '×';
          remove.addEventListener('click', () => {
            wrap.remove();
            uploadedMedia = { url: null, type: null };
            updatePreview();
          });
          wrap.appendChild(media);
          wrap.appendChild(remove);
          mediaPreview.appendChild(wrap);
        }
      }
      updatePreview();
      updateSelectedPagesSummary();
    }
  });

  // ----- Manage pages from create -----
  const managePagesBtn = document.getElementById('managePagesBtn');
  if (managePagesBtn) {
    managePagesBtn.addEventListener('click', () => {
      showPage('pages');
    });
  }

  // ----- إعدادات فيسبوك (معرف التطبيق وسر التطبيق) -----
  const facebookSettingsForm = document.getElementById('facebookSettingsForm');
  if (facebookSettingsForm) {
    facebookSettingsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('saveSettingsBtn');
      const appId = (document.getElementById('fbAppId')?.value || '').trim();
      const appSecret = (document.getElementById('fbAppSecret')?.value || '').trim();
      if (btn) { btn.disabled = true; btn.textContent = 'جاري الحفظ...'; }
      const res = await apiFetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ facebook_app_id: appId, facebook_app_secret: appSecret }),
      });
      if (btn) { btn.disabled = false; btn.textContent = 'حفظ الإعدادات'; }
      if (res && res.ok) {
        toast('تم حفظ إعدادات فيسبوك', 'success');
        if (appSecret && appSecret !== '••••••••') document.getElementById('fbAppSecret').value = '••••••••';
      } else {
        const err = await res?.json().catch(() => ({}));
        toast(err?.error || 'فشل الحفظ', 'error');
      }
    });
  }

  // ----- Global search -----
  const globalSearch = document.getElementById('globalSearch');
  if (globalSearch) {
    globalSearch.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') toast('البحث: ربط مع Flask /api/search', 'info');
    });
  }

  // ----- Notifications & User dropdowns -----
  const notifBtn = document.getElementById('notifBtn');
  const notifPanel = document.getElementById('notifPanel');
  const userBtn = document.getElementById('userBtn');
  const userPanel = document.getElementById('userPanel');
  const notifBadge = document.getElementById('notifBadge');
  const markAllRead = document.getElementById('markAllRead');
  const logoutBtn = document.getElementById('logoutBtn');

  function closeAllDropdowns() {
    if (notifPanel) { notifPanel.classList.remove('open'); notifPanel.setAttribute('aria-hidden', 'true'); }
    if (userPanel) { userPanel.classList.remove('open'); userPanel.setAttribute('aria-hidden', 'true'); }
    if (notifBtn) notifBtn.setAttribute('aria-expanded', 'false');
    if (userBtn) userBtn.setAttribute('aria-expanded', 'false');
  }

  if (notifBtn && notifPanel) {
    notifBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = notifPanel.classList.toggle('open');
      notifPanel.setAttribute('aria-hidden', !open);
      notifBtn.setAttribute('aria-expanded', open);
      if (userPanel) { userPanel.classList.remove('open'); userPanel.setAttribute('aria-hidden', 'true'); }
      if (userBtn) userBtn.setAttribute('aria-expanded', 'false');
    });
  }
  if (userBtn && userPanel) {
    userBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = userPanel.classList.toggle('open');
      userPanel.setAttribute('aria-hidden', !open);
      userBtn.setAttribute('aria-expanded', open);
      if (notifPanel) { notifPanel.classList.remove('open'); notifPanel.setAttribute('aria-hidden', 'true'); }
      if (notifBtn) notifBtn.setAttribute('aria-expanded', 'false');
    });
  }
  document.addEventListener('click', () => closeAllDropdowns());
  [notifPanel, userPanel].forEach(panel => {
    if (panel) panel.addEventListener('click', (e) => e.stopPropagation());
  });

  const notifList = document.getElementById('notifList');
  if (markAllRead) {
    markAllRead.addEventListener('click', async () => {
      const res = await apiFetch('/api/notifications/read', { method: 'POST' });
      if (res && res.ok) {
        if (notifList) notifList.querySelectorAll('.notif-item.unread').forEach(el => el.classList.remove('unread'));
        if (notifBadge) { notifBadge.textContent = '0'; notifBadge.style.display = 'none'; }
        toast('تم تعليم الكل كمقروء', 'success');
      }
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      closeAllDropdowns();
      await apiFetch('/api/logout', { method: 'POST' });
      window.location.href = LOGIN_URL || '/login';
    });
  }

  document.querySelectorAll('.user-dropdown .dropdown-link[data-page]').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const page = link.getAttribute('data-page');
      if (page) showPage(page);
      closeAllDropdowns();
    });
  });
})();
