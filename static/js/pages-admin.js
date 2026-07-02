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

function updateAssignSelectedCount() {
  const list = document.getElementById('assignEmployeeList');
  const counter = document.getElementById('assignSelectedCount');
  if (!list || !counter) return;
  const count = list.querySelectorAll('.assign-employee-checkbox:checked').length;
  counter.textContent = `${count} محدد`;
}

function filterAssignEmployees(query) {
  const list = document.getElementById('assignEmployeeList');
  if (!list) return;
  const q = String(query || '').trim().toLowerCase();
  list.querySelectorAll('.assign-employee-row').forEach((row) => {
    const name = row.querySelector('.assign-employee-name')?.textContent?.toLowerCase() || '';
    row.style.display = !q || name.includes(q) ? '' : 'none';
  });
}

function openAssignEmployees(pageId, pageName) {
  assignPageId = pageId;
  const title = document.getElementById('assignModalTitle');
  const subtitle = document.getElementById('assignModalSubtitle');
  const list = document.getElementById('assignEmployeeList');
  const search = document.getElementById('assignEmployeeSearch');
  if (!title || !list) return;

  title.textContent = pagesT('pages_assign_title');
  if (subtitle) subtitle.textContent = pageName ? `البيج: ${pageName}` : '';

  const assigned = new Set(
    ((window.PAGES_ASSIGN_MAP && window.PAGES_ASSIGN_MAP[String(pageId)]) || []).map((id) =>
      parseInt(id, 10)
    )
  );

  list.innerHTML = '';
  const employees = window.PAGES_EMPLOYEES || [];

  if (!employees.length) {
    const empty = document.createElement('div');
    empty.className = 'assign-list-empty';
    empty.textContent = 'لا يوجد موظفين نشطين';
    list.appendChild(empty);
  } else {
    employees.forEach((emp) => {
      const row = document.createElement('label');
      row.className = 'assign-employee-row';
      const isSelected = assigned.has(emp.id);
      if (isSelected) row.classList.add('is-selected');

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'assign-employee-checkbox';
      checkbox.value = emp.id;
      checkbox.checked = isSelected;
      checkbox.addEventListener('change', () => {
        row.classList.toggle('is-selected', checkbox.checked);
        updateAssignSelectedCount();
      });

      const avatar = document.createElement('span');
      avatar.className = 'assign-employee-avatar';
      avatar.textContent = (emp.name || '?').trim().charAt(0) || '?';

      const name = document.createElement('span');
      name.className = 'assign-employee-name';
      name.textContent = emp.name;

      row.appendChild(checkbox);
      row.appendChild(avatar);
      row.appendChild(name);
      list.appendChild(row);
    });
  }

  if (search) {
    search.value = '';
    search.oninput = () => filterAssignEmployees(search.value);
  }

  updateAssignSelectedCount();
  document.getElementById('assignModal')?.classList.add('is-open');
  search?.focus();
}

function closeAssignModal() {
  document.getElementById('assignModal').classList.remove('is-open');
  assignPageId = null;
}

function saveAssignEmployees() {
  if (!assignPageId) return;
  const list = document.getElementById('assignEmployeeList');
  const employee_ids = Array.from(list.querySelectorAll('.assign-employee-checkbox:checked')).map((el) =>
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

  document.querySelectorAll('.js-assign-employees-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const pageId = parseInt(btn.dataset.pageId, 10);
      const pageName = btn.dataset.pageName || btn.closest('tr')?.querySelector('td strong')?.textContent?.trim() || '';
      openAssignEmployees(pageId, pageName);
    });
  });

  document.querySelectorAll('.js-delete-page-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const pageId = parseInt(btn.dataset.pageId, 10);
      if (pageId) deletePage(pageId);
    });
  });

  document.querySelectorAll('.vis-checkbox').forEach((cb) => {
    cb.addEventListener('change', () => {
      const pageId = parseInt(cb.dataset.pageId, 10);
      const type = cb.dataset.type;
      if (pageId && type) updateVisibility(pageId, type, cb.checked);
    });
  });

  document.getElementById('assignModalCloseBtn')?.addEventListener('click', closeAssignModal);
  document.getElementById('assignModalCancelBtn')?.addEventListener('click', closeAssignModal);
  document.getElementById('assignModalSaveBtn')?.addEventListener('click', saveAssignEmployees);
});

window.pagesT = pagesT;
window.showToast = showToast;
window.toggleSection = toggleSection;
window.handleAddPage = handleAddPage;
window.updateVisibility = updateVisibility;
window.deletePage = deletePage;
window.openAssignEmployees = openAssignEmployees;
window.closeAssignModal = closeAssignModal;
window.saveAssignEmployees = saveAssignEmployees;
window.openAddPageSection = openAddPageSection;
