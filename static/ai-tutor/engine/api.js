/* Backend client. Any FEATURE_NOT_ENABLED answer shuts the tutor down immediately. */
const BASE = "/api/clinic/ai-tutor";

export class FeatureDisabledError extends Error {
  constructor() {
    super("FEATURE_NOT_ENABLED");
    this.name = "FeatureDisabledError";
  }
}

export class TutorApi {
  constructor({ onDisabled, fetchImpl } = {}) {
    this.onDisabled = onDisabled || (() => undefined);
    this.fetch = fetchImpl || ((...args) => window.fetch(...args));
  }

  async request(path, { method = "GET", body, keepalive = false } = {}) {
    const res = await this.fetch(`${BASE}${path}`, {
      method,
      credentials: "same-origin",
      keepalive,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 403 && data.error === "FEATURE_NOT_ENABLED") {
      this.onDisabled();
      throw new FeatureDisabledError();
    }
    if (!res.ok || data.ok === false) {
      const error = new Error(data.error || `HTTP ${res.status}`);
      error.status = res.status;
      throw error;
    }
    return data;
  }

  status() {
    return this.request("/status");
  }

  list() {
    return this.request("/tutorials");
  }

  active() {
    return this.request("/active");
  }

  start(id, body = {}) {
    return this.request(`/tutorials/${encodeURIComponent(id)}/start`, { method: "POST", body });
  }

  resume(id, body = {}) {
    return this.request(`/tutorials/${encodeURIComponent(id)}/resume`, { method: "POST", body });
  }

  facts() {
    return this.request("/facts");
  }

  knowledge() {
    return this.request("/knowledge");
  }

  ask(payload) {
    return this.request("/ask", { method: "POST", body: payload });
  }

  progress(id, payload, opts = {}) {
    return this.request(`/tutorials/${encodeURIComponent(id)}/progress`, { method: "POST", body: payload, ...opts });
  }

  verify(id, validator) {
    return this.request(`/tutorials/${encodeURIComponent(id)}/verify`, { method: "POST", body: { validator } });
  }

  complete(id) {
    return this.request(`/tutorials/${encodeURIComponent(id)}/complete`, { method: "POST", body: {} });
  }
}
