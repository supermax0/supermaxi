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
      <div class="ws-leon-core">
        <div class="ws-leon-face">
          <span class="ws-leon-eye"></span>
          <span class="ws-leon-eye"></span>
        </div>
      </div>
    `;
    this.bubbleEl = this.el.querySelector(".ws-leon-bubble");
    this.layer.appendChild(this.el);
    this.moveTo(0.5, 0.55, false);
  }

  setMode(mode) {
    this.mode = mode || "idle";
    this.el.className = `ws-leon ws-leon-mode-${this.mode}`;
  }

  moveTo(relX, relY, animate = true) {
    const { width, height } = this.canvas.getSize();
    const x = (relX ?? 0.5) * width;
    const y = (relY ?? 0.55) * height;
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
