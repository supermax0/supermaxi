import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { JSDOM } = require("../../desktop/finora_management/node_modules/jsdom");
const source = readFileSync(new URL("../../static/js/orders-views.js", import.meta.url), "utf8");

function setup(t, { stored, key = "tenant:1:all", blocked = false } = {}) {
  const dom = new JSDOM(`<input id="searchInput"><select id="filterStatus"><option value=""></option><option>تم الطلب</option></select>
    <section id="root" data-storage-key="${key}" data-msg-saved="saved" data-msg-applied="applied" data-msg-deleted="deleted"
      data-msg-name="name" data-msg-limit="limit" data-msg-select="select" data-msg-stale="stale" data-msg-storage="storage">
      <select data-view-select><option value="">Choose</option></select><input data-view-name maxlength="60">
      <button data-view-save></button><button data-view-apply></button><button data-view-delete></button><p data-view-status></p>
    </section>`, { url: "http://127.0.0.1/", runScripts: "outside-only" });
  t.after(() => dom.window.close());
  const window = dom.window;
  if (stored !== undefined) window.localStorage.setItem("finora.orders.views.v1." + key, stored);
  if (blocked) Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } });
  let state = { filters: { total: { filterType: "number", type: "greaterThan", filter: 1000 } }, sort: { field: "total", direction: "desc" } };
  const applied = [];
  window.eval(source);
  window.FinoraOrdersViews.init(window.document.getElementById("root"), {
    getGridState: () => state,
    applyGridState: value => applied.push(JSON.parse(JSON.stringify(value)))
  });
  const q = selector => window.document.querySelector(selector);
  function save(name) { q("[data-view-name]").value = name; q("[data-view-save]").click(); }
  return { window, q, save, applied, setState: value => { state = value; }, status: () => q("[data-view-status]").textContent };
}

test("save and explicitly apply restores controls, column filters and sort; reload never auto applies", t => {
  const first = setup(t);
  first.q("#searchInput").value = "Customer 525";
  first.q("#filterStatus").value = "تم الطلب";
  first.save("Pending work");
  assert.equal(first.status(), "saved");
  const second = setup(t, { stored: first.window.localStorage.getItem("finora.orders.views.v1.tenant:1:all") });
  assert.equal(second.q("#searchInput").value, "");
  assert.equal(second.applied.length, 0);
  second.q("[data-view-select]").value = "0";
  second.q("[data-view-apply]").click();
  assert.equal(second.q("#searchInput").value, "Customer 525");
  assert.equal(second.q("#filterStatus").value, "تم الطلب");
  assert.equal(second.applied[0].sort.field, "total");
  assert.equal(second.applied[0].filters.total.filter, 1000);
  second.q("[data-view-delete]").click();
  assert.equal(second.status(), "deleted");
  assert.equal(second.q("[data-view-select]").options.length, 1);
});

test("tenant, user and status keys isolate presets", t => {
  const env = setup(t, { key: "tenantB:2:packed" });
  env.save("Pack");
  assert.ok(env.window.localStorage.getItem("finora.orders.views.v1.tenantB:2:packed"));
  assert.equal(env.window.localStorage.getItem("finora.orders.views.v1.tenant:1:all"), null);
});

test("redesigned date and amount filters survive saving and applying a view", t => {
  const env = setup(t);
  for (const [id, value] of Object.entries({filterDateFrom:"2026-10-01", filterDateTo:"2026-10-19", filterAmountMin:"1000", filterAmountMax:"90000"})) {
    const input = env.window.document.createElement("input");
    input.id = id; input.value = value; env.window.document.body.appendChild(input);
  }
  env.save("October range");
  for (const id of ["filterDateFrom", "filterDateTo", "filterAmountMin", "filterAmountMax"]) env.q("#" + id).value = "";
  env.q("[data-view-select]").value = "0";
  env.q("[data-view-apply]").click();
  assert.equal(env.q("#filterDateFrom").value, "2026-10-01");
  assert.equal(env.q("#filterDateTo").value, "2026-10-19");
  assert.equal(env.q("#filterAmountMin").value, "1000");
  assert.equal(env.q("#filterAmountMax").value, "90000");
});

test("saved filter is a snapshot independent of later grid object mutations", t => {
  const env = setup(t);
  const state = { filters: { total: { type: "greaterThan", filter: 1000 } }, sort: null };
  env.setState(state);
  env.save("Snapshot");
  state.filters.total.filter = 99999;
  env.q("[data-view-apply]").click();
  assert.equal(env.applied[0].filters.total.filter, 1000);
});

test("stale select option refuses all changes", t => {
  const env = setup(t, { stored: JSON.stringify([{ name: "Old", controls: { searchInput: "do not change", filterStatus: "removed" }, grid: { filters: {}, sort: null } }]) });
  env.q("[data-view-select]").value = "0";
  env.q("[data-view-apply]").click();
  assert.equal(env.status(), "stale");
  assert.equal(env.q("#searchInput").value, "");
  assert.equal(env.applied.length, 0);
});

test("names use text, duplicate name updates, and ten preset limit is enforced", t => {
  const env = setup(t);
  env.save("<img src=x onerror=alert(1)>");
  assert.equal(env.q("[data-view-select]").querySelector("img"), null);
  env.save("<img src=x onerror=alert(1)>");
  assert.equal(env.q("[data-view-select]").options.length, 2);
  for (let i = 1; i < 10; i++) env.save("Filter " + i);
  env.save("Overflow");
  assert.equal(env.status(), "limit");
  assert.equal(env.q("[data-view-select]").options.length, 11);
});

for (const stored of ["null", "{}", "broken", '[{"name":"Bad","controls":{},"grid":{"filters":{},"sort":{"field":"unauthorized","direction":"asc"}}}]']) {
  test("damaged storage does not break the page: " + stored, t => {
    const env = setup(t, { stored });
    assert.equal(env.q("[data-view-select]").options.length, 1);
    assert.equal(env.applied.length, 0);
    env.save("Recover");
    assert.equal(env.status(), "saved");
  });
}

test("storage blocked does not report success or mutate saved choices", t => {
  const env = setup(t, { blocked: true });
  env.save("Unavailable");
  assert.equal(env.status(), "storage");
  assert.equal(env.q("[data-view-select]").options.length, 1);
});
