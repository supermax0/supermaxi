/**
 * Document viewer — Phase 2: real PDF/image preview + scan overlay.
 */
const DocumentViewerWindow = {
  render(container, spec) {
    const props = spec.props || {};
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
      this._wireAdd(container);
      return;
    }

    container.innerHTML = this._placeholderHtml(props);
    this._applyScanState(container, props);
  },

  _placeholderHtml(props) {
    const scanActive = !!props.scan_active;
    const progress = props.scan_progress || 0;
    return `
      <div class="ws-doc-viewer">
        <div class="ws-doc-meta ws-doc-meta-empty">
          <span>لم يُرفع مستند بعد</span>
        </div>
        <div class="ws-doc-paper">
          <div class="ws-doc-placeholder">
            <div class="ws-doc-lines">
              <div class="ws-doc-line" style="width:90%"></div>
              <div class="ws-doc-line" style="width:75%"></div>
              <div class="ws-doc-line" style="width:85%"></div>
            </div>
            <p class="ws-doc-hint">ارفع PDF أو صورة من شريط الأدوات</p>
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
    return `
      <div class="ws-doc-toolbar">
        <button type="button" class="tool" title="قائمة">&#9776;</button>
        <span class="sep"></span>
        <button type="button" class="tool" title="السابق">&#8250;</button>
        <span class="page">1 / ${pages}</span>
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

  _wireAdd(container) {
    const btn = container.querySelector("#ws-doc-add-more");
    if (btn) {
      btn.addEventListener("click", () => {
        window.dispatchEvent(new CustomEvent("ws:upload-request"));
      });
    }
  },

  _thumbsHtml(props) {
    const thumb = props.previewUrl
      ? `<div class="ws-doc-thumb active"><img src="${props.previewUrl}" alt="صفحة" onerror="this.style.display='none'"/></div>`
      : `<div class="ws-doc-thumb active"></div>`;
    const addBtn = `<button type="button" class="ws-doc-add" id="ws-doc-add-more"><span style="font-size:18px">&#8681;</span>إضافة ملفات أخرى</button>`;
    return `<div class="ws-doc-thumbs">${thumb}${addBtn}</div>`;
  },

  _scanOverlayHtml(active, progress) {
    return `
      <div class="ws-scan-overlay ${active ? "active" : ""}" data-progress="${progress}">
        <div class="ws-scan-shimmer"></div>
        <div class="ws-scan-line" style="top:${progress}%"></div>
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
    const paper = container.querySelector(".ws-doc-paper");
    if (!paper) return;

    let overlay = paper.querySelector(".ws-scan-overlay");
    if (!overlay) {
      paper.insertAdjacentHTML("beforeend", this._scanOverlayHtml(false, 0));
      overlay = paper.querySelector(".ws-scan-overlay");
    }

    const active = !!payload.active;
    const progress = payload.progress ?? 0;
    overlay.classList.toggle("active", active);
    overlay.dataset.progress = String(progress);
    const line = overlay.querySelector(".ws-scan-line");
    if (line) line.style.top = `${progress}%`;

    const hint = container.querySelector(".ws-doc-scan-hint");
    if (hint) {
      hint.textContent = active ? `جاري المسح... ${progress}%` : "اكتمل المسح البصري";
      hint.style.color = active ? "#6366f1" : "#15803d";
    }
  },

  _applyScanState(container, props) {
    if (props.scan_active || props.scan_progress) {
      this.updateScan(container, {
        active: !!props.scan_active,
        progress: props.scan_progress || 0,
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
