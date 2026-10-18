/**
 * Workspace Layout Director.
 *
 * Deterministic, responsive zone layout. Given the list of visible window
 * specs, it computes non-overlapping positions so:
 *   - document_viewer sits in the right column,
 *   - live_report / analysis sit in the left column,
 *   - secondary windows stack in the bottom band,
 *   - workflow_selector / approval_panel are centered modals.
 *
 * This overrides whatever absolute coordinates the backend sent, which is
 * what previously caused random overlapping windows.
 */
class WorkspaceLayoutDirector {
  constructor(getCanvasSize) {
    this.getCanvasSize = getCanvasSize;
    // window type -> { column, priority, pref }
    this.map = {
      courier_settlement_analysis: { zone: "left", priority: 1, pref: 640 },
      purchase_invoice_analysis: { zone: "left", priority: 1, pref: 650 },
      live_report: { zone: "left", priority: 2, pref: 220 },
      document_intelligence: { zone: "left", priority: 3, pref: 320 },
      courier_issues: { zone: "left", priority: 4, pref: 240 },
      order_details: { zone: "left", priority: 0, pref: 620 },

      document_viewer: { zone: "right", priority: 1, pref: 560 },
      assistant_notes: { zone: "right", priority: 2, pref: 220 },

      courier_rows: { zone: "bottom", priority: 1, pref: 260 },
      financial_preview: { zone: "bottom", priority: 2, pref: 260 },
      raw_table_preview: { zone: "bottom", priority: 3, pref: 260 },
      session_timeline: { zone: "bottom", priority: 4, pref: 200 },

      workflow_selector: { zone: "modal", priority: 1, pref: 260 },
      approval_panel: { zone: "modal", priority: 1, pref: 330 },
      employee_performance: { zone: "modal", priority: 0, pref: 680 },
      inventory_forensics: { zone: "modal", priority: 0, pref: 760 },
    };
  }

  _cfg(type) {
    return this.map[type] || { zone: "left", priority: 9, pref: 300 };
  }

