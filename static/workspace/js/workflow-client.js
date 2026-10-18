/**
 * Workflow API client — Phase 3.
 */
class WorkspaceWorkflowClient {
  constructor(options = {}) {
    this.apiBase = options.apiBase || "/workspace/api";
    this.getSessionId = options.getSessionId || (() => null);
    this.onSessionUpdate = options.onSessionUpdate || (() => {});
    this.onWaiting = options.onWaiting || (() => {});
    this.onError = options.onError || (() => {});
  }

  _sessionId() {
    return typeof this.getSessionId === "function" ? this.getSessionId() : null;
  }

  async _json(path, options = {}) {
    const res = await fetch(`${this.apiBase}${path}`, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const code = data.error || `HTTP ${res.status}`;
      if (code === "not_found") {
        const error = new Error("SESSION_NOT_FOUND");
        error.code = "SESSION_NOT_FOUND";
        throw error;
      }
      const rawMessage = data.message || code;
      const friendlyMessage = /internal server error/i.test(String(rawMessage))
        ? "حدث خطأ داخلي أثناء تحليل المستند. أعد المحاولة، وإذا تكرر الخطأ ارفع المستند بصورة أوضح."
        : rawMessage;
      throw new Error(friendlyMessage);
    }
    return data;
  }

  async getWorkflowState() {
    const id = this._sessionId();
    if (!id) throw new Error("لا توجد جلسة");
    return this._json(`/sessions/${id}/workflow`);
  }

  async startWorkflow(workflowType = "mock_workspace") {
    const id = this._sessionId();
    const data = await this._json(`/sessions/${id}/workflow/start`, {
      method: "POST",
      body: JSON.stringify({ workflow_type: workflowType }),
    });
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }

  async runNextStep(input = null) {
    const id = this._sessionId();
    const body = input ? { input } : {};
    const data = await this._json(`/sessions/${id}/workflow/next`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (data.waiting) this.onWaiting(data.waiting, data);
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }

  async runUntilBlocked(autoAdvance = true) {
    const id = this._sessionId();
    if (!autoAdvance) {
      return this.runNextStep();
    }
    let guard = 0;
    while (guard < 25) {
      guard += 1;
      const data = await this.runNextStep();
      if (data.waiting === "approval" || data.waiting === "user_input") {
        return data;
      }
      const session = data.session;
      if (!session || session.status === "completed" || session.status === "cancelled") {
        return data;
      }
      await new Promise((r) => setTimeout(r, 350));
    }
    return null;
  }

  async submitInput(stepId, input) {
    const id = this._sessionId();
    const data = await this._json(`/sessions/${id}/workflow/input`, {
      method: "POST",
      body: JSON.stringify({ step_id: stepId, input }),
    });
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }

  async submitApproval(approved, comment = "") {
    const id = this._sessionId();
    const data = await this._json(`/sessions/${id}/workflow/approval`, {
      method: "POST",
      body: JSON.stringify({ approved, comment }),
    });
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }

  async cancelWorkflow() {
    const id = this._sessionId();
    if (!id) throw new Error("لا توجد جلسة");
    const data = await this._json(`/sessions/${id}/workflow/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (data.session) this.onSessionUpdate(data.session);
    return data;
  }

  async selectWorkflowType(workflowType) {
    await this.startWorkflow(workflowType);
    return this.runUntilBlocked(false);
  }
}

window.WorkspaceWorkflowClient = WorkspaceWorkflowClient;
