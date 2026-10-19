(function (global) {
  "use strict";
  const reserved = new Set(["checkbox", "actions", "card", "id"]);
  const isObject = value => value && typeof value === "object" && !Array.isArray(value);

  function create({ grid, root, onApply, notify }) {
    // Keep the dialog above the sidebar/topbar stacking contexts.
    document.body.appendChild(root);
    const english = root.dataset.language === "en";
    const messages = english ? {
      count: (n, total) => `${n} of ${total} columns selected`, empty: "No matching columns.",
      required: "Select at least one column.", failed: "Your browser could not save these choices. Allow browser storage and try again.",
      saved: "Column choices saved for this account on this browser.",
      cards: "On small screens orders use cards. Your column choices are kept for the table view."
    } : {
      count: (n, total) => `تم اختيار ${n} من ${total} عمود`, empty: "لا توجد أعمدة مطابقة للبحث.",
      required: "اختر عموداً واحداً على الأقل.", failed: "تعذّر حفظ الاختيار في هذا المتصفح. تأكد من السماح بالتخزين ثم جرّب مرة ثانية.",
      saved: "تم حفظ اختيار الأعمدة لهذا الحساب في هذا المتصفح.",
      cards: "على الشاشات الصغيرة تظهر الطلبات كبطاقات؛ يبقى اختيار الأعمدة محفوظاً لعرض الجدول."
    };
    const columns = grid.getColumns().filter(col => !reserved.has(col.getColId()));
    const ids = columns.map(col => col.getColId());
    const defaults = new Set(columns.filter(col => col.getColDef().hide !== true).map(col => col.getColId()));
    const titles = new Map(columns.map(col => [col.getColId(), col.getColDef().headerName || col.getColId()]));
    const key = root.dataset.storageKey;
    const list = root.querySelector("#ordersColumnVisibilityList");
    const search = root.querySelector("[data-columns-search]");
    const error = root.querySelector("[data-columns-error]");
    const count = root.querySelector("[data-columns-count]");
    const empty = root.querySelector("[data-columns-empty]");
    const cardsNote = root.querySelector("[data-columns-cards]");
    let visible = new Set(defaults), draft = null, returnFocus = null, cards = false;

    function payload(selection) {
      return { version: 1, visibility: Object.fromEntries(ids.map(id => [id, selection.has(id)])) };
    }

    try {
      const raw = global.localStorage.getItem(key);
      if (raw !== null) {
        const saved = raw.length <= 20000 ? JSON.parse(raw) : null;
        if (isObject(saved) && saved.version === 1 && isObject(saved.visibility)
            && Object.values(saved.visibility).every(value => typeof value === "boolean")) {
          visible = new Set(ids.filter(id => Object.prototype.hasOwnProperty.call(saved.visibility, id) ? saved.visibility[id] : defaults.has(id)));
        }
      } else {
        // Migrate the old browser-wide choice once; no customer data is stored.
        const old = global.localStorage.getItem("orders_table_visible_columns");
        const saved = old && old.length <= 20000 ? JSON.parse(old) : null;
        if (Array.isArray(saved) && saved.every(id => typeof id === "string")) {
          const migrated = new Set(ids.filter(id => saved.includes(id)));
          if (migrated.size) {
            visible = migrated;
            try { global.localStorage.setItem(key, JSON.stringify(payload(visible))); }
            catch (_) { /* The legacy choice can still be read next time. */ }
          }
        }
      }
    } catch (_) { /* Unavailable/damaged storage uses the normal column defaults. */ }
    if (!visible.size) visible = new Set(defaults.size ? defaults : ids.slice(0, 1));

    function apply(cardLayout) {
      cards = !!cardLayout;
      const shown = cards ? new Set(["card", "checkbox"]) : new Set([...visible, "checkbox", "actions"]);
      const show = [], hide = [];
      grid.getColumns().forEach(col => {
        if (shown.has(col.getColId()) !== col.isVisible()) (shown.has(col.getColId()) ? show : hide).push(col.getColId());
      });
      if (hide.length) grid.setColumnsVisible(hide, false);
      if (show.length) grid.setColumnsVisible(show, true);
    }

    function updateList() {
      if (!draft) return;
      const q = search.value.trim().toLocaleLowerCase();
      let matches = 0;
      list.querySelectorAll(".vis-item").forEach(row => {
        const cb = row.querySelector("input");
        cb.checked = draft.has(cb.dataset.field);
        row.hidden = !String(titles.get(cb.dataset.field)).toLocaleLowerCase().includes(q);
        if (!row.hidden) matches++;
      });
      empty.hidden = matches > 0;
      count.textContent = messages.count(draft.size, ids.length);
    }

    function open() {
      returnFocus = document.activeElement;
      draft = new Set(visible);
      error.hidden = true;
      search.value = "";
      list.replaceChildren();
      columns.forEach((col, index) => {
        const id = col.getColId();
        const row = document.createElement("label");
        row.className = "vis-item";
        const title = document.createElement("span");
        title.textContent = titles.get(id);
        const toggle = document.createElement("span");
        toggle.className = "vis-switch";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = "orders-column-option-" + index;
        cb.dataset.field = id;
        cb.setAttribute("aria-label", titles.get(id));
        const slider = document.createElement("span");
        slider.className = "vis-slider";
        slider.setAttribute("aria-hidden", "true");
        cb.addEventListener("change", () => {
          if (cb.checked) draft.add(id); else draft.delete(id);
          error.hidden = true;
          updateList();
        });
        toggle.append(cb, slider);
        row.append(title, toggle);
        list.append(row);
      });
      cardsNote.hidden = !cards;
      cardsNote.textContent = messages.cards;
      empty.textContent = messages.empty;
      updateList();
      root.style.display = "flex";
      list.scrollTop = 0;
      search.focus();
    }

    function close() {
      root.style.display = "none";
      draft = null;
      if (returnFocus && returnFocus.isConnected) returnFocus.focus();
    }

    function save() {
      if (!draft) return false;
      if (!draft.size) {
        error.textContent = messages.required;
        error.hidden = false;
        return false;
      }
      try { global.localStorage.setItem(key, JSON.stringify(payload(draft))); }
      catch (_) {
        error.textContent = messages.failed;
        error.hidden = false;
        return false;
      }
      visible = new Set(draft);
      onApply();
      notify(messages.saved, "success");
      close();
      return true;
    }

    search.addEventListener("input", updateList);
    root.querySelectorAll("[data-columns-select]").forEach(button => button.addEventListener("click", () => {
      const selected = button.dataset.columnsSelect === "all";
      list.querySelectorAll(".vis-item:not([hidden]) input").forEach(cb => {
        if (selected) draft.add(cb.dataset.field); else draft.delete(cb.dataset.field);
      });
      error.hidden = true;
      updateList();
    }));
    root.querySelector("[data-columns-defaults]").addEventListener("click", () => {
      draft = new Set(defaults);
      error.hidden = true;
      updateList();
    });
    root.addEventListener("keydown", event => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
      if (event.key !== "Tab") return;
      const targets = [...root.querySelectorAll("button, input")].filter(el => !el.disabled && el.getClientRects().length);
      const first = targets[0], last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    return { apply, open, close, save };
  }
  global.FinoraOrderColumns = { create };
})(window);
