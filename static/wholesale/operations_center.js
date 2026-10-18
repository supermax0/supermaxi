(function () {
  const root = document.getElementById("wsOps");
  if (!root) return;

  const state = {
    ctx: null,
    op: root.dataset.initialOp || "sale",
    tabs: [{ id: 1, op: "sale", title: "بيع 1" }],
    activeTab: 1,
    saleLines: [],
    purLines: [],
    autosaveTimer: null,
  };

  const $ = (id) => document.getElementById(id);
  const toast = (msg, err) => {
    const el = $("wsToast");
    el.hidden = false;
    el.textContent = msg;
    el.classList.toggle("err", !!err);
    setTimeout(() => { el.hidden = true; }, 3200);
  };

  async function api(path, opts = {}) {
    const res = await fetch("/api/wholesale" + path, {
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      ...opts,
    });
    const data = await res.json().catch(() => ({ ok: false, error: "استجابة غير صالحة" }));
    if (!res.ok || data.ok === false) throw new Error(data.error || "فشل الطلب");
    return data.data;
  }

  function today() {
    return new Date().toISOString().slice(0, 10);
  }

  function fillSelect(el, items, map) {
    if (!el) return;
    el.innerHTML = (items || []).map(map).join("");
  }

  function showPanel(op) {
    state.op = op;
    document.querySelectorAll(".ws-op-btn[data-op]").forEach((b) => {
      b.classList.toggle("active", b.dataset.op === op);
    });
    document.querySelectorAll(".ws-panel").forEach((p) => {
      p.hidden = p.dataset.panel !== op;
    });
  }

  function renderTabs() {
    const box = $("wsDraftTabs");
    box.innerHTML = state.tabs
      .map(
        (t) =>
          `<button type="button" class="ws-tab ${t.id === state.activeTab ? "active" : ""}" data-tab="${t.id}">${t.title}</button>`
      )
      .join("");
    box.querySelectorAll(".ws-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.activeTab = Number(btn.dataset.tab);
        const tab = state.tabs.find((t) => t.id === state.activeTab);
        if (tab) showPanel(tab.op);
        renderTabs();
      });
    });
  }

  function bindSuggest(input, box, fetcher, onPick) {
    let t;
    input.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const q = input.value.trim();
        if (q.length < 1) {
          box.classList.remove("open");
          return;
        }
        const rows = await fetcher(q);
        box.innerHTML = rows
          .map(
            (r) =>
              `<button type="button" data-id="${r.id}">${r.label}</button>`
          )
          .join("");
        box.classList.add("open");
        box.querySelectorAll("button").forEach((b) => {
          b.addEventListener("click", () => {
            onPick(rows.find((x) => String(x.id) === b.dataset.id));
            box.classList.remove("open");
          });
        });
      }, 220);
    });
    document.addEventListener("click", (e) => {
      if (!box.contains(e.target) && e.target !== input) box.classList.remove("open");
    });
  }

  function money(n) {
    return Number(n || 0).toLocaleString("en-US");
  }

  function recalcSale() {
    let sub = 0;
    state.saleLines.forEach((l) => {
      l.total = Math.max(0, l.price * l.quantity - (l.discount || 0));
      sub += l.price * l.quantity;
    });
    const discount = Number($("saleDiscount").value || 0);
    const shipping = Number($("saleShipping").value || 0);
    const lineDisc = state.saleLines.reduce((a, l) => a + (l.discount || 0), 0);
    const grand = Math.max(0, sub - lineDisc - discount + shipping);
    let paid = Number($("salePaid").value || 0);
    const type = $("saleType").value;
    if (type === "cash") {
      paid = grand;
      $("salePaid").value = paid;
    }
    $("saleSub").textContent = money(sub - lineDisc);
    $("saleGrand").textContent = money(grand);
    $("saleRemain").textContent = money(Math.max(0, grand - paid));
    renderSaleLines();
  }

  function renderSaleLines() {
    const tb = $("saleLinesTable").querySelector("tbody");
    tb.innerHTML = state.saleLines
      .map(
        (l, i) => `<tr>
        <td>${l.name}</td>
        <td>${l.available_qty ?? "—"}${l.stock ? `<small style="display:block;color:var(--text-muted)">فعلي ${l.stock.on_hand} · محجوز ${l.stock.reserved} · بالطريق ${l.stock.in_transit}</small>` : ""}</td>
        <td><input type="number" data-i="${i}" data-f="quantity" value="${l.quantity}"></td>
        <td><input type="number" data-i="${i}" data-f="price" value="${l.price}"></td>
        <td><input type="number" data-i="${i}" data-f="discount" value="${l.discount || 0}"></td>
        <td>${money(l.total || 0)}</td>
        <td><button type="button" data-del="${i}">×</button></td>
      </tr>`
      )
      .join("");
    tb.querySelectorAll("input").forEach((inp) => {
      inp.addEventListener("change", () => {
        const i = Number(inp.dataset.i);
        state.saleLines[i][inp.dataset.f] = Number(inp.value || 0);
        recalcSale();
        scheduleAutosave();
      });
    });
    tb.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.saleLines.splice(Number(btn.dataset.del), 1);
        recalcSale();
      });
    });
  }

  function recalcPur() {
    let sub = 0;
    state.purLines.forEach((l) => {
      l.total = Math.max(0, l.price * l.quantity - (l.discount || 0));
      sub += l.total;
    });
    const extras =
      Number($("purShipping").value || 0) +
      Number($("purCustoms").value || 0) +
      Number($("purOther").value || 0);
    const grand = sub + extras;
    let paid = Number($("purPaid").value || 0);
    if ($("purMode").value === "cash") {
      paid = grand;
      $("purPaid").value = paid;
    }
    $("purGrand").textContent = money(grand);
    $("purRemain").textContent = money(Math.max(0, grand - paid));
    renderPurLines();
  }

  function renderPurLines() {
    const tb = $("purLinesTable").querySelector("tbody");
    tb.innerHTML = state.purLines
      .map(
        (l, i) => `<tr>
        <td>${l.name}</td>
        <td><input type="number" data-i="${i}" data-f="quantity" value="${l.quantity}"></td>
        <td><input type="number" data-i="${i}" data-f="price" value="${l.price}"></td>
        <td><input type="number" data-i="${i}" data-f="discount" value="${l.discount || 0}"></td>
        <td>${money(l.total || 0)}</td>
        <td><button type="button" data-del="${i}">×</button></td>
      </tr>`
      )
      .join("");
    tb.querySelectorAll("input").forEach((inp) => {
      inp.addEventListener("change", () => {
        state.purLines[Number(inp.dataset.i)][inp.dataset.f] = Number(inp.value || 0);
        recalcPur();
        scheduleAutosave();
      });
    });
    tb.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.purLines.splice(Number(btn.dataset.del), 1);
        recalcPur();
      });
    });
  }

  function salePayload(extra = {}) {
    return {
      invoice_no: $("saleInvoiceNo").value,
      date: $("saleDate").value,
      customer_id: Number($("saleCustomerId").value || 0),
      warehouse_id: Number($("saleWarehouse").value || 0),
      currency: $("saleCurrency").value,
      exchange_rate: Number($("saleRate").value || 1),
      sale_type: $("saleType").value,
      discount_amount: Number($("saleDiscount").value || 0),
      shipping_fee: Number($("saleShipping").value || 0),
      paid_amount: Number($("salePaid").value || 0),
      lines: state.saleLines.map((l) => ({
        product_id: l.product_id,
        quantity: l.quantity,
        price: l.price,
        discount: l.discount || 0,
      })),
      ...extra,
    };
  }

  function purPayload(extra = {}) {
    return {
      supplier_id: Number($("purSupplierId").value || 0),
      supplier_invoice_no: $("purSupplierInv").value,
      date: $("purDate").value,
      warehouse_id: Number($("purWarehouse").value || 0),
      currency: $("purCurrency").value,
      exchange_rate: Number($("purRate").value || 1),
      purchase_mode: $("purMode").value,
      shipping_extra: Number($("purShipping").value || 0),
      customs_extra: Number($("purCustoms").value || 0),
      other_extra: Number($("purOther").value || 0),
      paid_amount: Number($("purPaid").value || 0),
      lines: state.purLines.map((l) => ({
        product_id: l.product_id,
        quantity: l.quantity,
        price: l.price,
        discount: l.discount || 0,
      })),
      ...extra,
    };
  }

  function scheduleAutosave() {
    clearTimeout(state.autosaveTimer);
    state.autosaveTimer = setTimeout(async () => {
      try {
        const op = state.op;
        const payload =
          op === "sale"
            ? salePayload()
            : op === "purchase"
            ? purPayload()
            : op === "receipt"
            ? {
                customer_id: Number($("rcpCustomerId").value || 0),
                amount: Number($("rcpAmount").value || 0),
              }
            : {
                supplier_id: Number($("paySupplierId").value || 0),
                amount: Number($("payAmount").value || 0),
              };
        await api("/drafts", {
          method: "POST",
          body: JSON.stringify({ op_type: op, payload, title: op + " autosave" }),
        });
      } catch (_) {
        /* silent autosave */
      }
    }, 2500);
  }

  async function loadCustomerBalance(kind) {
    const id = Number($(kind === "rcp" ? "rcpCustomerId" : "paySupplierId").value || 0);
    if (!id) return;
    if (kind === "rcp") {
      const data = await api(`/customers/${id}/balance`);
      $("rcpBalanceBefore").value = money(data.balance);
      $("rcpBalanceAfter").textContent = money(
        data.balance - Number($("rcpAmount").value || 0)
      );
      const tb = $("rcpInvoicesTable").querySelector("tbody");
      tb.innerHTML = (data.open_invoices || [])
        .map(
          (i) => `<tr>
          <td>${i.invoice_no || i.id}</td><td>${money(i.total)}</td><td>${money(i.remaining)}</td>
          <td><input type="number" class="rcp-alloc" data-id="${i.id}" value="0" max="${i.remaining}"></td>
        </tr>`
        )
        .join("");
    } else {
      const data = await api(`/suppliers/${id}/balance`);
      $("payBalanceBefore").value = money(data.balance);
      $("payBalanceAfter").textContent = money(
        data.balance - Number($("payAmount").value || 0)
      );
      const tb = $("payPurchasesTable").querySelector("tbody");
      tb.innerHTML = (data.open_purchases || [])
        .map(
          (p) => `<tr>
          <td>${p.invoice_no || p.id}</td><td>${money(p.grand_total)}</td><td>${money(p.remaining)}</td>
          <td><input type="number" class="pay-alloc" data-id="${p.id}" value="0" max="${p.remaining}"></td>
        </tr>`
        )
        .join("");
    }
  }

  async function init() {
    $("saleDate").value = today();
    $("rcpDate").value = today();
    $("purDate").value = today();
    $("payDate").value = today();

    state.ctx = await api("/context");
    fillSelect($("saleWarehouse"), state.ctx.warehouses, (w) => `<option value="${w.id}"${Number(w.id) === Number(state.ctx.default_warehouse_id) ? " selected" : ""}>${w.name}</option>`);
    fillSelect($("purWarehouse"), state.ctx.warehouses, (w) => `<option value="${w.id}"${Number(w.id) === Number(state.ctx.default_warehouse_id) ? " selected" : ""}>${w.name}</option>`);
    fillSelect(
      $("rcpTreasury"),
      [{ id: "", name: "— افتراضي —" }].concat(state.ctx.treasury_accounts || []),
      (t) => `<option value="${t.id}">${t.name}</option>`
    );
    fillSelect(
      $("payTreasury"),
      [{ id: "", name: "— افتراضي —" }].concat(state.ctx.treasury_accounts || []),
      (t) => `<option value="${t.id}">${t.name}</option>`
    );
    $("saleInvoiceNo").value = state.ctx.next_sale_no || "";
    $("saleRate").value = state.ctx.default_exchange_rate || 1;

    document.querySelectorAll(".ws-op-btn[data-op]").forEach((btn) => {
      btn.addEventListener("click", () => {
        showPanel(btn.dataset.op);
        const tab = state.tabs.find((t) => t.id === state.activeTab);
        if (tab) {
          tab.op = btn.dataset.op;
          tab.title = ({ sale: "بيع", receipt: "قبض", purchase: "شراء", payment: "تسديد" })[btn.dataset.op];
        }
        renderTabs();
      });
    });
    $("wsNewTab").addEventListener("click", () => {
      const id = state.tabs.length ? Math.max(...state.tabs.map((t) => t.id)) + 1 : 1;
      state.tabs.push({ id, op: state.op, title: "تبويب " + id });
      state.activeTab = id;
      renderTabs();
    });

    bindSuggest(
      $("saleCustomerQ"),
      $("saleCustomerSuggest"),
      async (q) => {
        const rows = await api("/customers/search?q=" + encodeURIComponent(q));
        return rows.map((c) => ({ id: c.id, label: `${c.name} — ${c.phone || ""}`, ...c }));
      },
      (c) => {
        $("saleCustomerId").value = c.id;
        $("saleCustomerQ").value = c.name;
      }
    );
    bindSuggest(
      $("rcpCustomerQ"),
      $("rcpCustomerSuggest"),
      async (q) => {
        const rows = await api("/customers/search?q=" + encodeURIComponent(q));
        return rows.map((c) => ({ id: c.id, label: `${c.name} (${money(c.balance)})`, ...c }));
      },
      async (c) => {
        $("rcpCustomerId").value = c.id;
        $("rcpCustomerQ").value = c.name;
        await loadCustomerBalance("rcp");
      }
    );
    bindSuggest(
      $("purSupplierQ"),
      $("purSupplierSuggest"),
      async (q) => {
        const rows = await api("/suppliers/search?q=" + encodeURIComponent(q));
        return rows.map((s) => ({ id: s.id, label: `${s.name}`, ...s }));
      },
      (s) => {
        $("purSupplierId").value = s.id;
        $("purSupplierQ").value = s.name;
      }
    );
    bindSuggest(
      $("paySupplierQ"),
      $("paySupplierSuggest"),
      async (q) => {
        const rows = await api("/suppliers/search?q=" + encodeURIComponent(q));
        return rows.map((s) => ({ id: s.id, label: `${s.name} (${money(s.balance)})`, ...s }));
      },
      async (s) => {
        $("paySupplierId").value = s.id;
        $("paySupplierQ").value = s.name;
        await loadCustomerBalance("pay");
      }
    );

    const productPick = (lines, recalc) => async (q) => {
      const wh = Number((state.op === "sale" ? $("saleWarehouse") : $("purWarehouse")).value || 0);
      const rows = await api(
        `/products/search?q=${encodeURIComponent(q)}&warehouse_id=${wh || ""}`
      );
      return rows.map((p) => ({
        id: p.id,
        label: `${p.name} — ${money(p.sale_price)} ${p.stock ? `| فعلي ${p.stock.on_hand} · محجوز ${p.stock.reserved} · متاح ${p.stock.available}` : ""}`,
        ...p,
      }));
    };

    bindSuggest($("saleProductQ"), $("saleProductSuggest"), productPick(), (p) => {
      state.saleLines.push({
        product_id: p.id,
        name: p.name,
        quantity: 1,
        price: p.sale_price,
        discount: 0,
        available_qty: p.available_qty,
        stock: p.stock,
        total: p.sale_price,
      });
      $("saleProductQ").value = "";
      recalcSale();
      scheduleAutosave();
    });
    bindSuggest($("purProductQ"), $("purProductSuggest"), productPick(), (p) => {
      state.purLines.push({
        product_id: p.id,
        name: p.name,
        quantity: 1,
        price: p.buy_price || 0,
        discount: 0,
        total: p.buy_price || 0,
      });
      $("purProductQ").value = "";
      recalcPur();
      scheduleAutosave();
    });

    $("saleCustomerAdd").addEventListener("click", async () => {
      const name = prompt("اسم العميل");
      if (!name) return;
      const phone = prompt("هاتف العميل", "07000000000");
      const c = await api("/customers", { method: "POST", body: JSON.stringify({ name, phone }) });
      $("saleCustomerId").value = c.id;
      $("saleCustomerQ").value = c.name;
      toast("تم إضافة العميل");
    });
    $("purSupplierAdd").addEventListener("click", async () => {
      const name = prompt("اسم المورد");
      if (!name) return;
      const s = await api("/suppliers", { method: "POST", body: JSON.stringify({ name }) });
      $("purSupplierId").value = s.id;
      $("purSupplierQ").value = s.name;
      toast("تم إضافة المورد");
    });

    ["saleDiscount", "saleShipping", "salePaid", "saleType"].forEach((id) => {
      $(id).addEventListener("input", () => {
        recalcSale();
        scheduleAutosave();
      });
    });
    ["purShipping", "purCustoms", "purOther", "purPaid", "purMode"].forEach((id) => {
      $(id).addEventListener("input", () => {
        recalcPur();
        scheduleAutosave();
      });
    });
    $("rcpAmount").addEventListener("input", () => {
      const before = Number(String($("rcpBalanceBefore").value).replace(/,/g, "")) || 0;
      $("rcpBalanceAfter").textContent = money(before - Number($("rcpAmount").value || 0));
    });
    $("payAmount").addEventListener("input", () => {
      const before = Number(String($("payBalanceBefore").value).replace(/,/g, "")) || 0;
      $("payBalanceAfter").textContent = money(before - Number($("payAmount").value || 0));
    });
    $("saleCurrency").addEventListener("change", () => {
      $("saleRate").value = $("saleCurrency").value === "USD" ? state.ctx.default_exchange_rate || 1500 : 1;
    });

    document.querySelectorAll("[data-sale-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const action = btn.dataset.saleAction;
          const confirm = action !== "draft";
          const data = await api("/sales", {
            method: "POST",
            body: JSON.stringify(salePayload({ confirm, draft: action === "draft" })),
          });
          toast(action === "draft" ? "تم حفظ المسودة" : "تم حفظ فاتورة البيع " + (data.invoice_no || ""));
          if (confirm) {
            state.saleLines = [];
            $("saleInvoiceNo").value = (await api("/context")).next_sale_no;
            recalcSale();
            if (action === "print") window.print();
          }
        } catch (e) {
          toast(e.message, true);
        }
      });
    });
    document.querySelectorAll("[data-pur-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const draft = btn.dataset.purAction === "draft";
          const data = await api("/purchases", {
            method: "POST",
            body: JSON.stringify(purPayload({ confirm: !draft, draft })),
          });
          toast(draft ? "مسودة شراء" : "تم اعتماد الشراء " + (data.invoice_no || ""));
          if (!draft) {
            state.purLines = [];
            recalcPur();
          }
        } catch (e) {
          toast(e.message, true);
        }
      });
    });
    $("rcpSave").addEventListener("click", async () => {
      try {
        const allocations = [];
        document.querySelectorAll(".rcp-alloc").forEach((inp) => {
          const amount = Number(inp.value || 0);
          if (amount > 0) allocations.push({ invoice_id: Number(inp.dataset.id), amount });
        });
        const data = await api("/receipts", {
          method: "POST",
          body: JSON.stringify({
            customer_id: Number($("rcpCustomerId").value || 0),
            amount: Number($("rcpAmount").value || 0),
            currency: $("rcpCurrency").value,
            exchange_rate: Number($("rcpRate").value || 1),
            treasury_account_id: Number($("rcpTreasury").value || 0) || null,
            payment_method: $("rcpMethod").value,
            date: $("rcpDate").value,
            note: $("rcpNote").value,
            allocate_fifo: $("rcpFifo").checked && !allocations.length,
            allocations,
          }),
        });
        toast("تم القبض — الرصيد: " + money(data.balance_after));
        await loadCustomerBalance("rcp");
      } catch (e) {
        toast(e.message, true);
      }
    });
    $("paySave").addEventListener("click", async () => {
      try {
        const allocations = [];
        document.querySelectorAll(".pay-alloc").forEach((inp) => {
          const amount = Number(inp.value || 0);
          if (amount > 0) allocations.push({ purchase_id: Number(inp.dataset.id), amount });
        });
        const data = await api("/payments", {
          method: "POST",
          body: JSON.stringify({
            supplier_id: Number($("paySupplierId").value || 0),
            amount: Number($("payAmount").value || 0),
            currency: $("payCurrency").value,
            exchange_rate: Number($("payRate").value || 1),
            treasury_account_id: Number($("payTreasury").value || 0) || null,
            payment_method: $("payMethod").value,
            date: $("payDate").value,
            note: $("payNote").value,
            allocate_fifo: $("payFifo").checked && !allocations.length,
            allocations,
          }),
        });
        toast("تم التسديد — الرصيد: " + money(data.balance_after));
        await loadCustomerBalance("pay");
      } catch (e) {
        toast(e.message, true);
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (state.op === "sale") document.querySelector('[data-sale-action="save"]').click();
      }
      if (e.key === "F2") {
        e.preventDefault();
        if (state.op === "sale") $("saleProductQ").focus();
        if (state.op === "purchase") $("purProductQ").focus();
      }
      if (e.ctrlKey && e.key.toLowerCase() === "n") {
        e.preventDefault();
        $("wsNewTab").click();
      }
    });

    showPanel(state.op);
    renderTabs();
    recalcSale();
    recalcPur();
  }

  init().catch((e) => toast(e.message || "تعذر تحميل مركز العمليات", true));
})();
