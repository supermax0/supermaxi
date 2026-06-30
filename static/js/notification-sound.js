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

    osc.type = wave || "sine";
    osc.frequency.setValueAtTime(freq, start);

    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(Math.max(volume || 0.12, 0.0001), start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.02);
  }

  function playNotificationSound(type, options) {
    options = options || {};
    if (options.silent || !isEnabled()) return;

    getContext();
    if (!audioCtx) return;

    var soundType = options.soundType || type || "info";

    switch (soundType) {
      case "success":
        playTone(523.25, 0.1, "sine", 0.16, 0);
        playTone(659.25, 0.14, "sine", 0.18, 0.1);
        break;
      case "error":
        playTone(220, 0.16, "triangle", 0.14, 0);
        playTone(185, 0.22, "triangle", 0.12, 0.14);
        break;
      case "warning":
        playTone(440, 0.11, "triangle", 0.13, 0);
        playTone(440, 0.11, "triangle", 0.13, 0.15);
        break;
      case "order":
        playTone(784, 0.09, "sine", 0.18, 0);
        playTone(988, 0.11, "sine", 0.2, 0.09);
        playTone(1174.66, 0.15, "sine", 0.16, 0.18);
        break;
      default:
        playTone(587.33, 0.12, "sine", 0.13, 0);
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
  window.finoraNotificationSoundEnabled = isEnabled;
  window.finoraSetNotificationSound = setEnabled;
})();
