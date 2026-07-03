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
    this._bindPaste();
  }

  _bindInput() {
    this.fileInput = document.getElementById("ws-file-input");
    if (!this.fileInput) {
      this.fileInput = document.createElement("input");
      this.fileInput.type = "file";
      this.fileInput.id = "ws-file-input";
      this.fileInput.hidden = true;
      this.fileInput.accept = ".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp";
      this.fileInput.multiple = true;
      document.body.appendChild(this.fileInput);
    }
    this.fileInput.addEventListener("change", () => this._handleSelected());
  }

  _bindPaste() {
    document.addEventListener("paste", (event) => {
      const active = document.activeElement;
      const isTyping =
        active &&
        (active.tagName === "INPUT" ||
          active.tagName === "TEXTAREA" ||
          active.isContentEditable);
      if (isTyping) return;

      const items = [...(event.clipboardData && event.clipboardData.items ? event.clipboardData.items : [])];
      const files = items
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter(Boolean);
      if (!files.length) return;
      event.preventDefault();
      this.uploadCurrentSessionFiles(files);
    });
  }

  openPicker() {
    this.fileInput.value = "";
    this.fileInput.click();
  }

  async _handleSelected() {
    const files = this.fileInput.files ? [...this.fileInput.files] : [];
    if (!files.length) return;
    await this.uploadCurrentSessionFiles(files);
  }

  async uploadCurrentSessionFiles(files) {
    const sessionId = this._currentSessionId();
    if (!sessionId) {
      this.onError(new Error("لا توجد جلسة نشطة"));
      return;
    }
    await this.uploadFiles(sessionId, files);
  }

  _currentSessionId() {
    if (typeof this.getSessionId === "function") {
      return this.getSessionId();
    }
    return null;
  }

  async uploadFiles(sessionId, files) {
    const list = [...(files || [])].filter(Boolean);
    if (!list.length) return null;

    this.onStart(list[0], { index: 1, total: list.length });
    let lastData = null;
    const uploaded = [];
    try {
      for (let i = 0; i < list.length; i += 1) {
        lastData = await this.uploadFile(sessionId, list[i], {
          silentStart: true,
          silentSuccess: true,
          index: i + 1,
          total: list.length,
        });
        if (lastData && lastData.document) uploaded.push(lastData.document);
      }
      this.onSuccess(lastData || {}, { total: list.length, documents: uploaded });
      return lastData;
    } catch (err) {
      this.onError(err);
      throw err;
    }
  }

  async uploadFile(sessionId, file, options = {}) {
    if (!options.silentStart) {
      this.onStart(file, { index: options.index || 1, total: options.total || 1 });
    }
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
      if (!options.silentSuccess) {
        this.onSuccess(data, { index: options.index || 1, total: options.total || 1 });
      }
      return data;
    } catch (err) {
      if (!options.silentSuccess) {
        this.onError(err);
      }
      throw err;
    }
  }
}

window.WorkspaceUploadManager = WorkspaceUploadManager;
