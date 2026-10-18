class PurchaseAnalysisClient {
  constructor({ apiBase, getSessionId, onSessionUpdate }) {
    this.apiBase = apiBase || "/workspace/api";
    this.getSessionId = getSessionId;
    this.onSessionUpdate = onSessionUpdate || (() => {});
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

  _sid() {
    const id = this.getSessionId && this.getSessionId();
    if (!id) throw new Error("لا توجد جلسة نشطة");
    return id;
  }

  run(documentId = null) {
    return this._api(`/sessions/${this._sid()}/purchase-analysis/run`, {
      method: "POST",
      body: JSON.stringify(documentId ? { document_id: documentId } : {}),
    });
  }

  catalog(query = "", limit = 120) {
    const params = new URLSearchParams({ q: String(query || ""), limit: String(limit || 120) });
    return this._api(`/purchase-analysis/catalog?${params.toString()}`);
  }

  setSupplier(analysisId, { supplierId = null, supplierName = null } = {}) {
    return this._api(`/sessions/${this._sid()}/purchase-analysis/${analysisId}/supplier`, {
      method: "PATCH",
      body: JSON.stringify({ supplier_id: supplierId, supplier_name: supplierName }),
    });
  }

  decide(analysisId, rowIndex, decision, productId = null) {
    return this._api(`/sessions/${this._sid()}/purchase-analysis/${analysisId}/rows/${rowIndex}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, product_id: productId }),
    });
  }

  updateValues(analysisId, rowIndex, quantity, unitPrice, productName = null, unitPriceUsd = null) {
    return this._api(`/sessions/${this._sid()}/purchase-analysis/${analysisId}/rows/${rowIndex}/values`, {
      method: "PATCH",
      body: JSON.stringify({
        quantity,
        unit_price: unitPrice,
        unit_price_usd: unitPriceUsd,
        product_name: productName,
      }),
    });
  }

  prepare(analysisId) {
    return this._api(`/sessions/${this._sid()}/purchase-analysis/${analysisId}/posting/prepare`, {
      method: "POST",
      body: "{}",
    });
  }

  cancel(analysisId) {
    return this._api(`/sessions/${this._sid()}/purchase-analysis/${analysisId}/posting/cancel`, {
      method: "POST",
      body: "{}",
    });
  }

  approve(analysisId) {
    return this._api(`/sessions/${this._sid()}/purchase-analysis/${analysisId}/posting/approve`, {
      method: "POST",
      body: "{}",
    });
  }
}

window.PurchaseAnalysisClient = PurchaseAnalysisClient;
