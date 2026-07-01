/**
 * Assistant notes window.
 */
const AssistantNotesWindow = {
  render(container, spec) {
    const notes = (spec.props && spec.props.notes) || [];
    container.innerHTML = "";
    const ul = document.createElement("ul");
    ul.className = "ws-notes-list";

    if (!notes.length) {
      const li = document.createElement("li");
      li.textContent = "ملاحظات LEON ستظهر هنا...";
      ul.appendChild(li);
    } else {
      notes.forEach((n) => {
        const li = document.createElement("li");
        li.textContent = n;
        ul.appendChild(li);
      });
    }

    container.appendChild(ul);
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
