/**
 * Floating window manager for workspace.
 */
class WorkspaceWindowManager {
  constructor(layerEl) {
    this.layer = layerEl;
    this.windows = new Map();
    this.layoutDirector = null;
    this._layout = new Map();
    this._lastSpecs = [];
    this._manualGeometry = new Map();
    this._expandedRestore = new Map();
    this._documentScanState = null;
    this.workflowHandlers = {};
    this.renderers = {
      document_viewer: DocumentViewerWindow,
      live_report: LiveReportWindow,
      assistant_notes: AssistantNotesWindow,
      approval_panel: ApprovalPanelWindow,
      workflow_selector: WorkflowSelectorWindow,
      session_timeline: SessionTimelineWindow,
      document_intelligence: DocumentIntelligenceWindow,
      raw_table_preview: RawTablePreviewWindow,
      courier_settlement_analysis: CourierSettlementAnalysisWindow,
      courier_rows: CourierRowsWindow,
      courier_issues: CourierIssuesWindow,
      financial_preview: FinancialPreviewWindow,
      order_details: OrderDetailsWindow,
      employee_performance: EmployeePerformanceWindow,
      purchase_invoice_analysis: PurchaseInvoiceAnalysisWindow,
      inventory_forensics: InventoryForensicsWindow,
    };
    this.courierHandlers = {};
  }

  setCourierHandlers(handlers) {
    this.courierHandlers = handlers || {};
  }

  setWorkflowHandlers(handlers) {
    this.workflowHandlers = handlers || {};
  }

  setLayoutDirector(director) {
    this.layoutDirector = director;
  }

  _identity(spec) {
    const p = spec.props || {};
    const key = p.analysisId || p.documentId || "";
    return `${spec.type}::${key}`;
  }

  /** Drop closed/hidden windows and de-duplicate by identity (singleton). */
  _normalize(windowsList) {
    const byIdentity = new Map();
    (windowsList || []).forEach((spec) => {
      if (!spec || !spec.type) return;
      if ((spec.state || "open") === "closed" || spec.hidden) return;
      byIdentity.set(this._identity(spec), spec);
    });
    return [...byIdentity.values()];
  }

  renderWindows(windowsList) {
    const specs = this._normalize(windowsList);
    this._lastSpecs = specs;
    if (this.layoutDirector) {
      this._layout = this.layoutDirector.computeLayout(specs);
    }
    const ids = new Set(specs.map((w) => w.id));
    this.windows.forEach((_, id) => {
      if (!ids.has(id)) this.closeWindow(id);
    });
    specs.forEach((spec) => this.openOrUpdateWindow(spec));
  }

  /** Recompute zones and reposition existing windows (e.g. on resize). */
  relayout() {
    if (!this.layoutDirector || !this._lastSpecs.length) return;
    this._layout = this.layoutDirector.computeLayout(this._lastSpecs);
    this._lastSpecs.forEach((spec) => {
      const el = this.windows.get(spec.id);
      if (el) this._applyPosition(el, spec);
    });
  }

  openOrUpdateWindow(spec) {
    let el = this.windows.get(spec.id);
    if (!el) {
      el = this._createShell(spec);
      this.windows.set(spec.id, el);
      this.layer.appendChild(el);
    }
    this._applyPosition(el, spec);
    this._updateShell(el, spec);
    this._renderBody(el, spec);
  }

  openWindow(spec) {
    if (!spec || (spec.state || "open") === "closed" || spec.hidden) return;
    const idx = this._lastSpecs.findIndex((s) => s.id === spec.id);
    if (idx >= 0) this._lastSpecs[idx] = spec;
    else this._lastSpecs.push(spec);
    this._lastSpecs = this._normalize(this._lastSpecs);
    if (this.layoutDirector) {
      this._layout = this.layoutDirector.computeLayout(this._lastSpecs);
    }
    this.openOrUpdateWindow(spec);
    this._lastSpecs.forEach((s) => {
      const el = this.windows.get(s.id);
      if (el) this._applyPosition(el, s);
    });
  }

  updateWindow(windowId, patch) {
    const el = this.windows.get(windowId);
    if (!el) return;
    const current = JSON.parse(el.dataset.spec || "{}");
    const merged = { ...current, ...patch, props: { ...(current.props || {}), ...(patch.props || {}) } };
    this.openOrUpdateWindow(merged);
  }

