/**
 * Courier settlement analysis report window — polished LEON UI.
 * Read-only: no posting. Renders stat cards, donut, bar chart,
 * issues table, and a profit/loss preview.
 */
const CourierSettlementAnalysisWindow = {
  render(container, spec, handlers = {}) {
    const p = spec.props || {};
    const s = p.summary || p;

    const totalRows = s.total_rows ?? p.totalRows ?? 0;
    const matched = s.matched_rows ?? p.matchedRows ?? 0;
    const review = s.review_rows ?? p.reviewRows ?? 0;
    const unmatched = s.unmatched_rows ?? p.unmatchedRows ?? 0;
    const collected = s.total_collected_amount ?? p.totalCollected ?? 0;
    const fees = s.total_delivery_fees ?? p.totalFees ?? 0;
    const financialPreview = s.financial_preview || p.financial_preview || (s.summary && s.summary.financial_preview) || {};
    const posting = p.posting || (s.summary && s.summary.posting) || {};
    const safeToPost = financialPreview.safe_to_post_rows ?? p.safeToPostRows ?? matched;
    const isPosted = posting.status === "posted" || s.status === "posted";
    const expectedFees = s.expected_delivery_fees ?? p.expectedFees ?? Math.round(fees * 0.8);
    const feeDiff = Math.abs(fees - expectedFees);
    const issues = p.issues || [];

    const profit = p.profit || {};
    const totalProfit = profit.total_profit ?? null;
    const totalLoss = profit.total_loss ?? null;
    const netProfit = profit.net_profit ?? (s.expected_net_amount ?? p.expectedNet ?? null);
    const avgProfit = profit.avg_profit ?? (matched ? Math.round((netProfit || 0) / matched) : null);

    container.innerHTML = `
      <div class="ws-report">
        <div class="ws-stat-row">
          ${this._stat("green", "\u2713", collected != null ? this._fmt(collected) : "\u2014", "\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0645\u0628\u0644\u063a")}
          ${this._stat("blue", "\u2691", matched, "\u0627\u0644\u0637\u0644\u0628\u0627\u062a \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629")}
          ${this._stat("amber", "!", unmatched, "\u063a\u064a\u0631 \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629")}
          ${this._stat("violet", "\u25a4", totalRows, "\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0637\u0644\u0628\u0627\u062a")}
          ${this._stat("violet", "\u2609", this._fmt(fees), "\u0623\u062c\u0648\u0631 \u0627\u0644\u062a\u0648\u0635\u064a\u0644")}
        </div>

        <div class="ws-section-grid">
          <div class="ws-section">
            <h4 class="ws-section-title">\u0645\u0644\u062e\u0635 \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629</h4>
            ${this._donut(totalRows, matched, review, unmatched)}
          </div>
          <div class="ws-section">
            <h4 class="ws-section-title">\u0623\u062c\u0648\u0631 \u0627\u0644\u062a\u0648\u0635\u064a\u0644</h4>
            ${this._bars(expectedFees, fees, feeDiff)}
          </div>
        </div>

        <div class="ws-section">
          <h4 class="ws-section-title">\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0645\u0634\u0627\u0643\u0644</h4>
          ${this._issuesTable(issues)}
        </div>

        <div class="ws-section">
          <h4 class="ws-section-title">\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0623\u0631\u0628\u0627\u062d \u0648\u0627\u0644\u062e\u0633\u0627\u0626\u0631</h4>
          <div class="ws-profit-row">
            <div class="ws-profit green">
              <span class="ws-profit-label">\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0623\u0631\u0628\u0627\u062d</span>
              <span class="ws-profit-value">${this._fmt(totalProfit)}</span>
              <span class="ws-profit-sub">\u062f.\u0639</span>
            </div>
            <div class="ws-profit red">
              <span class="ws-profit-label">\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u062e\u0633\u0627\u0626\u0631</span>
              <span class="ws-profit-value">${totalLoss != null ? "-" + this._fmt(totalLoss) : "\u2014"}</span>
              <span class="ws-profit-sub">\u062f.\u0639</span>
            </div>
            <div class="ws-profit blue">
              <span class="ws-profit-label">\u0635\u0627\u0641\u064a \u0627\u0644\u0631\u0628\u062d</span>
              <span class="ws-profit-value">${this._fmt(netProfit)}</span>
              <span class="ws-profit-sub">\u062f.\u0639</span>
            </div>
            <div class="ws-profit violet">
              <span class="ws-profit-label">\u0645\u062a\u0648\u0633\u0637 \u0631\u0628\u062d \u0627\u0644\u0637\u0644\u0628</span>
              <span class="ws-profit-value">${this._fmt(avgProfit)}</span>
              <span class="ws-profit-sub">\u062f.\u0639</span>
            </div>
          </div>
        </div>

        <div class="ws-report-actions">
          <button type="button" class="ws-btn ws-btn-primary" data-act="settle" ${safeToPost > 0 && !isPosted ? "" : "disabled"}>${isPosted ? "\u062a\u0645 \u0627\u0644\u062a\u0646\u0641\u064a\u0630" : "\u062a\u0646\u0641\u064a\u0630 \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u0627\u0644\u0633\u0644\u064a\u0645\u0629"} (${safeToPost})</button>
          <button type="button" class="ws-btn ws-btn-ghost" data-act="export">\u062a\u0635\u062f\u064a\u0631 \u0627\u0644\u062a\u0642\u0631\u064a\u0631</button>
          <button type="button" class="ws-btn ws-btn-ghost" data-act="more">\u2807 \u0625\u062c\u0631\u0627\u0621\u0627\u062a \u0623\u062e\u0631\u0649</button>
        </div>
        <p class="ws-readonly-note">${isPosted ? "\u062a\u0645 \u062a\u0646\u0641\u064a\u0630 \u0627\u0644\u0635\u0641\u0648\u0641 \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629 \u0627\u0644\u0633\u0644\u064a\u0645\u0629 \u0641\u0642\u0637\u060c \u0648\u0628\u0642\u064a\u062a \u0628\u0627\u0642\u064a \u0627\u0644\u0635\u0641\u0648\u0641 \u0644\u0644\u0645\u0631\u0627\u062c\u0639\u0629." : "\u0627\u0644\u062a\u0646\u0641\u064a\u0630 \u064a\u0645\u0631 \u0639\u0628\u0631 \u0645\u0648\u0627\u0641\u0642\u0629 \u0635\u0631\u064a\u062d\u0629 \u0648\u064a\u0634\u0645\u0644 \u0627\u0644\u0635\u0641\u0648\u0641 \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629 \u0628\u0644\u0627 \u0645\u0634\u0627\u0643\u0644 \u062d\u0631\u062c\u0629 \u0641\u0642\u0637."}</p>
      </div>`;

    const exportBtn = container.querySelector('[data-act="export"]');
    if (exportBtn && handlers.onExport) {
      exportBtn.addEventListener("click", () => handlers.onExport(spec));
    }
    const settleBtn = container.querySelector('[data-act="settle"]');
    if (settleBtn && handlers.onSettle && !settleBtn.disabled) {
      settleBtn.addEventListener("click", () => handlers.onSettle(spec));
    }
  },

  _stat(color, icon, value, label) {
    return `
      <div class="ws-stat">
        <span class="ws-stat-ico ${color}">${icon}</span>
        <span class="ws-stat-value">${value ?? "\u2014"}</span>
        <span class="ws-stat-label">${label}</span>
      </div>`;
  },

  _donut(total, matched, review, unmatched) {
    const segs = [
      { val: matched, color: "#22b573", label: "\u0645\u0637\u0627\u0628\u0642\u0629 \u0628\u062f\u0648\u0646 \u0645\u0634\u0627\u0643\u0644" },
      { val: review, color: "#f5a524", label: "\u062a\u062d\u062a\u0627\u062c \u0645\u0631\u0627\u062c\u0639\u0629" },
      { val: unmatched, color: "#ef4d5c", label: "\u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f\u0629 \u0641\u064a \u0627\u0644\u0646\u0638\u0627\u0645" },
    ];
    const sum = segs.reduce((a, b) => a + (b.val || 0), 0) || 1;
    const r = 52;
    const c = 2 * Math.PI * r;
    let offset = 0;
    const circles = segs
      .map((seg) => {
        const frac = (seg.val || 0) / sum;
        const len = frac * c;
        const dash = `${len} ${c - len}`;
        const circle = `<circle cx="65" cy="65" r="${r}" fill="none" stroke="${seg.color}" stroke-width="16" stroke-dasharray="${dash}" stroke-dashoffset="${-offset}" stroke-linecap="butt"></circle>`;
        offset += len;
        return circle;
      })
      .join("");

    const legend = segs
      .map((seg) => {
        const pct = Math.round(((seg.val || 0) / sum) * 100);
        return `
        <div class="ws-legend-item">
          <span class="ws-legend-dot" style="background:${seg.color}"></span>
          <span>${seg.label}</span>
          <span class="ws-legend-val">${seg.val || 0} (${pct}%)</span>
        </div>`;
      })
      .join("");

    return `
      <div class="ws-donut-wrap">
        <div class="ws-donut">
          <svg width="130" height="130" viewBox="0 0 130 130">
            <circle cx="65" cy="65" r="${r}" fill="none" stroke="#eef1f8" stroke-width="16"></circle>
            ${circles}
          </svg>
          <div class="ws-donut-center"><strong>${total}</strong><span>\u0637\u0644\u0628</span></div>
        </div>
        <div class="ws-legend">${legend}</div>
      </div>`;
  },

  _bars(expected, computed, diff) {
    const max = Math.max(expected, computed, diff, 1);
    const h = (v) => `${Math.max(6, Math.round((v / max) * 120))}px`;
    return `
      <div class="ws-bars">
        <div class="ws-bar-col">
          <span class="ws-bar-value">${this._fmtShort(expected)}</span>
          <div class="ws-bar expected" style="height:${h(expected)}"></div>
          <span class="ws-bar-label">\u0627\u0644\u0645\u062a\u0648\u0642\u0639</span>
        </div>
        <div class="ws-bar-col">
          <span class="ws-bar-value">${this._fmtShort(computed)}</span>
          <div class="ws-bar computed" style="height:${h(computed)}"></div>
          <span class="ws-bar-label">\u0627\u0644\u0645\u062d\u062a\u0633\u0628</span>
        </div>
        <div class="ws-bar-col">
          <span class="ws-bar-value">${this._fmtShort(diff)}</span>
          <div class="ws-bar diff" style="height:${h(diff)}"></div>
          <span class="ws-bar-label">\u0627\u0644\u0641\u0631\u0642</span>
        </div>
      </div>`;
  },

  _issuesTable(issues) {
    if (!issues || !issues.length) {
      return `<p style="color:#7c869c;font-size:12.5px;margin:0">\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0634\u0627\u0643\u0644 \u062c\u0648\u0647\u0631\u064a\u0629 \u2014 \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u0633\u0644\u064a\u0645\u0629.</p>`;
    }
    const rows = issues
      .slice(0, 8)
      .map((i) => {
        const badge = this._sevBadge(i.severity);
        const order = (i.details && (i.details.order_number || i.details.invoice_id)) || "\u2014";
        return `
        <tr>
          <td>${badge}</td>
          <td>${this._esc(i.message || i.issue_type || "")}</td>
          <td>${this._esc(String(order))}</td>
        </tr>`;
      })
      .join("");
    return `
      <table class="ws-issues-table">
        <thead><tr><th>\u0646\u0648\u0639 \u0627\u0644\u0645\u0634\u0643\u0644\u0629</th><th>\u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644</th><th>\u0631\u0642\u0645 \u0627\u0644\u0637\u0644\u0628</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  },

  _sevBadge(sev) {
    const map = {
      critical: ["red", "\u062d\u0631\u062c"],
      error: ["red", "\u062e\u0637\u0623"],
      warning: ["amber", "\u062a\u062d\u0630\u064a\u0631"],
      info: ["violet", "\u0645\u0639\u0644\u0648\u0645\u0629"],
    };
    const [cls, label] = map[sev] || ["violet", sev || "\u2014"];
    return `<span class="ws-badge ${cls}">${label}</span>`;
  },

  _fmt(n) {
    if (n == null) return "\u2014";
    return Number(n).toLocaleString("en-US");
  },

  _fmtShort(n) {
    if (n == null) return "\u2014";
    const v = Number(n);
    if (v >= 1000) return (v / 1000).toFixed(v % 1000 === 0 ? 0 : 1) + "K";
    return String(v);
  },

  _esc(text) {
    const d = document.createElement("div");
    d.textContent = text || "";
    return d.innerHTML;
  },

  patchFromEvent(container, payload) {
    const spec = JSON.parse(container.closest(".ws-window")?.dataset.spec || "{}");
    const props = { ...(spec.props || {}), ...payload };
    if (payload.summary) props.summary = { ...(props.summary || {}), ...payload.summary };
    if (payload.issues) props.issues = payload.issues;
    CourierSettlementAnalysisWindow.render(container, { ...spec, props });
  },
};

window.CourierSettlementAnalysisWindow = CourierSettlementAnalysisWindow;
