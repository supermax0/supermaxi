import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { JSDOM } = require('../../desktop/finora_management/node_modules/jsdom');
const script = readFileSync(new URL('../../static/js/workspace-design.js', import.meta.url), 'utf8');

function render(content, { title = 'المخزون', active = true } = {}) {
  const dom = new JSDOM('<!doctype html><html><head></head><body class="' + (active ? 'finora-unified' : '') + '">' + content + '</body></html>', {
    url: 'https://finora.test/inventory/', runScripts: 'outside-only', pretendToBeVisual: true,
  });
  dom.window.document.title = title;
  dom.window.eval(script);
  return dom;
}

test('standalone audit waits for React before styling its existing header', async () => {
  const dom = new JSDOM('<body class="finora-unified finora-audit"><div id="root"></div></body>', {
    url: 'https://finora.test/inventory/smart-audit', runScripts: 'outside-only', pretendToBeVisual: true,
  });
  try {
    const d = dom.window.document;
    dom.window.eval(script);
    assert.equal(d.querySelector('.fu-generated-header'), null);
    d.querySelector('#root').innerHTML = '<main><header><h1>جرد المخزون</h1><button id="refresh">تحديث</button></header><section>8</section></main>';
    await new Promise(resolve => dom.window.setTimeout(resolve, 30));
    assert.ok(d.querySelector('main > header').classList.contains('fu-compact-header'));
    assert.equal(d.querySelectorAll('#refresh').length, 1);
    assert.equal(d.querySelector('.fu-generated-header'), null);
    assert.equal(d.body.dataset.workspaceDesign, 'finora-v1');
  } finally { dom.window.close(); }
});

test('shared presentation preserves product fields, values, handlers and form destinations', () => {
  const dom = render('<main class="page-main"><div id="fdPage"><header class="fd-header"><h1>المنتجات</h1></header><form action="/inventory/add" method="post"><input id="price" name="price" value="125000"><button id="save" class="fd-btn fd-btn--primary" onclick="saveProduct()">حفظ</button></form><article class="fd-kpi"><strong id="balance" data-dashboard-private="true">****</strong></article></div></main>');
  try {
    const d = dom.window.document;
    assert.equal(d.querySelector('#price').value, '125000');
    assert.equal(d.querySelector('form').getAttribute('action'), '/inventory/add');
    assert.equal(d.querySelector('#save').getAttribute('onclick'), 'saveProduct()');
    assert.equal(d.querySelector('#balance').textContent, '****');
    assert.equal(d.querySelector('#balance').dataset.dashboardPrivate, 'true');
    assert.equal(d.querySelectorAll('#save').length, 1);
    assert.equal(d.querySelectorAll('.fu-page-header').length, 1);
    assert.ok(d.querySelector('#save').classList.contains('fu-primary'));
  } finally { dom.window.close(); }
});

test('missing page headings use safe text and retain existing actions', () => {
  const dom = render('<main class="page-main"><section><nav><a id="new" href="/assets/create">إضافة أصل</a></nav><table><tbody><tr><td>12,500</td></tr></tbody></table></section></main>', { title: '<img src=x onerror=alert(1)> — Finora' });
  try {
    const d = dom.window.document;
    assert.equal(d.querySelector('.fu-title').textContent, '<img src=x onerror=alert(1)>');
    assert.equal(d.querySelectorAll('img').length, 0);
    assert.equal(d.querySelector('#new').getAttribute('href'), '/assets/create');
    assert.equal(d.querySelector('td').textContent, '12,500');
  } finally { dom.window.close(); }
});

test('existing header with only a subtitle gains a title without losing controls', () => {
  const dom = render('<main class="page-main"><section><header class="admin-page-header"><div class="admin-page-header__meta"><p>نشاط الفريق</p></div><button id="export">تصدير</button></header></section></main>', { title: 'سجل النشاط' });
  try {
    const d = dom.window.document;
    assert.equal(d.querySelector('.fu-title').textContent, 'سجل النشاط');
    assert.equal(d.querySelector('.fu-subtitle').textContent, 'نشاط الفريق');
    assert.equal(d.querySelectorAll('#export').length, 1);
  } finally { dom.window.close(); }
});

test('generated headers stay outside horizontal application layouts', () => {
  const dom = render('<main class="page-main"><div id="layout" style="display:grid"><aside id="list">العملاء</aside><section id="conversation">المحادثة</section></div></main>');
  try {
    const d = dom.window.document;
    assert.equal(d.querySelector('#layout').children.length, 2);
    assert.equal(d.querySelector('.fu-generated-header').nextElementSibling.id, 'layout');
    assert.equal(d.querySelector('#conversation').textContent, 'المحادثة');
  } finally { dom.window.close(); }
});

test('public pages are not restyled or given internal headers', () => {
  const dom = render('<section class="card"><h1>متجري</h1></section>', { active: false });
  try {
    assert.equal(dom.window.document.querySelectorAll('[class*="fu-"]').length, 0);
    assert.equal(dom.window.document.body.dataset.workspaceDesign, undefined);
  } finally { dom.window.close(); }
});

test('asynchronously loaded financial cards receive presentation without changing amounts', async () => {
  const dom = render('<main class="page-main"><section id="content"></section></main>');
  try {
    const card = dom.window.document.createElement('article');
    card.className = 'finance-stat';
    card.textContent = '5,000,000 د.ع';
    dom.window.document.querySelector('#content').appendChild(card);
    await new Promise(resolve => dom.window.setTimeout(resolve, 50));
    assert.ok(card.classList.contains('fu-stat'));
    assert.equal(card.textContent, '5,000,000 د.ع');
  } finally { dom.window.close(); }
});
