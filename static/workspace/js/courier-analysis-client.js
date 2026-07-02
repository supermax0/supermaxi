class CourierAnalysisClient {
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
    if (!res.ok) throw new Error(data.message || data.error || `HTTP ${res.status}`);
    return data;
  }

  async runForSession(sessionId, documentId = null) {
    const sid = sessionId || (this.getSessionId && this.getSessionId());
    if (!sid) throw new Error("لا توجد جلسة نشطة");
    this._busy = true;
    this.onStart();
    try {
      const body = documentId ? { document_id: documentId } : {};
      const data = await this._api(`/sessions/${sid}/courier-analysis/run`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (data.session) this.onSessionUpdate(data.session);
      this.onComplete(data.analysis);
      return data;
    } catch (e) {
      this.onError(e);
      throw e;
    } finally {
      this._busy = false;
    }
  }

  async getLatest(sessionId) {
    const sid = sessionId || (this.getSessionId && this.getSessionId());
    return this._api(`/sessions/${sid}/courier-analysis`);
  }

  async getAnalysis(analysisId) {
    return this._api(`/courier-analysis/${analysisId}`);
  }

  async getRows(analysisId, filters = {}) {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.page) params.set("page", String(filters.page));
    if (filters.page_size) params.set("page_size", String(filters.page_size));
    const q = params.toString();
    return this._api(`/courier-analysis/${analysisId}/rows${q ? `?${q}` : ""}`);
  }

  async getIssues(analysisId) {
    return this._api(`/courier-analysis/${analysisId}/issues`);
  }

  async getFinancialPreview(analysisId) {
    return this._api(`/courier-analysis/${analysisId}/financial-preview`);
  }

  async getPostingPreview(analysisId) {
    return this._api(`/courier-analysis/${analysisId}/posting-preview`);
  }

  async preparePosting(analysisId) {
    const data = await this._api(`/courier-analysis/${analysisId}/posting/prepare`, {
      method: "POST",
      body: "{}",
    });
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }

  async cancelPosting(analysisId) {
    const data = await this._api(`/courier-analysis/${analysisId}/posting/cancel`, {
      method: "POST",
      body: "{}",
    });
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }

  async approvePosting(analysisId, payload = {}) {
    const data = await this._api(`/courier-analysis/${analysisId}/posting/approve`, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }
}

window.CourierAnalysisClient = CourierAnalysisClient;
