(() => {
  'use strict';
  document.querySelectorAll('[data-flow-password]').forEach(button => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.flowPassword);
      if (!input) return;
      const reveal = input.type === 'password';
      input.type = reveal ? 'text' : 'password';
      button.textContent = reveal ? 'إخفاء' : 'إظهار';
      button.setAttribute('aria-label', reveal ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور');
      button.setAttribute('aria-pressed', String(reveal));
      input.focus();
    });
  });
  const form = document.getElementById('loginForm');
  if (!form) return;
  const tenant = document.getElementById('tenant_slug');
  const username = document.getElementById('username');
  const remember = document.getElementById('rememberAccount');
  const key = 'finora_login_remember_v1';
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null');
    if (saved) {
      if (tenant && tenant.type !== 'hidden' && !tenant.value) tenant.value = saved.tenant || '';
      if (username && !username.value) username.value = saved.username || '';
    }
  } catch (_) { /* Storage can be unavailable in private browsing. */ }
  if (tenant && tenant.type !== 'hidden') tenant.addEventListener('input', () => {
    tenant.value = tenant.value.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '');
  });
  form.addEventListener('submit', () => {
    try {
      if (remember.checked) localStorage.setItem(key, JSON.stringify({tenant: tenant.value.trim(), username: username.value.trim()}));
      else localStorage.removeItem(key);
    } catch (_) { /* Login does not depend on local storage. */ }
  });
})();
