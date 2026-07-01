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

document.addEventListener('DOMContentLoaded', () => {
  restoreSectionStates();
});
