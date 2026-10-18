(() => {
  "use strict";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const state = { notes: [], archived: [], activeId: null, filter: "all", search: "", saveTimer: null, loading: false, charts: [], savedRange: null, assistantContent: "", activeCheck: null };
  const el = {
    app: $("#notesApp"), toolbar: $("#notesToolbar"), list: $("#notesList"), empty: $("#notesEmpty"), shell: $("#notesEditorShell"), editor: $("#noteEditor"),
    title: $("#noteTitle"), category: $("#noteCategory"), tags: $("#noteTags"), priority: $("#notePriority"),
    dueAt: $("#noteDueAt"), dot: $("#notesDocDot"), save: $("#notesSaveState"), search: $("#notesSearch"),
    sort: $("#notesSort"), wordCount: $("#noteWordCount"), charCount: $("#noteCharCount"), updated: $("#noteUpdatedAt"),
    aiMenu: $("#notesAiMenu"), moreMenu: $("#notesMoreMenu"), toast: $("#notesToast"),
    assistantModal: $("#notesAssistantModal"), assistantPreview: $("#notesAssistantPreview"),
    assistantLoading: $("#notesAssistantLoading"), assistantError: $("#notesAssistantError"),
    templatesModal: $("#notesTemplatesModal"),
    checkMenu: $("#notesCheckMenu"),
  };

  async function api(url, options = {}) {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", "Accept": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) throw new Error(data.error || "تعذر إكمال العملية");
    return data;
  }
  function toast(message) {
    el.toast.textContent = message; el.toast.classList.add("show");
    clearTimeout(toast.timer); toast.timer = setTimeout(() => el.toast.classList.remove("show"), 2600);
  }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[ch]));
  }
  function current() { return [...state.notes, ...state.archived].find(n => n.id === state.activeId); }
  function relativeDate(iso) {
    if (!iso) return "";
    const diff = Date.now() - new Date(iso).getTime();
    if (diff < 60000) return "الآن";
    if (diff < 3600000) return `منذ ${Math.floor(diff / 60000)} د`;
    if (diff < 86400000) return `منذ ${Math.floor(diff / 3600000)} س`;
    return new Intl.DateTimeFormat("ar-IQ", { month:"short", day:"numeric" }).format(new Date(iso));
  }
  function priorityRank(value) { return ({ urgent:4, high:3, normal:2, low:1 })[value] || 0; }
  function renderList() {
    let source = state.filter === "archived" ? [...state.archived] : [...state.notes];
    if (state.filter === "pinned") source = source.filter(n => n.is_pinned);
    if (state.filter === "tasks") source = source.filter(n => n.category === "مهام" || n.status === "done" || /مهم|مهمة|task/i.test(n.title));
    const q = state.search.trim().toLowerCase();
    if (q) source = source.filter(n => [n.title, n.excerpt, n.category, ...(n.tags || [])].join(" ").toLowerCase().includes(q));
    const sort = el.sort.value;
    source.sort((a,b) => sort === "title" ? a.title.localeCompare(b.title, "ar") :
      sort === "priority" ? priorityRank(b.priority) - priorityRank(a.priority) :
      sort === "due" ? (a.due_at || "9999").localeCompare(b.due_at || "9999") :
      Number(b.is_pinned) - Number(a.is_pinned) || new Date(b.updated_at) - new Date(a.updated_at));
    $("#countAll").textContent = state.notes.length;
    $("#countPinned").textContent = state.notes.filter(n => n.is_pinned).length;
    $("#countTasks").textContent = state.notes.filter(n => n.category === "مهام" || n.status === "done").length;
    $("#countArchived").textContent = state.archived.length;
    if (!source.length) {
      el.list.innerHTML = `<div class="notes-list-empty"><i class="far fa-note-sticky"></i>لا توجد ملاحظات هنا</div>`; return;
    }
    el.list.innerHTML = source.map(note => `
      <article class="note-list-card ${note.id === state.activeId ? "active" : ""}" data-note-id="${note.id}" style="--card-color:${note.color}">
        <div class="note-card-top">${note.is_pinned ? '<i class="fas fa-thumbtack"></i>' : ""}<h3>${escapeHtml(note.title)}</h3>${note.status === "done" ? '<i class="fas fa-circle-check"></i>' : ""}</div>
        <p>${escapeHtml(note.excerpt || "ملاحظة فارغة")}</p>
        <div class="note-card-meta"><span>${escapeHtml(note.category)}</span>${note.priority === "urgent" ? "<span>عاجلة</span>" : ""}<time>${relativeDate(note.updated_at)}</time></div>
      </article>`).join("");
  }
  async function loadLists() {
    const [active, archived] = await Promise.all([api("/notes/api"), api("/notes/api?archived=1")]);
    state.notes = active.notes; state.archived = archived.notes; renderList();
  }
  async function openNote(id) {
    if (state.saveTimer) await saveNow();
    state.loading = true;
    try {
      const data = await api(`/notes/api/${id}`), note = data.note;
      state.activeId = note.id;
      el.app.classList.add("mobile-editor-open");
      const bucket = note.is_archived ? state.archived : state.notes;
      const ix = bucket.findIndex(n => n.id === note.id);
      if (ix >= 0) bucket[ix] = note; else bucket.unshift(note);
      el.empty.hidden = true; el.shell.hidden = false;
      el.title.value = note.title; el.editor.innerHTML = note.content || ""; normalizeTaskChecks();
      el.category.value = note.category || "عام"; el.tags.value = (note.tags || []).join("، ");
      el.priority.value = note.priority; el.dueAt.value = note.due_at || "";
      setAccent(note.color); updateStats(); updateStatus(note); renderCharts(); renderList();
    } finally { state.loading = false; }
  }
  async function createNote() {
    if (state.saveTimer) await saveNow();
    const data = await api("/notes/api", { method:"POST", body:JSON.stringify({}) });
    state.notes.unshift(data.note); state.filter = "all"; setFilterButton("all"); await openNote(data.note.id);
    requestAnimationFrame(() => { el.title.focus(); el.title.select(); }); toast("تم إنشاء ملاحظة جديدة");
  }
  function buildNoteTemplate(key) {
    const date = new Intl.DateTimeFormat("ar-IQ", { weekday:"long", year:"numeric", month:"long", day:"numeric" }).format(new Date());
    const check = '<span class="note-check" data-state="pending" contenteditable="false" role="checkbox" tabindex="0" aria-checked="false"></span>';
    const rows = (count, cells) => Array.from({length:count}, (_, index) => `<tr><td>${check}</td>${cells(index)}</tr>`).join("");
    const templates = {
      daily_tasks: {
        title: `مهام اليوم — ${date}`, category:"مهام", color:"#7c3aed", priority:"high", tags:["مهام اليوم","إنجاز"],
        content:`<div class="note-callout"><strong>📅 ${date}</strong><br>🎯 هدفي الرئيسي اليوم: اكتب الهدف هنا</div><h2>مهام اليوم</h2><table class="note-table"><thead><tr><th>تم</th><th>المهمة</th><th>الوقت</th><th>الأولوية</th><th>ملاحظات</th></tr></thead><tbody>${rows(7, i => `<td>${i === 0 ? "اكتب المهمة الأولى" : "مهمة جديدة"}</td><td>--:--</td><td><span class="note-priority">${i < 2 ? "مهمة" : "عادية"}</span></td><td>—</td>`)}</tbody></table><h3>مراجعة نهاية اليوم</h3><p>✅ ما الذي تم إنجازه؟</p><p>➡️ ما الذي سينتقل إلى الغد؟</p>`
      },
      quick_checklist: {
        title:"قائمة إنجاز سريعة", category:"مهام", color:"#2563eb", priority:"normal", tags:["قائمة","إنجاز"],
        content:`<div class="note-callout"><strong>قائمة إنجاز</strong><br>اضغط على المربع أمام كل نقطة عند إكمالها.</div><table class="note-table"><thead><tr><th>تم</th><th>النقطة</th><th>ملاحظة</th></tr></thead><tbody>${rows(10, i => `<td>${i === 0 ? "النقطة الأولى" : "أضف نقطة جديدة"}</td><td>—</td>`)}</tbody></table>`
      },
      meeting: {
        title:`محضر اجتماع — ${date}`, category:"اجتماع", color:"#059669", priority:"high", tags:["اجتماع","قرارات"],
        content:`<div class="note-callout"><strong>📅 التاريخ:</strong> ${date}<br><strong>🕐 الوقت:</strong> --:--<br><strong>📍 المكان:</strong> —<br><strong>👥 الحضور:</strong> —</div><h2>موضوع الاجتماع</h2><p>اكتب موضوع الاجتماع هنا…</p><h2>النقاط والقرارات</h2><table class="note-table"><thead><tr><th>تم</th><th>النقطة / القرار</th><th>المسؤول</th><th>الموعد</th></tr></thead><tbody>${rows(6, () => "<td>قرار أو مهمة</td><td>—</td><td>—</td>")}</tbody></table><h2>ملاحظات إضافية</h2><p>اكتب الملاحظات هنا…</p>`
      },
      weekly_plan: {
        title:`الخطة الأسبوعية — ${date}`, category:"تخطيط", color:"#ea580c", priority:"normal", tags:["أسبوعي","تخطيط"],
        content:`<div class="note-callout"><strong>🎯 أهداف هذا الأسبوع</strong><br>1. الهدف الأول<br>2. الهدف الثاني<br>3. الهدف الثالث</div><h2>خطة أيام الأسبوع</h2><table class="note-table"><thead><tr><th>تم</th><th>اليوم</th><th>أهم مهمة</th><th>ملاحظات</th></tr></thead><tbody>${["الأحد","الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت"].map(day => `<tr><td>${check}</td><td><strong>${day}</strong></td><td>أضف مهمة</td><td>—</td></tr>`).join("")}</tbody></table><h3>مراجعة الأسبوع</h3><p>أبرز إنجاز: —</p><p>شيء أريد تحسينه: —</p>`
      },
      customer_followup: {
        title:`متابعة العملاء — ${date}`, category:"عمل", color:"#db2777", priority:"high", tags:["عملاء","متابعة"],
        content:`<div class="note-callout"><strong>متابعة العملاء</strong><br>سجّل كل تواصل وحدد المتابعة المكتملة بعلامة صح.</div><table class="note-table"><thead><tr><th>تم</th><th>اسم العميل</th><th>رقم الهاتف</th><th>آخر تواصل</th><th>النتيجة</th><th>المتابعة القادمة</th></tr></thead><tbody>${rows(8, () => "<td>اسم العميل</td><td>07xxxxxxxxx</td><td>—</td><td>بانتظار الرد</td><td>—</td>")}</tbody></table>`
      },
      ideas: {
        title:"بنك الأفكار", category:"أفكار", color:"#0891b2", priority:"normal", tags:["أفكار","تطوير"],
        content:`<div class="note-callout"><strong>💡 لا تحكم على الفكرة بسرعة</strong><br>سجّلها أولاً، ثم قيّم فائدتها وسهولة تنفيذها.</div><table class="note-table"><thead><tr><th>اختيار</th><th>الفكرة</th><th>الفائدة</th><th>سهولة التنفيذ</th><th>الخطوة التالية</th></tr></thead><tbody>${rows(8, i => `<td>${i === 0 ? "فكرة جديدة" : "أضف فكرة"}</td><td>عالية / متوسطة / منخفضة</td><td>سهلة / متوسطة / صعبة</td><td>—</td>`)}</tbody></table>`
      }
    };
    return templates[key] || null;
  }
  async function createFromTemplate(key) {
    const template = buildNoteTemplate(key);
    if (!template) return;
    if (state.saveTimer) await saveNow();
    const card = $(`[data-template="${key}"]`);
    if (card) card.classList.add("is-loading");
    try {
      const data = await api("/notes/api", { method:"POST", body:JSON.stringify(template) });
      state.notes.unshift(data.note); state.filter = "all"; setFilterButton("all");
      el.templatesModal.hidden = true; await openNote(data.note.id);
      toast("تم إنشاء الملاحظة من القالب الجاهز");
    } catch (error) { toast(error.message); }
    finally { if (card) card.classList.remove("is-loading"); }
  }
  function payload() {
    return {
      title: el.title.value, content: el.editor.innerHTML, category: el.category.value,
      tags: el.tags.value.split(/[,،]/), priority: el.priority.value, due_at: el.dueAt.value || null,
      color: current()?.color || "#7c3aed",
    };
  }
  function setSaveState(kind, label) {
    el.save.className = `notes-save-state ${kind || ""}`;
    $("i", el.save).className = kind === "error" ? "fas fa-triangle-exclamation" : kind === "saving" ? "fas fa-cloud-arrow-up" : "fas fa-cloud";
    $("span", el.save).textContent = label;
  }
  function scheduleSave() {
    if (state.loading || !state.activeId) return;
    setSaveState("saving", "جارٍ الحفظ…"); clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(saveNow, 850); updateStats();
  }
  async function saveNow(extra = {}) {
    clearTimeout(state.saveTimer); state.saveTimer = null;
    if (!state.activeId) return;
    try {
      const data = await api(`/notes/api/${state.activeId}`, { method:"PUT", body:JSON.stringify({ ...payload(), ...extra }) });
      const old = current(), from = old?.is_archived ? state.archived : state.notes;
      const next = data.note, to = next.is_archived ? state.archived : state.notes;
      const ix = from.findIndex(n => n.id === next.id); if (ix >= 0) from.splice(ix, 1);
      const existing = to.findIndex(n => n.id === next.id); if (existing >= 0) to[existing] = next; else to.unshift(next);
      setSaveState("", "محفوظ"); updateStatus(next); renderList(); return next;
    } catch (error) { setSaveState("error", "تعذر الحفظ"); toast(error.message); }
  }
  function updateStats() {
    const text = el.editor.innerText.trim();
    el.wordCount.textContent = text ? text.split(/\s+/).length : 0; el.charCount.textContent = text.length;
  }
  function normalizeTaskChecks() {
    $$(".note-check", el.editor).forEach(check => {
      if (!check.dataset.state) check.dataset.state = check.dataset.checked === "true" ? "done" : "pending";
      check.removeAttribute("data-checked"); check.textContent = "";
      check.setAttribute("contenteditable", "false"); check.setAttribute("role", "checkbox"); check.setAttribute("tabindex", "0");
      check.setAttribute("aria-checked", check.dataset.state === "done" ? "true" : check.dataset.state === "cancelled" ? "mixed" : "false");
    });
  }
  function closeTaskCheckMenu() { el.checkMenu.hidden = true; state.activeCheck = null; }
  function openTaskCheckMenu(noteCheck) {
    if (!noteCheck || !el.editor.contains(noteCheck)) return;
    state.activeCheck = noteCheck; const rect = noteCheck.getBoundingClientRect();
    el.checkMenu.hidden = false;
    const menuRect = el.checkMenu.getBoundingClientRect();
    let left = rect.left + rect.width / 2 - menuRect.width / 2;
    left = Math.max(8, Math.min(left, innerWidth - menuRect.width - 8));
    let top = rect.bottom + 8;
    if (top + menuRect.height > innerHeight - 8) top = rect.top - menuRect.height - 8;
    el.checkMenu.style.left = `${left}px`; el.checkMenu.style.top = `${Math.max(8, top)}px`;
    $$("#notesCheckMenu [data-check-state]").forEach(button => button.classList.toggle("active", button.dataset.checkState === noteCheck.dataset.state));
  }
  function setTaskCheckState(value) {
    const check = state.activeCheck;
    if (!check || !["pending","done","cancelled"].includes(value)) return;
    check.dataset.state = value;
    check.setAttribute("aria-checked", value === "done" ? "true" : value === "cancelled" ? "mixed" : "false");
    closeTaskCheckMenu(); scheduleSave();
    toast(value === "done" ? "تم تحديد النقطة كمنجزة" : value === "cancelled" ? "تم تحديد النقطة كغير منجزة" : "أُعيد المربع فارغاً");
  }
  function updateStatus(note) { el.updated.textContent = note?.updated_at ? `آخر حفظ ${relativeDate(note.updated_at)}` : "—"; }
  function setAccent(color) {
    $("#notesApp").style.setProperty("--n-accent", color); el.dot.style.background = color;
    $$(".notes-color-picker button").forEach(b => b.classList.toggle("active", b.dataset.color === color));
    const note = current(); if (note) note.color = color;
  }
  function setFilterButton(filter) {
    state.filter = filter; $$(".notes-filters button").forEach(b => b.classList.toggle("active", b.dataset.filter === filter)); renderList();
  }
  function restoreEditorSelection() {
    el.editor.focus();
    if (!state.savedRange) return;
    const selection = window.getSelection();
    selection.removeAllRanges(); selection.addRange(state.savedRange);
  }
  function exec(command, value = null) {
    restoreEditorSelection(); document.execCommand(command, false, value); scheduleSave(); refreshToolbarState();
  }
  function insertHtml(html) { el.editor.focus(); document.execCommand("insertHTML", false, html); scheduleSave(); }
  function insertTable() {
    const rows = Math.min(12, Math.max(1, Number(prompt("عدد الصفوف:", "3")) || 0));
    if (!rows) return; const cols = Math.min(8, Math.max(1, Number(prompt("عدد الأعمدة:", "3")) || 0)); if (!cols) return;
    let html = '<table class="note-table"><tbody>';
    for (let r=0;r<rows;r++) { html += "<tr>"; for(let c=0;c<cols;c++) html += r===0 ? `<th>عنوان ${c+1}</th>` : "<td>بيان</td>"; html += "</tr>"; }
    insertHtml(html + "</tbody></table><p><br></p>");
  }
  function insertChart() {
    const labels = (prompt("أسماء الأعمدة مفصولة بفاصلة:", "يناير، فبراير، مارس") || "").split(/[,،]/).map(x=>x.trim()).filter(Boolean);
    if (!labels.length) return;
    const values = (prompt("القيم مفصولة بفاصلة:", "12، 19، 8") || "").split(/[,،]/).map(Number);
    if (values.some(Number.isNaN)) return toast("أدخل قيماً رقمية صحيحة");
    const type = (prompt("نوع الرسم: bar أو line أو pie", "bar") || "bar").toLowerCase();
    const data = { type:["bar","line","pie","doughnut"].includes(type) ? type : "bar", labels, values:values.slice(0,labels.length) };
    const encoded = escapeHtml(JSON.stringify(data));
    insertHtml(`<div class="note-chart" data-chart="${encoded}" data-chart-type="${data.type}">جارٍ تجهيز الرسم البياني…</div><p><br></p>`);
    renderCharts();
  }
  function renderCharts() {
    state.charts.forEach(chart => chart.destroy()); state.charts = [];
    $$(".note-chart", el.editor).forEach(box => {
      let cfg; try { cfg = JSON.parse(box.dataset.chart); } catch (_) { return; }
      box.innerHTML = ""; box.contentEditable = "false"; const canvas = document.createElement("canvas"); box.appendChild(canvas);
      if (!window.Chart) return;
      state.charts.push(new Chart(canvas, { type:cfg.type || "bar", data:{ labels:cfg.labels, datasets:[{ label:"البيانات", data:cfg.values, backgroundColor:["#7c3aedaa","#2563ebaa","#0891b2aa","#059669aa","#ca8a04aa","#ea580caa"], borderColor:"#7c3aed", borderWidth:2, tension:.35 }] }, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:cfg.type==="pie"||cfg.type==="doughnut"}} } }));
    });
  }
  function localWritingAssist(mode) {
    let lines = el.editor.innerText.split(/\n+/).map(line => line.trim()).filter(Boolean);
    if (lines.length === 1) lines = (lines[0].match(/[^.!؟؛]+[.!؟؛]?/g) || lines).map(line => line.trim()).filter(Boolean);
    if (!lines.length) return "";
    if (mode === "tasks") return `<h2>قائمة المهام</h2><ul>${lines.map(line => `<li>☐ ${escapeHtml(line.replace(/^[-*•\d.)\s]+/, ""))}</li>`).join("")}</ul>`;
    if (mode === "summary") return `<h2>الخلاصة</h2><ul>${[...new Set(lines)].slice(0, 8).map(line => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`;
    const firstIsTitle = lines.length > 1 && lines[0].length < 55;
    const title = firstIsTitle ? lines.shift().replace(/[:：]$/, "") : "الأفكار الرئيسية";
    return `<h2>${escapeHtml(title)}</h2><ul>${lines.map(line => `<li>${escapeHtml(line.replace(/^[-*•\d.)\s]+/, ""))}</li>`).join("")}</ul>`;
  }
  function setAssistantMode(mode) {
    $$("#notesAssistantModal [data-assistant-mode]").forEach(button => button.classList.toggle("active", button.dataset.assistantMode === mode));
    $("#notesAssistantTitle").textContent = ({organize:"ترتيب الملاحظة",tasks:"تحويل النص إلى مهام",summary:"استخراج الخلاصة"})[mode] || "مساعد الكتابة";
  }
  async function smartOrganize(mode) {
    if (!el.editor.innerText.trim()) return toast("اكتب بعض الأفكار أولاً");
    el.aiMenu.hidden = true; el.assistantModal.hidden = false; setAssistantMode(mode);
    el.assistantPreview.innerHTML = ""; el.assistantPreview.hidden = true;
    el.assistantError.hidden = true; el.assistantLoading.hidden = false;
    try {
      const data = await api("/notes/api/organize", { method:"POST", body:JSON.stringify({ content:el.editor.innerHTML, mode }) });
      state.assistantContent = data.content || localWritingAssist(mode);
    } catch (error) {
      state.assistantContent = localWritingAssist(mode);
      el.assistantError.textContent = "تعذر الاتصال بالخدمة، لذلك استُخدم الترتيب المحلي داخل جهازك.";
      el.assistantError.hidden = false;
    } finally {
      el.assistantLoading.hidden = true; el.assistantPreview.hidden = false;
      el.assistantPreview.innerHTML = state.assistantContent;
    }
  }
  function closeAssistant() { el.assistantModal.hidden = true; state.assistantContent = ""; }
  function applyAssistant(append = false) {
    if (!state.assistantContent) return;
    if (append) el.editor.insertAdjacentHTML("beforeend", `<hr>${state.assistantContent}`);
    else el.editor.innerHTML = state.assistantContent;
    closeAssistant(); updateStats(); scheduleSave(); toast("تم تطبيق اقتراح مساعد الكتابة");
  }
  function refreshToolbarState() {
    if (!state.savedRange) return;
    ["bold","italic","underline","strikeThrough","insertUnorderedList","insertOrderedList","justifyRight","justifyCenter","justifyLeft"].forEach(command => {
      const button = $(`#notesToolbar [data-cmd="${command}"]`);
      if (button) {
        try { button.classList.toggle("active", document.queryCommandState(command)); } catch (_) {}
      }
    });
  }
  function setupDrawing() {
    const modal = $("#notesDrawModal"), canvas = $("#notesDrawCanvas"), ctx = canvas.getContext("2d");
    ctx.lineCap = "round"; ctx.lineJoin = "round"; let drawing = false;
    const point = e => { const r=canvas.getBoundingClientRect(), p=e.touches?.[0]||e; return {x:(p.clientX-r.left)*canvas.width/r.width,y:(p.clientY-r.top)*canvas.height/r.height}; };
    const start = e => { drawing=true; const p=point(e); ctx.beginPath(); ctx.moveTo(p.x,p.y); e.preventDefault(); };
    const move = e => { if(!drawing)return; const p=point(e); ctx.strokeStyle=$("#drawColor").value;ctx.lineWidth=$("#drawSize").value;ctx.lineTo(p.x,p.y);ctx.stroke();e.preventDefault(); };
    ["pointerdown"].forEach(n=>canvas.addEventListener(n,start)); canvas.addEventListener("pointermove",move); window.addEventListener("pointerup",()=>drawing=false);
    return { modal, canvas, ctx };
  }
  const drawing = setupDrawing();
  async function showHistory() {
    const data = await api(`/notes/api/${state.activeId}/revisions`), list = $("#notesHistoryList");
    list.innerHTML = data.revisions.length ? data.revisions.map((r,i)=>`<div class="notes-history-item"><i class="fas fa-clock-rotate-left"></i><div><b>${escapeHtml(r.title)}</b><small>${new Intl.DateTimeFormat("ar-IQ",{dateStyle:"medium",timeStyle:"short"}).format(new Date(r.created_at))}</small></div><button data-restore-index="${i}">استعادة</button></div>`).join("") : '<div class="notes-list-empty">لا توجد نسخ سابقة بعد</div>';
    list._revisions = data.revisions; $("#notesHistoryModal").hidden = false;
  }
  async function deleteCurrent() {
    const note=current(); if(!note || !confirm(`حذف «${note.title}» نهائياً؟ لا يمكن التراجع.`)) return;
    await api(`/notes/api/${note.id}`,{method:"DELETE"}); state.notes=state.notes.filter(n=>n.id!==note.id);state.archived=state.archived.filter(n=>n.id!==note.id);state.activeId=null;el.app.classList.remove("mobile-editor-open");el.shell.hidden=true;el.empty.hidden=false;renderList();toast("تم حذف الملاحظة");
  }
  function exportCurrent() {
    const note=current(); if(!note)return; const html=`<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>${escapeHtml(note.title)}</title><style>body{max-width:850px;margin:40px auto;font-family:Arial;line-height:1.8}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:8px}img{max-width:100%}</style><h1>${escapeHtml(el.title.value)}</h1>${el.editor.innerHTML}`;
    const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([html],{type:"text/html;charset=utf-8"}));a.download=`${el.title.value||"note"}.html`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }
  document.addEventListener("click", async e => {
    const noteCard=e.target.closest("[data-note-id]"); if(noteCard){ await openNote(Number(noteCard.dataset.noteId));return; }
    const filter=e.target.closest("[data-filter]"); if(filter){ if(filter.dataset.filter==="archived"&&!state.archived.length)await loadLists();setFilterButton(filter.dataset.filter);return; }
    const cmd=e.target.closest("[data-cmd]"); if(cmd){exec(cmd.dataset.cmd);return;}
    const action=e.target.closest("[data-action]")?.dataset.action;
    if (!action) { if(!e.target.closest(".notes-ai-wrap"))el.aiMenu.hidden=true;if(!e.target.closest(".notes-more-wrap"))el.moreMenu.hidden=true;if(!e.target.closest(".notes-check-menu,.note-check"))closeTaskCheckMenu();return; }
    if(action==="new-note")createNote(); else if(action==="back-library"){await saveNow();el.app.classList.remove("mobile-editor-open");el.toolbar.classList.remove("tools-expanded");}
    else if(action==="toggle-library"){const collapsed=el.app.classList.toggle("library-collapsed");localStorage.setItem("finora-notes-library-collapsed",collapsed?"1":"0");}
    else if(action==="focus-mode"){el.app.classList.toggle("focus-mode");}
    else if(action==="toggle-tools"){const expanded=el.toolbar.classList.toggle("tools-expanded");const button=e.target.closest("[data-action='toggle-tools']");button.setAttribute("aria-expanded",String(expanded));$("span",button).textContent=expanded?"أدوات أقل":"كل الأدوات";}
    else if(action==="open-templates")el.templatesModal.hidden=false;
    else if(action==="close-templates")el.templatesModal.hidden=true;
    else if(action==="close-assistant")closeAssistant();
    else if(action==="assistant-apply")applyAssistant(false);
    else if(action==="assistant-append")applyAssistant(true);
    else if(action==="smart-menu")el.aiMenu.hidden=!el.aiMenu.hidden;
    else if(action==="more")el.moreMenu.hidden=!el.moreMenu.hidden; else if(action==="link"){const u=prompt("عنوان الرابط:","https://");if(u)exec("createLink",u);}
    else if(action==="table")insertTable(); else if(action==="chart")insertChart(); else if(action==="draw"){drawing.modal.hidden=false;drawing.ctx.fillStyle="#fff";drawing.ctx.fillRect(0,0,drawing.canvas.width,drawing.canvas.height);}
    else if(action==="close-draw")drawing.modal.hidden=true; else if(action==="clear-draw"){drawing.ctx.fillStyle="#fff";drawing.ctx.fillRect(0,0,drawing.canvas.width,drawing.canvas.height);}
    else if(action==="insert-drawing"){insertHtml(`<img src="${drawing.canvas.toDataURL("image/png")}" alt="رسم يدوي"><p><br></p>`);drawing.modal.hidden=true;}
    else if(action==="pin"){const n=current();await saveNow({is_pinned:!n.is_pinned});toast(n.is_pinned?"تم إلغاء التثبيت":"تم تثبيت الملاحظة");}
    else if(action==="archive"){const n=current();const archived=!n.is_archived;await saveNow({is_archived:archived});state.activeId=null;el.app.classList.remove("mobile-editor-open");el.shell.hidden=true;el.empty.hidden=false;el.moreMenu.hidden=true;renderList();toast(archived?"نُقلت إلى الأرشيف":"أُعيدت من الأرشيف");}
    else if(action==="toggle-done"){const n=current();await saveNow({status:n.status==="done"?"active":"done"});el.moreMenu.hidden=true;toast("تم تحديث حالة الملاحظة");}
    else if(action==="duplicate"){const d=await api(`/notes/api/${state.activeId}/duplicate`,{method:"POST"});state.notes.unshift(d.note);await openNote(d.note.id);toast("تم إنشاء نسخة");}
    else if(action==="delete")deleteCurrent(); else if(action==="print")window.print(); else if(action==="export")exportCurrent();
    else if(action==="history")showHistory(); else if(action==="close-history")$("#notesHistoryModal").hidden=true;
  });
  document.addEventListener("click", e => {
    const smart=e.target.closest("[data-smart]");if(smart)smartOrganize(smart.dataset.smart);
    const assistantMode=e.target.closest("[data-assistant-mode]");if(assistantMode)smartOrganize(assistantMode.dataset.assistantMode);
    const template=e.target.closest("[data-template]");if(template)createFromTemplate(template.dataset.template);
    const templateFilter=e.target.closest("[data-template-filter]");if(templateFilter){const filter=templateFilter.dataset.templateFilter;$$("[data-template-filter]").forEach(button=>button.classList.toggle("active",button===templateFilter));$$("[data-template]").forEach(card=>card.hidden=filter!=="all"&&card.dataset.templateCategory!==filter);}
    const noteCheck=e.target.closest(".note-check");if(noteCheck)openTaskCheckMenu(noteCheck);
    const checkState=e.target.closest("[data-check-state]");if(checkState)setTaskCheckState(checkState.dataset.checkState);
    const color=e.target.closest("[data-color]");if(color){setAccent(color.dataset.color);scheduleSave();}
    const restore=e.target.closest("[data-restore-index]");if(restore){const r=$("#notesHistoryList")._revisions[Number(restore.dataset.restoreIndex)];el.title.value=r.title;el.editor.innerHTML=r.content;$("#notesHistoryModal").hidden=true;scheduleSave();toast("تمت إعادة النسخة إلى المحرر");}
  });
  $$("#notesToolbar [data-format]").forEach(select=>select.addEventListener("change",()=>exec(select.dataset.format,select.value)));
  $$("#notesToolbar [data-color-command]").forEach(input=>input.addEventListener("input",()=>exec(input.dataset.colorCommand,input.value)));
  [el.title,el.category,el.tags,el.priority,el.dueAt].forEach(input=>input.addEventListener("input",scheduleSave));el.editor.addEventListener("input",scheduleSave);
  document.addEventListener("selectionchange",()=>{const selection=window.getSelection();if(!selection||!selection.rangeCount)return;const node=selection.anchorNode;if(node&&(node===el.editor||el.editor.contains(node))){state.savedRange=selection.getRangeAt(0).cloneRange();refreshToolbarState();}});
  el.search.addEventListener("input",()=>{state.search=el.search.value;renderList();});el.sort.addEventListener("change",renderList);
  document.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();el.search.focus();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"){e.preventDefault();saveNow();}if((e.ctrlKey||e.metaKey)&&e.key==="Enter"){e.preventDefault();createNote();}if(e.key==="Escape"){if(el.app.classList.contains("focus-mode"))el.app.classList.remove("focus-mode");else if(innerWidth<=720)el.app.classList.remove("mobile-editor-open");}});
  el.editor.addEventListener("keydown",e=>{const check=e.target.closest?.(".note-check");if(check&&(e.key==="Enter"||e.key===" ")){e.preventDefault();openTaskCheckMenu(check);}});
  window.addEventListener("beforeunload",()=>{if(state.saveTimer)saveNow();});
  if(localStorage.getItem("finora-notes-library-collapsed")==="1"&&innerWidth>720)el.app.classList.add("library-collapsed");
  let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(innerWidth>720&&!state.activeId&&state.notes.length)openNote(state.notes[0].id);},180);});
  loadLists().then(()=>{if(state.notes.length&&innerWidth>720)openNote(state.notes[0].id);}).catch(err=>toast(err.message));
})();
