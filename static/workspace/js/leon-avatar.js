/**
 * LEON avatar adapter — lightweight CSS avatar (Phase 1).
 * Designed for later swap to Three.js AssistantCharacter.
 */
class LeonAvatarAdapter {
  constructor(layerEl, canvasHelper) {
    this.layer = layerEl;
    this.canvas = canvasHelper;
    this.mode = "idle";
    this.el = null;
    this.bubbleEl = null;
    this._init();
  }

  _init() {
    this.el = document.createElement("div");
    this.el.className = "ws-leon ws-leon-mode-idle";
    this.el.innerHTML = `
      <div class="ws-leon-bubble"></div>
      <div class="ws-leon-orb-wrap">
        <div class="ws-leon-halo"></div>
        <div class="ws-leon-core">
          <span class="ws-leon-eye"></span>
          <span class="ws-leon-eye"></span>
        </div>
      </div>
      <div class="ws-leon-platform"></div>
    `;
    this.bubbleEl = this.el.querySelector(".ws-leon-bubble");
    this.layer.appendChild(this.el);
    this.moveTo(0.5, 0.5, false);
  }

  setMode(mode) {
    this.mode = mode || "idle";
    this.el.className = `ws-leon ws-leon-mode-${this.mode}`;
  }

  _safeLane(relX, width) {
    // Keep LEON inside the center gap between the left and right window
    // columns so it never covers the document viewer or report.
    if (width < 900) return 0.5;
    const colW = Math.min(460, Math.round(width * 0.30));
    const rightW = Math.min(540, Math.round(width * 0.36));
    const minRel = (colW + 60) / width;
    const maxRel = (width - rightW - 60) / width;
    if (maxRel <= minRel) return 0.5;
    return Math.min(maxRel, Math.max(minRel, relX ?? 0.5));
  }

  moveTo(relX, relY, animate = true) {
    const { width, height } = this.canvas.getSize();
    const safeX = this._safeLane(relX, width);
    const x = safeX * width;
    const y = Math.min(0.72, Math.max(0.3, relY ?? 0.5)) * height;
    if (!animate) {
      this.el.style.transition = "none";
    } else {
      this.el.style.transition = "";
    }
    this.el.style.left = `${x}px`;
    this.el.style.top = `${y}px`;
    if (!animate) {
      requestAnimationFrame(() => {
        this.el.style.transition = "";
      });
    }
  }

  moveToWindow(windowSpec, anchor = "near") {
    if (!windowSpec || !windowSpec.position) return;
    const { width, height } = this.canvas.getSize();
    const pos = windowSpec.position;
    const wx = (pos.x + pos.width / 2) / width;
    const wy = (pos.y + pos.height / 2) / height;
    let tx = wx;
    let ty = wy;
    if (windowSpec.placement === "right") {
      tx = Math.max(0.15, wx - 0.12);
    } else if (windowSpec.placement === "left") {
      tx = Math.min(0.85, wx + 0.12);
    }
    this.moveTo(tx, ty);
  }

  speak(text, options = {}) {
    if (!text) {
      this.bubbleEl.classList.remove("visible");
      this.bubbleEl.textContent = "";
      return;
    }
    this.bubbleEl.textContent = text;
    this.bubbleEl.classList.add("visible");
    if (options.duration) {
      clearTimeout(this._bubbleTimer);
      this._bubbleTimer = setTimeout(() => this.speak(""), options.duration);
    }
  }

  setProgress(p) {
    this.el.dataset.progress = String(p ?? 0);
  }

  applyState(state) {
    if (!state) return;
    if (state.mode) this.setMode(state.mode);
    if (state.position) {
      this.moveTo(state.position.x, state.position.y);
    }
    if (state.speech) this.speak(state.speech);
    if (state.progress != null) this.setProgress(state.progress);
  }
}

window.LeonAvatarAdapter = LeonAvatarAdapter;
