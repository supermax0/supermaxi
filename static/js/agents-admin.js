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
  document.getElementById('loadingOverlay')?.classList.add('active');
}

function hideLoading() {
  document.getElementById('loadingOverlay')?.classList.remove('active');
}

function addAgent(event) {
  event.preventDefault();
  const name = document.getElementById('agentName').value.trim();
  const phone = document.getElementById('agentPhone').value.trim();
  const notes = document.getElementById('agentNotes').value.trim();
  const btn = document.getElementById('addAgentBtn');
  if (!name) {
    showToast(window.AGENTS_I18N?.err_name || 'الاسم مطلوب', 'warning');
    return;
  }
  btn?.classList.add('button-loading');
  showLoading();
  fetch('/agents/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, phone, notes }),
  })
    .then((r) => r.json())
    .then((data) => {
      hideLoading();
      btn?.classList.remove('button-loading');
      if (data.success) {
        showToast(window.AGENTS_I18N?.add_ok || 'تمت الإضافة', 'success');
        document.getElementById('addAgentForm')?.reset();
        setTimeout(() => location.reload(), 800);
      } else {
        showToast(data.error || window.AGENTS_I18N?.err_generic || 'خطأ', 'error');
      }
    })
    .catch(() => {
      hideLoading();
      btn?.classList.remove('button-loading');
      showToast(window.AGENTS_I18N?.err_add || 'فشل الإضافة', 'error');
    });
}

function deleteAgent(agentId, agentName) {
  const msg = (window.AGENTS_I18N?.confirm_delete || 'حذف {name}?').replace('{name}', agentName);
  if (!confirm(msg)) return;
  showLoading();
  fetch('/agents/delete/' + agentId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
    .then((r) => r.json())
    .then((data) => {
      hideLoading();
      if (data.success) {
        showToast(window.AGENTS_I18N?.delete_ok || 'تم الحذف', 'success');
        setTimeout(() => location.reload(), 800);
      } else {
        showToast(data.error || window.AGENTS_I18N?.err_generic || 'خطأ', 'error');
      }
    })
    .catch(() => {
      hideLoading();
      showToast(window.AGENTS_I18N?.err_delete || 'فشل الحذف', 'error');
    });
}

function editAgent(id, name, phone, notes) {
  const n = prompt(window.AGENTS_I18N?.prompt_name || 'اسم المندوب', name);
  if (n === null) return;
  const ph = prompt(window.AGENTS_I18N?.prompt_phone || 'الهاتف', phone || '');
  if (ph === null) return;
  const nt = prompt(window.AGENTS_I18N?.prompt_notes || 'ملاحظات', notes || '');
  if (nt === null) return;
  showLoading();
  fetch('/agents/edit/' + id, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: n, phone: ph, notes: nt }),
  })
    .then((r) => r.json())
    .then((d) => {
      hideLoading();
      showToast(d.message || d.error, d.success ? 'success' : 'error');
      if (d.success) setTimeout(() => location.reload(), 600);
    })
    .catch(() => {
      hideLoading();
      showToast(window.AGENTS_I18N?.err_generic || 'خطأ', 'error');
    });
}

function setAgentCredentials(agentId, agentName, currentUsername) {
  const username = prompt('اسم مستخدم الدخول للمندوب: ' + agentName, currentUsername || '');
  if (username === null) return;
  const u = username.trim();
  if (!u) {
    showToast('يرجى إدخال اسم المستخدم', 'warning');
    return;
  }
  const password = prompt('كلمة المرور للمندوب:');
  if (password === null) return;
  if (!password.trim()) {
    showToast('يرجى إدخال كلمة المرور', 'warning');
    return;
  }
  showLoading();
  fetch('/agents/set-credentials/' + agentId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: u, password: password.trim() }),
  })
    .then((r) => r.json())
    .then((d) => {
      hideLoading();
      showToast(d.message || d.error, d.success ? 'success' : 'error');
      if (d.success) setTimeout(() => location.reload(), 600);
    })
    .catch(() => {
      hideLoading();
      showToast(window.AGENTS_I18N?.err_generic || 'خطأ', 'error');
    });
}

function filterTable() {
  const searchInput = (document.getElementById('searchInput')?.value || '').toLowerCase();
  const agentFilter = document.getElementById('filterAgent')?.value || '';
  const rows = document.querySelectorAll('#agentsTableBody tr[data-search]');
  let visibleCount = 0;
  rows.forEach((row) => {
    const searchText = row.getAttribute('data-search') || '';
    const agentName = row.getAttribute('data-agent-name') || '';
    const ok =
      (!searchInput || searchText.toLowerCase().includes(searchInput)) &&
      (!agentFilter || agentName === agentFilter);
    row.style.display = ok ? '' : 'none';
    if (ok) visibleCount++;
  });
  const emptyState = document.getElementById('emptyState');
  if (visibleCount === 0 && rows.length && !emptyState) {
    const tr = document.createElement('tr');
    tr.id = 'emptyState';
    tr.innerHTML = `<td colspan="8" class="admin-empty"><div class="admin-empty-icon">🔍</div><div>${window.AGENTS_I18N?.empty_filter || 'لا نتائج'}</div></td>`;
    document.getElementById('agentsTableBody')?.appendChild(tr);
  } else if (visibleCount > 0 && emptyState) {
    emptyState.remove();
  }
}

document.addEventListener('DOMContentLoaded', () => filterTable());
