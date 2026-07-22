(function () {
  "use strict";

  var STORAGE_KEY = "finora_notification_sound";
  var LEGACY_SOUNDS_KEY = "sounds_enabled";
  var MAP_KEY = "finora_sound_event_map";
  var audioCtx = null;
  var unlocked = false;

  var EVENTS = ["payment", "return", "cancel", "order"];

  var EVENT_LABELS = {
    payment: "تسديد",
    return: "إرجاع",
    cancel: "إلغاء",
    order: "طلب جديد",
  };

  var DEFAULT_MAP = {
    payment: "s02",
    return: "s03",
    cancel: "s04",
    order: "s01",
  };

  var PRESETS = window.FINORA_SOUND_PRESETS || {};

  var ACTION_TYPES = {
    payment: true,
    paid: true,
    settle: true,
    return: true,
    returned: true,
    cancel: true,
    cancelled: true,
    canceled: true,
    order: true,
    buzz: true,
  };

  function isEnabled() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      if (v === "off") return false;
      if (v === "on") return true;
      var legacy = localStorage.getItem(LEGACY_SOUNDS_KEY);
      return legacy === null ? true : legacy === "true";
    } catch (e) {
      return true;
    }
  }

  function setEnabled(on) {
    try {
      localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
      localStorage.setItem(LEGACY_SOUNDS_KEY, on ? "true" : "false");
    } catch (e) {}
    dispatchChange();
  }

  function getEventSoundMap() {
    try {
      var raw = JSON.parse(localStorage.getItem(MAP_KEY) || "{}");
      var legacy = {
        chime: "s01", cash: "s02", slide: "s03", soft: "s04", bell: "s05",
        ping: "s06", melody: "s07", drop: "s08", alert: "s09", tone: "s10",
      };
      var map = {};
      EVENTS.forEach(function (ev) {
        var preset = raw[ev] || DEFAULT_MAP[ev];
        if (legacy[preset]) preset = legacy[preset];
        map[ev] = PRESETS[preset] ? preset : DEFAULT_MAP[ev];
      });
      return map;
    } catch (e) {
      return Object.assign({}, DEFAULT_MAP);
    }
  }

  function setEventSound(event, presetId) {
    if (EVENTS.indexOf(event) < 0 || !PRESETS[presetId]) return false;
    var map = getEventSoundMap();
    map[event] = presetId;
    try {
      localStorage.setItem(MAP_KEY, JSON.stringify(map));
    } catch (e) {
      return false;
    }
    dispatchChange();
    return true;
  }

  function resetEventSoundMap() {
    try {
      localStorage.removeItem(MAP_KEY);
    } catch (e) {}
    dispatchChange();
  }

  function dispatchChange() {
    document.dispatchEvent(new CustomEvent("finora:notification-sound-changed", {
      detail: {
        enabled: isEnabled(),
        map: getEventSoundMap(),
      },
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

  function playChime(freq, duration, options) {
    var ctx = getContext();
    if (!ctx) return;

    options = options || {};
    var start = ctx.currentTime + (options.delay || 0);
    var vol = Math.min(Math.max(options.volume || 0.22, 0.0001), 0.45);
    var wave = options.wave || "sine";
    var dur = duration || 0.18;

    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    var filter = ctx.createBiquadFilter();

    osc.type = wave;
    osc.frequency.setValueAtTime(freq, start);
    if (options.slideTo) {
      osc.frequency.exponentialRampToValueAtTime(
        Math.max(options.slideTo, 40),
        start + dur * 0.85
      );
    }

    filter.type = "lowpass";
    filter.frequency.setValueAtTime(options.filterFreq || 2400, start);
    filter.Q.setValueAtTime(0.7, start);

    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(vol, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);

    osc.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + dur + 0.05);
  }

  function playPresetNotes(presetId) {
    var preset = PRESETS[presetId];
    if (!preset) return;
    getContext();
    if (!audioCtx) return;
    preset.notes.forEach(function (n) {
      playChime(n.freq, n.dur, n);
    });
  }

  function playPreset(presetId, options) {
    options = options || {};
    if (!options.force && (options.silent || !isEnabled())) return;
    playPresetNotes(presetId);
  }

  function playPresetForEvent(event, options) {
    var map = getEventSoundMap();
    var ev = normalizeActionType(event);
    var presetId = map[ev] || DEFAULT_MAP[ev];
    playPreset(presetId, options);
  }

  function inferActionSoundFromMessage(message) {
    var msg = String(message || "");
    if (/تسديد|مسدد|تحصيل|settle|paid|payment/i.test(msg)) return "payment";
    if (/ترجيع|إرجاع|ارجاع|مرتجع|راجعة|return/i.test(msg)) return "return";
    if (/إلغاء|الغاء|ملغي|cancel/i.test(msg)) return "cancel";
    if (/طلب جديد|كشف المندوب|new order/i.test(msg)) return "order";
    return null;
  }

  function normalizeActionType(type) {
    var key = String(type || "").toLowerCase();
    if (key === "paid" || key === "settle") return "payment";
    if (key === "returned") return "return";
    if (key === "cancelled" || key === "canceled") return "cancel";
    if (key === "buzz") return "order";
    return key;
  }

  function isActionSound(type) {
    return !!ACTION_TYPES[normalizeActionType(type)];
  }

  function playOrderActionSound(type, options) {
    options = options || {};
    if (options.silent || !isEnabled()) return;
    var event = normalizeActionType(type);
    if (!isActionSound(event)) return;
    playPresetForEvent(event, options);
  }

  function playNotificationSound(type, options) {
    options = options || {};
    if (options.silent || !isEnabled()) return;

    var soundType = options.soundType || type || "";
    if (!soundType && options.message) {
      soundType = inferActionSoundFromMessage(options.message) || "";
    }
    soundType = normalizeActionType(soundType);
    if (!isActionSound(soundType)) return;
    playOrderActionSound(soundType, options);
  }

  function getSoundPresets() {
    return Object.keys(PRESETS).sort().map(function (id) {
      return { id: id, name: PRESETS[id].name };
    });
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
  window.playOrderActionSound = playOrderActionSound;
  window.finoraInferNotificationSound = inferActionSoundFromMessage;
  window.finoraNotificationSoundEnabled = isEnabled;
  window.finoraSetNotificationSound = setEnabled;
  window.finoraGetSoundPresets = getSoundPresets;
  window.finoraGetSoundEventLabels = function () { return Object.assign({}, EVENT_LABELS); };
  window.finoraGetEventSoundMap = getEventSoundMap;
  window.finoraSetEventSound = setEventSound;
  window.finoraResetEventSoundMap = resetEventSoundMap;
  window.finoraPreviewSoundPreset = function (presetId) {
    playPreset(presetId, { force: true });
  };
  window.finoraPreviewEventSound = function (event) {
    playPresetForEvent(event, { force: true });
  };
})();
