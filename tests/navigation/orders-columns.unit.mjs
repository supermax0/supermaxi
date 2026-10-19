import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { JSDOM } = require("../../desktop/finora_management/node_modules/jsdom");
const source = readFileSync(new URL("../../static/js/orders-columns.js", import.meta.url), "utf8");
const key = "finora.orders.columns.v1.company:7";

function setup(t, { records = {}, scope = key, blocked = false } = {}) {
  const dom = new JSDOM(`<button id="trigger">Columns</button><div id="root" data-language="en" data-storage-key="${scope}" style="display:none">
    <button>Close</button><input data-columns-search><button data-columns-select="all"></button><button data-columns-select="none"></button>
    <span data-columns-count></span><div id="ordersColumnVisibilityList"></div><div data-columns-empty hidden></div>
    <p data-columns-error hidden></p><p data-columns-cards hidden></p><button data-columns-defaults></button></div>`,
    { url: "http://localhost/", runScripts: "outside-only" });
  t.after(() => dom.window.close());
  const w = dom.window;
  Object.entries(records).forEach(([k, value]) => w.localStorage.setItem(k, value));
  const defs = [
    ["checkbox", "", false], ["order_id", "Number", false], ["customer_name", "Customer", false],
    ["total", "Total", false], ["barcode", "Barcode", true], ["phone", "Phone", true],
    ["actions", "Actions", false], ["card", "Orders", true]
  ];
  const cols = defs.map(([id, title, hide]) => ({ id, visible: !hide, getColId: () => id,
    getColDef: () => ({ headerName: title, hide }), isVisible() { return this.visible; } }));
  const grid = { getColumns: () => cols, setColumnsVisible(ids, visible) { cols.filter(col => ids.includes(col.id)).forEach(col => col.visible = visible); } };
  const saved = [];
  let cards = false, prefs;
  if (blocked) w.localStorage.setItem = () => { throw new Error("blocked"); };
  // Storage's methods are native bindings in JSDOM; override the prototype for quota tests.
  if (blocked) Object.defineProperty(w.Storage.prototype, "setItem", { value() { throw new Error("quota"); } });
  w.eval(source);
  prefs = w.FinoraOrderColumns.create({ grid, root: w.document.getElementById("root"), onApply: () => prefs.apply(cards), notify: msg => saved.push(msg) });
  prefs.apply(false);
  const q = s => w.document.querySelector(s);
  const visible = id => cols.find(c => c.id === id).visible;
  const choose = (id, value) => { const cb = q(`input[data-field="${id}"]`); cb.checked = value; cb.dispatchEvent(new w.Event("change")); };
  return { w, prefs, q, choose, visible, saved, dump: () => ({ [scope]: w.localStorage.getItem(scope) }), layout(value) { cards = value; prefs.apply(value); } };
}

test("enabled default-hidden columns and hidden default-visible columns both survive reload", t => {
  const a = setup(t); a.prefs.open(); a.choose("barcode", true); a.choose("total", false); assert.equal(a.prefs.save(), true);
  const b = setup(t, { records: a.dump() });
  assert.equal(b.visible("barcode"), true);
  assert.equal(b.visible("total"), false);
  assert.equal(b.visible("checkbox"), true); assert.equal(b.visible("actions"), true); assert.equal(b.visible("card"), false);
});

test("legacy visible list migrates and cannot expose the internal card column", t => {
  const a = setup(t, { records: { orders_table_visible_columns: JSON.stringify(["order_id", "barcode", "card", "missing"]) } });
  assert.equal(a.visible("barcode"), true); assert.equal(a.visible("customer_name"), false); assert.equal(a.visible("card"), false);
  assert.ok(a.w.localStorage.getItem(key));
  a.prefs.open(); assert.equal(a.q('input[data-field="card"]'), null); assert.equal(a.q('input[data-field="actions"]'), null);
});

