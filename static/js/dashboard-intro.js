(function () {
  "use strict";

  var overlay = document.getElementById("finoraDashboardIntro");
  if (!overlay) return;

  var video = document.getElementById("finoraDashboardIntroVideo");
  var soundButton = document.getElementById("finoraDashboardIntroSound");
  var waitsForDashboardData = overlay.dataset.waitDashboardData === "true";
  var pageReady = document.readyState === "complete";
  var dataReady = !waitsForDashboardData;
  var videoDone = false;
  var dismissed = false;
  var fallbackTimer = null;

  document.documentElement.classList.add("finora-dashboard-intro-active");

  function dismissIntro() {
    if (dismissed) return;
    dismissed = true;
    window.clearTimeout(fallbackTimer);
    overlay.classList.add("is-leaving");
    document.documentElement.classList.remove("finora-dashboard-intro-active");

    window.setTimeout(function () {
      if (video) {
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
      overlay.remove();
    }, 520);
  }

  function dismissWhenReady(force) {
    if (force || (pageReady && dataReady && videoDone)) {
      dismissIntro();
    }
  }

  function markVideoDone() {
    if (soundButton) soundButton.hidden = true;
    videoDone = true;
    dismissWhenReady(false);
  }

  function playMutedWithSoundOption() {
    video.muted = true;
    if (soundButton) soundButton.hidden = false;
    var mutedAttempt = video.play();
    if (mutedAttempt && typeof mutedAttempt.catch === "function") {
      mutedAttempt.catch(markVideoDone);
    }
  }

  function tryAudiblePlayback() {
    video.muted = false;
    video.volume = 1;
    var audibleAttempt = video.play();
    if (audibleAttempt && typeof audibleAttempt.then === "function") {
      audibleAttempt.then(function () {
        if (soundButton) soundButton.hidden = true;
      }).catch(playMutedWithSoundOption);
    } else if (video.paused) {
      playMutedWithSoundOption();
    }
  }

  if (soundButton && video) {
    soundButton.addEventListener("click", function () {
      video.muted = false;
      video.volume = 1;
      var soundAttempt = video.play();
      if (soundAttempt && typeof soundAttempt.then === "function") {
        soundAttempt.then(function () {
          soundButton.hidden = true;
        }).catch(function () {
          soundButton.hidden = false;
        });
      } else {
        soundButton.hidden = false;
      }
    });
  }

  window.addEventListener("load", function () {
    pageReady = true;
    dismissWhenReady(false);
  }, { once: true });

  window.addEventListener("finora:dashboard-ready", function () {
    dataReady = true;
    dismissWhenReady(false);
  }, { once: true });

  if (!video) {
    markVideoDone();
  } else if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    video.pause();
    markVideoDone();
  } else {
    video.addEventListener("ended", markVideoDone, { once: true });
    video.addEventListener("error", markVideoDone, { once: true });

    tryAudiblePlayback();
  }

  if (pageReady) dismissWhenReady(false);

  // Safety net for a stalled media or API request.
  fallbackTimer = window.setTimeout(function () {
    dismissWhenReady(true);
  }, 8000);
})();
