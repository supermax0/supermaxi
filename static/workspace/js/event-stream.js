/**
 * SSE client for workspace events.
 */
class WorkspaceEventStream {
  constructor(sessionId) {
    this.sessionId = sessionId;
    this.source = null;
    this.handlers = new Map();
    this.lastEventId = 0;
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

  _dispatch(data) {
    const type = data.type || "message";
    if (data.event_id) {
      this.lastEventId = Math.max(this.lastEventId, Number(data.event_id) || 0);
    }
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
    const url = `/workspace/api/sessions/${this.sessionId}/stream?after=${this.lastEventId}`;
    this.source = new EventSource(url);

    this.source.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        this._dispatch(data);
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
      "workflow.step.started",
      "workflow.step.completed",
      "session.completed",
      "session.cancelled",
      "session.created",
    ];

    eventTypes.forEach((type) => {
      this.source.addEventListener(type, (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (ev.lastEventId) {
            this.lastEventId = Math.max(this.lastEventId, Number(ev.lastEventId) || 0);
          }
          this._dispatch(data);
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
