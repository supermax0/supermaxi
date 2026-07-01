/**
 * SSE client with event id dedup and replay cursor.
 */
class WorkspaceEventStream {
  constructor(sessionId) {
    this.sessionId = sessionId;
    this.source = null;
    this.handlers = new Map();
    this.lastEventId = 0;
    this.handledEventIds = new Set();
    this._storageKey = `workspace:lastEventId:${sessionId}`;
    const stored = localStorage.getItem(this._storageKey);
    if (stored) {
      const n = parseInt(stored, 10);
      if (!Number.isNaN(n)) this.lastEventId = n;
    }
  }

  on(eventType, handler) {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType).add(handler);
    return () => this.handlers.get(eventType)?.delete(handler);
  }

  onAny(handler) {
    return this.on("*", handler);
  }

  _persistCursor(id) {
    if (!id) return;
    const n = Number(id);
    if (Number.isNaN(n)) return;
    this.lastEventId = Math.max(this.lastEventId, n);
    try {
      localStorage.setItem(this._storageKey, String(this.lastEventId));
    } catch (e) {
      /* ignore */
    }
  }

  _dispatch(data, fromReplay = false) {
    const type = data.type || "message";
    const eid = data.id || data.event_id;
    if (eid) {
      const key = String(eid);
      if (this.handledEventIds.has(key)) return;
      this.handledEventIds.add(key);
      this._persistCursor(eid);
    }
    data._fromReplay = fromReplay;

    const handlers = this.handlers.get(type);
    if (handlers) {
      handlers.forEach((h) => h(data));
    }
    const any = this.handlers.get("*");
    if (any) {
      any.forEach((h) => h(data));
    }
  }

  connect() {
    this.disconnect();
    const url = `/workspace/api/sessions/${this.sessionId}/stream?since=${this.lastEventId}`;
    this.source = new EventSource(url);

    this.source.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (ev.lastEventId) this._persistCursor(ev.lastEventId);
        this._dispatch(data, true);
      } catch (e) {
        console.warn("SSE parse error", e);
      }
    };

    const eventTypes = [
      "report.appended",
      "avatar.updated",
      "window.opened",
      "window.updated",
      "document.scan.updated",
      "document.upload.started",
      "document.uploaded",
      "document.preview.ready",
      "workflow.started",
      "workflow.step.started",
      "workflow.step.completed",
      "workflow.completed",
      "workflow.failed",
      "workflow.cancelled",
      "user.input.required",
      "user.input.received",
      "approval.required",
      "approval.accepted",
      "approval.rejected",
      "session.completed",
      "session.cancelled",
      "session.created",
      "document.intelligence.started",
      "document.text.extracted",
      "document.tables.extracted",
      "document.normalized",
      "document.classified",
      "document.intelligence.completed",
      "document.intelligence.failed",
      "courier.analysis.started",
      "courier.rows.parsed",
      "courier.matching.started",
      "courier.row.matched",
      "courier.issues.detected",
      "courier.financial_preview.ready",
      "courier.analysis.completed",
      "courier.analysis.failed",
    ];

    eventTypes.forEach((type) => {
      this.source.addEventListener(type, (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (ev.lastEventId) this._persistCursor(ev.lastEventId);
          this._dispatch(data, false);
        } catch (e) {
          console.warn("SSE typed event error", e);
        }
      });
    });

    this.source.onerror = () => {
      console.warn("SSE connection error — will retry via browser");
    };
  }

  disconnect() {
    if (this.source) {
      this.source.close();
      this.source = null;
    }
  }
}

window.WorkspaceEventStream = WorkspaceEventStream;
