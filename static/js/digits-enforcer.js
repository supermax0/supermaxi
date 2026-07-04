/**
 * Accept Western digits (0-9) only in numeric fields.
 * Converts Eastern Arabic (٠-٩) and Persian (۰-۹) on input.
 */
(function () {
  "use strict";

  function toEnglishDigits(value) {
    if (value == null) return "";
    return String(value)
      .replace(/[\u0660-\u0669]/g, function (ch) {
        return String(ch.charCodeAt(0) - 0x0660);
      })
      .replace(/[\u06F0-\u06F9]/g, function (ch) {
        return String(ch.charCodeAt(0) - 0x06F0);
      });
  }

  function normalizeDigits(value, allowDecimal) {
    var v = toEnglishDigits(value);
    if (allowDecimal) {
      v = v.replace(/[^\d.]/g, "");
      var parts = v.split(".");
      if (parts.length > 2) {
        v = parts[0] + "." + parts.slice(1).join("");
      }
      return v;
    }
    return v.replace(/\D/g, "");
  }

  function enforceInput(el) {
    if (!el || el.dataset.digitsEnBound === "1") return;
    el.dataset.digitsEnBound = "1";
    var allowDecimal = (el.getAttribute("data-digits-en") || "") === "decimal";

    function apply() {
      var normalized = normalizeDigits(el.value, allowDecimal);
      if (el.value !== normalized) el.value = normalized;
    }

    el.addEventListener("input", apply);
    el.addEventListener("paste", function () {
      setTimeout(apply, 0);
    });
    apply();
  }

  function init(root) {
    var scope = root || document;
    scope.querySelectorAll("[data-digits-en]").forEach(enforceInput);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      init(document);
    });
  } else {
    init(document);
  }

  window.FinoraDigits = {
    toEnglishDigits: toEnglishDigits,
    normalizeDigits: normalizeDigits,
    enforceInput: enforceInput,
    init: init,
  };
})();
