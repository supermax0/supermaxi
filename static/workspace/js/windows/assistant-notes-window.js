/**
 * Assistant notes window.
 */
const AssistantNotesWindow = {
  render(container, spec) {
    const notes = (spec.props && spec.props.notes) || [];
    container.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "ws-notes";

    const ul = document.createElement("ul");
    ul.className = "ws-notes-list";

    if (!notes.length) {
      const li = document.createElement("li");
      li.textContent = "ملاحظات LEON ستظهر هنا بعد التحليل...";
      ul.appendChild(li);
    } else {
      notes.forEach((n) => {
        const li = document.createElement("li");
        li.textContent = typeof n === "string" ? n : n.text || "";
        ul.appendChild(li);
      });
    }
    wrap.appendChild(ul);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ws-notes-details-btn";
    btn.textContent = "عرض التفاصيل";
    btn.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("ws:show-issues-details"));
    });
    wrap.appendChild(btn);

    container.appendChild(wrap);
  },

  addNote(container, text) {
    let ul = container.querySelector(".ws-notes-list");
    if (!ul) {
      ul = document.createElement("ul");
      ul.className = "ws-notes-list";
      container.appendChild(ul);
    }
    const li = document.createElement("li");
    li.textContent = text;
    ul.appendChild(li);
  },
};

window.AssistantNotesWindow = AssistantNotesWindow;
