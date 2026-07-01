/**
 * Live report window renderer.
 */
const LiveReportWindow = {
  _seenEventIds: new Set(),

  resetDedup() {
    this._seenEventIds.clear();
  },

  render(container, spec) {
    container.innerHTML = "";
    const lines = (spec.props && spec.props.lines) || [];
    const wrap = document.createElement("div");
    wrap.className = "ws-report-lines";
    wrap.dataset.windowId = spec.id;

    if (!lines.length) {
      const empty = document.createElement("div");
      empty.className = "ws-report-empty";
      empty.textContent = "سيظهر التقرير هنا أثناء التحليل...";
      wrap.appendChild(empty);
    } else {
      lines.forEach((line) => {
        wrap.appendChild(this._lineEl(line));
      });
    }

    container.appendChild(wrap);
  },

  appendLine(container, line, eventId = null) {
    if (eventId) {
      if (this._seenEventIds.has(String(eventId))) return false;
      this._seenEventIds.add(String(eventId));
    }
    let wrap = container.querySelector(".ws-report-lines");
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.className = "ws-report-lines";
      container.appendChild(wrap);
    }
    const empty = wrap.querySelector(".ws-report-empty");
    if (empty) empty.remove();
    wrap.appendChild(this._lineEl(line));
    wrap.scrollTop = wrap.scrollHeight;
    return true;
  },

  _lineEl(text) {
    const el = document.createElement("div");
    el.className = "ws-report-line";
    el.textContent = text;
    return el;
  },
};

window.LiveReportWindow = LiveReportWindow;
