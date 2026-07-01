const CourierIssuesWindow = {
  render(container, spec) {
    const p = spec.props || {};
    container.innerHTML = `<div class="ws-courier-issues"><p class="ws-courier-issues-loading">جاري تحميل المشاكل...</p></div>`;
    if (p.issues) {
      this.showIssues(container, p.issues);
    }
  },

  showIssues(container, issues) {
    const root = container.querySelector(".ws-courier-issues") || container;
    const groups = { critical: [], error: [], warning: [], info: [] };
    (issues || []).forEach((i) => {
      const sev = i.severity || "info";
      if (!groups[sev]) groups[sev] = [];
      groups[sev].push(i);
    });
    root.innerHTML = "";
    ["critical", "error", "warning", "info"].forEach((sev) => {
      if (!groups[sev].length) return;
      const block = document.createElement("div");
      block.className = `ws-courier-issue-group ws-courier-sev-${sev}`;
      block.innerHTML = `<h4>${this._sevLabel(sev)} (${groups[sev].length})</h4>`;
      const ul = document.createElement("ul");
      groups[sev].forEach((issue) => {
        const li = document.createElement("li");
        li.innerHTML = `<strong>${issue.issue_type}</strong> — ${issue.message}`;
        ul.appendChild(li);
      });
      block.appendChild(ul);
      root.appendChild(block);
    });
    if (!issues || !issues.length) {
      root.innerHTML = "<p>لا توجد مشاكل مكتشفة</p>";
    }
  },

  _sevLabel(sev) {
    return { critical: "حرج", error: "خطأ", warning: "تحذير", info: "معلومة" }[sev] || sev;
  },
};

window.CourierIssuesWindow = CourierIssuesWindow;
