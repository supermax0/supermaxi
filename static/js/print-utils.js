/**
 * Finora print helpers — opens the browser print dialog without a new tab.
 */
(function (global) {
  const FRAME_ID = "finora-print-frame";
  let activeTimers = [];

  function getFrame() {
    let frame = document.getElementById(FRAME_ID);
    if (!frame) {
      frame = document.createElement("iframe");
      frame.id = FRAME_ID;
      frame.setAttribute("aria-hidden", "true");
      frame.setAttribute("title", "طباعة");
      frame.style.cssText =
        "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden;pointer-events:none";
      (document.body || document.documentElement).appendChild(frame);
    }
    return frame;
  }

  function clearTimers() {
    activeTimers.forEach(clearTimeout);
    activeTimers = [];
  }

  function appendEmbedParam(url) {
    try {
      const u = new URL(url, global.location.origin);
      u.searchParams.set("finora_embed", "1");
      return u.pathname + u.search + u.hash;
    } catch (e) {
      const sep = url.indexOf("?") >= 0 ? "&" : "?";
      return url + sep + "finora_embed=1";
    }
  }

  function schedulePrint(frame, delay, printedRef) {
    const timer = setTimeout(function () {
      if (printedRef.done) return;
      try {
        const win = frame.contentWindow;
        if (!win || !win.document) return;
        if (win.document.readyState === "loading") return;
        printedRef.done = true;
        win.focus();
        win.print();
      } catch (e) { /* ignore */ }
    }, delay);
    activeTimers.push(timer);
  }

  function isSelfPrintingUrl(url) {
    return /\/orders\/print-invoices|\/orders\/print-batch|\/orders\/print-report-page/i.test(url);
  }

  function finoraPrintUrl(url, options) {
    options = options || {};
    const frame = getFrame();
    clearTimers();

    const printedRef = { done: false };
    const finalUrl = appendEmbedParam(url);

    const onLoad = function () {
      frame.removeEventListener("load", onLoad);
      if (!isSelfPrintingUrl(finalUrl)) {
        schedulePrint(frame, options.delay != null ? options.delay : 600, printedRef);
      }
    };

    frame.addEventListener("load", onLoad);
    frame.src = finalUrl;

    if (!isSelfPrintingUrl(finalUrl)) {
      schedulePrint(frame, options.fallbackDelay != null ? options.fallbackDelay : 4000, printedRef);
    }
    return true;
  }

  function finoraPrintHtml(html, options) {
    options = options || {};
    const frame = getFrame();
    clearTimers();

    const printedRef = { done: false };
    const doc = frame.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();

    schedulePrint(frame, options.delay != null ? options.delay : 300, printedRef);
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
