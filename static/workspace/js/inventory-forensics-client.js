class InventoryForensicsClient {
  constructor({ apiBase, getSessionId, onSessionUpdate }) {
    this.apiBase = apiBase || "/workspace/api";
    this.getSessionId = getSessionId;
    this.onSessionUpdate = onSessionUpdate || (() => {});
  }

  _sid() {
    const id = this.getSessionId && this.getSessionId();
    if (!id) throw new Error("لا توجد جلسة نشطة");
    return id;
  }

  async _api(path, options = {}) {
    const response = await fetch(`${this.apiBase}${path}`, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }

  analyze(filters) {
    return this._api(`/sessions/${this._sid()}/inventory-forensics/analyze`, {
      method: "POST",
      body: JSON.stringify(filters || {}),
    });
  }

  searchCatalog(query) {
    return this._api(`/inventory-forensics/catalog?q=${encodeURIComponent(query || "")}&limit=200`);
  }
}

window.InventoryForensicsClient = InventoryForensicsClient;
