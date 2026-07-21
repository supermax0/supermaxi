(function () {
  "use strict";

  var STORAGE_KEY = "finora_notification_sound";
  var audioCtx = null;
  var unlocked = false;

  function isEnabled() {
    try {
      return localStorage.getItem(STORAGE_KEY) !== "off";
    } catch (e) {
      return true;
    }
  }

  function setEnabled(on) {
    try {
      localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
    } catch (e) {}
    document.dispatchEvent(new CustomEvent("finora:notification-sound-changed", {
      detail: { enabled: !!on }
    }));
  }

  function getContext() {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtx) audioCtx = new Ctx();
    if (audioCtx.state === "suspended") {
      audioCtx.resume().catch(function () {});
    }
    return audioCtx;
  }

  function playTone(freq, duration, wave, volume, delay) {
    var ctx = getContext();
    if (!ctx) return;

    var start = ctx.currentTime + (delay || 0);
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    var vol = Math.min(Math.max(volume || 0.35, 0.0001), 0.72);

    osc.type = wave || "square";
    osc.frequency.setValueAtTime(freq, start);

    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(vol, start + 0.008);
    gain.gain.setValueAtTime(vol, start + Math.max(duration - 0.04, 0.02));
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.03);
  }

  function playBuzzPulse(freq, duration, volume, delay) {
    playTone(freq, duration, "square", volume, delay);
    playTone(freq * 2, duration * 0.85, "square", (volume || 0.4) * 0.45, delay);
  }

  function playStrongBuzz() {
    playBuzzPulse(880, 0.14, 0.52, 0);
    playBuzzPulse(880, 0.14, 0.52, 0.18);
    playBuzzPulse(880, 0.14, 0.52, 0.36);
    playBuzzPulse(660, 0.32, 0.48, 0.54);
  }

  /** تسديد — رنين نقدي صاعد قوي */
  function playPaymentSound() {
    playTone(660, 0.1, "square", 0.48, 0);
    playTone(880, 0.11, "square", 0.52, 0.1);
    playTone(1174.66, 0.14, "square", 0.55, 0.2);
    playBuzzPulse(1318.51, 0.28, 0.5, 0.34);
  }

  /** إرجاع — buzz هابط تحذيري قوي */
  function playReturnSound() {
    playBuzzPulse(740, 0.14, 0.52, 0);
    playBuzzPulse(554, 0.16, 0.5, 0.16);
    playTone(415, 0.22, "sawtooth", 0.48, 0.34);
    playBuzzPulse(370, 0.3, 0.46, 0.52);
  }

  /** إلغاء — buzz منخفض حاد */
  function playCancelSoundFx() {
    playTone(220, 0.16, "sawtooth", 0.55, 0);
    playBuzzPulse(185, 0.18, 0.52, 0.14);
    playTone(165, 0.22, "square", 0.5, 0.3);
    playBuzzPulse(147, 0.34, 0.48, 0.48);
  }

  function inferSoundTypeFromMessage(message, fallback) {
    var msg = String(message || "");
    if (/فشل|خطأ|❌|error/i.test(msg)) return fallback || "error";
    if (/تسديد|مسدد|تحصيل|settle|paid|payment/i.test(msg)) return "payment";
    if (/ترجيع|إرجاع|ارجاع|مرتجع|راجعة|return/i.test(msg)) return "return";
    if (/إلغاء|الغاء|ملغي|cancel/i.test(msg)) return "cancel";
    return fallback || "info";
  }

  function playNotificationSound(type, options) {
    options = options || {};
    if (options.silent || !isEnabled()) return;

    getContext();
    if (!audioCtx) return;

    var soundType = options.soundType || type || "info";
    if (options.inferFromMessage && options.message) {
      soundType = inferSoundTypeFromMessage(options.message, soundType);
    }

    switch (soundType) {
      case "payment":
      case "paid":
      case "settle":
        playPaymentSound();
        break;
      case "return":
      case "returned":
        playReturnSound();
        break;
      case "cancel":
      case "cancelled":
      case "canceled":
        playCancelSoundFx();
        break;
      case "success":
        playTone(523.25, 0.12, "square", 0.38, 0);
        playTone(659.25, 0.16, "square", 0.42, 0.11);
        playTone(783.99, 0.2, "square", 0.36, 0.24);
        break;
      case "error":
        playTone(220, 0.2, "sawtooth", 0.4, 0);
        playTone(185, 0.28, "sawtooth", 0.38, 0.16);
        break;
      case "warning":
        playBuzzPulse(440, 0.14, 0.45, 0);
        playBuzzPulse(440, 0.14, 0.45, 0.18);
        break;
      case "order":
      case "buzz":
        playStrongBuzz();
        break;
      default:
        playStrongBuzz();
        break;
    }
  }

  function unlockAudio() {
    if (unlocked) return;
    unlocked = true;
    getContext();
  }

  ["click", "touchstart", "keydown"].forEach(function (evt) {
    document.addEventListener(evt, unlockAudio, { once: true, passive: true });
  });

  window.playNotificationSound = playNotificationSound;
  window.finoraInferNotificationSound = inferSoundTypeFromMessage;
  window.finoraNotificationSoundEnabled = isEnabled;
  window.finoraSetNotificationSound = setEnabled;
})();
