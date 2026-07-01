/**
 * Floating window manager for workspace.
 */
class WorkspaceWindowManager {
  constructor(layerEl) {
    this.layer = layerEl;
    this.windows = new Map();
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
    };
    this.courierHandlers = {};
  }

  setCourierHandlers(handlers) {
    this.courierHandlers = handlers || {};
  }

  setWorkflowHandlers(handlers) {
    this.workflowHandlers = handlers || {};
  }

  renderWindows(windowsList) {
    const ids = new Set((windowsList || []).map((w) => w.id));
    this.windows.forEach((_, id) => {
      if (!ids.has(id)) this.closeWindow(id);
    });
    (windowsList || []).forEach((spec) => this.openOrUpdateWindow(spec));
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
    this.openOrUpdateWindow(spec);
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
      const docWin = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "document_viewer";
      });
      if (docWin) {
        const body = docWin[1].querySelector(".ws-window-body");
        DocumentViewerWindow.updateScan(body, payload);
      }
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
    if (type === "courier.financial_preview.ready") {
      const win = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "financial_preview";
      });
      if (win) {
        FinancialPreviewWindow.patchFromEvent(win[1].querySelector(".ws-window-body"), payload);
      }
    }
    if (type === "courier.analysis.completed" && payload.summary) {
      const win = [...this.windows.entries()].find(([, el]) => {
        const spec = JSON.parse(el.dataset.spec || "{}");
        return spec.type === "courier_settlement_analysis";
      });
      if (win) {
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
        <span class="ws-window-status"></span>
      </div>
      <div class="ws-window-body"></div>
    `;
    el.addEventListener("mousedown", () => this.focusWindow(spec.id));
    return el;
  }

  _applyPosition(el, spec) {
    const pos = spec.position || {};
    el.style.left = `${pos.x ?? 40}px`;
    el.style.top = `${pos.y ?? 80}px`;
    el.style.width = `${pos.width ?? 360}px`;
    el.style.height = `${pos.height ?? 400}px`;
    el.style.zIndex = spec.z_index ?? 10;
  }

  _updateShell(el, spec) {
    el.dataset.spec = JSON.stringify(spec);
    el.querySelector(".ws-window-title").textContent = spec.title || "";
    el.querySelector(".ws-window-status").textContent = spec.status || "";
  }

  _renderBody(el, spec) {
    const body = el.querySelector(".ws-window-body");
    const renderer = this.renderers[spec.type];
    const h = this.workflowHandlers;
    if (renderer && renderer.render) {
      if (spec.type === "approval_panel") {
        renderer.render(body, spec, {
          onApprove: (stepId) => h.onApprove && h.onApprove(stepId),
          onReject: (stepId) => h.onReject && h.onReject(stepId),
        });
      } else if (spec.type === "workflow_selector") {
        renderer.render(body, spec, {
          onSelect: (type) => h.onSelectWorkflow && h.onSelectWorkflow(type),
        });
      } else if (spec.type === "courier_rows") {
        renderer.render(body, spec, {
          onFilter: (f) => this.courierHandlers.onFilter && this.courierHandlers.onFilter(spec, f),
          loadRows: (aid, f) => this.courierHandlers.loadRows && this.courierHandlers.loadRows(aid, f, body),
        });
      } else if (spec.type === "courier_issues" && this.courierHandlers.loadIssues) {
        renderer.render(body, spec);
        if (spec.props && spec.props.analysisId) {
          this.courierHandlers.loadIssues(spec.props.analysisId, body);
        }
      } else if (spec.type === "courier_settlement_analysis") {
        renderer.render(body, spec, {
          onExport: (s) => this.courierHandlers.onExport && this.courierHandlers.onExport(s),
        });
        if (spec.props && spec.props.analysisId && !(spec.props.issues && spec.props.issues.length) && this.courierHandlers.loadReportIssues) {
          this.courierHandlers.loadReportIssues(spec.props.analysisId, body);
        }
      } else {
        renderer.render(body, spec);
      }
    } else {
      body.innerHTML = `<p style="color:#64748b;font-size:13px">نافذة: ${spec.type}</p>`;
    }
  }
}

window.WorkspaceWindowManager = WorkspaceWindowManager;