  updateTimelineItems(items) {
    const el = [...this.windows.entries()].find(([, node]) => {
      const spec = JSON.parse(node.dataset.spec || "{}");
      return spec.type === "session_timeline";
    });
    if (!el) return;
    const body = el[1].querySelector(".ws-window-body");
    SessionTimelineWindow.update(body, items);
  }

  focusWindow(windowId) {
    this.windows.forEach((el, id) => {
      el.classList.toggle("ws-window-focused", id === windowId);
      el.style.zIndex = id === windowId ? 100 : (JSON.parse(el.dataset.spec || "{}").z_index || 10);
    });
  }

  closeWindow(windowId) {
    const el = this.windows.get(windowId);
    if (el) {
      el.remove();
      this.windows.delete(windowId);
      this._manualGeometry.delete(windowId);
      this._expandedRestore.delete(windowId);
    }
  }

  applyEvent(event) {
    const type = event.type;
    const payload = event.payload || {};
    const eventId = event.id || event.event_id;

    if (type === "window.opened" && payload.window) {
      this.openWindow(payload.window);
    }
    if (type === "window.updated" && payload.windows) {
      this.renderWindows(payload.windows);
    }
    if (type === "report.appended" && payload.line) {
      const reportWin = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "live_report";
      });
      if (reportWin) {
        const body = reportWin[1].querySelector(".ws-window-body");
        const added = LiveReportWindow.appendLine(body, payload.line, eventId);
        if (added) {
          const spec = JSON.parse(reportWin[1].dataset.spec || "{}");
          spec.props = spec.props || {};
          spec.props.lines = spec.props.lines || [];
          spec.props.lines.push(payload.line);
          reportWin[1].dataset.spec = JSON.stringify(spec);
        }
      }
    }
    if (type === "document.scan.updated") {
      const previous = this._documentScanState || {};
      const active = payload.active === undefined
        ? !!previous.active
        : !!payload.active;
      const requestedProgress = Math.max(
        0,
        Math.min(100, Number(payload.progress ?? previous.progress ?? 0))
      );
      const progress = active && previous.active
        ? Math.max(Number(previous.progress || 0), requestedProgress)
        : requestedProgress;
      this._documentScanState = {
        ...previous,
        ...payload,
        active,
        progress,
        error: !!payload.error,
      };
      const docWindows = [...this.windows.entries()].filter(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "document_viewer";
      });
      docWindows.forEach(([, el]) => {
        const body = el.querySelector(".ws-window-body");
        DocumentViewerWindow.updateScan(body, this._documentScanState);
      });
    }
    if (type === "document.text.extracted" || type === "document.classified" || type === "document.intelligence.completed" || type === "document.intelligence.failed") {
      const intelWin = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "document_intelligence";
      });
      if (intelWin) {
        const body = intelWin[1].querySelector(".ws-window-body");
        DocumentIntelligenceWindow.patchFromEvent(body, payload);
      }
    }
    if (type === "document.tables.extracted") {
      const tblWin = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "raw_table_preview";
      });
      if (tblWin) {
        const body = tblWin[1].querySelector(".ws-window-body");
        RawTablePreviewWindow.patchFromEvent(body, payload);
      }
    }
    if (type === "courier.row.matched" && payload.row) {
      const analysisId = payload.analysisId;
      const rowsWin = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "courier_rows"
          && (!analysisId || (spec.props || {}).analysisId === analysisId);
      });
      if (rowsWin) {
        CourierRowsWindow.upsertLiveRow(
          rowsWin[1].querySelector(".ws-window-body"),
          payload.row,
          {
            processed: payload.processed,
            total: payload.total,
            counts: payload.counts || {},
          }
        );
      }

      const reportWin = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "courier_settlement_analysis"
          && (!analysisId || (spec.props || {}).analysisId === analysisId);
      });
      if (reportWin) {
        const counts = payload.counts || {};
        const totals = payload.totals || {};
        CourierSettlementAnalysisWindow.patchFromEvent(
          reportWin[1].querySelector(".ws-window-body"),
          {
            status: "matching",
            totalRows: payload.total || counts.all || 0,
            processedRows: payload.processed || 0,
            matchedRows: counts.matched || 0,
            reviewRows: counts.review || 0,
            unmatchedRows: counts.unmatched || 0,
            duplicateRows: counts.duplicate || 0,
            totalCollected: totals.collected || 0,
            totalFees: totals.fees || 0,
            expectedNet: totals.net || 0,
            streaming: true,
          }
        );
      }
    }
    if (type === "courier.financial_preview.ready") {
      const analysisId = payload.analysisId;
      const win = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "financial_preview"
          && (!analysisId || (spec.props || {}).analysisId === analysisId);
      });
      if (win) {
        FinancialPreviewWindow.patchFromEvent(win[1].querySelector(".ws-window-body"), payload);
      }
    }
    if (type === "courier.analysis.completed" && payload.summary) {
      const analysisId = payload.analysisId;
      const win = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "courier_settlement_analysis"
          && (!analysisId || (spec.props || {}).analysisId === analysisId);
      });
      if (win) {
        const currentSpec = JSON.parse(win[1].dataset.spec || "{}");
        const currentUpdatedAt = Date.parse(
          (currentSpec.props || {}).analysisUpdatedAt || ""
        );
        const eventUpdatedAt = Date.parse(payload.summary.updated_at || "");
        if (
          Number.isFinite(currentUpdatedAt)
          && Number.isFinite(eventUpdatedAt)
          && eventUpdatedAt < currentUpdatedAt
        ) {
          return;
        }
        CourierSettlementAnalysisWindow.patchFromEvent(
          win[1].querySelector(".ws-window-body"),
          payload
        );
      }
    }
  }

  _createShell(spec) {
    const el = document.createElement("div");
    el.className = "ws-window";
    el.dataset.windowId = spec.id;
    el.dataset.spec = JSON.stringify(spec);
    el.innerHTML = `
      <div class="ws-window-header">
        <h3 class="ws-window-title"></h3>
        <div class="ws-window-header-actions">
          <span class="ws-window-status"></span>
          <button type="button" class="ws-window-expand" title="تكبير النافذة" aria-label="تكبير النافذة">↗</button>
          <button type="button" class="ws-window-hide" title="إخفاء النافذة" hidden>&times;</button>
        </div>
      </div>
      <div class="ws-window-body"></div>
      <div class="ws-window-resize" title="اسحب لتغيير حجم النافذة" aria-hidden="true"></div>
    `;
    el.addEventListener("mousedown", () => this.focusWindow(spec.id));
    this._enableWindowInteractions(el, spec.id);
    return el;
  }

  _applyPosition(el, spec) {
    const manual = this._manualGeometry.get(spec.id);
    if (manual) {
      el.style.left = `${manual.x}px`;
      el.style.top = `${manual.y}px`;
      el.style.width = `${manual.width}px`;
      el.style.height = `${manual.height}px`;
      el.style.zIndex = spec.z_index ?? 90;
      return;
    }
    const zone = this._layout && this._layout.get(spec.id);
    const pos = zone || spec.position || {};
    el.style.left = `${pos.x ?? 40}px`;
    el.style.top = `${pos.y ?? 80}px`;
    el.style.width = `${pos.width ?? 360}px`;
    el.style.height = `${pos.height ?? 400}px`;
    el.style.zIndex = (zone && zone.z_index) ?? spec.z_index ?? 10;
  }

  _enableWindowInteractions(el, windowId) {
    const header = el.querySelector(".ws-window-header");
    const resizeHandle = el.querySelector(".ws-window-resize");
    const expandButton = el.querySelector(".ws-window-expand");

    const clampGeometry = (geometry) => {
      const bounds = this.layer.getBoundingClientRect();
      const maxWidth = Math.max(320, bounds.width - 24);
      const maxHeight = Math.max(220, bounds.height - 24);
      const width = Math.min(maxWidth, Math.max(320, geometry.width));
      const height = Math.min(maxHeight, Math.max(220, geometry.height));
      return {
        x: Math.min(Math.max(12, geometry.x), Math.max(12, bounds.width - width - 12)),
        y: Math.min(Math.max(12, geometry.y), Math.max(12, bounds.height - height - 12)),
        width,
        height,
      };
    };

    const currentGeometry = () => ({
      x: Number.parseFloat(el.style.left) || el.offsetLeft || 0,
      y: Number.parseFloat(el.style.top) || el.offsetTop || 0,
      width: el.offsetWidth,
      height: el.offsetHeight,
    });

    const applyManual = (geometry) => {
      const next = clampGeometry(geometry);
      this._manualGeometry.set(windowId, next);
      el.style.left = `${next.x}px`;
      el.style.top = `${next.y}px`;
      el.style.width = `${next.width}px`;
      el.style.height = `${next.height}px`;
    };

    if (header) {
      header.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || event.target.closest("button")) return;
        event.preventDefault();
        this.focusWindow(windowId);
        el.classList.add("ws-window-dragging");
        const start = currentGeometry();
        const originX = event.clientX;
        const originY = event.clientY;
        header.setPointerCapture(event.pointerId);

        const move = (moveEvent) => {
          applyManual({
            ...start,
            x: start.x + moveEvent.clientX - originX,
            y: start.y + moveEvent.clientY - originY,
          });
        };
        const finish = () => {
          el.classList.remove("ws-window-dragging");
          header.removeEventListener("pointermove", move);
          header.removeEventListener("pointerup", finish);
          header.removeEventListener("pointercancel", finish);
        };
        header.addEventListener("pointermove", move);
        header.addEventListener("pointerup", finish);
        header.addEventListener("pointercancel", finish);
      });
    }

    if (resizeHandle) {
      resizeHandle.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        this.focusWindow(windowId);
        el.classList.add("ws-window-resizing");
        const start = currentGeometry();
        const originX = event.clientX;
        const originY = event.clientY;
        resizeHandle.setPointerCapture(event.pointerId);

        const move = (moveEvent) => {
          const rtl = document.documentElement.dir === "rtl";
          const deltaX = moveEvent.clientX - originX;
          applyManual({
            ...start,
            x: rtl ? start.x + deltaX : start.x,
            width: rtl ? start.width - deltaX : start.width + deltaX,
            height: start.height + moveEvent.clientY - originY,
          });
        };
        const finish = () => {
          el.classList.remove("ws-window-resizing");
          resizeHandle.removeEventListener("pointermove", move);
          resizeHandle.removeEventListener("pointerup", finish);
          resizeHandle.removeEventListener("pointercancel", finish);
        };
        resizeHandle.addEventListener("pointermove", move);
        resizeHandle.addEventListener("pointerup", finish);
        resizeHandle.addEventListener("pointercancel", finish);
      });
    }

    if (expandButton) {
      expandButton.addEventListener("click", (event) => {
        event.stopPropagation();
        if (this._expandedRestore.has(windowId)) {
          const restore = this._expandedRestore.get(windowId);
          this._expandedRestore.delete(windowId);
          el.classList.remove("ws-window-expanded");
          expandButton.textContent = "↗";
          expandButton.title = "تكبير النافذة";
          applyManual(restore);
          return;
        }
        this._expandedRestore.set(windowId, currentGeometry());
        const bounds = this.layer.getBoundingClientRect();
        el.classList.add("ws-window-expanded");
        expandButton.textContent = "↙";
        expandButton.title = "استعادة الحجم";
        applyManual({
          x: 12,
          y: 12,
          width: bounds.width - 24,
          height: bounds.height - 24,
        });
      });
    }
  }

  _updateShell(el, spec) {
    el.dataset.spec = JSON.stringify(spec);
    el.querySelector(".ws-window-title").textContent = spec.title || "";
    el.querySelector(".ws-window-status").textContent = spec.status || "";
    const hideButton = el.querySelector(".ws-window-hide");
    if (hideButton) {
      hideButton.hidden = !spec.ui_auxiliary;
      hideButton.onclick = (event) => {
        event.stopPropagation();
        window.dispatchEvent(
          new CustomEvent("ws:hide-window", { detail: { windowId: spec.id } })
        );
      };
    }
  }

  _renderBody(el, spec) {
    const body = el.querySelector(".ws-window-body");
    const renderer = this.renderers[spec.type];
    const h = this.workflowHandlers;
    if (spec.type === "document_viewer" && this._documentScanState) {
      body.__documentScanState = { ...this._documentScanState };
    }
    if (renderer && renderer.render) {
      if (spec.type === "approval_panel") {
        renderer.render(body, spec, {
          onApprove: (stepId) => {
            if ((spec.props || {}).action === "courier_posting" && h.onCourierPostingApprove) {
              return h.onCourierPostingApprove(spec);
            }
            if ((spec.props || {}).action === "return_posting" && h.onReturnPostingApprove) {
              return h.onReturnPostingApprove(spec);
            }
            if ((spec.props || {}).action === "purchase_posting" && h.onPurchasePostingApprove) {
              return h.onPurchasePostingApprove(spec);
            }
            if (h.onApprove) return h.onApprove(stepId);
          },
          onReject: (stepId) => {
            if ((spec.props || {}).action === "courier_posting" && h.onCourierPostingReject) {
              return h.onCourierPostingReject(spec);
            }
            if ((spec.props || {}).action === "return_posting" && h.onReturnPostingReject) {
              return h.onReturnPostingReject(spec);
            }
            if ((spec.props || {}).action === "purchase_posting" && h.onPurchasePostingReject) {
              return h.onPurchasePostingReject(spec);
            }
            if (h.onReject) return h.onReject(stepId);
          },
        });
      } else if (spec.type === "workflow_selector") {
        renderer.render(body, spec, {
          onSelect: (type) => h.onSelectWorkflow && h.onSelectWorkflow(type),
        });
      } else if (spec.type === "courier_rows") {
        renderer.render(body, spec, {
          onFilter: (f) => this.courierHandlers.onFilter && this.courierHandlers.onFilter(spec, f),
          loadRows: (aid, f) => this.courierHandlers.loadRows && this.courierHandlers.loadRows(aid, f, body),
          onChangeOrder: (row, orderNumber) => (
            this.courierHandlers.onChangeOrder
              && this.courierHandlers.onChangeOrder(spec, row, orderNumber)
          ),
          onApproveCandidate: (row) => (
            this.courierHandlers.onApproveCandidate
              && this.courierHandlers.onApproveCandidate(spec, row)
          ),
          onPaymentMethodChange: (row, treasuryAccountId) => (
            this.courierHandlers.onPaymentMethodChange
              && this.courierHandlers.onPaymentMethodChange(spec, row, treasuryAccountId)
          ),
          onConfirmReplacement: (row) => (
            this.courierHandlers.onConfirmReplacement
              && this.courierHandlers.onConfirmReplacement(spec, row)
          ),
          onDeleteRow: (row) => (
            this.courierHandlers.onDeleteRow
              && this.courierHandlers.onDeleteRow(spec, row)
          ),
        });
      } else if (spec.type === "courier_issues" && this.courierHandlers.loadIssues) {
        renderer.render(body, spec);
        if (spec.props && spec.props.analysisId) {
          this.courierHandlers.loadIssues(spec.props.analysisId, body);
        }
      } else if (spec.type === "courier_settlement_analysis") {
        renderer.render(body, spec, {
          onExport: (s) => this.courierHandlers.onExport && this.courierHandlers.onExport(s),
          onPrintCourier: (s) => (
            this.courierHandlers.onPrintCourier
              && this.courierHandlers.onPrintCourier(s)
          ),
          onSettle: (s) => this.courierHandlers.onSettle && this.courierHandlers.onSettle(s),
          onReanalyze: (s) => this.courierHandlers.onReanalyze && this.courierHandlers.onReanalyze(s),
          onShowWindow: (type) => (
            this.courierHandlers.onShowWindow
              && this.courierHandlers.onShowWindow(type)
          ),
        });
        if (spec.props && spec.props.analysisId && !(spec.props.issues && spec.props.issues.length) && this.courierHandlers.loadReportIssues) {
          this.courierHandlers.loadReportIssues(spec.props.analysisId, body);
        }
      } else if (spec.type === "purchase_invoice_analysis") {
        renderer.render(body, spec, {
          onPrepare: (s) => h.onPurchasePrepare && h.onPurchasePrepare(s),
          onDecision: (s, rowIndex, decision, productId) => (
            h.onPurchaseDecision && h.onPurchaseDecision(s, rowIndex, decision, productId)
          ),
          onValues: (s, rowIndex, quantity, unitPrice, productName, unitPriceUsd) => (
            h.onPurchaseValues && h.onPurchaseValues(s, rowIndex, quantity, unitPrice, productName, unitPriceUsd)
          ),
          onSupplier: (s, values) => h.onPurchaseSupplier && h.onPurchaseSupplier(s, values),
          onCatalogSearch: (query) => h.onPurchaseCatalogSearch && h.onPurchaseCatalogSearch(query),
        });
      } else if (spec.type === "inventory_forensics") {
        renderer.render(body, spec, {
          onAnalyze: (s, filters) => (
            h.onInventoryAnalyze && h.onInventoryAnalyze(s, filters)
          ),
        });
      } else {
        renderer.render(body, spec);
      }
    } else {
      body.innerHTML = `<p style="color:#64748b;font-size:13px">نافذة: ${spec.type}</p>`;
    }
  }
}

window.WorkspaceWindowManager = WorkspaceWindowManager;
