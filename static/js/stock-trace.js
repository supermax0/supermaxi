(function () {
  "use strict";

  let modal = null;
  let traceMap = null;
  let lastFocus = null;

  function text(value, fallback) {
    const result = String(value == null ? "" : value).trim();
    return result || fallback || "—";
  }

  function formatDate(value) {
    if (!value) return "بدون تاريخ محفوظ";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return text(value);
    return window.FinoraTime.format(parsed, {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit"
    });
  }

  function branchList(rows, emptyLabel) {
    if (!Array.isArray(rows) || !rows.length) return emptyLabel;
    return rows.map((row) => `${text(row.name)} (${Number(row.quantity || 0).toLocaleString("ar-IQ")})`).join("، ");
  }

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value != null) node.textContent = value;
    return node;
  }

  function ensureModal() {
    if (modal) return modal;
    modal = element("div", "stock-trace-modal");
    modal.hidden = true;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "stockTraceTitle");

    const backdrop = element("div", "stock-trace-modal__backdrop");
    backdrop.addEventListener("click", close);
    const dialog = element("div", "stock-trace-modal__dialog");
    const header = element("header", "stock-trace-modal__header");
    const heading = element("div");
    heading.appendChild(element("div", "stock-trace-modal__eyebrow", "تفاصيل حركة المخزون"));
    const title = element("h2", "stock-trace-modal__title", "مسار مخزون الطلب");
    title.id = "stockTraceTitle";
    heading.appendChild(title);
    heading.appendChild(element("p", "stock-trace-modal__subtitle", "كل عملية خصم أو إرجاع مع الفرع والكمية"));
    const closeButton = element("button", "stock-trace-modal__close", "×");
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", "إغلاق");
    closeButton.addEventListener("click", close);
    header.append(heading, closeButton);
    const body = element("div", "stock-trace-modal__body");
    body.id = "stockTraceBody";
    dialog.append(header, body);
    modal.append(backdrop, dialog);
    document.body.appendChild(modal);
    return modal;
  }

  function summaryCard(label, value) {
    const card = element("div", "stock-trace-summary__card");
    card.append(element("span", "stock-trace-summary__label", label));
    card.append(element("strong", "stock-trace-summary__value", value));
    return card;
  }

  function renderEvent(event) {
    const eventKind = event.kind === "return"
      ? "return"
      : event.kind === "transfer"
        ? "transfer"
        : event.kind === "correction"
          ? "correction"
          : "out";
    const row = element("div", `stock-trace-event stock-trace-event--${eventKind}`);
    const kind = element("div", "stock-trace-event__kind", `${text(event.label)} — ${Number(event.quantity || 0).toLocaleString("ar-IQ")}`);
    const route = element("div", "stock-trace-event__route");
    route.append(element("strong", "", text(event.from)));
    route.append(element("span", "stock-trace-event__arrow", "←"));
    route.append(element("strong", "", text(event.to)));
    const savedLabel = event.recorded === false ? " · بيانات قديمة مستنتجة" : "";
    const meta = element("div", "stock-trace-event__meta", formatDate(event.at) + savedLabel);
    row.append(kind, route, meta);
    return row;
  }

  function renderLine(line) {
    const card = element("section", "stock-trace-line");
    const header = element("div", "stock-trace-line__header");
    const name = element("div", "stock-trace-line__name", text(line.product_name, "منتج"));
    const qty = element("span", "stock-trace-line__qty", `كمية الطلب: ${Number(line.ordered_quantity || 0).toLocaleString("ar-IQ")}`);
    header.append(name, qty);
    card.appendChild(header);
    const events = element("div", "stock-trace-events");
    if (Array.isArray(line.events) && line.events.length) {
      line.events.forEach((event) => events.appendChild(renderEvent(event)));
    } else {
      events.appendChild(element("div", "stock-trace-empty", "هذا المنتج لم يُخصم من المخزون حتى الآن."));
    }
    card.appendChild(events);
    return card;
  }

  function open(trace, trigger) {
    if (!trace) return;
    const root = ensureModal();
    const body = root.querySelector("#stockTraceBody");
    const title = root.querySelector("#stockTraceTitle");
    body.replaceChildren();
    title.textContent = `مسار مخزون الطلب #${text(trace.order_id)}`;

    const summary = element("div", "stock-trace-summary");
    summary.append(
      summaryCard("إجمالي الكمية", Number(trace.ordered_units || 0).toLocaleString("ar-IQ")),
      summaryCard("خرجت من", branchList(trace.source_branches, "لم يُخصم بعد")),
      summaryCard("الوجهة", text(trace.destination)),
      summaryCard("رجعت إلى", branchList(trace.return_branches, "لا يوجد إرجاع"))
    );
    body.appendChild(summary);
    const lines = element("div", "stock-trace-lines");
    if (Array.isArray(trace.lines) && trace.lines.length) {
      trace.lines.forEach((line) => lines.appendChild(renderLine(line)));
    } else {
      lines.appendChild(element("div", "stock-trace-empty", "لا توجد منتجات مخزنية داخل هذا الطلب."));
    }
    body.appendChild(lines);

    lastFocus = trigger || document.activeElement;
    root.hidden = false;
    document.body.style.overflow = "hidden";
    root.querySelector(".stock-trace-modal__close").focus();
  }

  function close() {
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    document.body.style.overflow = "";
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
  }

  function createButton(trace, options) {
    const wrap = element("div", "stock-trace-cell");
    const showLabel = !options || options.showLabel !== false;
    if (showLabel) wrap.appendChild(element("span", "stock-trace-cell__label", text(trace && trace.summary_label, "لا توجد حركة")));
    const button = element("button", "stock-trace-help", "؟");
    button.type = "button";
    button.title = "عرض تفاصيل خروج ورجوع الكميات";
    button.setAttribute("aria-label", `عرض تفاصيل حركة مخزون الطلب ${trace && trace.order_id ? trace.order_id : ""}`);
    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      open(trace, button);
    });
    wrap.appendChild(button);
    return wrap;
  }

  function loadTraceMap() {
    if (traceMap) return traceMap;
    const source = document.getElementById("stockTraceMap");
    if (!source) return {};
    try { traceMap = JSON.parse(source.textContent || "{}"); }
    catch (error) { traceMap = {}; }
    return traceMap;
  }

  document.addEventListener("click", function (event) {
    const trigger = event.target.closest("[data-stock-trace-order]");
    if (!trigger) return;
    event.preventDefault();
    event.stopPropagation();
    const map = loadTraceMap();
    const trace = map[String(trigger.getAttribute("data-stock-trace-order"))];
    open(trace, trigger);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") close();
  });

  window.StockTraceUI = { open, close, createButton };
})();
