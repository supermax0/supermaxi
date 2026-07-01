/**
 * Floating window manager for workspace.
 */
class WorkspaceWindowManager {
  constructor(layerEl) {
    this.layer = layerEl;
    this.windows = new Map();
    this.renderers = {
      document_viewer: DocumentViewerWindow,
      live_report: LiveReportWindow,
      assistant_notes: AssistantNotesWindow,
    };
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
        LiveReportWindow.appendLine(body, payload.line);
        const spec = JSON.parse(reportWin[1].dataset.spec || "{}");
        spec.props = spec.props || {};
        spec.props.lines = spec.props.lines || [];
        spec.props.lines.push(payload.line);
        reportWin[1].dataset.spec = JSON.stringify(spec);
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
    if (renderer && renderer.render) {
      renderer.render(body, spec);
    } else {
      body.innerHTML = `<p style="color:#64748b;font-size:13px">نافذة: ${spec.type}</p>`;
    }
  }
}

window.WorkspaceWindowManager = WorkspaceWindowManager;
