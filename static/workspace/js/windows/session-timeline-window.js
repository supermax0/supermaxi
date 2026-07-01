const SessionTimelineWindow = {
  render(container, spec) {
    const items = (spec.props && spec.props.items) || [];
    container.innerHTML = "";
    const ul = document.createElement("ul");
    ul.className = "ws-timeline-list";
    if (!items.length) {
      const li = document.createElement("li");
      li.textContent = "لا أحداث بعد...";
      ul.appendChild(li);
    } else {
      items.slice(-40).forEach((item) => {
        const li = document.createElement("li");
        li.innerHTML = `<span class="ws-timeline-type">${this._esc(item.type)}</span>
          <span class="ws-timeline-msg">${this._esc(item.message)}</span>`;
        ul.appendChild(li);
      });
    }
    container.appendChild(ul);
    ul.scrollTop = ul.scrollHeight;
  },

  update(container, items) {
    this.render(container, { props: { items } });
  },

  _esc(t) {
    const d = document.createElement("div");
    d.textContent = t || "";
    return d.innerHTML;
  },
};

window.SessionTimelineWindow = SessionTimelineWindow;
