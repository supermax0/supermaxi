(function (global) {
  "use strict";

  var ACTIVE_SHIPPING_ID_KEY = "finora_active_shipping_company_id";
  var ACTIVE_SHIPPING_NAME_KEY = "finora_active_shipping_company_name";

  function getActiveShippingCompany() {
    try {
      var id = localStorage.getItem(ACTIVE_SHIPPING_ID_KEY);
      var name = localStorage.getItem(ACTIVE_SHIPPING_NAME_KEY);
      if (!id) return null;
      var parsed = parseInt(id, 10);
      if (!parsed || parsed <= 0) return null;
      return { id: parsed, name: name || "" };
    } catch (_) {
      return null;
    }
  }

  function setActiveShippingCompany(id, name) {
    try {
      localStorage.setItem(ACTIVE_SHIPPING_ID_KEY, String(id));
      localStorage.setItem(ACTIVE_SHIPPING_NAME_KEY, name || "");
    } catch (_) {}
  }

  function clearActiveShippingCompany() {
    try {
      localStorage.removeItem(ACTIVE_SHIPPING_ID_KEY);
      localStorage.removeItem(ACTIVE_SHIPPING_NAME_KEY);
    } catch (_) {}
  }

  function createBarcodeScanner(options) {
    var onScan = options.onScan || function () {};
    var ignoreWhen = options.ignoreWhen || function () { return false; };
    var timeoutMs = options.timeoutMs != null ? options.timeoutMs : 300;
    var buffer = "";
    var timeout = null;

    function flush() {
      var trimmed = String(buffer || "").trim();
      buffer = "";
      clearTimeout(timeout);
      if (trimmed) onScan(trimmed);
    }

    function handleKeydown(e) {
      if (ignoreWhen(e)) return;
      if (e.key === "Enter" && buffer) {
        e.preventDefault();
        flush();
        return;
      }
      if (e.key.length === 1 && /[0-9a-zA-Z]/.test(e.key)) {
        buffer += e.key;
        clearTimeout(timeout);
        timeout = setTimeout(flush, timeoutMs);
      }
    }

    document.addEventListener("keydown", handleKeydown);

    return {
      destroy: function () {
        document.removeEventListener("keydown", handleKeydown);
        clearTimeout(timeout);
        buffer = "";
      },
      reset: function () {
        buffer = "";
        clearTimeout(timeout);
      }
    };
  }

  global.FinoraBarcode = {
    getActiveShippingCompany: getActiveShippingCompany,
    setActiveShippingCompany: setActiveShippingCompany,
    clearActiveShippingCompany: clearActiveShippingCompany,
    createBarcodeScanner: createBarcodeScanner,
    ACTIVE_SHIPPING_ID_KEY: ACTIVE_SHIPPING_ID_KEY,
    ACTIVE_SHIPPING_NAME_KEY: ACTIVE_SHIPPING_NAME_KEY
  };
})(window);
