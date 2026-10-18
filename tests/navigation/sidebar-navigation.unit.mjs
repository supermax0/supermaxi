import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { JSDOM } = require("../../desktop/finora_management/node_modules/jsdom");
const source = readFileSync(new URL("../../static/js/sidebar-navigation.js", import.meta.url), "utf8");

function setup(t, preferences, path = "/") {
  const dom = new JSDOM(`<nav data-organized-navigation data-nav-storage-key="test:1">
    <input data-nav-search><button data-nav-clear hidden></button><span data-nav-search-status></span><section data-nav-favorites hidden><span data-nav-favorite-count></span><div data-nav-favorite-links></div></section>
    <p data-nav-empty hidden></p>
    <details data-nav-section="sales" open><summary>Sales</summary><div data-nav-item data-nav-search-terms="فاتورة">
      <a href="/orders" id="ordersLink">الطلبات<span id="counter">2</span></a><button data-nav-pin="/orders"><i></i></button>
    </div></details>
    <details data-nav-section="stock"><summary>Stock</summary><div data-nav-item>
      <a href="/inventory">المخزون</a><button data-nav-pin="/inventory"><i></i></button>
    </div></details>
    <details data-nav-section="other"><summary>Other</summary><div data-nav-item>
      <a href="/orders/ordered" class="active">تم الطلب</a><button data-nav-pin="/orders/ordered"><i></i></button>
    </div></details>
  </nav>`, { url: "http://127.0.0.1" + path, runScripts: "outside-only" });
  t.after(() => dom.window.close());
  if (preferences !== undefined) dom.window.localStorage.setItem("finora.navigation.v2.test:1", preferences);
  dom.window.eval(source);
  return dom.window;
}

test("search filters pages and empty sections, then restores the active section", t => {
  const window = setup(t);
  const input = window.document.querySelector("[data-nav-search]");
  input.value = "المخزون";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(window.document.querySelector('[data-nav-section="sales"]').hidden, true);
  assert.equal(window.document.querySelector('[data-nav-section="stock"]').open, true);
  input.value = "nonexistent";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(window.document.querySelector("[data-nav-empty]").hidden, false);
  input.value = "";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(window.document.querySelector('[data-nav-section="sales"]').hidden, false);
  assert.equal(window.document.querySelector('[data-nav-section="sales"]').open, true);
});

test("favorites persist per user without duplicating badge IDs", t => {
  const window = setup(t);
  const pin = window.document.querySelector('[data-nav-pin="/orders"]');
  pin.click();
  assert.equal(pin.getAttribute("aria-pressed"), "true");
  assert.equal(window.document.querySelectorAll("#counter").length, 1);
  assert.equal(window.document.querySelectorAll("#ordersLink").length, 1);
  assert.equal(window.document.querySelector("[data-nav-favorites]").hidden, false);
  assert.deepEqual(JSON.parse(window.localStorage.getItem("finora.navigation.v2.test:1")).favorites, ["/orders"]);
  pin.click();
  assert.equal(window.document.querySelector("[data-nav-favorites]").hidden, true);
});

test("search accepts a page synonym", t => {
  const window = setup(t);
  const input = window.document.querySelector("[data-nav-search]");
  input.value = "فاتورة";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(window.document.querySelector('[data-nav-section="sales"]').hidden, false);
  assert.equal(window.document.querySelector('[data-nav-section="stock"]').hidden, true);
});

test("stale favorite permissions cannot recreate a forbidden page", t => {
  const window = setup(t, JSON.stringify({ favorites: ["/accounts/finance", "/inventory"] }));
  assert.equal(window.document.querySelector('a[href="/accounts/finance"]'), null);
  assert.equal(window.document.querySelector('[data-nav-favorite-links] a').getAttribute("href"), "/inventory");
});

for (const stored of ["not json", "null", "[]"]) {
  test(`damaged preferences do not break navigation: ${stored}`, t => {
    const window = setup(t, stored);
    window.document.querySelector('[data-nav-pin="/orders"]').click();
    assert.equal(window.document.querySelector('[data-nav-pin="/orders"]').getAttribute("aria-pressed"), "true");
  });
}

test("only the longest matching destination is active, including in favorites", t => {
  const window = setup(t, JSON.stringify({ favorites: ["/orders", "/orders/ordered"] }), "/orders/ordered/");
  const active = window.document.querySelectorAll('[data-nav-item] a[aria-current="page"]');
  assert.equal(active.length, 1);
  assert.equal(active[0].getAttribute("href"), "/orders/ordered");
  assert.equal(window.document.querySelectorAll('[data-nav-item].is-current').length, 1);
  const favorite = window.document.querySelector('[data-nav-favorite-links] a[aria-current="page"]');
  assert.equal(favorite.getAttribute("href"), "/orders/ordered");
  assert.equal(window.document.querySelector('[data-nav-favorite-count]').textContent, "2");
});

test("similar path prefixes do not select a different page", t => {
  const window = setup(t, undefined, "/inventory-old");
  assert.equal(window.document.querySelector('[aria-current="page"]'), null);
});

test("clear restores groups and returns focus; Escape clears before closing a drawer", t => {
  const window = setup(t);
  const input = window.document.querySelector('[data-nav-search]');
  input.value = "المخزون";
  input.dispatchEvent(new window.Event("input"));
  assert.equal(window.document.querySelector('[data-nav-clear]').hidden, false);
  assert.equal(window.document.querySelector('[data-nav-search-status]').textContent, "1 نتيجة");
  window.document.querySelector('[data-nav-clear]').click();
  assert.equal(input.value, "");
  assert.equal(window.document.activeElement, input);
  assert.equal(window.document.querySelector('[data-nav-clear]').hidden, true);
  input.value = "again";
  let escaped = false;
  window.document.addEventListener('keydown', () => { escaped = true; });
  input.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  assert.equal(input.value, "");
  assert.equal(escaped, false);
});
