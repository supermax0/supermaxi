const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('../../desktop/finora_management/node_modules/jsdom');
const root = path.resolve(__dirname, '../..');

function page() {
  const dom = new JSDOM('<input type="time" value="22:00" data-finora-clock="22:00"><time data-finora-timestamp="2026-10-20T21:00:00Z"></time>', { runScripts: 'outside-only', url: 'https://finora.test' });
  dom.window.FINORA_TIME_CONFIG = { format: '12', authenticated: false };
  dom.window.eval(fs.readFileSync(path.join(root, 'static/js/time-format.js'), 'utf8'));
  return dom;
}

test('both display clocks respect Baghdad midnight, date-only values and editable inputs', () => {
  const dom = page();
  try {
    const t = dom.window.FinoraTime;
    assert.match(t.dateTime('2026-10-20T16:30:00Z'), /07:30 م/);
    assert.equal(t.clock('22:00'), '10:00 م');
    t.setFormat('24');
    assert.match(t.dateTime('2026-10-20T21:00:00Z'), /00:00/);
    assert.match(dom.window.document.querySelector('time').textContent, /00:00/);
    assert.equal(dom.window.document.querySelector('input').value, '22:00');
    assert.equal(t.dateTime('2026-10-21'), '2026-10-21');
    assert.equal(t.dateTime('bad date'), 'bad date');
    assert.doesNotThrow(() => t.dateTime(new dom.window.Date('bad date')));
    assert.throws(() => t.setFormat('25'));
  } finally { dom.window.close(); }
});

test('clinic appointment labels change while rescheduling keeps the entered wall clock', () => {
  const dom = page();
  try {
    for (const [file, exportName, method] of [
      ['appointments.js', 'ClinicsAppointments', 'drawerBodyHtml'],
      ['reception.js', 'ClinicsReception', 'lateActions'],
    ]) {
      const source = fs.readFileSync(path.join(root, 'static/clinics', file), 'utf8');
      dom.window.eval(source.replace(`window.${exportName} = { render };`, `window.${exportName} = { render, ${method} };`));
      const appt = { id: 7, start_time: '22:00', appointment_date: '2026-10-21', patient_name: 'مريض', late_minutes: 31 };
      const ctx = { esc: String, badge: String, bootstrap: { user: { role: 'admin' } } };
      for (const mode of ['12', '24']) {
        dom.window.FinoraTime.setFormat(mode);
        const html = dom.window[exportName][method](appt, ctx);
        const fragment = JSDOM.fragment(html);
        const button = fragment.querySelector('[data-time]');
        assert.equal(button.dataset.time, '22:00');
        assert.equal(button.dataset.date, '2026-10-21');
        if (file === 'appointments.js') assert.ok(fragment.textContent.includes(mode === '12' ? '10:00 م' : '22:00'));
      }
    }
  } finally { dom.window.close(); }
});
