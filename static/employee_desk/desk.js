(() => {
  const $ = (sel) => document.querySelector(sel);
  const app = $(".ed-app");

  const state = {
    status: "ALL",
    search: "",
    threads: [],
    active: null,        // selected thread meta
    chat: { page_id: "", psid: "", thread_id: "", sending: false, file: null },
    book: { customer: null, lines: [], saving: false },
    quick: { replies: [], loaded: false },
  };

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

  const money = (n) => `${Number(n || 0).toLocaleString("en-US")} د.ع`;

  function toast(text, kind = "ok") {
    const node = $("#ed-toast");
    node.textContent = text;
    node.className = `ed-toast ${kind}`;
    node.hidden = false;
    requestAnimationFrame(() => node.classList.add("show"));
    clearTimeout(node._t);
    node._t = setTimeout(() => {
      node.classList.remove("show");
      setTimeout(() => { node.hidden = true; }, 220);
    }, 3200);
  }

  function avatar(src, initials) {
    return `<span class="ed-avatar">${esc(initials || "ف")}</span>`;
  }

  function applyInbox(data) {
    state.threads = data.messages || [];
    const counts = data.status_counts || {};
    if ($("#ed-inbox-count")) {
      $("#ed-inbox-count").textContent = `${Number(counts.ALL || state.threads.length).toLocaleString("en-US")}`;
    }
    const waiting = Number(counts.WAITING_REPLY || 0) + Number(counts.LATE || 0);
    const badge = $("#ed-tab-badge");
    if (badge) {
      badge.hidden = waiting < 1;
      badge.textContent = waiting > 99 ? "99+" : String(waiting);
    }
    const useful = state.threads.some((row) => {
      const preview = String(row.preview || "");
      return preview && !preview.includes("افتح المحادثة");
    });
    renderHome();
    if (useful) {
      try { sessionStorage.setItem("ed-inbox", JSON.stringify({ messages: state.threads, status_counts: counts })); } catch (err) {}
    }
    renderInbox();
  }

  /* ── Inbox ──────────────────────────────────────────────────────────── */
  async function loadInbox() {
    const list = $("#ed-inbox");
    if (!state.threads.length) {
      try {
        const cached = JSON.parse(sessionStorage.getItem("ed-inbox") || "null");
        if (cached && cached.messages) applyInbox(cached);
      } catch (err) {}
    }
    if (!state.threads.length) {
      list.innerHTML = `<div class="ed-skel">${"<i></i>".repeat(6)}</div>`;
    }
    try {
      const response = await fetch("/api/employee-desk/inbox");
      if (response.status === 401 || response.status === 403) {
        window.location = "/employee-desk/login";
        return;
      }
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        list.innerHTML = `<div class="ed-blank small"><strong>ما وصلت الرسائل</strong>${esc(data.error || "حاول مرة ثانية")}</div>`;
        return;
      }
      applyInbox(data);
    } catch (err) {
      list.innerHTML = `<div class="ed-blank small">انقطع الاتصال.</div>`;
    }
  }

  function visibleThreads() {
    const term = state.search.trim().toLowerCase();
    return state.threads.filter((row) => {
      if (state.status !== "ALL" && row.status !== state.status) return false;
      if (!term) return true;
      return `${row.customer_name || ""} ${row.preview || ""} ${row.page_name || ""}`.toLowerCase().includes(term);
    });
  }

  function renderInbox() {
    const rows = visibleThreads();
    const list = $("#ed-inbox");
    if (!rows.length) {
      list.innerHTML = `<div class="ed-blank small">ماكو رسائل بهذا الفلتر.</div>`;
      return;
    }
    list.innerHTML = rows.map((row, index) => `
      <article class="ed-thread ${state.active && state.active.key === threadKey(row) ? "active" : ""} ${Number(row.unread_count) > 0 ? "has-unread" : ""}" data-index="${index}">
        ${avatar(row.customer_avatar || row.page_avatar, row.customer_initials || row.page_initials)}
        <div class="ed-thread-body">
          <div class="ed-thread-row">
            <p class="ed-thread-name">${esc(row.customer_name || "عميل")}</p>
            <span class="ed-thread-time">${esc(row.time_label || "")}</span>
          </div>
          <p class="ed-thread-prev">${esc(row.preview || "افتح المحادثة")}</p>
          <div class="ed-thread-row ed-thread-meta">
            ${threadChip(row)}
            ${Number(row.unread_count) > 0 ? `<span class="ed-unread">${Number(row.unread_count) > 99 ? "99+" : Number(row.unread_count)}</span>` : ""}
            <span class="ed-channel">${esc(row.page_name || "فيسبوك")}</span>
          </div>
        </div>
      </article>
    `).join("");
    list._rows = rows;
  }

  function threadChip(row) {
    const status = row.status || "";
    if (status === "LATE") return `<span class="ed-chip hot">${esc(row.status_label || "متأخر")}</span>`;
    if (status === "WAITING_REPLY") return `<span class="ed-chip wait">${esc(row.status_label || "بانتظار")}</span>`;
    if (status === "ANSWERED" || status === "ORDER_CREATED" || status === "CLOSED") return `<span class="ed-chip ok">${esc(row.status_label || "تم الرد")}</span>`;
    return "";
  }

  function renderHome() {
    const stats = $("#ed-home-stats");
    const tasks = $("#ed-home-tasks");
    if (!stats || !tasks) return;
    const rows = state.threads;
    const late = rows.filter((row) => row.status === "LATE");
    const waiting = rows.filter((row) => row.status === "WAITING_REPLY");
    const done = rows.filter((row) => ["ANSWERED", "ORDER_CREATED", "CLOSED"].includes(row.status));
    stats.innerHTML = `
      <article><span>اليوم</span><strong>${rows.length}</strong><small>إجمالي المحادثات</small></article>
      <article class="hot"><span>عاجل</span><strong>${late.length}</strong><small>متأخرة</small></article>
      <article><span>بانتظار</span><strong>${waiting.length}</strong><small>بانتظار الرد</small></article>
      <article><span>تم</span><strong>${done.length}</strong><small>تم الرد</small></article>`;
    const urgent = [...late, ...waiting].slice(0, 4);
    tasks.innerHTML = urgent.length
      ? urgent.map((row) => `
          <button type="button" class="ed-task" data-home-key="${esc(threadKey(row))}">
            <strong>${esc(row.customer_name || "زبون")}</strong>
            <span>${esc(row.preview || row.status_label || "")}</span>
          </button>`).join("")
      : `<p class="ed-blank small">ماكو مهام عاجلة حالياً.</p>`;
  }

  const threadKey = (row) => `${row.external_page_id || ""}:${row.customer_psid || ""}:${row.thread_id || ""}`;

  function markThreadAnswered(preview) {
    const active = state.active;
    if (!active) return;
    const key = threadKey(active);
    const row = state.threads.find((item) => threadKey(item) === key) || active;
    row.status = "ANSWERED";
    row.status_label = "تم الرد";
    row.response_tone = "success";
    if (preview) {
      const text = String(preview).replace(/^(أنت|انت|العميل):\s*/, "");
      row.preview = `أنت: ${text}`;
    }
    row.unread_count = 0;
    renderInbox();
  }

  /* ── Chat ───────────────────────────────────────────────────────────── */
  function friendlyChatError(raw) {
    const text = String(raw || "");
    if (/does not exist|missing permissions|Unsupported get request|Object with ID/i.test(text)) {
      return "فيسبوك ما رجّع هذي المحادثة. تقدر تحجز الطلب من بطاقة الزبون.";
    }
    if (/permission|#10|OAuth/i.test(text)) return "صلاحية الصفحة ناقصة. بلّغ المسؤول.";
    return text || "ما قدرنا نجيب المحادثة.";
  }

  function chatError(text) {
    const node = $("#ed-chat-error");
    node.hidden = !text;
    node.textContent = text || "";
  }

  const MEDIA_LABELS = /^(صورة|فيديو|صوت|ملف|وسائط|ملصق)$/;

  function mediaKind(att) {
    const mime = String((att && att.mime) || "").toLowerCase();
    const name = String((att && att.name) || "").toLowerCase();
    if (mime.startsWith("image/") || /\.(jpe?g|png|gif|webp|bmp)$/.test(name)) return "image";
    if (mime.startsWith("video/") || /\.(mp4|mov|m4v|webm)$/.test(name)) return "video";
    if (mime.startsWith("audio/") || /\.(mp3|ogg|m4a|aac|wav|opus)$/.test(name)) return "audio";
    if (att && att.kind === "sticker") return "image";
    return (att && att.kind) || "file";
  }

  function bubble(message) {
    const att = message.attachment;
    let media = "";
    const kind = att && att.url ? mediaKind(att) : "";
    if (att && att.url && kind === "image") media = `<img class="ed-media" src="${esc(att.url)}" alt="">`;
    else if (att && att.url && kind === "video") media = `<video class="ed-media" src="${esc(att.url)}" controls playsinline></video>`;
    else if (att && att.url && kind === "audio") media = `<audio controls src="${esc(att.url)}" style="width:100%;margin-bottom:6px"></audio>`;
    else if (att && att.url) media = `<a class="ed-filelink" href="${esc(att.url)}" target="_blank" rel="noopener">📎 ${esc(att.name || "ملف")}</a>`;
    else if (att) media = `<span class="ed-filelink">📎 ${esc(att.name || "وسائط غير متاحة")}</span>`;
    const text = String(message.text || "").trim();
    const showText = text && !(media && MEDIA_LABELS.test(text));
    return `
      <div class="ed-row ${message.direction === "out" ? "out" : "in"}">
        <div class="ed-bubble">${media}${showText ? `<div class="ed-bubble-txt">${esc(text)}</div>` : ""}</div>
        <span class="ed-bubble-time">${esc(message.time_label || "")}</span>
      </div>`;
  }

  function composerEnabled(on) {
    const input = $("#ed-chat-input");
    input.disabled = false;
    input.readOnly = false;
    input.removeAttribute("disabled");
    $("#ed-chat-send").disabled = !on;
    $("#ed-chat-attach").disabled = !on;
  }

  async function openThread(row) {
    state.active = { ...row, key: threadKey(row) };
    row.unread_count = 0;
    const listed = state.threads.find((item) => threadKey(item) === state.active.key);
    if (listed) listed.unread_count = 0;
    state.chat.page_id = row.external_page_id || "";
    state.chat.psid = row.customer_psid || "";
    state.chat.thread_id = row.thread_id || "";
    clearFile();
    chatError("");
    renderInbox();
    showPane("ed-pane-chat");

    $("#ed-chat-name").textContent = row.customer_name || "عميل";
    $("#ed-chat-page").textContent = row.page_name || "";
    const face = row.customer_avatar || row.page_avatar || "";
    $("#ed-chat-avatar").innerHTML = face
      ? `<img src="${esc(face)}" alt="">`
      : esc((row.customer_name || "ف").slice(0, 1));
    $("#ed-stream").innerHTML = `<div class="ed-blank small">جاري تحميل المحادثة…</div>`;
    composerEnabled(Boolean(state.chat.page_id && state.chat.psid));
    $("#ed-chat-input").focus();
    renderCustomerFromThread(row);
    loadTeammates(state.chat.page_id);

    const params = new URLSearchParams({
      page_id: state.chat.page_id,
      thread_id: state.chat.thread_id,
      customer_psid: state.chat.psid,
    });
    try {
      const response = await fetch(`/api/facebook-monitor/thread?${params}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        $("#ed-stream").innerHTML = `<div class="ed-blank"><strong>ما قدرنا نجيب المحادثة</strong>${esc(friendlyChatError(data.error))}</div>`;
        composerEnabled(Boolean(state.chat.page_id && state.chat.psid));
        return;
      }
      const thread = data.thread || {};
      state.chat.thread_id = thread.thread_id || state.chat.thread_id;
      state.chat.page_id = thread.external_page_id || state.chat.page_id;
      state.chat.psid = thread.customer_psid || state.chat.psid;
      $("#ed-chat-name").textContent = thread.customer_name || row.customer_name || "عميل";
      $("#ed-chat-page").textContent = thread.page_name || row.page_name || "";
      const face = thread.customer_avatar || row.customer_avatar || row.page_avatar || "";
      $("#ed-chat-avatar").innerHTML = face
        ? `<img src="${esc(face)}" alt="">`
        : esc((thread.customer_name || row.customer_name || "ف").slice(0, 1));
      const messages = thread.messages || [];
      const stream = $("#ed-stream");
      stream.innerHTML = messages.length
        ? messages.map(bubble).join("")
        : `<div class="ed-blank small">ماكو رسائل بهالمحادثة.</div>`;
      stream.scrollTop = stream.scrollHeight;
      composerEnabled(Boolean(state.chat.page_id && state.chat.psid));
      if (!state.chat.psid) chatError("ما نقدر نرد — معرّف العميل ناقص.");
    } catch (err) {
      $("#ed-stream").innerHTML = `<div class="ed-blank small">انقطع الاتصال.</div>`;
      composerEnabled(Boolean(state.chat.page_id && state.chat.psid));
    }
  }

  function appendBubble(message) {
    const stream = $("#ed-stream");
    const blank = stream.querySelector(".ed-blank");
    if (blank) blank.remove();
    stream.insertAdjacentHTML("beforeend", bubble(message));
    stream.scrollTop = stream.scrollHeight;
  }

  function clearFile() {
    state.chat.file = null;
    $("#ed-chat-file").value = "";
    $("#ed-file-chip").hidden = true;
    $("#ed-file-chip").innerHTML = "";
  }

  function setFile(file) {
    if (!file) return clearFile();
    state.chat.file = file;
    const chip = $("#ed-file-chip");
    chip.hidden = false;
    const thumb = file.type.startsWith("image/") ? `<img src="${URL.createObjectURL(file)}" alt="">` : "📎";
    chip.innerHTML = `${thumb}<span>${esc(file.name)}</span><button type="button" id="ed-file-clear">إزالة</button>`;
  }

  async function sendTextNow(text, { fromInput = false } = {}) {
    if (state.chat.sending) return false;
    const body = String(text || "").trim();
    if (!body && !state.chat.file) return false;
    if (!state.chat.page_id || !state.chat.psid) {
      chatError("افتح محادثة من القائمة أولاً.");
      return false;
    }
    state.chat.sending = true;
    $("#ed-chat-send").disabled = true;
    chatError("");
    try {
      let data;
      if (fromInput && state.chat.file) {
        const form = new FormData();
        form.append("file", state.chat.file);
        form.append("page_id", state.chat.page_id);
        form.append("customer_psid", state.chat.psid);
        if (body) form.append("caption", body);
        const response = await fetch("/api/facebook-monitor/thread/media", { method: "POST", body: form });
        data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) { chatError(data.error || "فشل إرسال الوسائط"); return false; }
        clearFile();
      } else {
        const response = await fetch("/api/facebook-monitor/thread/reply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ page_id: state.chat.page_id, customer_psid: state.chat.psid, text: body }),
        });
        data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) { chatError(data.error || "فشل الإرسال"); return false; }
      }
      appendBubble(data.message || { direction: "out", text: body, time_label: "الآن" });
      pulse("replying", $("#ed-chat-name")?.textContent || "");
      clearTimeout(pulse._idle);
      pulse._idle = setTimeout(() => { pulseMode = "open"; pulse("open"); }, 8000);
      markThreadAnswered(body || (data.message && data.message.text) || "");
      if (fromInput) {
        const input = $("#ed-chat-input");
        input.value = "";
        input.style.height = "auto";
        input.focus();
      }
      loadInbox();
      return true;
    } finally {
      state.chat.sending = false;
      $("#ed-chat-send").disabled = !state.chat.psid;
    }
  }

  async function sendReply(event) {
    event.preventDefault();
    await sendTextNow($("#ed-chat-input").value, { fromInput: true });
  }

  function renderQuickReplies() {
    const list = $("#ed-quick-list");
    const rows = state.quick.replies;
    if (!rows.length) {
      list.innerHTML = `<div class="ed-quick-empty">ماكو ردود بعد.<br>أضف جملة يستخدمها المكتب كل يوم.</div>`;
      return;
    }
    list.innerHTML = rows.map((row) => `
      <div class="ed-quick-row">
        <button type="button" class="ed-quick-item" data-id="${row.id}">${esc(row.text)}</button>
        <button type="button" class="ed-quick-del" data-del="${row.id}" aria-label="حذف">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>
    `).join("");
  }

  async function loadQuickReplies() {
    try {
      const response = await fetch("/api/employee-desk/quick-replies");
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) return;
      state.quick.replies = data.replies || [];
      state.quick.loaded = true;
      renderQuickReplies();
    } catch (err) { /* keep last list */ }
  }

  function toggleQuickPop(force) {
    const pop = $("#ed-quick-pop");
    const open = force === true ? true : force === false ? false : pop.hidden;
    pop.hidden = !open;
    $("#ed-quick-open").setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      if (!state.quick.loaded) loadQuickReplies();
      else renderQuickReplies();
      setTimeout(() => $("#ed-quick-text").focus(), 40);
    }
  }

  /* ── Customer pane ──────────────────────────────────────────────────── */
  function renderCustomerFromThread(row) {
    // Facebook gives us a name only; phone/address come from the CRM match.
    $("#ed-customer-body").innerHTML = `
      <div class="ed-cust-card">
        <div class="ed-cust-top">
          <span class="ed-avatar">${esc((row.customer_name || "ف").slice(0, 1))}</span>
          <div>
            <h3>${esc(row.customer_name || "عميل فيسبوك")}</h3>
            <span>${esc(row.page_name || "")}</span>
          </div>
        </div>
        <dl class="ed-kv"><dt>المصدر</dt><dd>${esc(row.source || "Facebook")}</dd></dl>
        ${row.campaign ? `<dl class="ed-kv"><dt>الحملة</dt><dd>${esc(row.campaign)}</dd></dl>` : ""}
        <dl class="ed-kv"><dt>الحالة</dt><dd>${esc(row.status_label || "")}</dd></dl>
      </div>`;
    $("#ed-customer-orders").innerHTML = `<div class="ed-blank small">ابحث عن الزبون داخل ورقة الحجز لعرض طلباته.</div>`;
  }

  function renderPickedCustomer(customer) {
    $("#ed-customer-body").innerHTML = `
      <div class="ed-cust-card">
        <div class="ed-cust-top">
          <span class="ed-avatar">${esc((customer.name || "ف").slice(0, 1))}</span>
          <div>
            <h3>${esc(customer.name)}</h3>
            <span>زبون مسجّل</span>
          </div>
        </div>
        <dl class="ed-kv"><dt>الهاتف</dt><dd>${esc(customer.phone || "—")}</dd></dl>
        <dl class="ed-kv"><dt>المحافظة</dt><dd>${esc(customer.city || "—")}</dd></dl>
        <dl class="ed-kv"><dt>العنوان</dt><dd>${esc(customer.address || "—")}</dd></dl>
      </div>`;
    loadCustomerOrders(customer.id);
  }

  async function loadCustomerOrders(customerId) {
    const box = $("#ed-customer-orders");
    box.innerHTML = `<div class="ed-blank small">…</div>`;
    try {
      const response = await fetch(`/api/employee-desk/customers/${customerId}/orders`);
      const data = await response.json().catch(() => ({}));
      const orders = (data && data.orders) || [];
      box.innerHTML = orders.length
        ? orders.map((row) => `
          <div class="ed-order">
            <b>${esc(row.label)}</b>
            <div class="ed-grow"><span class="date">${esc(window.FinoraTime.dateTime(row.date))}</span></div>
            <span class="ed-tag muted">${esc(row.status || "—")}</span>
            <b>${esc(row.total_label)}</b>
          </div>`).join("")
        : `<div class="ed-blank small">ماكو طلبات سابقة.</div>`;
    } catch (err) {
      box.innerHTML = `<div class="ed-blank small">تعذر جلب الطلبات.</div>`;
    }
  }

  /* ── Booking sheet ──────────────────────────────────────────────────── */
  function toggleNewCustomer(open) {
    const form = $("#ed-cust-new");
    const show = open === true ? true : open === false ? false : form.hidden;
    form.hidden = !show;
    $("#ed-sheet").classList.toggle("ed-pos-new-open", show);
    if (show) {
      if (!state.book.customer && state.active && state.active.customer_name && !$("#ed-nc-name").value) {
        $("#ed-nc-name").value = state.active.customer_name;
      }
      $("#ed-nc-name").focus();
    }
  }

  function openSheet() {
    const sheet = $("#ed-sheet");
    const back = $("#ed-sheet-back");
    sheet.hidden = false;
    back.hidden = false;
    requestAnimationFrame(() => { sheet.classList.add("show"); back.classList.add("show"); });
    sheetError("");
    toggleNewCustomer(false);
    if (!state.book.customer && state.active && state.active.customer_name) {
      $("#ed-nc-name").value = state.active.customer_name;
    }
    $("#ed-prod-results").innerHTML = "";
    if (!state.book.customer) $("#ed-cust-q").focus();
  }

  function closeSheet() {
    const sheet = $("#ed-sheet");
    const back = $("#ed-sheet-back");
    toggleNewCustomer(false);
    sheet.classList.remove("show");
    back.classList.remove("show");
    setTimeout(() => { sheet.hidden = true; back.hidden = true; }, 240);
  }

  function sheetError(text) {
    const node = $("#ed-sheet-error");
    node.hidden = !text;
    node.textContent = text || "";
  }

  function setCustomer(customer) {
    state.book.customer = customer;
    $("#ed-cust-pick").hidden = true;
    $("#ed-cust-change").hidden = false;
    const picked = $("#ed-cust-picked");
    picked.hidden = false;
    picked.innerHTML = `
      <span class="ed-avatar" style="width:34px;height:34px;background:#fff;color:#650016">${esc((customer.name || "ف").slice(0, 1))}</span>
      <div class="ed-grow">
        <strong>${esc(customer.name)}</strong>
        <small>${esc(customer.phone || "")} · ${esc(customer.city || "")}</small>
      </div>`;
    $("#ed-grp-customer").classList.add("done");
    toggleNewCustomer(false);
    renderPickedCustomer(customer);
    refreshConfirm();
    $("#ed-prod-q").focus();
  }

  function unsetCustomer() {
    state.book.customer = null;
    $("#ed-cust-pick").hidden = false;
    $("#ed-cust-picked").hidden = true;
    $("#ed-cust-change").hidden = true;
    $("#ed-grp-customer").classList.remove("done");
    $("#ed-cust-q").value = "";
    $("#ed-cust-results").innerHTML = "";
    refreshConfirm();
  }

  let custTimer = null;
  async function searchCustomers(term) {
    const box = $("#ed-cust-results");
    if (term.trim().length < 2) { box.innerHTML = ""; return; }
    const response = await fetch(`/api/employee-desk/customers?q=${encodeURIComponent(term)}`);
    const data = await response.json().catch(() => ({}));
    const rows = (data && data.customers) || [];
    box.innerHTML = rows.length
      ? rows.map((row) => `
        <button type="button" class="ed-opt" data-customer='${esc(JSON.stringify(row))}'>
          <span class="ed-avatar" style="width:34px;height:34px;font-size:11px">${esc((row.name || "ف").slice(0, 1))}</span>
          <span class="ed-grow"><strong>${esc(row.name)}</strong><small>${esc(row.phone)} · ${esc(row.city || "—")}</small></span>
        </button>`).join("")
      : `<div class="ed-blank small">ماكو نتيجة. سجّله كزبون جديد.</div>`;
  }

  async function saveNewCustomer() {
    sheetError("");
    const body = {
      name: $("#ed-nc-name").value.trim(),
      phone: $("#ed-nc-phone").value.trim(),
      city: $("#ed-nc-city").value,
      address: $("#ed-nc-address").value.trim(),
    };
    if (!body.name || !body.phone) { sheetError("الاسم والهاتف مطلوبان."); return; }
    const button = $("#ed-nc-save");
    button.disabled = true;
    try {
      const response = await fetch("/api/employee-desk/customers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) { sheetError(data.error || "تعذر حفظ الزبون"); return; }
      setCustomer(data.customer);
      toast(data.existing ? "الزبون موجود مسبقاً — تم ربطه" : "تم حفظ الزبون");
    } finally {
      button.disabled = false;
    }
  }

  let prodTimer = null;
  function colorNames(colors) {
    return (colors || []).map((row) => (typeof row === "string" ? row : (row && row.name) || "")).filter(Boolean);
  }

  async function searchProducts(term) {
    const box = $("#ed-prod-results");
    const q = (term || "").trim();
    if (q.length < 2) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="ed-pos-empty">جاري البحث…</div>`;
    const response = await fetch(`/api/employee-desk/products?q=${encodeURIComponent(q)}`);
    const data = await response.json().catch(() => ({}));
    const rows = (data && data.products) || [];
    box.innerHTML = rows.length
      ? rows.map((row) => `
        <button type="button" class="ed-opt" data-product='${esc(JSON.stringify({ id: row.id, name: row.name, price: row.price, colors: row.colors || [] }))}'>
          <span class="ed-grow"><strong>${esc(row.name)}</strong><small>${esc(row.sku || "")}</small></span>
          <span class="ed-opt-price">${esc(row.price_label)}</span>
        </button>`).join("")
      : `<div class="ed-pos-empty">ماكو منتج بهذا الاسم.</div>`;
  }

  function addLine(product) {
    const existing = state.book.lines.find((row) => row.product_id === product.id);
    if (existing) existing.qty += 1;
    else state.book.lines.push({
      product_id: product.id,
      name: product.name,
      price: product.price,
      qty: 1,
      color: "",
      colors: colorNames(product.colors),
    });
    $("#ed-prod-q").value = "";
    $("#ed-prod-results").innerHTML = "";
    renderCart();
  }

  function renderCart() {
    const box = $("#ed-cart");
    const count = state.book.lines.reduce((sum, row) => sum + row.qty, 0);
    const countNode = $("#ed-cart-count");
    if (countNode) countNode.textContent = count ? `${count} قطعة` : "فارغة";
    box.innerHTML = state.book.lines.length
      ? state.book.lines.map((row, index) => `
      <div class="ed-line">
        <div class="ed-grow">
          <strong>${esc(row.name)}</strong>
          <small>${money(row.price)}</small>
          ${row.colors && row.colors.length ? `
            <select class="ed-line-color" data-color="${index}" aria-label="اللون">
              <option value="">اختر اللون</option>
              ${row.colors.map((name) => `<option value="${esc(name)}"${row.color === name ? " selected" : ""}>${esc(name)}</option>`).join("")}
            </select>` : ""}
        </div>
        <div class="ed-qty">
          <button type="button" data-qty="-1" data-index="${index}" aria-label="أقل">−</button>
          <b>${row.qty}</b>
          <button type="button" data-qty="1" data-index="${index}" aria-label="أكثر">+</button>
        </div>
        <b class="ed-line-sum">${money(row.price * row.qty)}</b>
        <button type="button" class="ed-line-del" data-del="${index}" aria-label="حذف">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>`).join("")
      : `<div class="ed-pos-empty">اضغط منتج لإضافته</div>`;
    const total = state.book.lines.reduce((sum, row) => sum + row.price * row.qty, 0);
    $("#ed-total").textContent = money(total);
    $("#ed-grp-products").classList.toggle("done", state.book.lines.length > 0);
    refreshConfirm();
  }

  function refreshConfirm() {
    const ready = Boolean(state.book.customer) && state.book.lines.length > 0;
    $("#ed-confirm").disabled = !ready || state.book.saving;
    $("#ed-sheet-step").textContent = !state.book.customer
      ? "اختر زبون ثم اضغط المنتجات"
      : (!state.book.lines.length ? "اضغط المنتجات لإضافتها" : "جاهز — احجز الطلب");
  }

  async function confirmBooking() {
    if (state.book.saving) return;
    sheetError("");
    state.book.saving = true;
    const button = $("#ed-confirm");
    button.disabled = true;
    button.textContent = "جاري الحجز…";
    try {
      const response = await fetch("/api/employee-desk/book", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_id: state.book.customer.id,
          items: state.book.lines.map((row) => ({ product_id: row.product_id, qty: row.qty, color: row.color })),
          note: $("#ed-note").value.trim(),
          facebook_page_id: state.chat.page_id || "",
          facebook_page_name: (state.active && state.active.page_name) || "",
          customer_psid: state.chat.psid || "",
          submission_token: `desk-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        sheetError(data.error || "تعذر حجز الطلب");
        return;
      }
      toast(`تم حجز الطلب ${data.label} · ${data.total_label}`, "ok");
      if (data.stock_locked) {
        toast("الطلب محجوز بانتظار توفر المخزون", "bad");
      }
      const customer = state.book.customer;
      state.book.lines = [];
      $("#ed-note").value = "";
      $("#ed-prod-q").value = "";
      $("#ed-prod-results").innerHTML = "";
      renderCart();
      loadCustomerOrders(customer.id);
      closeSheet();
    } catch (err) {
      sheetError("انقطع الاتصال. أعد المحاولة.");
    } finally {
      state.book.saving = false;
      button.textContent = "احجز الطلب";
      refreshConfirm();
    }
  }

  /* ── Panes / tabs ───────────────────────────────────────────────────── */
  function showPane(id) {
    const isPhone = window.matchMedia("(max-width: 720px)").matches;
    const isTablet = window.matchMedia("(max-width: 1080px)").matches;
    const titles = {
      "ed-pane-home": "الرئيسية",
      "ed-pane-inbox": "الرسائل",
      "ed-pane-orders": "الطلبات",
      "ed-pane-chat": (state.active && state.active.customer_name) || "المحادثة",
      "ed-pane-customer": "العملاء",
      "ed-pane-more": "الحساب",
    };
    app.dataset.pane = id;
    app.classList.toggle("ed-thread-open", Boolean(state.active) && id === "ed-pane-chat");
    const title = $("#ed-nav-title");
    if (title) title.textContent = titles[id] || "مكتب الموظف";
    if (isPhone) {
      document.querySelectorAll(".ed-pane").forEach((pane) => pane.classList.toggle("active", pane.id === id));
      document.querySelectorAll(".ed-tabs button").forEach((btn) => btn.classList.toggle("active", btn.dataset.pane === id));
      return;
    }
    if (isTablet && id === "ed-pane-customer") $("#ed-pane-customer").classList.add("show");
  }

  /* ── Events ─────────────────────────────────────────────────────────── */
  $("#ed-inbox").addEventListener("click", (event) => {
    const card = event.target.closest(".ed-thread");
    if (!card) return;
    const rows = $("#ed-inbox")._rows || [];
    const row = rows[Number(card.dataset.index)];
    if (row) openThread(row);
  });

  $("#ed-inbox-search").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderInbox();
  });

  $("#ed-inbox-filters").addEventListener("click", (event) => {
    const button = event.target.closest(".ed-seg-btn");
    if (!button) return;
    state.status = button.dataset.status;
    document.querySelectorAll("#ed-inbox-filters .ed-seg-btn").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    renderInbox();
  });

  $("#ed-chat-form").addEventListener("submit", sendReply);
  $("#ed-chat-attach").addEventListener("click", () => $("#ed-chat-file").click());
  $("#ed-chat-file").addEventListener("change", (event) => setFile(event.target.files && event.target.files[0]));
  $(".ed-compose")?.addEventListener("click", () => $("#ed-chat-input").focus());
  $("#ed-chat-input").addEventListener("input", (event) => {
    event.target.style.height = "auto";
    event.target.style.height = `${Math.min(event.target.scrollHeight, 108)}px`;
    if (!String(event.target.value || "").trim()) return;
    const name = $("#ed-chat-name")?.textContent || "";
    pulse("typing", name && name !== "اختر محادثة" ? name : "");
    clearTimeout(pulse._idle);
    pulse._idle = setTimeout(() => { pulseMode = "open"; pulse("open"); }, 2500);
  });
  $("#ed-chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("#ed-chat-form").requestSubmit();
    }
  });
  $("#ed-chat-back").addEventListener("click", () => showPane("ed-pane-inbox"));
  $("#ed-open-customer").addEventListener("click", () => showPane("ed-pane-customer"));
  $("#ed-close-customer").addEventListener("click", () => $("#ed-pane-customer").classList.remove("show"));

  document.body.addEventListener("click", (event) => {
    if (event.target.id === "ed-file-clear") clearFile();
  });

  document.querySelectorAll(".ed-tabs button").forEach((button) => {
    button.addEventListener("click", () => {
      const pane = button.dataset.pane;
      if (pane === "ed-pane-chat" && !state.active) {
        const pick = state.threads.find((row) => Number(row.unread_count) > 0) || state.threads[0];
        if (pick) {
          openThread(pick);
          return;
        }
      }
      showPane(pane);
    });
  });

  $("#ed-quick-open").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleQuickPop();
  });
  $("#ed-quick-add").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#ed-quick-text");
    const text = input.value.trim();
    if (text.length < 2) return;
    const response = await fetch("/api/employee-desk/quick-replies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      toast(data.error || "ما انحفظ الرد", "bad");
      return;
    }
    input.value = "";
    if (!data.existing) state.quick.replies.unshift(data.reply);
    renderQuickReplies();
  });
  $("#ed-quick-list").addEventListener("click", async (event) => {
    const del = event.target.closest("[data-del]");
    const send = event.target.closest("[data-id]");
    if (del) {
      event.preventDefault();
      const id = Number(del.dataset.del);
      const response = await fetch(`/api/employee-desk/quick-replies/${id}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        toast(data.error || "ما انحذف", "bad");
        return;
      }
      state.quick.replies = state.quick.replies.filter((row) => row.id !== id);
      renderQuickReplies();
      return;
    }
    if (send) {
      const row = state.quick.replies.find((item) => String(item.id) === String(send.dataset.id));
      if (!row) return;
      toggleQuickPop(false);
      const ok = await sendTextNow(row.text);
      if (ok) toast("تم إرسال الرد");
    }
  });
  document.addEventListener("click", (event) => {
    const pop = $("#ed-quick-pop");
    if (pop.hidden) return;
    if (event.target.closest("#ed-quick-pop") || event.target.closest("#ed-quick-open")) return;
    toggleQuickPop(false);
  });

  $("#ed-pane-more")?.addEventListener("click", async (event) => {
    const hide = event.target.closest("[data-hide-money]");
    if (hide) {
      const root = document.querySelector(".ed-account");
      const hidden = root.classList.toggle("is-money-hidden");
      hide.textContent = hidden ? "إظهار الأرقام" : "إخفاء الأرقام";
      hide.setAttribute("aria-pressed", hidden ? "true" : "false");
      return;
    }
    const copy = event.target.closest("[data-copy]");
    if (!copy || !copy.dataset.copy) return;
    try {
      await navigator.clipboard.writeText(copy.dataset.copy);
      toast("تم النسخ");
    } catch (error) {
      toast("ما اننسخ", "bad");
    }
  });
  $("#ed-open-book")?.addEventListener("click", openSheet);
  document.querySelectorAll("[data-open-book]").forEach((button) => button.addEventListener("click", openSheet));
  document.querySelectorAll("[data-pane-jump]").forEach((button) => {
    button.addEventListener("click", () => showPane(button.dataset.paneJump));
  });
  $("#ed-home-tasks")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-home-key]");
    if (!button) return;
    const row = state.threads.find((item) => threadKey(item) === button.dataset.homeKey);
    if (row) openThread(row);
  });
  $("#ed-bell")?.addEventListener("click", () => {
    state.status = "LATE";
    document.querySelectorAll("#ed-inbox-filters .ed-seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.status === "LATE"));
    renderInbox();
    showPane("ed-pane-inbox");
  });
  $("#ed-book-from-chat").addEventListener("click", openSheet);
  $("#ed-book-from-customer").addEventListener("click", openSheet);
  $("#ed-sheet-close").addEventListener("click", closeSheet);
  $("#ed-sheet-back").addEventListener("click", closeSheet);
  $("#ed-cust-change").addEventListener("click", unsetCustomer);
  $("#ed-cust-new-toggle").addEventListener("click", () => toggleNewCustomer());
  $("#ed-cust-new-cancel")?.addEventListener("click", () => toggleNewCustomer(false));
  $("#ed-nc-save").addEventListener("click", saveNewCustomer);
  $("#ed-confirm").addEventListener("click", confirmBooking);

  $("#ed-cust-q").addEventListener("input", (event) => {
    clearTimeout(custTimer);
    const term = event.target.value;
    custTimer = setTimeout(() => searchCustomers(term), 260);
  });
  $("#ed-cust-results").addEventListener("click", (event) => {
    const option = event.target.closest("[data-customer]");
    if (!option) return;
    try { setCustomer(JSON.parse(option.dataset.customer)); } catch (err) { /* ignore */ }
  });

  $("#ed-prod-q").addEventListener("input", (event) => {
    clearTimeout(prodTimer);
    const term = event.target.value;
    prodTimer = setTimeout(() => searchProducts(term), 260);
  });
  $("#ed-prod-q").addEventListener("focus", () => {
    if (($("#ed-prod-q").value || "").trim().length < 2) $("#ed-prod-results").innerHTML = "";
  });
  $("#ed-prod-results").addEventListener("click", (event) => {
    const option = event.target.closest("[data-product]");
    if (!option) return;
    try { addLine(JSON.parse(option.dataset.product)); } catch (err) { /* ignore */ }
  });

  $("#ed-cart").addEventListener("change", (event) => {
    const select = event.target.closest("[data-color]");
    if (!select) return;
    const line = state.book.lines[Number(select.dataset.color)];
    if (line) line.color = select.value;
  });
  $("#ed-cart").addEventListener("click", (event) => {
    const step = event.target.closest("[data-qty]");
    const del = event.target.closest("[data-del]");
    if (step) {
      const index = Number(step.dataset.index);
      const line = state.book.lines[index];
      if (!line) return;
      line.qty += Number(step.dataset.qty);
      if (line.qty < 1) state.book.lines.splice(index, 1);
      renderCart();
    } else if (del) {
      state.book.lines.splice(Number(del.dataset.del), 1);
      renderCart();
    }
  });

  function closeTransferPop() {
    const pop = $("#ed-transfer-pop");
    if (!pop) return;
    pop.hidden = true;
    pop.classList.remove("show");
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("#ed-transfer-pop, #ed-transfer-open")) return;
    closeTransferPop();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if ($("#ed-transfer-pop") && !$("#ed-transfer-pop").hidden) closeTransferPop();
    else if (!$("#ed-quick-pop").hidden) toggleQuickPop(false);
    else if ($("#ed-sheet").classList.contains("ed-pos-new-open")) toggleNewCustomer(false);
    else if (!$("#ed-sheet").hidden) closeSheet();
    else $("#ed-pane-customer").classList.remove("show");
  });

  async function loadPresence() {
    const box = $("#ed-accept-messages");
    if (!box) return;
    const response = await fetch("/api/facebook-routing/me");
    const data = await response.json().catch(() => ({}));
    if (data.ok) box.checked = data.accept_messages !== false;
  }

  async function loadTeammates(pageId) {
    const pop = $("#ed-transfer-pop");
    if (!pop) return;
    const response = await fetch(`/api/facebook-routing/teammates?page_id=${encodeURIComponent(pageId || "")}`);
    const data = await response.json().catch(() => ({}));
    const rows = (data.employees || []).filter((row) => String(row.id) !== String(app.dataset.viewerId || ""));
    pop.innerHTML = rows.length
      ? rows.map((row) => `<button type="button" data-emp="${row.id}">${esc(row.name)} · ${row.active} مفتوحة</button>`).join("")
      : `<button type="button" disabled>ماكو موظف ثاني بهالصفحة</button>`;
  }

  $("#ed-accept-messages")?.addEventListener("change", async (event) => {
    await fetch("/api/facebook-routing/me", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accept_messages: event.target.checked }),
    });
  });
  $("#ed-transfer-open")?.addEventListener("click", (event) => {
    event.stopPropagation();
    const pop = $("#ed-transfer-pop");
    if (!state.chat.page_id) {
      toast("افتح محادثة أولاً", "bad");
      return;
    }
    pop.hidden = !pop.hidden;
    pop.classList.toggle("show", !pop.hidden);
  });
  $("#ed-transfer-pop")?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-emp]");
    if (!button) return;
    const response = await fetch("/api/facebook-routing/transfer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_id: state.chat.page_id,
        customer_psid: state.chat.psid,
        employee_id: Number(button.dataset.emp),
      }),
    });
    const data = await response.json().catch(() => ({}));
    closeTransferPop();
    if (!response.ok || !data.ok) {
      toast(data.error || "ما تحولت المحادثة", "bad");
      return;
    }
    toast("تم تحويل المحادثة");
    showPane("ed-pane-inbox");
    loadInbox();
  });

  function nativeNotify(title, body) {
    try {
      if (window.FinoraDesk && typeof window.FinoraDesk.notify === "function") {
        window.FinoraDesk.notify(String(title || "رسالة جديدة"), String(body || ""));
        return;
      }
    } catch (err) {}
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    try {
      new Notification(title || "رسالة جديدة", { body: body || "", tag: "employee-desk", renotify: true });
    } catch (err) {}
  }

  async function startDeskAlerts() {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/employee-desk/sw.js").catch(() => {});
    }
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
    let lastKey = "";
    const tick = async () => {
      try {
        const response = await fetch("/api/employee-desk/alerts");
        if (response.status === 401 || response.status === 403) return;
        const data = await response.json();
        if (!data.ok) return;
        const unread = Number(data.unread || 0);
        const badge = $("#ed-tab-badge");
        if (badge && unread > 0) {
          badge.hidden = false;
          badge.textContent = unread > 99 ? "99+" : String(unread);
        }
        document.title = unread ? `(${unread}) مكتب الموظف` : "مكتب الموظف";
        const latest = data.latest || null;
        const key = latest ? `${latest.page_id || ""}:${latest.psid || ""}:${latest.preview || ""}` : "";
        if (unread > 0 && key && key !== lastKey && !document.hasFocus()) {
          nativeNotify(latest.name || "زبون", latest.preview || "رسالة جديدة");
        }
        if (key) lastKey = key;
      } catch (err) {}
    };
    tick();
    setInterval(tick, 20000);
  }

  function pinComposerToKeyboard() {
    const vv = window.visualViewport;
    const focused = document.activeElement && document.activeElement.closest(".ed-composer-wrap, .ed-compose, #ed-chat-input");
    let lift = 0;
    if (vv) lift = Math.max(0, window.innerHeight - vv.height - (vv.offsetTop || 0));
    const open = Boolean(focused) && lift > 48;
    app.classList.toggle("ed-kb", open);
    document.documentElement.style.setProperty("--ed-kb-lift", `${open ? lift : 0}px`);
    if (open) {
      const stream = $("#ed-stream");
      if (stream) stream.scrollTop = stream.scrollHeight;
    }
  }
  const viewport = document.querySelector('meta[name="viewport"]');
  if (viewport) {
    viewport.content = "width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover, interactive-widget=overlays-content";
  }
  $("#ed-chat-input")?.addEventListener("focus", pinComposerToKeyboard);
  $("#ed-chat-input")?.addEventListener("blur", () => setTimeout(pinComposerToKeyboard, 80));
  window.visualViewport?.addEventListener("resize", pinComposerToKeyboard);
  window.visualViewport?.addEventListener("scroll", pinComposerToKeyboard);

  if (window.matchMedia("(max-width: 720px)").matches) {
    showPane($("#ed-pane-home") ? "ed-pane-home" : "ed-pane-inbox");
  }

  renderCart();
  loadPresence();
  let pulseMode = "open";
  let pulseLabel = "";
  function pulse(activity, label) {
    pulseMode = activity || "open";
    if (arguments.length > 1) pulseLabel = label || "";
    fetch("/api/facebook-routing/pulse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ activity: pulseMode, label: pulseLabel }),
    }).catch(() => {});
  }
  if (document.visibilityState === "visible") pulse("open");
  setInterval(() => {
    if (document.visibilityState === "visible") pulse(pulseMode);
  }, 12000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") pulse(pulseMode);
  });

  loadInbox();
  setInterval(loadInbox, 45000);
  startDeskAlerts();
})();
