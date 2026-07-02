function pagesT(key) {
  return (window.PAGES_I18N && window.PAGES_I18N[key]) || key;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  toast.innerHTML = `<span>${icons[type] || icons.info}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

function showLoading() {
  const overlay = document.getElementById('loadingOverlay');
  if (overlay) overlay.classList.add('active');
}

function hideLoading() {
  const overlay = document.getElementById('loadingOverlay');
  if (overlay) overlay.classList.remove('active');
}

function toggleSection(sectionId) {
  const section = document.getElementById(sectionId);
  if (!section) return;
  const isCollapsed = section.classList.toggle('collapsed');
  try {
    const states = JSON.parse(localStorage.getItem('pages_sections_states') || '{}');
    states[sectionId] = isCollapsed;
    localStorage.setItem('pages_sections_states', JSON.stringify(states));
  } catch (e) { /* ignore */ }
}

function restoreSectionStates() {
  try {
    const states = JSON.parse(localStorage.getItem('pages_sections_states') || '{}');
    for (const [id, isCollapsed] of Object.entries(states)) {
      const section = document.getElementById(id);
      if (section) section.classList.toggle('collapsed', !!isCollapsed);
    }
  } catch (e) { /* ignore */ }
}

function handleAddPage(event) {
  event.preventDefault();
  const form = event.target;
  const btn = document.getElementById('addPageBtn');
  if (btn) btn.classList.add('button-loading');
  showLoading();
  fetch('/pages/', { method: 'POST', body: new FormData(form) })
    .then((r) => {
      if (r.ok) {
        showToast(pagesT('pages_toast_add_success'), 'success');
        setTimeout(() => location.reload(), 800);
      } else throw new Error(pagesT('pages_err_add_failed'));
    })
    .catch((err) => {
      hideLoading();
      if (btn) btn.classList.remove('button-loading');
      showToast(err.message, 'error');
    });
}

function updateVisibility(pageId, type, checked) {
  const data = {};
  if (type === 'cashier') data.visible_to_cashier = checked;
  else if (type === 'admin') data.visible_to_admin = checked;
  showLoading();
  fetch(`/pages/update-visibility/${pageId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
    .then((r) => r.json())
    .then((res) => {
      hideLoading();
      if (res.success) showToast(pagesT('pages_toast_visibility_updated'), 'success');
      else {
        showToast(res.error || pagesT('pages_err_generic'), 'error');
        const cb = document.querySelector(`input[data-page-id="${pageId}"][data-type="${type}"]`);
        if (cb) cb.checked = !checked;
      }
    })
    .catch(() => {
      hideLoading();
      showToast(pagesT('pages_err_connection'), 'error');
      const cb = document.querySelector(`input[data-page-id="${pageId}"][data-type="${type}"]`);
      if (cb) cb.checked = !checked;
    });
}

function deletePage(id) {
  if (!confirm(pagesT('pages_confirm_delete'))) return;
  showLoading();
  fetch(`/pages/delete/${id}`, {
    method: 'POST',
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
  })
    .then((r) => r.json())
    .then((d) => {
      hideLoading();
      showToast(d.error || pagesT('pages_toast_deleted'), d.success ? 'success' : 'error');
      if (d.success) setTimeout(() => location.reload(), 600);
    })
    .catch(() => {
      hideLoading();
      showToast(pagesT('pages_err_connection'), 'error');
    });
}

let assignPageId = null;

function openAssignEmployees(pageId, pageName) {
  assignPageId = pageId;
  const title = document.getElementById('assignModalTitle');
  const list = document.getElementById('assignEmployeeList');
  if (!title || !list) return;
  title.textContent = `${pagesT('pages_assign_title')}: ${pageName}`;
  const assigned = new Set(
    (window.PAGES_ASSIGN_MAP && window.PAGES_ASSIGN_MAP[String(pageId)]) || []
  );
  list.innerHTML = '';
  const employees = window.PAGES_EMPLOYEES || [];
  employees.forEach((emp) => {
    const label = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = emp.id;
    if (assigned.has(emp.id)) cb.checked = true;
    label.appendChild(cb);
    label.appendChild(document.createTextNode(emp.name));
    list.appendChild(label);
  });
  document.getElementById('assignModal').classList.add('is-open');
}

function closeAssignModal() {
  document.getElementById('assignModal').classList.remove('is-open');
  assignPageId = null;
}

function saveAssignEmployees() {
  if (!assignPageId) return;
  const list = document.getElementById('assignEmployeeList');
  const employee_ids = Array.from(list.querySelectorAll('input:checked')).map((el) =>
    parseInt(el.value, 10)
  );
  showLoading();
  fetch(`/pages/assign-employees/${assignPageId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ employee_ids }),
  })
    .then((r) => r.json())
    .then((d) => {
      hideLoading();
      showToast(d.message || d.error, d.success ? 'success' : 'error');
      if (d.success) {
        closeAssignModal();
        setTimeout(() => location.reload(), 600);
      }
    })
    .catch(() => {
      hideLoading();
      showToast(pagesT('pages_err_connection'), 'error');
    });
}

function openAddPageSection() {
  const el = document.getElementById('groupAddPage');
  if (el) {
    el.classList.remove('collapsed');
    document.getElementById('pageName')?.focus();
  }
}

let pagesImportFile = null;
let pagesImportExisting = new Set();

function normalizePageName(name) {
  return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase();
}

function uploadPagesImage(forceAi = false) {
  const input = document.getElementById('pagesImportImage');
  const file = input?.files?.[0];
  if (!file) {
    showToast(pagesT('pages_import_err_image'), 'warning');
    return;
  }
  pagesImportFile = file;

  const formData = new FormData();
  formData.append('image', file);
  if (forceAi) formData.append('force_ai', '1');

  showLoading();
  fetch('/pages/import-from-image', { method: 'POST', body: formData })
    .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
    .then(({ ok, data }) => {
      hideLoading();
      if (!ok && !data.names?.length) {
        showToast(data.error || pagesT('pages_import_err_no_names'), 'error');
        if (data.raw_text) {
          openPagesImportModal({
            ...data,
            names: data.names || [],
            success: true,
          });
        }
        return;
      }
      openPagesImportModal(data);
    })
    .catch(() => {
      hideLoading();
      showToast(pagesT('pages_err_connection'), 'error');
    });
}

function retryPagesImportWithAI() {
  if (!pagesImportFile) {
    showToast(pagesT('pages_import_err_image'), 'warning');
    return;
  }
  uploadPagesImage(true);
}

function openPagesImportModal(data) {
  const modal = document.getElementById('pagesImportModal');
  const list = document.getElementById('pagesImportList');
  const meta = document.getElementById('pagesImportMeta');
  if (!modal || !list || !meta) return;

  const names = Array.isArray(data.names) ? data.names : [];
  pagesImportExisting = new Set(
    (data.existing || []).map((n) => normalizePageName(n))
  );

  const sourceLabel = data.source === 'openai'
    ? pagesT('pages_import_source_openai')
    : pagesT('pages_import_source_tesseract');
  const warnings = (data.warnings || []).filter(Boolean);
  meta.textContent = [sourceLabel, warnings.join(' · ')].filter(Boolean).join(' — ');

  list.innerHTML = '';
  if (!names.length) {
    const empty = document.createElement('div');
    empty.className = 'pages-import-empty';
    empty.textContent = pagesT('pages_import_err_no_names');
    list.appendChild(empty);
  } else {
    names.forEach((name, index) => {
      const row = document.createElement('label');
      row.className = 'pages-import-item';
      const exists = pagesImportExisting.has(normalizePageName(name));
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = !exists;
      checkbox.disabled = exists;
      checkbox.dataset.index = String(index);

      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'pages-import-name-input';
      input.value = name;
      input.disabled = exists;

      row.appendChild(checkbox);
      row.appendChild(input);
      if (exists) {
        const badge = document.createElement('span');
        badge.className = 'pages-import-existing-badge';
        badge.textContent = pagesT('pages_import_existing_badge');
        row.appendChild(badge);
      }
      list.appendChild(row);
    });
  }

  modal.classList.add('is-open');
}

function closePagesImportModal() {
  document.getElementById('pagesImportModal')?.classList.remove('is-open');
}

function collectSelectedImportNames() {
  const list = document.getElementById('pagesImportList');
  if (!list) return [];
  const names = [];
  list.querySelectorAll('.pages-import-item').forEach((row) => {
    const checkbox = row.querySelector('input[type="checkbox"]');
    const input = row.querySelector('.pages-import-name-input');
    if (!checkbox || !input || checkbox.disabled || !checkbox.checked) return;
    const value = input.value.trim();
    if (value.length >= 2) names.push(value);
  });
  return names;
}

function confirmBulkPagesImport() {
  const names = collectSelectedImportNames();
  if (!names.length) {
    showToast(pagesT('pages_import_err_no_names'), 'warning');
    return;
  }

  showLoading();
  fetch('/pages/bulk-create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ names }),
  })
    .then((r) => r.json())
    .then((data) => {
      hideLoading();
      if (!data.success) {
        showToast(data.error || pagesT('pages_err_generic'), 'error');
        return;
      }
      const addedMsg = pagesT('pages_import_result_added').replace('{count}', data.added || 0);
      const skippedMsg = pagesT('pages_import_result_skipped').replace('{count}', (data.skipped || []).length);
      showToast(`${addedMsg} — ${skippedMsg}`, 'success');
      closePagesImportModal();
      setTimeout(() => location.reload(), 700);
    })
    .catch(() => {
      hideLoading();
      showToast(pagesT('pages_err_connection'), 'error');
    });
}

document.addEventListener('DOMContentLoaded', () => {
  restoreSectionStates();

  document.getElementById('pagesImportExtractBtn')?.addEventListener('click', () => uploadPagesImage());
  document.getElementById('pagesImportRetryBtn')?.addEventListener('click', () => retryPagesImportWithAI());
  document.getElementById('pagesImportConfirmBtn')?.addEventListener('click', () => confirmBulkPagesImport());
  document.getElementById('pagesImportCancelBtn')?.addEventListener('click', () => closePagesImportModal());
  document.getElementById('pagesImportCloseBtn')?.addEventListener('click', () => closePagesImportModal());
});

window.uploadPagesImage = uploadPagesImage;
window.retryPagesImportWithAI = retryPagesImportWithAI;
window.openPagesImportModal = openPagesImportModal;
window.closePagesImportModal = closePagesImportModal;
window.confirmBulkPagesImport = confirmBulkPagesImport;
