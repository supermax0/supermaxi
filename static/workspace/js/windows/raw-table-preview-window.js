const RawTablePreviewWindow = {
  render(container, spec) {
    const props = spec.props || {};
    const tables = props.tables || [];
    const maxRows = props.maxRows || 100;
    container.innerHTML = "";

    const root = document.createElement("div");
    root.className = "ws-raw-table-preview";

    const disclaimer = document.createElement("p");
    disclaimer.className = "ws-doc-intel-disclaimer";
    disclaimer.textContent =
      props.disclaimer || "جداول خام — بدون تفسير أو ترحيل.";
    root.appendChild(disclaimer);

    if (!tables.length) {
      root.appendChild(document.createTextNode("لا توجد جداول مستخرجة بعد."));
      container.appendChild(root);
      return;
    }

    tables.forEach((tbl, tIdx) => {
      const block = document.createElement("div");
      block.className = "ws-raw-table-block";

      const meta = document.createElement("p");
      meta.className = "ws-raw-table-meta";
      meta.textContent = `جدول ${tbl.index ?? tIdx} | صفحة ${tbl.page ?? "—"} | ثقة ${tbl.confidence ?? "—"} | ${tbl.method || "—"}`;
      block.appendChild(meta);

      const tableEl = document.createElement("table");
      tableEl.className = "ws-raw-table";
      const rows = (tbl.rows || []).slice(0, maxRows);
      rows.forEach((row) => {
        const tr = document.createElement("tr");
        (row || []).forEach((cell) => {
          const td = document.createElement("td");
          td.textContent = cell != null ? String(cell) : "";
          tr.appendChild(td);
        });
        tableEl.appendChild(tr);
      });
      block.appendChild(tableEl);

      if ((tbl.rows || []).length > maxRows) {
        const more = document.createElement("p");
        more.className = "ws-raw-table-more";
        more.textContent = `يُعرض ${maxRows} صفاً من ${tbl.rows.length}`;
        block.appendChild(more);
      }

      root.appendChild(block);
    });

    container.appendChild(root);
  },

  patchFromEvent(container, payload) {
    const spec = JSON.parse(container.closest(".ws-window")?.dataset.spec || "{}");
    const props = { ...(spec.props || {}) };
    if (payload.tables) props.tables = payload.tables;
    RawTablePreviewWindow.render(container, { ...spec, props });
  },
};

window.RawTablePreviewWindow = RawTablePreviewWindow;
