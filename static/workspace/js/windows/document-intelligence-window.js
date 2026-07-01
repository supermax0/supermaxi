const KIND_LABELS = {
  courier_settlement: "كشف تسديد شركة توصيل",
  return_statement: "كشف راجع",
  purchase_invoice: "فاتورة شراء",
  unknown_document: "مستند غير معروف",
};

const DocumentIntelligenceWindow = {
  render(container, spec) {
    const props = spec.props || {};
    container.innerHTML = "";
    const root = document.createElement("div");
    root.className = "ws-doc-intel";

    const disclaimer = document.createElement("p");
    disclaimer.className = "ws-doc-intel-disclaimer";
    disclaimer.textContent =
      props.disclaimer ||
      "هذه قراءة أولية للمستند فقط. لم يتم تنفيذ أي ترحيل أو تعديل على البيانات.";
    root.appendChild(disclaimer);

    root.appendChild(this._row("نوع المستند", props.kindLabel || KIND_LABELS[props.documentKind] || "—"));
    root.appendChild(this._confidenceRow(props.confidence));
    root.appendChild(this._row("حالة الاستخراج", props.status || spec.status || "—"));

    const signals = props.signals || [];
    const sigBlock = document.createElement("div");
    sigBlock.className = "ws-doc-intel-section";
    sigBlock.innerHTML = "<h4>الإشارات</h4>";
    if (!signals.length) {
      sigBlock.appendChild(document.createTextNode("لا توجد إشارات بعد"));
    } else {
      const ul = document.createElement("ul");
      ul.className = "ws-doc-intel-signals";
      signals.forEach((s) => {
        const li = document.createElement("li");
        li.textContent = s;
        ul.appendChild(li);
      });
      sigBlock.appendChild(ul);
    }
    root.appendChild(sigBlock);

    const ext = props.extractionSummary || {};
    const methods = document.createElement("div");
    methods.className = "ws-doc-intel-section";
    methods.innerHTML = `<h4>ملخص الاستخراج</h4>
      <p class="ws-doc-intel-meta">نص: ${ext.textStatus || "—"} | جداول: ${ext.tablesStatus || "—"}</p>`;
    root.appendChild(methods);

    const sampleBlock = document.createElement("div");
    sampleBlock.className = "ws-doc-intel-section";
    sampleBlock.innerHTML = "<h4>عينة النص</h4>";
    const pre = document.createElement("pre");
    pre.className = "ws-doc-intel-sample";
    pre.textContent = props.textSample || "—";
    sampleBlock.appendChild(pre);
    if (props.textSample) {
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "ws-btn ws-btn-ghost ws-doc-intel-copy";
      copyBtn.textContent = "نسخ العينة";
      copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(props.textSample).catch(() => {});
      });
      sampleBlock.appendChild(copyBtn);
    }
    root.appendChild(sampleBlock);

    const warnings = props.warnings || [];
    if (warnings.length || props.error) {
      const warnBlock = document.createElement("div");
      warnBlock.className = "ws-doc-intel-section ws-doc-intel-warnings";
      warnBlock.innerHTML = "<h4>تحذيرات</h4>";
      const ul = document.createElement("ul");
      [...warnings, props.error].filter(Boolean).forEach((w) => {
        const li = document.createElement("li");
        li.textContent = w;
        ul.appendChild(li);
      });
      warnBlock.appendChild(ul);
      root.appendChild(warnBlock);
    }

    container.appendChild(root);
  },

  _row(label, value) {
    const row = document.createElement("div");
    row.className = "ws-doc-intel-row";
    row.innerHTML = `<span class="ws-doc-intel-label">${label}</span><span class="ws-doc-intel-value">${value}</span>`;
    return row;
  },

  _confidenceRow(confidence) {
    const pct = confidence != null ? Math.round(Number(confidence) * 100) : null;
    const row = document.createElement("div");
    row.className = "ws-doc-intel-row";
    row.innerHTML = `<span class="ws-doc-intel-label">الثقة</span>`;
    const badge = document.createElement("span");
    badge.className = "ws-confidence-badge";
    if (pct == null) {
      badge.textContent = "—";
    } else {
      badge.textContent = `${pct}%`;
      if (pct >= 70) badge.classList.add("ws-confidence-high");
      else if (pct >= 55) badge.classList.add("ws-confidence-mid");
      else badge.classList.add("ws-confidence-low");
    }
    row.appendChild(badge);
    return row;
  },

  patchFromEvent(container, payload) {
    const spec = JSON.parse(container.closest(".ws-window")?.dataset.spec || "{}");
    const props = { ...(spec.props || {}) };
    if (payload.kind) {
      props.documentKind = payload.kind;
      props.kindLabel = payload.kindLabel || KIND_LABELS[payload.kind];
    }
    if (payload.confidence != null) props.confidence = payload.confidence;
    if (payload.signals) props.signals = payload.signals;
    if (payload.text_sample) props.textSample = payload.text_sample;
    if (payload.status) props.status = payload.status;
    if (payload.error) props.error = payload.error;
    if (payload.result) Object.assign(props, payload.result);
    DocumentIntelligenceWindow.render(container, { ...spec, props });
  },
};

window.DocumentIntelligenceWindow = DocumentIntelligenceWindow;
