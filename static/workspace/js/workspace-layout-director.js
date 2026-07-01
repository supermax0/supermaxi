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
      live_report: { zone: "left", priority: 2, pref: 220 },
      document_intelligence: { zone: "left", priority: 3, pref: 320 },
      courier_issues: { zone: "left", priority: 4, pref: 240 },

      document_viewer: { zone: "right", priority: 1, pref: 560 },
      assistant_notes: { zone: "right", priority: 2, pref: 220 },

      courier_rows: { zone: "bottom", priority: 1, pref: 260 },
      financial_preview: { zone: "bottom", priority: 2, pref: 260 },
      raw_table_preview: { zone: "bottom", priority: 3, pref: 260 },
      session_timeline: { zone: "bottom", priority: 4, pref: 200 },

      workflow_selector: { zone: "modal", priority: 1, pref: 260 },
      approval_panel: { zone: "modal", priority: 1, pref: 240 },
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
      const width = Math.min(460, Math.round(W * 0.5));
      const height = cfg.pref;
      result.set(w.id, {
        x: Math.round(W / 2 - width / 2),
        y: Math.round(H / 2 - height / 2) + i * 24,
        width,
        height,
        z_index: 1000 + i,
      });
    });
  }
}

window.WorkspaceLayoutDirector = WorkspaceLayoutDirector;
