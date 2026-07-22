(function (window) {
  "use strict";

  var NAMES = [
    "نغمة هادئة", "نجاح مالي", "هبوط ناعم", "إلغاء خفيف", "جرس ذهبي",
    "تنبيه قصير", "لحن صاعد", "قطرة ماء", "تنبيه مزدوج", "نغمة طويلة",
    "رنين فضي", "نبضة سريعة", "موجة بحر", "نجمة لامعة", "صدى خفيف",
    "فقاعة", "صباح مشرق", "شروق", "غروب", "نسيم عليل",
    "كريستال", "فضة", "نحاس", "لؤلؤ", "ياقوت أحمر",
    "زمرد", "عنبر", "كهرمان", "سحابة", "مطر خفيف",
    "رعد بعيد", "ريح عليا", "خطوة واثقة", "طرقة لطيفة", "فتح باب",
    "غلق ناعم", "تأكيد", "موافقة", "رفض هادئ", "انتظار",
    "اكتمال", "بداية جديدة", "نهاية هادئة", "تذكير", "إشعار فوري",
    "مكالمة", "رسالة واردة", "تحديث", "مزامنة", "ختام راقٍ",
  ];

  var BASE = [
    196, 207.65, 220, 233.08, 246.94, 261.63, 277.18, 293.66, 311.13, 329.63,
    349.23, 369.99, 392, 415.3, 440, 466.16, 493.88, 523.25, 554.37, 587.33,
    622.25, 659.25, 698.46, 739.99, 783.99, 830.61, 880, 932.33, 987.77, 1046.5,
  ];

  function note(freq, dur, extra) {
    var n = { freq: freq, dur: dur || 0.14, volume: 0.2 };
    if (extra) {
      Object.keys(extra).forEach(function (k) { n[k] = extra[k]; });
    }
    return n;
  }

  function buildNotes(i) {
    var f1 = BASE[i % BASE.length];
    var f2 = BASE[(i + 7) % BASE.length];
    var f3 = BASE[(i + 13) % BASE.length];
    var wave = i % 5 === 0 ? "triangle" : "sine";
    var pattern = i % 10;

    if (pattern === 0) {
      return [note(f1, 0.14, { filterFreq: 2800 }), note(f2, 0.2, { delay: 0.11, filterFreq: 3000, volume: 0.22 })];
    }
    if (pattern === 1) {
      return [note(f1, 0.11), note(f2, 0.12, { delay: 0.08, volume: 0.21 }), note(f3, 0.2, { delay: 0.17, volume: 0.24 })];
    }
    if (pattern === 2) {
      return [note(f2, 0.16, { slideTo: f1 * 0.84 }), note(f1, 0.22, { delay: 0.13, slideTo: f1 * 0.72, volume: 0.22 })];
    }
    if (pattern === 3) {
      return [note(f1, 0.14, { wave: "triangle", slideTo: f1 * 0.78 }), note(f1 * 0.78, 0.2, { delay: 0.1, wave: "triangle", volume: 0.17 })];
    }
    if (pattern === 4) {
      return [note(f2, 0.08, { filterFreq: 3200 }), note(f3, 0.28, { delay: 0.06, filterFreq: 3000, volume: 0.24 })];
    }
    if (pattern === 5) {
      return [note(f3, 0.1, { filterFreq: 3500, volume: 0.22 })];
    }
    if (pattern === 6) {
      return [note(f1, 0.1), note(f2, 0.1, { delay: 0.09 }), note(f3, 0.1, { delay: 0.18 }), note(f3 * 1.25, 0.18, { delay: 0.27, volume: 0.23 })];
    }
    if (pattern === 7) {
      return [note(f3, 0.06, { slideTo: f2, filterFreq: 2800 }), note(f2, 0.14, { delay: 0.05, slideTo: f1, volume: 0.18 })];
    }
    if (pattern === 8) {
      return [note(f2, 0.12, { volume: 0.19 }), note(f2, 0.12, { delay: 0.15, volume: 0.19 })];
    }
    return [note(f1, 0.35, { wave: wave, filterFreq: 2200, volume: 0.2 })];
  }

  function buildPresets() {
    var presets = {};
    for (var i = 0; i < 50; i++) {
      var id = "s" + String(i + 1).padStart(2, "0");
      presets[id] = {
        id: id,
        name: NAMES[i] || ("صوت " + (i + 1)),
        notes: buildNotes(i),
      };
    }
    return presets;
  }

  window.FINORA_SOUND_PRESETS = buildPresets();
})(window);
