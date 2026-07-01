/**
 * Document viewer window with mock scan overlay.
 */
const DocumentViewerWindow = {
  render(container, spec) {
    const props = spec.props || {};
    const scanActive = !!props.scan_active;
    const progress = props.scan_progress || 0;

    container.innerHTML = `
      <div class="ws-doc-paper">
        <div class="ws-doc-placeholder">
          <div class="ws-doc-lines">
            <div class="ws-doc-line" style="width:90%"></div>
            <div class="ws-doc-line" style="width:75%"></div>
            <div class="ws-doc-line" style="width:85%"></div>
            <div class="ws-doc-line" style="width:60%"></div>
            <div class="ws-doc-line" style="width:80%"></div>
          </div>
          <p style="margin-top:20px">مستند تجريبي — المرحلة 1</p>
          ${scanActive ? `<p style="font-size:12px;color:#6366f1">جاري المسح... ${progress}%</p>` : ""}
        </div>
        <div class="ws-scan-overlay ${scanActive ? "active" : ""}" data-progress="${progress}">
          <div class="ws-scan-shimmer"></div>
          <div class="ws-scan-line" style="top:${progress}%"></div>
        </div>
      </div>
    `;
  },

  updateScan(container, payload) {
    const overlay = container.querySelector(".ws-scan-overlay");
    if (!overlay) return;
    const active = !!payload.active;
    const progress = payload.progress ?? 0;
    overlay.classList.toggle("active", active);
    overlay.dataset.progress = String(progress);
    const line = overlay.querySelector(".ws-scan-line");
    if (line) line.style.top = `${progress}%`;

    const hint = container.querySelector(".ws-doc-placeholder p:last-child");
    if (hint && active) {
      hint.textContent = `جاري المسح... ${progress}%`;
      hint.style.fontSize = "12px";
      hint.style.color = "#6366f1";
    } else if (hint && !active && progress >= 100) {
      hint.textContent = "اكتمل المسح التجريبي";
      hint.style.color = "#15803d";
    }
  },
};

window.DocumentViewerWindow = DocumentViewerWindow;