test("mobile layout and saves never replace desktop choices with card visibility", t => {
  const a = setup(t); a.layout(true); assert.equal(a.visible("card"), true); assert.equal(a.visible("actions"), false);
  a.prefs.open(); assert.equal(a.q('[data-field="customer_name"]').checked, true);
  a.choose("phone", true); a.choose("total", false); a.prefs.save();
  assert.equal(a.visible("card"), true); assert.equal(a.visible("phone"), false);
  a.layout(false); assert.equal(a.visible("phone"), true); assert.equal(a.visible("total"), false); assert.equal(a.visible("card"), false);
  const b = setup(t, { records: a.dump() }); assert.equal(b.visible("phone"), true); assert.equal(b.visible("total"), false);
});

test("choices are isolated by company and user", t => {
  const a = setup(t); a.prefs.open(); a.choose("barcode", true); a.prefs.save();
  for (const scope of ["finora.orders.columns.v1.other-company:7", "finora.orders.columns.v1.company:8"]) {
    const b = setup(t, { records: a.dump(), scope }); assert.equal(b.visible("barcode"), false);
  }
});

test("search bulk selection changes matches and keeps other selections", t => {
  const a = setup(t); a.prefs.open(); a.q("[data-columns-search]").value = "Barcode";
  a.q("[data-columns-search]").dispatchEvent(new a.w.Event("input"));
  a.q('[data-columns-select="all"]').click(); assert.equal(a.q('[data-field="barcode"]').checked, true);
  assert.equal(a.q('[data-field="customer_name"]').checked, true);
  a.q('[data-columns-select="none"]').click(); assert.equal(a.q('[data-field="barcode"]').checked, false);
  a.q("[data-columns-search]").value = "missing"; a.q("[data-columns-search]").dispatchEvent(new a.w.Event("input"));
  assert.equal(a.q("[data-columns-empty]").hidden, false);
});

test("cancel and Escape discard unsaved changes and restore focus", t => {
  const a = setup(t); a.q("#trigger").focus(); a.prefs.open(); a.choose("barcode", true);
  a.q("[data-columns-search]").dispatchEvent(new a.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.equal(a.w.document.activeElement.id, "trigger"); assert.equal(a.visible("barcode"), false);
  a.prefs.open(); assert.equal(a.q('[data-field="barcode"]').checked, false); a.prefs.close();
  assert.equal(a.w.localStorage.getItem(key), null);
});

test("default reset is a draft until saved, then survives reload", t => {
  const a = setup(t); a.prefs.open(); a.choose("barcode", true); a.prefs.save();
  a.prefs.open(); a.q("[data-columns-defaults]").click(); a.prefs.close(); assert.equal(a.visible("barcode"), true);
  a.prefs.open(); a.q("[data-columns-defaults]").click(); a.prefs.save();
  const b = setup(t, { records: a.dump() }); assert.equal(b.visible("barcode"), false); assert.equal(b.visible("total"), true);
});

test("a blank table cannot be saved", t => {
  const a = setup(t); a.prefs.open(); a.q('[data-columns-select="none"]').click(); assert.equal(a.prefs.save(), false);
  assert.equal(a.q("[data-columns-error]").hidden, false); assert.equal(a.w.localStorage.getItem(key), null);
});

test("storage failure never reports a successful save or changes applied columns", t => {
  const a = setup(t, { blocked: true }); a.prefs.open(); a.choose("barcode", true); assert.equal(a.prefs.save(), false);
  assert.equal(a.visible("barcode"), false); assert.equal(a.saved.length, 0); assert.equal(a.q("[data-columns-error]").hidden, false);
});

for (const value of ["broken", "null", "[]", '{"version":1,"visibility":{"total":"false"}}', '{"version":1,"visibility":{"order_id":false,"customer_name":false,"total":false}}']) {
  test("damaged or empty preferences retain a useful table: " + value, t => {
    const a = setup(t, { records: { [key]: value } }); assert.equal(a.visible("order_id"), true); assert.equal(a.visible("total"), true);
  });
}

test("new columns use their default if an older saved preference lacks them", t => {
  const a = setup(t, { records: { [key]: '{"version":1,"visibility":{"barcode":true}}' } });
  assert.equal(a.visible("barcode"), true); assert.equal(a.visible("customer_name"), true);
});
