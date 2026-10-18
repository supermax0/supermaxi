/**
 * Finora print helpers — opens the browser print dialog without a new tab.
 * Mobile: uses a full-size print surface (0×0 iframes produce blank/broken pages).
 * Batch/self-print: opens a real window so nested invoices are not clipped.
 * Never prints login / session-expired pages (common iframe auth failure).
 */
(function (global) {
  const FRAME_ID = "finora-print-frame";
  const HIDDEN_STYLE =
    "position:fixed;right:0;bottom:0;width:1px;height:1px;border:0;opacity:0;visibility:hidden;pointer-events:none;z-index:-1";
  const MOBILE_PRINT_STYLE =
    "position:fixed;inset:0;width:100%;height:100%;border:0;z-index:2147483646;background:#fff;visibility:visible;opacity:1;pointer-events:auto";
  const DESKTOP_OFFSCREEN_STYLE =
    "position:fixed;left:-10000px;top:0;width:794px;height:1123px;border:0;opacity:0;visibility:hidden;pointer-events:none;z-index:-1";
  /* Full viewport — required for multi-invoice / long documents */
  const SELF_PRINT_STYLE =
    "position:fixed;inset:0;width:100%;height:100%;border:0;opacity:0;visibility:hidden;pointer-events:none;z-index:-1";

  let activeTimers = [];
  let afterPrintCleanup = null;
  let batchReadyCleanup = null;

  function isMobileHost() {
    if ((global.innerWidth || 0) >= 900) return false;
    try {
      if (global.navigator && global.navigator.userAgentData && global.navigator.userAgentData.mobile) {
        return true;
      }
    } catch (e) { /* ignore */ }
    const ua = (global.navigator && global.navigator.userAgent) || "";
    return /Android|iPhone|iPad|iPod|Mobile|webOS|BlackBerry|IEMobile|Opera Mini/i.test(ua);
  }

  function getFrame() {
    let frame = document.getElementById(FRAME_ID);
    if (!frame) {
      frame = document.createElement("iframe");
      frame.id = FRAME_ID;
      frame.setAttribute("aria-hidden", "true");
      frame.setAttribute("title", "طباعة");
      frame.style.cssText = HIDDEN_STYLE;
      (document.body || document.documentElement).appendChild(frame);
    }
    return frame;
  }

  function clearTimers() {
    activeTimers.forEach(clearTimeout);
    activeTimers = [];
  }

  function resetFrame(frame) {
    if (!frame) return;
    frame.style.cssText = HIDDEN_STYLE;
    try {
      frame.removeAttribute("aria-hidden");
      frame.setAttribute("aria-hidden", "true");
    } catch (e) { /* ignore */ }
  }

  function prepareFrameSurface(frame, selfPrint) {
    if (selfPrint) {
      frame.style.cssText = isMobileHost() ? MOBILE_PRINT_STYLE : SELF_PRINT_STYLE;
    } else {
      frame.style.cssText = isMobileHost() ? MOBILE_PRINT_STYLE : DESKTOP_OFFSCREEN_STYLE;
    }
    if (isMobileHost()) {
      frame.setAttribute("aria-hidden", "false");
    }
  }

  function cleanPrintUrl(url) {
    try {
      const u = new URL(url, global.location.origin);
      u.searchParams.delete("finora_embed");
      u.searchParams.delete("_print_ts");
      return u.pathname + u.search + u.hash;
    } catch (e) {
      return String(url || "")
        .replace(/([?&])finora_embed=1&?/g, "$1")
        .replace(/([?&])_print_ts=\d+&?/g, "$1")
        .replace(/[?&]$/, "");
    }
  }

  function notifyUser(message) {
    try {
      if (typeof global.showToast === "function") {
        global.showToast(message, "warning");
        return;
      }
    } catch (e) { /* ignore */ }
    try {
      alert(message);
    } catch (e2) { /* ignore */ }
  }

  function openFallbackWindow(url) {
    const clean = cleanPrintUrl(url);
    try {
      const w = global.open(clean, "_blank");
      if (!w) {
        notifyUser("تعذّر فتح الفاتورة. اسمح بالنوافذ المنبثقة ثم أعد الطباعة.");
        return false;
      }
      try { w.opener = null; } catch (e) { /* ignore */ }
      return true;
    } catch (e) {
      return false;
    }
  }

  /** Login / session pages must never be sent to the printer. */
  function getPrintBlockReason(doc, win) {
    if (!doc) return "empty";
    try {
      if (doc.querySelector("[data-finora-print-blocked]")) return "blocked";
      const path = String((win && win.location && win.location.pathname) || "");
      if (/\/login(?:\/|$)/i.test(path) || /\/pos\/login/i.test(path)) return "login";
      if (/\/pricing/i.test(path)) return "pricing";
      if (doc.querySelector(".login-page, .login-box, .login-card, .login-form, form.login-form")) {
        return "login";
      }
      const title = String(doc.title || "");
      if (/تسجيل الدخول|login/i.test(title) && doc.querySelector("input[type='password']")) {
        return "login";
      }
    } catch (e) {
      return "blocked";
    }
    return null;
  }

  function isPrintableDoc(doc) {
    if (!doc || !doc.body) return false;
    return !!(
      doc.getElementById("thermalReceipt") ||
      doc.getElementById("thermalPrintOverrides") ||
      doc.querySelector(
        ".invoice, .invoice-container, .receipt, .paper, .page-shell, #receipt, " +
        ".invoice-sheet, [data-finora-print-ready], .print-document, main.receipt"
      )
    );
  }

  function isThermalPrintDoc(doc) {
    if (!doc) return false;
    if (doc.getElementById("thermalReceipt") || doc.getElementById("thermalPrintOverrides")) {
      return true;
    }
    try {
      const body = doc.body;
      if (body && body.getAttribute("data-paper") === "thermal") return true;
      if (
        doc.querySelector("main.receipt, #receipt.receipt") &&
        !doc.querySelector(".invoice, .invoice-container, .page-shell")
      ) {
        return true;
      }
    } catch (e) { /* ignore */ }
    return false;
  }

  function injectPrintFixes(doc) {
    if (!doc || doc.getElementById("finora-print-fix")) return;
    const thermal = isThermalPrintDoc(doc);
    const style = doc.createElement("style");
    style.id = "finora-print-fix";
    style.textContent = thermal
      ? [
          "@page{size:80mm auto;margin:0;}",
          "@media print{",
          "html,body{width:80mm!important;height:auto!important;min-height:0!important;",
          "overflow:visible!important;background:#fff!important;margin:0!important;padding:0!important;}",
          ".no-print,.invoice-actions,.actions,.toolbar,.load-status{",
          "display:none!important;}",
          ".receipt,#thermalReceipt,#receipt{",
          "width:80mm!important;max-width:80mm!important;margin:0!important;",
          "box-shadow:none!important;border:0!important;}",
          "}"
        ].join("")
      : [
          "@media print{",
          "html,body{height:auto!important;min-height:0!important;overflow:visible!important;",
          "background:#fff!important;margin:0!important;padding:0!important;}",
          ".no-print,.invoice-actions,.actions,.toolbar,.load-status{",
          "display:none!important;}",
          ".invoice,.invoice-container,.page-shell{",
          "box-shadow:none!important;margin:0!important;max-width:100%!important;",
          "width:100%!important;border-radius:0!important;}",
          ".invoice-footer,.codes{page-break-inside:avoid!important;page-break-before:avoid!important;}",
          "@page{size:auto;margin:8mm;}",
          "}"
        ].join("");
    (doc.head || doc.documentElement).appendChild(style);
  }

  function bindAfterPrint(frame) {
    if (afterPrintCleanup) {
      try { afterPrintCleanup(); } catch (e) { /* ignore */ }
      afterPrintCleanup = null;
    }

    const win = frame.contentWindow;
    let cleaned = false;
    const cleanup = function () {
      if (cleaned) return;
      cleaned = true;
      resetFrame(frame);
      try {
        if (win) {
          win.removeEventListener("afterprint", cleanup);
        }
      } catch (e) { /* ignore */ }
      afterPrintCleanup = null;
    };

    afterPrintCleanup = cleanup;
    try {
      if (win) win.addEventListener("afterprint", cleanup);
    } catch (e) { /* ignore */ }
    activeTimers.push(setTimeout(cleanup, 90000));
  }

  function appendEmbedParam(url) {
    try {
      const u = new URL(url, global.location.origin);
      u.searchParams.set("finora_embed", "1");
      u.searchParams.set("_print_ts", String(Date.now()));
      return u.pathname + u.search + u.hash;
    } catch (e) {
      const sep = url.indexOf("?") >= 0 ? "&" : "?";
      return url + sep + "finora_embed=1&_print_ts=" + Date.now();
    }
  }

  function abortBadPrint(frame, printedRef, sourceUrl, reason) {
    printedRef.done = true;
    clearTimers();
    resetFrame(frame);
    const isLogin = reason === "login" || reason === "blocked" || reason === "session";
    notifyUser(
      isLogin
        ? "تعذّرت الطباعة: انتهت الجلسة أو يلزم تسجيل الدخول. سيتم فتح المستند في نافذة جديدة."
        : "تعذّر تحميل مستند الطباعة. سيتم فتحه في نافذة جديدة."
    );
    openFallbackWindow(sourceUrl);
  }

  function triggerPrint(frame, printedRef, selfPrint, sourceUrl) {
    if (printedRef.done) return;
    try {
      const win = frame.contentWindow;
      if (!win || !win.document) return;
      if (win.document.readyState === "loading") return;

      const blockReason = getPrintBlockReason(win.document, win);
      if (blockReason) {
        abortBadPrint(frame, printedRef, sourceUrl, blockReason);
        return;
      }
      if (!isPrintableDoc(win.document)) {
        /* Fallback timer may fire before content is ready — keep waiting. */
        return;
      }

      printedRef.done = true;
      injectPrintFixes(win.document);
      prepareFrameSurface(frame, !!selfPrint);
      bindAfterPrint(frame);
      const delay = isMobileHost() ? 250 : 50;
      const timer = setTimeout(function () {
        try {
          win.focus();
          win.print();
        } catch (e) { /* ignore */ }
      }, delay);
      activeTimers.push(timer);
    } catch (e) { /* ignore */ }
  }

  function schedulePrint(frame, delay, printedRef, selfPrint, sourceUrl) {
    const timer = setTimeout(function () {
      triggerPrint(frame, printedRef, selfPrint, sourceUrl);
    }, delay);
    activeTimers.push(timer);
  }

  function isSelfPrintingUrl(url) {
    return /\/orders\/print-invoices|\/orders\/print-batch|\/orders\/print-report-page/i.test(url);
  }

  function openSelfPrintWindow(url) {
    try {
      const w = global.open(url, "_blank");
      if (!w) return false;
      try { w.opener = null; } catch (e) { /* ignore */ }
      return true;
    } catch (e) {
      return false;
    }
  }

  function finoraPrintUrl(url, options) {
    options = options || {};
    clearTimers();
    if (afterPrintCleanup) {
      try { afterPrintCleanup(); } catch (e) { /* ignore */ }
    }
    if (batchReadyCleanup) {
      try { batchReadyCleanup(); } catch (e) { /* ignore */ }
      batchReadyCleanup = null;
    }

    const finalUrl = appendEmbedParam(url);
    const selfPrint = isSelfPrintingUrl(finalUrl);

    const frame = getFrame();
    const printedRef = { done: false };

    prepareFrameSurface(frame, selfPrint);

    if (selfPrint) {
      const onBatchReady = function (event) {
        if (
          event.source !== frame.contentWindow ||
          !event.data ||
          event.data.type !== "finora-batch-ready"
        ) {
          return;
        }
        global.removeEventListener("message", onBatchReady);
        batchReadyCleanup = null;
        triggerPrint(frame, printedRef, true, finalUrl);
      };
      global.addEventListener("message", onBatchReady);
      batchReadyCleanup = function () {
        global.removeEventListener("message", onBatchReady);
      };
    }

    const onLoad = function () {
      frame.removeEventListener("load", onLoad);
      try {
        const win = frame.contentWindow;
        const doc = win && win.document;
        const blockReason = getPrintBlockReason(doc, win);
        if (blockReason) {
          abortBadPrint(frame, printedRef, finalUrl, blockReason);
          return;
        }
      } catch (e) {
        abortBadPrint(frame, printedRef, finalUrl, "blocked");
        return;
      }
      if (!selfPrint) {
        try {
          injectPrintFixes(frame.contentWindow && frame.contentWindow.document);
        } catch (e) { /* ignore */ }
        schedulePrint(
          frame,
          options.delay != null ? options.delay : (isMobileHost() ? 900 : 600),
          printedRef,
          false,
          finalUrl
        );
      }
    };

    frame.addEventListener("load", onLoad);
    frame.src = finalUrl;

    if (!selfPrint) {
      /* Last resort: if still not printable, open a real tab — never print login. */
      const failSafe = setTimeout(function () {
        if (printedRef.done) return;
        try {
          const win = frame.contentWindow;
          const doc = win && win.document;
          const blockReason = getPrintBlockReason(doc, win);
          if (blockReason) {
            abortBadPrint(frame, printedRef, finalUrl, blockReason);
            return;
          }
          if (isPrintableDoc(doc)) {
            triggerPrint(frame, printedRef, false, finalUrl);
            return;
          }
        } catch (e) { /* ignore */ }
        abortBadPrint(frame, printedRef, finalUrl, "empty");
      }, options.fallbackDelay != null ? options.fallbackDelay : 5000);
      activeTimers.push(failSafe);
    } else {
      schedulePrint(
        frame,
        options.fallbackDelay != null ? options.fallbackDelay : 30000,
        printedRef,
        true,
        finalUrl
      );
    }
    return true;
  }

  function finoraPrintHtml(html, options) {
    options = options || {};
    const frame = getFrame();
    clearTimers();
    if (afterPrintCleanup) {
      try { afterPrintCleanup(); } catch (e) { /* ignore */ }
    }

    const printedRef = { done: false };
    prepareFrameSurface(frame, false);

    const doc = frame.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();

    injectPrintFixes(doc);
    schedulePrint(
      frame,
      options.delay != null ? options.delay : (isMobileHost() ? 500 : 300),
      printedRef,
      false,
      ""
    );
    return true;
  }

  function setupPrintLinks() {
    document.addEventListener(
      "click",
      function (e) {
        const link = e.target.closest("a[data-finora-print], a.finora-print-link");
        if (!link) return;
        const href = link.getAttribute("href");
        if (!href || href === "#" || href.startsWith("javascript:")) return;
        e.preventDefault();
        finoraPrintUrl(href);
      },
      true
    );
  }

  global.finoraPrintUrl = finoraPrintUrl;
  global.finoraPrintHtml = finoraPrintHtml;

  if (document.body) {
    setupPrintLinks();
  } else {
    document.addEventListener("DOMContentLoaded", setupPrintLinks);
  }
})(window);
