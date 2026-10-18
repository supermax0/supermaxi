/**
 * Document viewer — Phase 2: real PDF/image preview + scan overlay.
 */
const DocumentViewerWindow = {
  render(container, spec) {
    const props = { ...(spec.props || {}) };
    const liveScan = container.__documentScanState;
    if (liveScan) {
      props.scan_active = !!liveScan.active;
      props.scan_progress = liveScan.progress || 0;
      props.scan_stage = liveScan.stage || "";
      props.scan_error = !!liveScan.error;
    }
    const status = props.status || spec.status || "idle";

    if (status === "loading" || props.loading) {
      container.innerHTML = this._loadingHtml();
      return;
    }

    if (props.error) {
      container.innerHTML = this._errorHtml(props.error);
      return;
    }

    if (props.previewUrl && (props.documentId || props.fileName)) {
      container.innerHTML = this._previewHtml(props);
      this._applyScanState(container, props);
      this._wireUpload(container);
      this._wireDocumentSelection(container, spec);
      return;
    }

    container.innerHTML = this._placeholderHtml(props);
    this._applyScanState(container, props);
    this._wireUpload(container);
  },

  _placeholderHtml(props) {
    const scanActive = !!props.scan_active;
    const progress = props.scan_progress || 0;
    return `
      <div class="ws-doc-viewer">
        <div class="ws-doc-meta ws-doc-meta-empty">
          <span>لم يُرفع مستند بعد</span>
        </div>
        <div class="ws-doc-paper ws-doc-upload-zone" data-upload-trigger tabindex="0" role="button" aria-label="رفع مستند">
          <div class="ws-doc-placeholder">
            <div class="ws-doc-upload-icon">&#8681;</div>
            <div class="ws-doc-lines">
              <div class="ws-doc-line" style="width:90%"></div>
              <div class="ws-doc-line" style="width:75%"></div>
              <div class="ws-doc-line" style="width:85%"></div>
            </div>
            <p class="ws-doc-hint">انقر للرفع أو اسحب PDF/صورة هنا</p>
            <p class="ws-doc-subhint">يدعم PDF و PNG و JPG و WEBP. يمكنك أيضاً لصق صورة من الحافظة.</p>
            ${scanActive ? `<p class="ws-doc-scan-hint">جاري المسح... ${progress}%</p>` : ""}
          </div>
          ${this._scanOverlayHtml(scanActive, progress)}
        </div>
      </div>
    `;
  },

  _previewHtml(props) {
    const mime = (props.mimeType || "").toLowerCase();
    const isPdf = mime === "application/pdf" || (props.fileName || "").toLowerCase().endsWith(".pdf");
    const scanActive = !!props.scan_active;
    const progress = props.scan_progress || 0;
    const previewUrl = props.previewUrl;
    const sizeLabel = this._formatSize(props.fileSize);

    let previewBlock = "";
    if (isPdf) {
      previewBlock = `
        <div class="ws-doc-preview-frame">
          <iframe class="ws-doc-pdf-frame" src="${previewUrl}" title="معاينة PDF"></iframe>
        </div>
      `;
    } else {
      previewBlock = `
        <div class="ws-doc-preview-frame ws-doc-image-frame">
          <img class="ws-doc-image" src="${previewUrl}" alt="${this._esc(props.fileName || "صورة")}" />
        </div>
      `;
    }

    return `
      <div class="ws-doc-viewer">
        ${this._toolbarHtml(props)}
        <div class="ws-doc-paper ws-doc-paper-has-preview">
          ${previewBlock}
          ${this._scanOverlayHtml(scanActive, progress)}
        </div>
        ${this._thumbsHtml(props)}
      </div>
    `;
  },

  _toolbarHtml(props) {
    const pages = props.pageCount || props.page_count || 1;
    const documents = props.documents || [];
    const activeIndex = Math.max(
      0,
      documents.findIndex((doc) => (doc.documentId || doc.id) === props.documentId)
    );
    const documentCount = documents.length || props.documentCount || 1;
    return `
      <div class="ws-doc-toolbar">
        <button type="button" class="tool" title="قائمة">&#9776;</button>
        <span class="sep"></span>
        <button type="button" class="tool" title="السابق">&#8250;</button>
        <span class="page">الملف ${activeIndex + 1} / ${documentCount} • ${pages} صفحة</span>
        <button type="button" class="tool" title="التالي">&#8249;</button>
        <span class="sep"></span>
        <button type="button" class="tool" title="تصغير">&minus;</button>
        <span class="zoom">100%</span>
        <button type="button" class="tool" title="تكبير">+</button>
        <span class="sep"></span>
        <button type="button" class="tool" title="تحميل">&#8681;</button>
        <button type="button" class="tool" title="طباعة" onclick="window.print()">&#128424;</button>
      </div>
    `;
  },

  _wireUpload(container) {
    container.querySelectorAll("[data-upload-trigger]").forEach((trigger) => {
      trigger.addEventListener("click", () => {
        window.dispatchEvent(new CustomEvent("ws:upload-request"));
      });
      trigger.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          window.dispatchEvent(new CustomEvent("ws:upload-request"));
        }
      });
      trigger.addEventListener("dragenter", (event) => {
        event.preventDefault();
        trigger.classList.add("ws-doc-dragover");
      });
      trigger.addEventListener("dragover", (event) => {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
        trigger.classList.add("ws-doc-dragover");
      });
      trigger.addEventListener("dragleave", () => {
        trigger.classList.remove("ws-doc-dragover");
      });
      trigger.addEventListener("drop", (event) => {
        event.preventDefault();
        trigger.classList.remove("ws-doc-dragover");
        const files = event.dataTransfer ? [...event.dataTransfer.files] : [];
        if (files.length) {
          window.dispatchEvent(new CustomEvent("ws:upload-files", { detail: { files } }));
        }
      });
    });
  },

  _thumbsHtml(props) {
    const documents = (props.documents && props.documents.length)
      ? props.documents
      : [{
          documentId: props.documentId,
          fileName: props.fileName,
          mimeType: props.mimeType,
          previewUrl: props.previewUrl,
          fileSize: props.fileSize,
          pageCount: props.pageCount || props.page_count,
        }];
    const thumbs = documents.map((doc, index) => {
      const id = doc.documentId || doc.id;
      const name = doc.fileName || doc.original_filename || `ملف ${index + 1}`;
      const mime = (doc.mimeType || doc.mime_type || "").toLowerCase();
      const url = doc.previewUrl || doc.preview_url || "";
      const isPdf = mime === "application/pdf" || name.toLowerCase().endsWith(".pdf");
      const preview = isPdf
        ? `<span class="ws-doc-thumb-pdf">PDF</span>`
        : `<img src="${url}" alt="${this._esc(name)}" onerror="this.style.display='none'"/>`;
      return `<button type="button" class="ws-doc-thumb ${id === props.documentId ? "active" : ""}" data-doc-index="${index}" title="${this._esc(name)}">${preview}<span class="ws-doc-thumb-index">${index + 1}</span></button>`;
    }).join("");
    const addBtn = `<button type="button" class="ws-doc-add" data-upload-trigger><span style="font-size:18px">&#8681;</span>إضافة ملفات أخرى</button>`;
    return `<div class="ws-doc-thumbs">${thumbs}${addBtn}</div>`;
  },

  _wireDocumentSelection(container, spec) {
    const props = { ...(spec.props || {}) };
    const liveScan = container.__documentScanState;
    if (liveScan) {
      props.scan_active = !!liveScan.active;
      props.scan_progress = liveScan.progress || 0;
      props.scan_stage = liveScan.stage || "";
      props.scan_error = !!liveScan.error;
    }
    const documents = props.documents || [];
    container.querySelectorAll("[data-doc-index]").forEach((button) => {
      button.addEventListener("click", () => {
        const doc = documents[Number(button.dataset.docIndex)];
        if (!doc) return;
        const selected = {
          ...props,
          documentId: doc.documentId || doc.id,
          fileName: doc.fileName || doc.original_filename,
          mimeType: doc.mimeType || doc.mime_type,
          previewUrl: doc.previewUrl || doc.preview_url,
          fileSize: doc.fileSize ?? doc.file_size,
          pageCount: doc.pageCount ?? doc.page_count,
          status: doc.status || "preview_ready",
        };
        this.render(container, { ...spec, props: selected });
      });
    });
  },

  _scanOverlayHtml(active, progress) {
    return `
      <div class="ws-scan-overlay ${active ? "active" : ""}" data-progress="${progress}" aria-live="polite">
        <div class="ws-scan-shimmer"></div>
        <div class="ws-scan-beam">
          <div class="ws-scan-line"></div>
        </div>
        <div class="ws-scan-status">
          <span class="ws-scan-status-dot"></span>
          <span class="ws-scan-stage">${active ? "جاري فحص المستند" : "جاهز للمسح"}</span>
          <strong class="ws-scan-percent">${progress}%</strong>
        </div>
      </div>
    `;
  },

  _loadingHtml() {
    return `
      <div class="ws-doc-viewer">
        <div class="ws-doc-loading">
          <div class="ws-doc-skeleton"></div>
          <p>جاري تحميل المعاينة...</p>
        </div>
      </div>
    `;
  },

  _errorHtml(message) {
    return `
      <div class="ws-doc-viewer">
        <div class="ws-doc-error" role="alert">${this._esc(message)}</div>
      </div>
    `;
  },

  updateScan(container, payload) {
    const previous = container.__documentScanState || {};
    const active = payload.active === undefined ? !!previous.active : !!payload.active;
    const requestedProgress = Math.max(
      0,
      Math.min(100, Number(payload.progress ?? previous.progress ?? 0))
    );
    const progress = active && previous.active
      ? Math.max(Number(previous.progress || 0), requestedProgress)
      : requestedProgress;
    const state = {
      ...previous,
      ...payload,
      active,
      progress,
      error: !!payload.error,
    };
    container.__documentScanState = state;

    const paper = container.querySelector(".ws-doc-paper");
    if (!paper) {
      if (active) this._startScanTicker(container);
      else this._stopScanTicker(container);
      return;
    }

    let overlay = paper.querySelector(".ws-scan-overlay");
    if (!overlay) {
      paper.insertAdjacentHTML("beforeend", this._scanOverlayHtml(false, 0));
      overlay = paper.querySelector(".ws-scan-overlay");
    }

    overlay.classList.toggle("active", active);
    overlay.classList.toggle("complete", !active && progress >= 100 && !payload.error);
    overlay.classList.toggle("failed", !!payload.error);
    overlay.dataset.progress = String(progress);
    overlay.style.setProperty("--scan-progress", `${progress}%`);

    const stage = overlay.querySelector(".ws-scan-stage");
    if (stage) {
      stage.textContent = payload.stage
        || (payload.error ? "تعذّر فحص المستند" : (active ? "جاري فحص المستند" : "اكتمل فحص المستند"));
    }
    const percent = overlay.querySelector(".ws-scan-percent");
    if (percent) percent.textContent = `${Math.round(progress)}%`;
    if (active) this._startScanTicker(container);
    else this._stopScanTicker(container);

    const hint = container.querySelector(".ws-doc-scan-hint");
    if (hint) {
      hint.textContent = active ? `جاري المسح... ${progress}%` : "اكتمل المسح البصري";
      hint.style.color = active ? "#6366f1" : "#15803d";
    }
  },

  _startScanTicker(container) {
    if (container.__documentScanTimer) return;
    container.__documentScanTimer = window.setInterval(() => {
      const state = container.__documentScanState;
      if (!container.isConnected || !state || !state.active) {
        this._stopScanTicker(container);
        return;
      }
      const current = Number(state.progress || 0);
      const step = current < 70 ? 1 : 0.5;
      const next = Math.min(97, current + step);
      if (next <= current) return;
      this.updateScan(container, { ...state, progress: next });
    }, 800);
  },

  _stopScanTicker(container) {
    if (!container.__documentScanTimer) return;
    window.clearInterval(container.__documentScanTimer);
    container.__documentScanTimer = null;
  },

  _applyScanState(container, props) {
    const liveScan = container.__documentScanState;
    if (liveScan || props.scan_active || props.scan_progress) {
      this.updateScan(container, {
        active: liveScan ? !!liveScan.active : !!props.scan_active,
        progress: liveScan ? (liveScan.progress || 0) : (props.scan_progress || 0),
        stage: liveScan ? liveScan.stage : props.scan_stage,
        error: liveScan ? !!liveScan.error : !!props.scan_error,
      });
    }
  },

  _formatSize(bytes) {
    const n = Number(bytes);
    if (!n || Number.isNaN(n)) return "";
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  },

  _esc(text) {
    const d = document.createElement("div");
    d.textContent = text || "";
    return d.innerHTML;
  },
};

window.DocumentViewerWindow = DocumentViewerWindow;
