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
    this.bubbleTextEl = null;
    this.bubbleHintEl = null;
    this.voiceButtonEl = null;
    this.accentModeEl = null;
    this.accentValueEl = null;
    this.accentGaugeEl = null;
    this.taskEl = null;
    this.voiceEnabled = true;
    this._militaryVoice = null;
    this._lastVoiceMode = "";
    try {
      this.voiceEnabled = localStorage.getItem("finora.leon.voice") !== "off";
    } catch (_) {
      this.voiceEnabled = true;
    }
    this._init();
  }

  _init() {
    this.el = document.createElement("div");
    this.el.className = "ws-leon ws-leon-mode-idle";
    this.el.innerHTML = `
      <div class="ws-leon-bubble" role="status" aria-live="polite">
        <div class="ws-leon-bubble-accent" aria-hidden="true">
          <div class="ws-leon-accent-live">
            <span class="ws-leon-accent-live-dot"></span>
            <span>LIVE</span>
          </div>
          <div class="ws-leon-accent-gauge">
            <div class="ws-leon-accent-gauge-core">
              <strong class="ws-leon-accent-value">ON</strong>
            </div>
          </div>
          <strong class="ws-leon-accent-mode">READY</strong>
          <span class="ws-leon-accent-caption">SYSTEM STATUS</span>
        </div>
        <div class="ws-leon-bubble-shell">
          <div class="ws-leon-bubble-kicker">
            <span class="ws-leon-kicker-dot"></span>
            <span>LEON • FINORA AI</span>
          </div>
          <div class="ws-leon-bubble-text"></div>
          <div class="ws-leon-bubble-footer">
            <span class="ws-leon-bubble-hint">اسألني عن التقارير، المبيعات، المصاريف أو أي موضوع مالي</span>
            <div class="ws-leon-bubble-actions">
              <button type="button" class="ws-leon-bubble-voice" title="تشغيل أو إيقاف صوت LEON" aria-label="تشغيل أو إيقاف صوت LEON">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 9v6h4l5 4V5L9 9H5Z"></path>
                  <path class="ws-leon-sound-wave" d="M17 9.5c1.2 1.4 1.2 3.6 0 5"></path>
                  <path class="ws-leon-sound-wave" d="M19.5 7c2.6 2.8 2.6 7.2 0 10"></path>
                </svg>
              </button>
              <button type="button" class="ws-leon-bubble-chat" title="اكتب أمراً إلى LEON" aria-label="اكتب أمراً إلى LEON">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M20 11.5a8 8 0 0 1-8.5 8 8.7 8.7 0 0 1-3.4-.8L4 20l1.3-3.7A8 8 0 1 1 20 11.5Z"></path>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
      <div class="ws-leon-orb-wrap">
        <div class="ws-leon-halo"></div>
        <div class="ws-leon-energy-ring ws-leon-energy-ring-one"></div>
        <div class="ws-leon-energy-ring ws-leon-energy-ring-two"></div>
        <div class="ws-leon-particles" aria-hidden="true">
          <i></i><i></i><i></i>
        </div>
        <div class="ws-leon-core">
          <span class="ws-leon-data-bus" aria-hidden="true"></span>
          <span class="ws-leon-data-port ws-leon-data-port-output" title="مخرجات LEON إلى التقرير" aria-hidden="true"></span>
          <span class="ws-leon-eye"></span>
          <span class="ws-leon-eye"></span>
          <span class="ws-leon-data-port ws-leon-data-port-input" title="بيانات المستند الداخلة إلى LEON" aria-hidden="true"></span>
        </div>
      </div>
      <div class="ws-leon-platform"></div>
      <div class="ws-leon-task"><span class="ws-leon-task-dot"></span><span class="ws-leon-task-text">جاهز</span></div>
    `;
    this.bubbleEl = this.el.querySelector(".ws-leon-bubble");
    this.bubbleTextEl = this.el.querySelector(".ws-leon-bubble-text");
    this.bubbleHintEl = this.el.querySelector(".ws-leon-bubble-hint");
    this.voiceButtonEl = this.el.querySelector(".ws-leon-bubble-voice");
    this.accentModeEl = this.el.querySelector(".ws-leon-accent-mode");
    this.accentValueEl = this.el.querySelector(".ws-leon-accent-value");
    this.accentGaugeEl = this.el.querySelector(".ws-leon-accent-gauge");
    this.taskEl = this.el.querySelector(".ws-leon-task-text");
    this.voiceButtonEl.addEventListener("click", (event) => {
      event.stopPropagation();
      this.toggleVoice();
    });
    this.el.querySelector(".ws-leon-bubble-chat").addEventListener("click", (event) => {
      event.stopPropagation();
      const input = document.getElementById("ws-chat-input");
      if (input) input.focus();
      this.speakMilitary("Awaiting your command.");
    });
    this._updateVoiceButton();
    this.layer.appendChild(this.el);
    this.moveTo(0.5, 0.5, false);
  }

  setMode(mode) {
    const previousMode = this.mode;
    this.mode = mode || "idle";
    this.el.className = `ws-leon ws-leon-mode-${this.mode}`;
    const taskLabels = {
      idle: "جاهز",
      ready: "جاهز",
      thinking: "أفكر وأراجع بيانات النظام",
      reading_document: "أقرأ المستند",
      scanning: "أفحص الصورة",
      matching: "أطابق السجلات",
      running: "أعمل على المهمة",
      executing: "أنفّذ المهمة",
      waiting_approval: "بانتظار موافقتك",
      waiting_user: "بانتظارك",
      success: "اكتمل العمل",
      completed: "اكتمل العمل",
      warning: "يحتاج مراجعة",
      error: "تعذّر إكمال المهمة",
      failed: "تعذّر إكمال المهمة",
    };
    this.setTask(taskLabels[this.mode] || "أعمل على المهمة");
    const hintLabels = {
      thinking: "جاري تحليل طلبك ومراجعة بيانات النظام",
      reading_document: "جاري تحسين الصورة وقراءة محتوى المستند",
      scanning: "المسح البصري نشط الآن",
      matching: "جاري مطابقة الطلبات والحسابات",
      running: "المهمة قيد العمل — يرجى الانتظار",
      executing: "التنفيذ الفعلي جارٍ الآن",
      waiting_approval: "راجع الخطة ثم أعطِ موافقتك قبل التنفيذ",
      success: "اكتب أمراً جديداً أو اضغط زر المحادثة للمتابعة",
      completed: "اكتب أمراً جديداً أو اضغط زر المحادثة للمتابعة",
      warning: "تحتاج هذه النتيجة إلى مراجعتك",
      error: "راجع الخطأ الظاهر ثم حاول مرة أخرى",
      failed: "راجع الخطأ الظاهر ثم حاول مرة أخرى",
    };
    this.setHint(hintLabels[this.mode] || "اسألني عن التقارير، المبيعات، المصاريف أو أي موضوع مالي");
    this.setAccentMode(this.mode);
    window.dispatchEvent(new CustomEvent("ws:leon-mode-changed", {
      detail: { mode: this.mode, previousMode },
    }));
    if (this.mode !== previousMode) this._announceMode(this.mode);
  }

  setAccentMode(mode) {
    if (!this.accentModeEl) return;
    const labels = {
      idle: "READY",
      ready: "READY",
      thinking: "THINKING",
      reading_document: "READING",
      scanning: "SCANNING",
      matching: "MATCHING",
      running: "RUNNING",
      executing: "EXECUTING",
      waiting_approval: "APPROVAL",
      waiting_user: "AWAITING",
      success: "COMPLETE",
      completed: "COMPLETE",
      warning: "REVIEW",
      error: "ERROR",
      failed: "ERROR",
    };
    this.accentModeEl.textContent = labels[mode] || "ACTIVE";
    this.el.dataset.accentMode = mode || "idle";
  }

  setTask(text) {
    if (!this.taskEl) return;
    this.taskEl.textContent = text || "جاهز";
  }

  setHint(text) {
    if (!this.bubbleHintEl) return;
    this.bubbleHintEl.textContent = text || "";
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
      this.bubbleTextEl.textContent = "";
      return;
    }
    this.bubbleTextEl.textContent = text;
    this.bubbleEl.classList.add("visible");
    if (options.duration) {
      clearTimeout(this._bubbleTimer);
      this._bubbleTimer = setTimeout(() => this.speak(""), options.duration);
    }
  }

  _selectMilitaryVoice() {
    if (this._militaryVoice) return this._militaryVoice;
    if (!("speechSynthesis" in window)) return null;
    const voices = window.speechSynthesis.getVoices() || [];
    const englishVoices = voices.filter((voice) => /^en[-_]/i.test(voice.lang || ""));
    const preferredNames = [
      /Microsoft Mark/i,
      /Microsoft David/i,
      /Microsoft Guy/i,
      /Google US English/i,
      /Daniel/i,
      /Alex/i,
    ];
    for (const pattern of preferredNames) {
      const matched = englishVoices.find((voice) => pattern.test(voice.name || ""));
      if (matched) {
        this._militaryVoice = matched;
        return matched;
      }
    }
    this._militaryVoice = englishVoices[0] || voices[0] || null;
    return this._militaryVoice;
  }

  speakMilitary(phrase) {
    if (!this.voiceEnabled || !phrase || !("speechSynthesis" in window)) return;
    try {
      const utterance = new SpeechSynthesisUtterance(phrase);
      const voice = this._selectMilitaryVoice();
      if (voice) utterance.voice = voice;
      utterance.lang = "en-US";
      utterance.rate = 0.88;
      utterance.pitch = 0.72;
      utterance.volume = 0.92;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
    } catch (_) {
      // The visual state remains the fallback when speech synthesis is unavailable.
    }
  }

  _announceMode(mode) {
    const phrases = {
      thinking: "Command received. Analyzing the situation.",
      reading_document: "Document received. Beginning scan.",
      scanning: "Optical scan in progress.",
      matching: "Cross checking records. Stand by.",
      running: "Operation in progress. Stand by.",
      executing: "Execution in progress. Stand by.",
      waiting_approval: "Approval required. Awaiting command.",
      success: "Mission complete. Response ready.",
      completed: "Mission complete. Response ready.",
      warning: "Attention. Manual review required.",
      error: "Mission interrupted. Check the reported error.",
      failed: "Mission interrupted. Check the reported error.",
    };
    const phrase = phrases[mode];
    if (!phrase || this._lastVoiceMode === mode) return;
    this._lastVoiceMode = mode;
    this.speakMilitary(phrase);
  }

  _updateVoiceButton() {
    if (!this.voiceButtonEl) return;
    this.voiceButtonEl.classList.toggle("muted", !this.voiceEnabled);
    this.voiceButtonEl.setAttribute("aria-pressed", this.voiceEnabled ? "true" : "false");
    this.voiceButtonEl.title = this.voiceEnabled ? "إيقاف صوت LEON" : "تشغيل صوت LEON";
  }

  toggleVoice(force) {
    this.voiceEnabled = typeof force === "boolean" ? force : !this.voiceEnabled;
    try {
      localStorage.setItem("finora.leon.voice", this.voiceEnabled ? "on" : "off");
    } catch (_) {
      // Local storage can be unavailable in private browsing.
    }
    if (!this.voiceEnabled && "speechSynthesis" in window) window.speechSynthesis.cancel();
    this._updateVoiceButton();
    if (this.voiceEnabled) this.speakMilitary("Voice channel active. Awaiting command.");
  }

  playTone(kind = "info") {
    if (this.voiceEnabled && "speechSynthesis" in window) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      this._audioContext = this._audioContext || new AudioCtx();
      const ctx = this._audioContext;
      if (ctx.state === "suspended") ctx.resume();
      const patterns = {
        success: [523.25, 659.25, 783.99],
        error: [392, 293.66],
        warning: [440, 440],
        info: [523.25],
      };
      const notes = patterns[kind] || patterns.info;
      const start = ctx.currentTime;
      notes.forEach((frequency, index) => {
        const oscillator = ctx.createOscillator();
        const gain = ctx.createGain();
        const noteStart = start + index * 0.11;
        oscillator.type = kind === "error" ? "sawtooth" : "sine";
        oscillator.frequency.setValueAtTime(frequency, noteStart);
        gain.gain.setValueAtTime(0.0001, noteStart);
        gain.gain.exponentialRampToValueAtTime(0.08, noteStart + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001, noteStart + 0.16);
        oscillator.connect(gain);
        gain.connect(ctx.destination);
        oscillator.start(noteStart);
        oscillator.stop(noteStart + 0.18);
      });
    } catch (_) {
      // بعض المتصفحات تمنع الصوت؛ يبقى الإشعار المرئي هو البديل.
    }
  }

  setProgress(p) {
    const hasProgress = p !== null && p !== undefined && p !== "";
    const numeric = Number(p);
    let value = hasProgress && Number.isFinite(numeric)
      ? Math.max(0, Math.min(100, numeric))
      : 0;
    const isComplete = this.mode === "success" || this.mode === "completed";
    const isReady = this.mode === "idle" || this.mode === "ready";
    if (isComplete) value = 100;
    const showProgress = hasProgress && !(isReady && value === 0);
    this.el.dataset.progress = showProgress ? String(value) : "";
    if (this.accentGaugeEl) {
      this.accentGaugeEl.style.setProperty("--leon-progress", `${value}%`);
      this.accentGaugeEl.classList.toggle("has-progress", showProgress);
    }
    if (this.accentValueEl) {
      this.accentValueEl.textContent = showProgress ? `${Math.round(value)}%` : "ON";
    }
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