  /**
   * @param {Array} windows  list of window specs ({id, type, ...})
   * @returns {Map<string, {x,y,width,height,z_index}>}
   */
  computeLayout(windows) {
    const { width: W, height: H } = this.getCanvasSize();
    const gap = 16;
    const topPad = 18;
    const result = new Map();

    // Narrow screens: single stacked column with scroll-ish spacing.
    const narrow = W < 900;

    const colW = narrow ? Math.max(260, W - 2 * gap) : Math.min(460, Math.round(W * 0.30));
    const rightW = narrow ? colW : Math.min(540, Math.round(W * 0.36));
    const leftX = gap;
    const rightX = narrow ? gap : W - rightW - gap;

    const visible = (windows || []).filter(
      (w) => w && w.type && (w.state || "open") !== "closed" && !w.hidden
    );

    const docWindow = visible.find((w) => w.type === "document_viewer");
    const reportWindow =
      visible.find((w) => w.type === "courier_settlement_analysis") ||
      visible.find((w) => w.type === "purchase_invoice_analysis") ||
      visible.find((w) => w.type === "live_report");
    const flowMode = docWindow && reportWindow;

    if (!narrow && flowMode) {
      const sidePad = 24;
      const top = 24;
      const bottomReserve = 128;
      let reportW = Math.min(600, Math.max(420, Math.round(W * 0.32)));
      let docW = Math.min(660, Math.max(460, Math.round(W * 0.36)));
      const minCenterGap = 250;
      const total = sidePad * 2 + reportW + docW + minCenterGap;
      if (total > W) {
        const scale = (W - sidePad * 2 - minCenterGap) / (reportW + docW);
        reportW = Math.max(340, Math.round(reportW * scale));
        docW = Math.max(360, Math.round(docW * scale));
      }
      const h = Math.max(360, Math.min(650, H - top - bottomReserve));
      result.set(reportWindow.id, {
        x: sidePad,
        y: top,
        width: reportW,
        height: h,
        z_index: 12,
      });
      result.set(docWindow.id, {
        x: W - docW - sidePad,
        y: top,
        width: docW,
        height: h,
        z_index: 12,
      });
      const aux = visible.filter((w) => w.id !== docWindow.id && w.id !== reportWindow.id);
      const orderWindow = aux.find((w) => w.type === "order_details");
      if (orderWindow) {
        const orderW = Math.min(680, Math.max(520, Math.round(W * 0.36)));
        const orderH = Math.min(690, Math.max(470, H - top - 96));
        result.set(orderWindow.id, {
          x: sidePad,
          y: top,
          width: orderW,
          height: orderH,
          z_index: 260,
        });
      }
      const rowsWindow = aux.find((w) => w.type === "courier_rows");
      if (rowsWindow) {
        const rowsW = Math.min(1160, Math.max(760, W - 160));
        const rowsH = Math.min(680, Math.max(440, H - 150));
        result.set(rowsWindow.id, {
          x: Math.round((W - rowsW) / 2),
          y: Math.max(56, Math.round((H - rowsH) / 2)),
          width: rowsW,
          height: rowsH,
          z_index: 220,
        });
      }
      const employeeWindow = aux.find((w) => w.type === "employee_performance");
      if (employeeWindow) {
        const employeeW = Math.min(1240, Math.max(860, W - 72));
        const employeeH = Math.min(760, Math.max(520, H - 92));
        result.set(employeeWindow.id, {
          x: Math.round((W - employeeW) / 2),
          y: Math.max(30, Math.round((H - employeeH) / 2) - 12),
          width: employeeW,
          height: employeeH,
          z_index: 1200,
        });
      }
      const approvalWindow = aux.find((w) => w.type === "approval_panel");
      if (approvalWindow) {
        const approvalW = Math.min(720, Math.max(600, Math.round(W * 0.39)));
        const approvalH = Math.min(560, Math.max(430, Math.round(H * 0.53)));
        result.set(approvalWindow.id, {
          x: Math.round((W - approvalW) / 2),
          y: Math.max(42, Math.round((H - approvalH) / 2) - 18),
          width: approvalW,
          height: approvalH,
          z_index: 1300,
        });
      }
      const remainingAux = aux.filter(
        (w) => w.id !== rowsWindow?.id
          && w.id !== orderWindow?.id
          && w.id !== employeeWindow?.id
          && w.id !== approvalWindow?.id
      );
      const auxW = Math.min(460, Math.max(340, Math.round(W * 0.24)));
      const auxH = Math.min(300, Math.max(220, Math.round(H * 0.32)));
      const auxX = Math.round(W / 2 - auxW / 2);
      const auxY = Math.max(top + 56, Math.round(H / 2 - auxH / 2));
      remainingAux.forEach((w, i) => {
        result.set(w.id, {
          x: auxX + i * 18,
          y: auxY + i * 22,
          width: auxW,
          height: auxH,
          z_index: 80 + i,
        });
      });
      return result;
    }

    const groups = { left: [], right: [], bottom: [], modal: [] };
    visible.forEach((w) => {
      const cfg = this._cfg(w.type);
      groups[cfg.zone].push({ w, cfg });
    });
    Object.keys(groups).forEach((z) =>
      groups[z].sort((a, b) => a.cfg.priority - b.cfg.priority)
    );

    if (narrow) {
      // Stack everything in one scrolling column, top to bottom.
      let y = topPad;
      const order = [...groups.left, ...groups.right, ...groups.bottom];
      order.forEach(({ w, cfg }, i) => {
        const h = Math.min(cfg.pref, 420);
        result.set(w.id, { x: leftX, y, width: colW, height: h, z_index: 10 + i });
        y += h + gap;
      });
      this._placeModals(groups.modal, result, W, H);
      return result;
    }

    const bottomBandH = groups.bottom.length ? 250 : 0;
    const columnBottom = H - (bottomBandH ? bottomBandH + gap : 0) - gap;
    const columnAvail = columnBottom - topPad;

    this._stackColumn(groups.left, result, leftX, colW, topPad, columnAvail, gap, 10);
    this._stackColumn(groups.right, result, rightX, rightW, topPad, columnAvail, gap, 10);

    // Bottom band: lay out horizontally across the center between columns.
    if (groups.bottom.length) {
      const bx = leftX + colW + gap;
      const bandW = rightX - bx - gap;
      const n = groups.bottom.length;
      const cellW = Math.max(240, Math.floor((bandW - gap * (n - 1)) / n));
      const by = H - bottomBandH - gap;
      groups.bottom.forEach(({ w }, i) => {
        result.set(w.id, {
          x: bx + i * (cellW + gap),
          y: by,
          width: cellW,
          height: bottomBandH,
          z_index: 9,
        });
      });
    }

    this._placeModals(groups.modal, result, W, H);
    return result;
  }

  _stackColumn(items, result, x, width, top, avail, gap, baseZ) {
    if (!items.length) return;
    const totalPref = items.reduce((s, it) => s + it.cfg.pref, 0);
    const totalGap = gap * (items.length - 1);
    const usable = avail - totalGap;
    const scale = totalPref > usable ? usable / totalPref : 1;
    let y = top;
    items.forEach(({ w, cfg }, i) => {
      const h = Math.max(140, Math.round(cfg.pref * scale));
      result.set(w.id, { x, y, width, height: h, z_index: baseZ + i });
      y += h + gap;
    });
  }

  _placeModals(items, result, W, H) {
    items.forEach(({ w, cfg }, i) => {
      const largeDashboard = ["employee_performance", "inventory_forensics"].includes(w.type);
      const width = largeDashboard
        ? Math.min(1400, Math.max(320, W - (W < 900 ? 24 : 72)))
        : Math.min(460, Math.round(W * 0.5));
      const height = largeDashboard
        ? Math.min(820, Math.max(420, H - (H < 650 ? 24 : 72)))
        : cfg.pref;
      result.set(w.id, {
        x: Math.round(W / 2 - width / 2),
        y: Math.max(12, Math.round(H / 2 - height / 2) + i * 24),
        width,
        height,
        z_index: (largeDashboard ? 1200 : 1000) + i,
      });
    });
  }
}

window.WorkspaceLayoutDirector = WorkspaceLayoutDirector;
