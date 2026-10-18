(function () {
  "use strict";
  const controlIds = ["searchInput", "filterCity", "filterStatus", "filterPayment", "filterEmployee", "filterShipping", "filterDeliveryAgent", "filterScheduledDate", "filterInstallmentType", "filterInstallmentStatus"];
  const fields = new Set(["order_id", "date", "barcode", "customer_name", "phone", "phone2", "total", "paid_amount", "remaining", "status", "payment_status", "employee", "page_name", "city", "address", "shipping_company", "shipping_barcode", "delivery_agent", "note"]);
  const object = value => value && typeof value === "object" && !Array.isArray(value);
  function validGrid(state) {
    return object(state) && object(state.filters) && JSON.stringify(state.filters).length <= 12000
      && Object.entries(state.filters).every(([field, model]) => fields.has(field) && object(model))
      && (state.sort === null || (object(state.sort) && fields.has(state.sort.field) && ["asc", "desc"].includes(state.sort.direction)));
  }
  function validView(view) {
    return object(view) && typeof view.name === "string" && view.name.trim() && view.name.length <= 60
      && object(view.controls) && Object.entries(view.controls).every(([id, value]) => controlIds.includes(id) && typeof value === "string" && value.length <= 500)
      && validGrid(view.grid);
  }
  function init(root, adapter) {
    if (root.dataset.initialized) return;
    root.dataset.initialized = "true";
    const key = "finora.orders.views.v1." + root.dataset.storageKey;
    const select = root.querySelector("[data-view-select]");
    const name = root.querySelector("[data-view-name]");
    const status = root.querySelector("[data-view-status]");
    function tell(message, error) { status.textContent = root.dataset["msg" + message]; status.dataset.error = String(!!error); }
    let views = [];
    try {
      const raw = localStorage.getItem(key) || "[]";
      const parsed = raw.length <= 150000 ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) views = parsed.filter(validView).slice(0, 10);
    } catch (error) { tell("Storage", true); }
    function render(selected) {
      select.replaceChildren(select.options[0]);
      views.forEach(function (view, index) {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = view.name;
        select.appendChild(option);
      });
      select.value = selected === undefined ? "" : String(selected);
    }
    function persist(next) {
      try {
        const serialized = JSON.stringify(next);
        localStorage.setItem(key, serialized);
        views = JSON.parse(serialized);
        return true;
      }
      catch (error) { tell("Storage", true); return false; }
    }
    function selectedIndex() { return select.value === "" ? -1 : Number(select.value); }
    root.querySelector("[data-view-save]").addEventListener("click", function () {
      const title = name.value.trim();
      if (!title) return tell("Name", true);
      const index = views.findIndex(view => view.name === title);
      if (index === -1 && views.length >= 10) return tell("Limit", true);
      const controls = {};
      controlIds.forEach(id => { const control = document.getElementById(id); if (control) controls[id] = control.value; });
      const view = { name: title, controls, grid: adapter.getGridState() };
      if (!validView(view)) return tell("Stale", true);
      const next = views.slice();
      const target = index === -1 ? next.length : index;
      next[target] = view;
      if (persist(next)) { render(target); name.value = ""; tell("Saved"); }
    });
    root.querySelector("[data-view-apply]").addEventListener("click", function () {
      const view = views[selectedIndex()];
      if (!view) return tell("Select", true);
      // Validate all options before changing any control; stale employee/company names must not silently broaden a filter.
      const entries = Object.entries(view.controls);
      if (entries.some(([id, value]) => {
        const control = document.getElementById(id);
        return !control || (control.tagName === "SELECT" && !Array.from(control.options).some(option => option.value === value));
      })) return tell("Stale", true);
      entries.forEach(([id, value]) => { document.getElementById(id).value = value; });
      adapter.applyGridState(view.grid);
      tell("Applied");
    });
    root.querySelector("[data-view-delete]").addEventListener("click", function () {
      const index = selectedIndex();
      if (!views[index]) return tell("Select", true);
      if (persist(views.filter((view, position) => position !== index))) { render(); tell("Deleted"); }
    });
    render();
  }
  window.FinoraOrdersViews = { init };
})();
