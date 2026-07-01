function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('is-open');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('is-open');
}

function closeModalOnBackdrop(event, id) {
  if (event.target === event.currentTarget) closeModal(id);
}

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('.team-modal-overlay.is-open').forEach((m) => m.classList.remove('is-open'));
});

document.addEventListener('change', (e) => {
  const input = e.target;
  if (!input || input.type !== 'checkbox' || !input.closest('[data-perm-row]')) return;
  const row = input.closest('[data-perm-row]');
  row.classList.toggle('is-on', input.checked);
});
