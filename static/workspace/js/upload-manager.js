/**
 * Workspace document upload manager — Phase 2.
 */
class WorkspaceUploadManager {
  constructor(options = {}) {
    this.apiBase = options.apiBase || "/workspace/api";
    this.getSessionId = options.getSessionId || null;
    this.onStart = options.onStart || (() => {});
    this.onSuccess = options.onSuccess || (() => {});
    this.onError = options.onError || (() => {});
    this.fileInput = null;
    this._bindInput();
  }

  _bindInput() {
    this.fileInput = document.getElementById("ws-file-input");
    if (!this.fileInput) {
      this.fileInput = document.createElement("input");
      this.fileInput.type = "file";
      this.fileInput.id = "ws-file-input";
      this.fileInput.hidden = true;
      this.fileInput.accept = ".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp";
      document.body.appendChild(this.fileInput);
    }
    this.fileInput.addEventListener("change", () => this._handleSelected());
  }

  openPicker() {
    this.fileInput.value = "";
    this.fileInput.click();
  }

  async _handleSelected() {
    const file = this.fileInput.files && this.fileInput.files[0];
    if (!file) return;
    const sessionId = this._currentSessionId();
    if (!sessionId) {
      this.onError(new Error("لا توجد جلسة نشطة"));
      return;
    }
    await this.uploadFile(sessionId, file);
  }

  _currentSessionId() {
    if (typeof this.getSessionId === "function") {
      return this.getSessionId();
    }
    return null;
  }

  async uploadFile(sessionId, file) {
    this.onStart(file);
    const form = new FormData();
    form.append("file", file);

    try {
      const res = await fetch(`${this.apiBase}/sessions/${sessionId}/documents`, {
        method: "POST",
        body: form,
        credentials: "same-origin",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.message || data.error || `HTTP ${res.status}`);
      }
      this.onSuccess(data);
      return data;
    } catch (err) {
      this.onError(err);
      throw err;
    }
  }
}

window.WorkspaceUploadManager = WorkspaceUploadManager;
