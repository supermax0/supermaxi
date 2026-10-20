/* Company display clock. ISO values, input values and stored timestamps stay unchanged. */
(function (root) {
  "use strict";
  const config = root.FINORA_TIME_CONFIG || {};
  let mode = config.format === "24" ? "24" : "12";
  const locale = "ar-IQ-u-nu-latn";
  function parse(value) {
    if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
    if (typeof value === "number") { const date = new Date(value); return Number.isNaN(date.getTime()) ? null : date; }
    if (typeof value !== "string" || !value) return null;
    let text = value.trim().replace(" ", "T");
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text) && !/[zZ]$|[+-]\d{2}:?\d{2}$/.test(text)) text += "Z";
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  function format(value, options) {
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const date = parse(value);
    if (!date) return value == null || value === "" ? "—" : String(value);
    return new Intl.DateTimeFormat(locale, Object.assign({}, options, { timeZone: "Asia/Baghdad", hour12: mode === "12" })).format(date);
  }
  function dateTime(value) {
    return format(value, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  function time(value) { return format(value, { hour: "2-digit", minute: "2-digit" }); }
  function clock(value) {
    const match = /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(value || ""));
    if (!match || +match[1] > 23 || +match[2] > 59) return value;
    const hour = +match[1];
    return mode === "24" ? match[1] + ":" + match[2] : String(hour % 12 || 12).padStart(2, "0") + ":" + match[2] + (hour < 12 ? " ص" : " م");
  }
  function refresh() {
    if (!root.document) return;
    root.document.querySelectorAll("[data-finora-timestamp],[data-finora-clock]").forEach(function (node) {
      if (/^(INPUT|TEXTAREA|SELECT|OPTION)$/.test(node.tagName) || node.isContentEditable) return;
      node.textContent = node.hasAttribute("data-finora-clock") ? clock(node.dataset.finoraClock) : dateTime(node.dataset.finoraTimestamp);
    });
  }
  function setFormat(value) {
    if (value !== "12" && value !== "24") throw new Error("Invalid time format");
    mode = value;
    refresh();
    if (root.dispatchEvent && root.CustomEvent) root.dispatchEvent(new CustomEvent("finora:time-format", { detail: mode }));
  }
  root.FinoraTime = { format, dateTime, time, clock, setFormat, getFormat: function () { return mode; }, refresh };
  if (root.document) {
    root.document.addEventListener("DOMContentLoaded", refresh);
    if (config.authenticated && root.fetch) {
      let pending = false;
      const sync = async function () {
        if (pending || root.document.hidden) return;
        pending = true;
        try {
          const response = await fetch("/api/v1/desktop/display-preferences", { cache: "no-store", credentials: "same-origin" });
          if (response.ok) {
            const data = await response.json();
            if (data.ok && (data.time_format === "12" || data.time_format === "24") && data.time_format !== mode) setFormat(data.time_format);
          }
        } catch (_) { /* Keep the last server-provided display format while offline. */ }
        finally { pending = false; }
      };
      root.setInterval(sync, 30000);
      root.addEventListener("focus", sync);
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
