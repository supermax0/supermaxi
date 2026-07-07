(function (window) {
  'use strict';

  var audioCtx = null;
  var audioUnlocked = false;
  var STORAGE_KEY = 'finora_last_notified_msg';

  function getAudioCtx() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(function () {});
    }
    return audioCtx;
  }

  function unlockAudio() {
    if (audioUnlocked) return;
    audioUnlocked = true;
    try {
      var ctx = getAudioCtx();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      gain.gain.value = 0.0001;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.01);
    } catch (_) {}
  }

  function tone(ctx, freq, start, duration, volume) {
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(freq, start);
    gain.gain.setValueAtTime(volume, start);
    gain.gain.exponentialRampToValueAtTime(0.001, start + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(start);
    osc.stop(start + duration + 0.02);
  }

  function play(kind) {
    try {
      unlockAudio();
      var ctx = getAudioCtx();
      var now = ctx.currentTime;
      if (kind === 'send') {
        tone(ctx, 880, now, 0.1, 0.2);
        tone(ctx, 1100, now + 0.1, 0.12, 0.18);
      } else {
        tone(ctx, 660, now, 0.1, 0.22);
        tone(ctx, 880, now + 0.14, 0.12, 0.2);
      }
    } catch (_) {}
  }

  function requestPermission() {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'default') {
      Notification.requestPermission().catch(function () {});
    }
  }

  function notify(title, body, tag) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    try {
      new Notification(title || '', {
        body: body || '',
        icon: '/static/favicon.png',
        tag: tag || ('finora-msg-' + Date.now())
      });
    } catch (_) {}
  }

  function shouldNotify(messageId) {
    var id = parseInt(messageId, 10);
    if (!id) return false;
    var last = parseInt(window.sessionStorage.getItem(STORAGE_KEY) || '0', 10);
    if (id <= last) return false;
    window.sessionStorage.setItem(STORAGE_KEY, String(id));
    return true;
  }

  function markNotified(messageId) {
    var id = parseInt(messageId, 10);
    if (!id) return;
    var last = parseInt(window.sessionStorage.getItem(STORAGE_KEY) || '0', 10);
    if (id > last) {
      window.sessionStorage.setItem(STORAGE_KEY, String(id));
    }
  }

  document.addEventListener('click', unlockAudio, { once: true, passive: true });
  document.addEventListener('keydown', unlockAudio, { once: true, passive: true });

  window.FinoraMsgNotify = {
    play: play,
    notify: notify,
    requestPermission: requestPermission,
    shouldNotify: shouldNotify,
    markNotified: markNotified,
    unlockAudio: unlockAudio
  };
})(window);
