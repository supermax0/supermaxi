(function (window, document) {
  "use strict";

  var EVENTS = ["payment", "return", "cancel", "order"];

  function getPresets() {
    return typeof window.finoraGetSoundPresets === "function"
      ? window.finoraGetSoundPresets()
      : [];
  }

  function getLabels() {
    return typeof window.finoraGetSoundEventLabels === "function"
      ? window.finoraGetSoundEventLabels()
      : {};
  }

  function getMap() {
    return typeof window.finoraGetEventSoundMap === "function"
      ? window.finoraGetEventSoundMap()
      : {};
  }

  function buildPresetOptions(selectedId) {
    return getPresets().map(function (p) {
      var sel = p.id === selectedId ? " selected" : "";
      return '<option value="' + p.id + '"' + sel + ">" + p.name + " (" + p.id + ")</option>";
    }).join("");
  }

  function filterPresets(query) {
    var q = String(query || "").trim().toLowerCase();
    var presets = getPresets();
    if (!q) return presets;
    return presets.filter(function (p) {
      return p.name.toLowerCase().indexOf(q) >= 0 || p.id.toLowerCase().indexOf(q) >= 0;
    });
  }

  function renderPresetGrid(query) {
    var grid = document.getElementById("soundPresetsGrid");
    if (!grid) return;
    var presets = filterPresets(query);
    grid.innerHTML = presets.map(function (p) {
      var num = parseInt(p.id.replace(/\D/g, ""), 10) || 0;
      return (
        '<button type="button" class="sound-preset-chip" data-preview-preset="' + p.id + '">' +
        '<span class="sound-preset-num">' + num + "</span>" +
        "<span>" + p.name + "</span>" +
        "</button>"
      );
    }).join("");
    if (!presets.length) {
      grid.innerHTML = '<div class="sound-presets-empty">لا توجد نتائج</div>';
    }
  }

  function renderSoundSettings() {
    var panel = document.getElementById("soundEventsPanel");
    if (!panel) return;

    var labels = getLabels();
    var map = getMap();

    panel.innerHTML = EVENTS.map(function (ev) {
      return (
        '<div class="sound-event-row" data-event="' + ev + '">' +
        '<label class="sound-event-label">' + (labels[ev] || ev) + "</label>" +
        '<div class="sound-event-controls">' +
        '<select class="sound-event-select" data-event="' + ev + '" aria-label="صوت ' + (labels[ev] || ev) + '">' +
        buildPresetOptions(map[ev]) +
        "</select>" +
        '<button type="button" class="sound-preview-btn" data-preview-event="' + ev + '" title="معاينة الحدث">' +
        '<i class="fas fa-play"></i></button>' +
        "</div></div>"
      );
    }).join("");

    var search = document.getElementById("soundPresetSearch");
    renderPresetGrid(search ? search.value : "");

    var enabledToggle = document.getElementById("notificationSoundEnabled");
    if (enabledToggle) {
      enabledToggle.checked = typeof window.finoraNotificationSoundEnabled === "function"
        ? window.finoraNotificationSoundEnabled()
        : true;
    }
  }

  function bindSoundSettings() {
    var panel = document.getElementById("soundEventsPanel");
    var grid = document.getElementById("soundPresetsGrid");
    var resetBtn = document.getElementById("soundSettingsReset");
    var search = document.getElementById("soundPresetSearch");
    var enabledToggle = document.getElementById("notificationSoundEnabled");

    if (panel && !panel.dataset.bound) {
      panel.dataset.bound = "1";
      panel.addEventListener("change", function (e) {
        var sel = e.target.closest(".sound-event-select");
        if (!sel) return;
        if (typeof window.finoraSetEventSound === "function") {
          window.finoraSetEventSound(sel.getAttribute("data-event"), sel.value);
        }
      });
      panel.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-preview-event]");
        if (!btn) return;
        e.preventDefault();
        if (typeof window.finoraPreviewEventSound === "function") {
          window.finoraPreviewEventSound(btn.getAttribute("data-preview-event"));
        }
      });
    }

    if (grid && !grid.dataset.bound) {
      grid.dataset.bound = "1";
      grid.addEventListener("click", function (e) {
        var chip = e.target.closest("[data-preview-preset]");
        if (!chip) return;
        e.preventDefault();
        if (typeof window.finoraPreviewSoundPreset === "function") {
          window.finoraPreviewSoundPreset(chip.getAttribute("data-preview-preset"));
        }
      });
    }

    if (search && !search.dataset.bound) {
      search.dataset.bound = "1";
      search.addEventListener("input", function () {
        renderPresetGrid(search.value);
      });
    }

    if (resetBtn && !resetBtn.dataset.bound) {
      resetBtn.dataset.bound = "1";
      resetBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (typeof window.finoraResetEventSoundMap === "function") {
          window.finoraResetEventSoundMap();
        }
        renderSoundSettings();
        if (typeof window.showToast === "function") {
          window.showToast("تمت إعادة ضبط أصوات الأحداث", "success", { silent: true });
        }
      });
    }

    if (enabledToggle && !enabledToggle.dataset.bound) {
      enabledToggle.dataset.bound = "1";
      enabledToggle.addEventListener("change", function () {
        if (typeof window.finoraSetNotificationSound === "function") {
          window.finoraSetNotificationSound(enabledToggle.checked);
        }
        if (enabledToggle.checked && typeof window.finoraPreviewEventSound === "function") {
          window.finoraPreviewEventSound("payment");
        }
      });
    }
  }

  function init() {
    renderSoundSettings();
    bindSoundSettings();
  }

  window.finoraRenderSoundSettings = renderSoundSettings;

  document.addEventListener("finora:notification-sound-changed", renderSoundSettings);
  document.addEventListener("DOMContentLoaded", init);
})(window, document);
