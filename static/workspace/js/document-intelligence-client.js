/**
 * Document intelligence API client — Phase 4.
 */
class DocumentIntelligenceClient {
  constructor({ apiBase, getSessionId, onSessionUpdate, onError, onStart, onComplete }) {
    this.apiBase = apiBase || "/workspace/api";
    this.getSessionId = getSessionId;
    this.onSessionUpdate = onSessionUpdate || (() => {});
    this.onError = onError || ((e) => console.warn(e));
    this.onStart = onStart || (() => {});
    this.onComplete = onComplete || (() => {});
    this._busy = false;
  }

  isBusy() {
    return this._busy;
  }

  async _api(path, options = {}) {
    const res = await fetch(`${this.apiBase}${path}`, {
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.message || data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  async runForDocument(documentId, sessionId) {
    const sid = sessionId || (this.getSessionId && this.getSessionId());
    if (!sid) throw new Error("لا توجد جلسة نشطة");
    this._busy = true;
    this.onStart();
    try {
      const data = await this._api(`/documents/${documentId}/intelligence/run`, {
        method: "POST",
        body: JSON.stringify({ session_id: sid }),
      });
      if (data.session) this.onSessionUpdate(data.session);
      this.onComplete(data.result);
      return data;
    } catch (e) {
      this.onError(e);
      throw e;
    } finally {
      this._busy = false;
    }
  }

  async runForActiveSessionDocument(sessionId) {
    const sid = sessionId || (this.getSessionId && this.getSessionId());
    if (!sid) throw new Error("لا توجد جلسة نشطة");
    this._busy = true;
    this.onStart();
    try {
      const data = await this._api(`/sessions/${sid}/intelligence/run-active`, {
        method: "POST",
        body: "{}",
      });
      if (data.session) this.onSessionUpdate(data.session);
      this.onComplete(data.result);
      return data;
    } catch (e) {
      this.onError(e);
      throw e;
    } finally {
      this._busy = false;
    }
  }

  async getResult(documentId) {
    return this._api(`/documents/${documentId}/intelligence`);
  }
}

window.DocumentIntelligenceClient = DocumentIntelligenceClient;
