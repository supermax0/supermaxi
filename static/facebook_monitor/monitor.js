(() => {
  const state = {
    range: "last_30",
    from: "",
    to: "",
    page_id: "",
    employee_id: "",
    ad_id: "",
    status: "ALL",
    search: "",
    has_order: "",
    employee_sort: "default",
    within: "",
    cursor: "",
    messages: [],
    next_cursor: "",
  };

  const $ = (sel) => document.querySelector(sel);
  const list = {
    pages: $("#fm-pages"),
    messages: $("#fm-messages"),
    employees: $("#fm-employees"),
    ads: $("#fm-ads"),
  };

  const chips = [
    ["ALL", "الكل"],
    ["NEW", "جديد"],
    ["WAITING_REPLY", "بانتظار الرد"],
    ["LATE", "متأخر"],
    ["ANSWERED", "تم الرد"],
    ["ORDER_CREATED", "تحول لطلب"],
  ];

  function query(extra = {}) {
    const params = new URLSearchParams();
    const data = { ...state, ...extra };
    ["range", "from", "to", "page_id", "employee_id", "ad_id", "status", "search", "has_order", "employee_sort", "cursor"].forEach((key) => {
      if (data[key]) params.set(key, data[key]);
    });
    return params.toString();
  }

  function skeleton(target, rows = 4) {
    if (!target) return;
    target.innerHTML = `<div class="fm-skeleton">${"<div></div>".repeat(rows)}</div>`;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char]));
  }

  function avatar(src, initials, round = false) {
    const cls = round ? "fm-avatar round" : "fm-avatar";
    if (src) return `<span class="${cls}"><img src="${escapeHtml(src)}" alt="" onerror="this.replaceWith(document.createTextNode('${escapeHtml(initials || "ف")}'))"></span>`;
    return `<span class="${cls}">${escapeHtml(initials || "ف")}</span>`;
  }

  const num = (value) => Number(value || 0).toLocaleString("en-US");

  // The manager's #1 question is "who is still waiting on us"; that number leads,
  // every other figure is context and stays visually subordinate.
  function renderStats(overview) {
    const counts = overview.counts || {};
    const late = Number(counts.LATE || 0);
    const waiting = Number(counts.WAITING_REPLY || 0) + Number(counts.NEW || 0);
    const hint = waiting ? `و${num(waiting)} بانتظار الرد` : "كل الرسائل مردود عليها";
    const items = [
      ["رسالة", num(overview.messages)],
      ["طلب", num(overview.orders)],
      ["مبيعات", overview.sales_label],
      ["راجع", num(overview.returns)],
      ["صفحة", num(overview.pages)],
    ];
    $("#fm-stats").innerHTML = `
      <button type="button" class="fm-hero ${late ? "" : "calm"}" data-status="LATE">
        <span class="fm-hero-num">${num(late)}</span>
        <span class="fm-hero-txt">
          <b>${late ? "متأخر عن الرد" : "لا شيء متأخر"}</b>
          <span>${escapeHtml(hint)}</span>
        </span>
      </button>
      <div class="fm-stat-row">
        ${items.map(([label, value]) => `
          <div class="fm-stat"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>
        `).join("")}
      </div>`;
    const banner = $("#fm-banner");
    if (overview.meta && overview.meta.degraded) {
      banner.classList.add("show");
      banner.textContent = `${overview.meta.message} آخر مزامنة: ${overview.meta.last_sync || "—"}`;
    } else {
      banner.classList.remove("show");
    }
  }

  function renderPages(pages) {
    if (!pages.length) {
      list.pages.innerHTML = `<div class="fm-empty"><strong>لا توجد صفحات مرتبطة</strong>افتح الإعدادات واربط صفحات فيسبوك لتبدأ المراقبة.</div>`;
      return;
    }
    list.pages.innerHTML = pages.map((page) => `
      <article class="fm-page ${state.page_id === page.id ? "active" : ""}" data-page="${escapeHtml(page.id)}">
        <div class="fm-page-top">
          <span class="fm-rank">${page.rank}</span>
          ${avatar(page.avatar, page.initials)}
          <p class="fm-page-name fm-grow">${escapeHtml(page.name)}</p>
          <span class="fm-page-state ${page.routing_on ? "on" : page.connected ? "linked" : "off"}">${page.routing_on ? "مفعّلة" : page.connected ? "متصلة" : "غير مفعّلة"}</span>
          <span class="fm-score ${page.tone}">${page.score}%</span>
        </div>
        <div class="fm-bar"><span class="${page.tone}" style="width:${page.score}%"></span></div>
        <div class="fm-metrics">
          <div><b>${num(page.messages)}</b><span>رسالة</span></div>
          <div><b>${page.orders}</b><span>طلب</span></div>
          <div><b>${escapeHtml(page.conversion_label)}</b><span>تحويل</span></div>
          <div><b>${escapeHtml(page.response_label)}</b><span>رد</span></div>
        </div>
      </article>
    `).join("");
  }

  function renderChips(counts) {
    $("#fm-chips").innerHTML = chips.map(([id, label]) => {
      const hot = id === "LATE" && Number(counts.LATE || 0) > 0;
      return `
      <button type="button" class="fm-chip ${hot ? "hot" : ""} ${state.status === id ? "active" : ""}" data-status="${id}">
        <span>${label}</span><strong>${num(counts[id])}</strong>
      </button>`;
    }).join("");
    $("#fm-message-count").textContent = `${num(counts.ALL)} رسالة في الفترة المحددة`;
  }

  function filterByTime(messages) {
    const minutes = Number(state.within || 0);
    if (!minutes) return messages;
    const cutoff = Date.now() - minutes * 60 * 1000;
    return messages.filter((message) => {
      const stamp = Date.parse(message.received_at || "");
      return Number.isFinite(stamp) && stamp >= cutoff;
    });
  }

  function renderMessages(messages, append = false) {
    if (!messages.length && !append) {
      list.messages.innerHTML = `<div class="fm-empty"><strong>ما في رسائل بهذه الفلاتر</strong>وسّع الفترة الزمنية أو <button type="button" class="fm-text-btn" id="fm-clear-empty">امسح الفلاتر</button></div>`;
      $("#fm-more").hidden = true;
      return;
    }
    const html = messages.map((message) => `
      <article class="fm-msg tone-${escapeHtml(message.response_tone || "muted")} ${message.can_open || message.thread_id || message.customer_psid ? "open-hint" : ""}"
        data-open-chat="1"
        data-thread="${escapeHtml(message.thread_id || "")}"
        data-page-ext="${escapeHtml(message.external_page_id || "")}"
        data-psid="${escapeHtml(message.customer_psid || "")}"
        data-customer="${escapeHtml(message.customer_name || "")}"
        data-page-name="${escapeHtml(message.page_name || "")}"
        data-page-avatar="${escapeHtml(message.customer_avatar || message.page_avatar || "")}">
        <span class="fm-msg-rail"></span>
        ${avatar(message.customer_avatar || message.page_avatar, message.customer_initials || message.page_initials)}
        <div class="fm-msg-body">
          <div class="fm-msg-row">
            <strong class="fm-customer">${escapeHtml(message.customer_name)}</strong>
            <span class="fm-time">${escapeHtml(message.time_label)}</span>
          </div>
          <p class="fm-preview">${escapeHtml(message.preview)}</p>
          <div class="fm-meta">
            <span class="fm-badge ${message.response_tone}">${escapeHtml(message.status_label)} · ${escapeHtml(message.response_label)}</span>
            <span class="fm-meta-item">${escapeHtml(message.page_name)}</span>
            <span class="fm-meta-item">${escapeHtml(message.source)}</span>
            ${message.campaign ? `<span class="fm-meta-item">${escapeHtml(message.campaign)}</span>` : ""}
            ${message.employee_name ? `<span class="fm-meta-item">${escapeHtml(message.employee_name)}</span>` : ""}
          </div>
          ${message.order_id && (message.attribution === "DIRECT" || message.attribution === "HIGH") ? `
            <div class="fm-order">
              <span>تحول لطلب</span>
              <strong>${escapeHtml(message.order_label)}</strong>
              <span>${escapeHtml(message.order_total_label)}</span>
              ${message.employee_name ? `<span>أضافه ${escapeHtml(message.employee_name)}</span>` : ""}
              ${message.order_after ? `<span>بعد ${escapeHtml(message.order_after)}</span>` : ""}
            </div>` : ""}
        </div>
      </article>
    `).join("");
    if (append) list.messages.insertAdjacentHTML("beforeend", html);
    else list.messages.innerHTML = html;
    $("#fm-more").hidden = !state.next_cursor;
  }

  function renderPull(pull) {
    const limit = Math.max(8, Math.min(50, Number(pull.limit || 25)));
    const pulled = Number(pull.pulled || 0);
    const pct = limit ? Math.min(100, Math.round((pulled / limit) * 100)) : 0;
    const box = $("#fm-fb-cap");
    if (!box) return;
    box.classList.toggle("is-full", Boolean(pull.error));
    $("#fm-fb-cap-label").textContent = `${pulled} / ${limit}`;
    $("#fm-fb-cap-fill").style.width = `${pct}%`;
    const input = $("#fm-fb-pull-limit");
    if (input && document.activeElement !== input) input.value = String(limit);
    const note = $("#fm-fb-cap-note");
    if (!note) return;
    if (pull.error) note.textContent = pull.error;
    else if (pulled) note.textContent = `آخر جلب: ${pulled} محادثة من ${pull.pages || 0} صفحة. الأقدم يبان إذا وسّعت الفترة.`;
    else if (pull.at) note.textContent = "ماكو محادثات جديدة. المحفوظ مسبقاً ما ينجلب مرة ثانية.";
    else note.textContent = "ارفع الرقم ثم اضغط جلب الآن. الأعلى 50 حتى ما ينضرب حد فيسبوك.";
  }

  function liveLine(row) {
    const who = row.live_label ? ` · ${escapeHtml(row.live_label)}` : "";
    if (row.live === "typing") {
      return `<p class="fm-emp-live is-typing">جاري الكتابة${who}<span class="fm-type" aria-hidden="true"><i></i><i></i><i></i></span></p>`;
    }
    if (row.live === "replying") return `<p class="fm-emp-live is-reply">يرد الآن${who}</p>`;
    if (row.live === "open" || row.presence === "online") return `<p class="fm-emp-live is-open">فاتح النظام</p>`;
    if (row.seen_label) return `<p class="fm-emp-live">آخر ظهور منذ ${escapeHtml(row.seen_label)}</p>`;
    return `<p class="fm-emp-live">غير متصل</p>`;
  }

  function renderEmployees(rows) {
    state.employees = rows;
    const typing = rows.filter((row) => row.live === "typing").length;
    const replying = rows.filter((row) => row.live === "replying").length;
    const open = rows.filter((row) => row.live === "open" || (row.presence === "online" && row.live !== "typing" && row.live !== "replying")).length;
    const offline = Math.max(0, rows.length - typing - replying - open);
    const bits = [];
    if (typing) bits.push(`${typing} يكتب`);
    if (replying) bits.push(`${replying} يرد`);
    bits.push(`${open} فاتح النظام`);
    bits.push(`${offline} غير متصل`);
    $("#fm-emp-sub").textContent = bits.join(" · ");
    if (!rows.length) {
      list.employees.innerHTML = `<div class="fm-empty">ما في موظفين بهذه الفترة.</div>`;
      return;
    }
    list.employees.innerHTML = rows.map((row) => {
      const dot = row.live === "typing" ? "typing" : row.live === "replying" ? "replying" : row.presence || "offline";
      const cap = Number(row.cap || 10);
      const load = Number(row.load || 0);
      const pct = cap ? Math.min(100, Math.round((load / cap) * 100)) : 0;
      return `
      <article class="fm-emp ${String(state.employee_id) === String(row.id) ? "active" : ""}" data-employee="${row.id}">
        <span class="fm-avatar round">${row.avatar ? `<img src="${escapeHtml(row.avatar)}" alt="">` : escapeHtml(row.initials)}<i class="fm-dot ${dot}"></i></span>
        <div class="fm-grow">
          <p class="fm-emp-name">${escapeHtml(row.name)}</p>
          ${liveLine(row)}
          <div class="fm-emp-track" title="حد محادثات فيسبوك ${load}/${cap}"><i class="${row.full ? "is-full" : ""}" style="width:${pct}%"></i></div>
        </div>
        <div class="fm-emp-stats"><span class="${row.full ? "hot" : ""}"><b>${load}/${cap}</b></span><span><b>${row.orders}</b> طلب</span></div>
      </article>`;
    }).join("");
  }

  function renderAds(rows) {
    $("#fm-ad-sub").textContent = rows.length ? `${rows.length} حملة` : "لا توجد إعلانات مرتبطة";
    if (!rows.length) {
      list.ads.innerHTML = `<div class="fm-empty">ما في إعلانات. اربط حساب الإعلانات من الإعدادات.</div>`;
      return;
    }
    list.ads.innerHTML = rows.map((row) => `
      <article class="fm-ad ${state.ad_id === row.id ? "active" : ""}" data-ad="${escapeHtml(row.id)}">
        <span class="fm-thumb"${row.thumbnail ? ` style="background-image:url('${escapeHtml(row.thumbnail)}')"` : ""}></span>
        <div class="fm-grow">
          <p class="fm-ad-name">
            <span class="fm-label">${escapeHtml(row.name)}</span>
            <span class="fm-pill ${row.active === false ? "off" : ""}">${row.active === false ? "متوقف" : "نشطة"}</span>
          </p>
          <p class="fm-sub">${escapeHtml(row.page_name || "حملة فيسبوك")}</p>
          <div class="fm-ad-stats">
            <span><b>${num(row.messages)}</b> رسالة</span>
            <span><b>${num(row.orders)}</b> طلب</span>
            <span><b>${escapeHtml(row.spend_label)}</b> إنفاق</span>
          </div>
        </div>
      </article>
    `).join("");
  }

  function renderFilterBar(options) {
    const page = (options.pages || []).find((item) => item.id === state.page_id);
    const employee = (options.employees || []).find((item) => String(item.id) === String(state.employee_id));
    const ad = (options.ads || []).find((item) => item.id === state.ad_id);
    const labels = [page && page.name, employee && employee.name, ad && ad.name].filter(Boolean);
    const bar = $("#fm-filter-bar");
    if (!labels.length && !state.search && state.status === "ALL") {
      bar.classList.remove("show");
      return;
    }
    bar.classList.add("show");
    bar.querySelector("span").textContent = labels.join(" · ") || "فلاتر نشطة";
  }

  function fillSelects(options) {
    fill("#fm-page-filter", options.pages, "جميع الصفحات", state.page_id);
    fill("#fm-employee-filter", options.employees, "جميع الموظفين", state.employee_id);
    fill("#fm-ad-filter", options.ads, "جميع الإعلانات", state.ad_id);
  }

  function fill(selector, rows, placeholder, current) {
    const node = $(selector);
    const value = node.value;
    node.innerHTML = `<option value="">${placeholder}</option>` + (rows || []).map((row) =>
      `<option value="${escapeHtml(row.id)}">${escapeHtml(row.name)}</option>`
    ).join("");
    node.value = current ? String(current) : "";
  }

  let loading = false;
  async function load({ append = false, silent = false } = {}) {
    if (loading && !append) return;
    loading = true;
    try {
    if (!silent && !append) {
      skeleton(list.pages, 5);
      skeleton(list.messages, 6);
      skeleton(list.employees, 4);
      skeleton(list.ads, 3);
    }
    const response = await fetch(`/api/facebook-monitor/snapshot?${query(append ? { cursor: state.cursor } : { cursor: "" })}`);
    if (response.status === 401 || response.status === 403) {
      window.location = "/login";
      return;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      const message = data.error || "تعذر تحميل البيانات. أعد تشغيل السيرفر ثم حدّث الصفحة.";
      list.messages.innerHTML = `<div class="fm-empty"><strong>ما قدرنا نجيب البيانات</strong>${escapeHtml(message)}</div>`;
      return;
    }
    if (!append) {
      renderStats({ ...data.overview, meta: data.meta, counts: data.status_counts || {} });
      renderPages(data.pages || []);
      renderChips(data.status_counts || {});
      renderEmployees(data.employees || []);
      renderPull(data.facebook_pull || {});
      renderAds(data.ads || []);
      fillSelects(data.filter_options || {});
      renderFilterBar(data.filter_options || {});
      state.messages = data.messages || [];
    } else {
      state.messages = state.messages.concat(data.messages || []);
    }
    state.next_cursor = data.next_cursor || "";
    const visible = filterByTime(append ? data.messages || [] : state.messages);
    renderMessages(visible, append);
    const statusNode = $("#fm-status-filter");
    if (statusNode && statusNode.value !== state.status) statusNode.value = state.status;
    } finally {
      loading = false;
    }
  }

  function resetCursorAndLoad() {
    state.cursor = "";
    load();
  }

  let searchTimer = null;
  $("#fm-search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = event.target.value.trim();
      resetCursorAndLoad();
    }, 300);
  });

  $("#fm-range").addEventListener("change", (event) => {
    state.range = event.target.value;
    $("#fm-custom").hidden = state.range !== "custom";
    if (state.range !== "custom") resetCursorAndLoad();
  });
  $("#fm-from").addEventListener("change", (event) => { state.from = event.target.value; if (state.range === "custom") resetCursorAndLoad(); });
  $("#fm-to").addEventListener("change", (event) => { state.to = event.target.value; if (state.range === "custom") resetCursorAndLoad(); });
  $("#fm-page-filter").addEventListener("change", (event) => { state.page_id = event.target.value; resetCursorAndLoad(); });
  $("#fm-employee-filter").addEventListener("change", (event) => { state.employee_id = event.target.value; resetCursorAndLoad(); });
  $("#fm-ad-filter").addEventListener("change", (event) => { state.ad_id = event.target.value; resetCursorAndLoad(); });
  $("#fm-sort").addEventListener("change", (event) => { state.employee_sort = event.target.value; resetCursorAndLoad(); });
  $("#fm-status-filter").addEventListener("change", (event) => { state.status = event.target.value || "ALL"; resetCursorAndLoad(); });
  $("#fm-time-filter").addEventListener("change", (event) => { state.within = event.target.value; renderMessages(filterByTime(state.messages)); });

  document.body.addEventListener("click", async (event) => {
    const chatRow = event.target.closest("[data-open-chat]");
    const page = event.target.closest("[data-page]");
    const employee = event.target.closest("[data-employee]");
    const ad = event.target.closest("[data-ad]");
    const chip = event.target.closest("[data-status]");
    if (chatRow) {
      openChat({
        thread_id: chatRow.dataset.thread || "",
        page_id: chatRow.dataset.pageExt || "",
        customer_psid: chatRow.dataset.psid || "",
        customer_name: chatRow.dataset.customer || "",
        page_name: chatRow.dataset.pageName || "",
        page_avatar: chatRow.dataset.pageAvatar || "",
      });
    } else if (page && !event.target.closest(".fm-drawer") && !event.target.closest(".fm-settings")) {
      openPage(page.dataset.page);
    } else if (chip) {
      state.status = chip.dataset.status;
      resetCursorAndLoad();
    } else if (ad && !event.target.closest(".fm-drawer") && !event.target.closest(".fm-settings")) {
      openAd(ad.dataset.ad);
    } else if (employee && !event.target.closest(".fm-drawer")) {
      openEmployee(employee.dataset.employee);
    } else if (event.target.id === "fm-clear" || event.target.id === "fm-clear-bar" || event.target.id === "fm-clear-empty" || event.target.id === "fm-show-all" || event.target.id === "fm-show-all-emp" || event.target.id === "fm-show-all-ads") {
      clearFilters();
    } else if (event.target.id === "fm-more") {
      state.cursor = state.next_cursor;
      load({ append: true, silent: true });
    } else if (event.target.id === "fm-drawer-close" || event.target.id === "fm-drawer-back") {
      closeDrawer();
    } else if (event.target.id === "fm-emp-cap-save") {
      saveEmployeeCap();
    } else if (event.target.id === "fm-filter-employee") {
      state.employee_id = $("#fm-drawer").dataset.employee || "";
      closeDrawer();
      resetCursorAndLoad();
    }
  });

  async function openEmployee(id) {
    const response = await fetch(`/api/facebook-monitor/employees/${id}?${query({ employee_id: "", cursor: "" })}`);
    const data = await response.json();
    const row = data.employee;
    if (!row) return;
    const presence = row.presence === "online" ? "متصل" : row.presence === "busy" ? "مشغول" : "غير متصل";
    const pages = row.pages || [];
    const maxSales = Math.max(...pages.map((page) => Number(page.sales) || 0), 1);
    $("#fm-drawer").dataset.kind = "employee";
    $("#fm-drawer").dataset.employee = row.id;
    const filterBtn = $("#fm-filter-employee");
    if (filterBtn) filterBtn.hidden = false;
    $("#fm-drawer-body").innerHTML = `
      <div class="fm-dos">
        <header class="fm-dos-head">
          <span class="fm-avatar lg">${row.avatar ? `<img src="${escapeHtml(row.avatar)}" alt="">` : escapeHtml(row.initials || "ف")}</span>
          <div>
            <h3>${escapeHtml(row.name)}</h3>
            <p class="fm-dos-status ${escapeHtml(row.presence || "offline")}">${presence} · ${escapeHtml(row.range_label || "اليوم")}</p>
            <p class="fm-dos-seen">آخر طلب ${escapeHtml(row.last_order_label || "—")} · آخر رسالة ${escapeHtml(row.last_message_label || "—")}</p>
          </div>
        </header>
        <section class="fm-dos-hero">
          <span>مبيعات الفترة</span>
          <strong>${escapeHtml(row.sales_label || "0 د.ع")}</strong>
          <p>${escapeHtml(row.avg_ticket_label || "0 د.ع")} متوسط الطلب · ${escapeHtml(row.conversion || "—")} اكتمال · ${row.customers || 0} زبون</p>
        </section>
        <div class="fm-dos-pipe">
          <div><b>${row.orders || 0}</b><span>طلب</span></div>
          <div><b>${row.pending || 0}</b><span>بالطريق</span></div>
          <div><b>${row.completed || 0}</b><span>مكتمل</span></div>
          <div class="${Number(row.returns) > 0 ? "bad" : ""}"><b>${row.returns || 0}</b><span>راجع ${escapeHtml(row.return_rate || "")}</span></div>
          <div><b>${row.cancelled || 0}</b><span>ملغي</span></div>
        </div>
        <section class="fm-dos-block">
          <h4>حد الاستقبال</h4>
          <div class="fm-dos-cap ${row.full ? "is-full" : ""}">
            <div class="fm-dos-cap-row">
              <strong>${row.load || 0} / ${row.cap || 10}</strong>
              <span>${row.full ? "وصلت الحد" : `${row.free || 0} شاغر`}</span>
            </div>
            <i style="width:${Math.min(100, Math.round(((row.load || 0) / Math.max(1, row.cap || 10)) * 100))}%"></i>
            <p>${row.full ? "ردّي على محادثة حتى توصلها وحدة جديدة من الطابور." : "إذا ردت على وحدة، توصلها محادثة جديدة بمكانها."}${Number(row.queue) > 0 ? ` الطابور: ${row.queue} بانتظار موظف.` : ""}</p>
            <label class="fm-dos-cap-edit">الحد المسموح
              <input type="number" id="fm-emp-cap" min="1" max="80" value="${row.cap || 10}">
            </label>
            <button type="button" class="fm-text-btn" id="fm-emp-cap-save">حفظ الحد</button>
          </div>
        </section>
        <section class="fm-dos-block">
          <h4>الردود</h4>
          <div class="fm-dos-reply">
            <div><b>${escapeHtml(row.avg_response || "—")}</b><span>متوسط</span></div>
            <div><b>${row.waiting_chats || 0}</b><span>محادثة تنتظر</span></div>
            <div class="${Number(row.late_messages) > 0 ? "bad" : ""}"><b>${row.late_messages || 0}</b><span>متأخر</span></div>
          </div>
          <p class="fm-dos-note">${row.open_chats || 0} محادثة مفتوحة · ${row.handled_messages || 0} رسالة · ${escapeHtml(row.reply_rate || "—")} تم الرد · أسرع ${escapeHtml(row.fastest || "—")} · أبطأ ${escapeHtml(row.slowest || "—")}</p>
        </section>
        <section class="fm-dos-block">
          <h4>الصفحات</h4>
          ${pages.length ? pages.map((page) => `
            <article class="fm-dos-page">
              <div class="fm-dos-page-row">
                <strong>${escapeHtml(page.name)}</strong>
                <span>${page.orders} طلب · ${escapeHtml(page.sales_label || "0 د.ع")}</span>
              </div>
              <i style="width:${Math.max(8, Math.round((Number(page.sales) || 0) / maxSales * 100))}%"></i>
            </article>
          `).join("") : `<p class="fm-dos-empty">ماكو طلبات مربوطة بصفحة بهالفترة.</p>`}
        </section>
      </div>
    `;
    $("#fm-drawer").hidden = false;
    $("#fm-drawer").classList.add("show");
    $("#fm-drawer-back").classList.add("show");
  }

  async function openPage(id) {
    if (!id) return;
    $("#fm-drawer").dataset.kind = "page";
    $("#fm-drawer").dataset.employee = "";
    const filterBtn = $("#fm-filter-employee");
    if (filterBtn) filterBtn.hidden = true;
    $("#fm-drawer-body").innerHTML = `<div class="fm-dos"><p class="fm-dos-empty">جاري تحميل تفاصيل الصفحة...</p></div>`;
    $("#fm-drawer").hidden = false;
    $("#fm-drawer").classList.add("show");
    $("#fm-drawer-back").classList.add("show");
    const response = await fetch(`/api/facebook-monitor/pages/${encodeURIComponent(id)}?${query({ page_id: "", employee_id: "", cursor: "" })}`);
    const data = await response.json().catch(() => ({}));
    const row = data.page;
    if (!row) {
      $("#fm-drawer-body").innerHTML = `<div class="fm-dos"><p class="fm-dos-empty">${escapeHtml(data.error || "ما لقيت تفاصيل هالصفحة.")}</p></div>`;
      return;
    }
    const staff = row.employees || [];
    const maxSales = Math.max(...staff.map((item) => Number(item.sales) || 0), 1);
    $("#fm-drawer-body").innerHTML = `
      <div class="fm-dos">
        <header class="fm-dos-head">
          <span class="fm-avatar lg">${row.avatar ? `<img src="${escapeHtml(row.avatar)}" alt="">` : escapeHtml(row.initials || "ف")}</span>
          <div>
            <h3>${escapeHtml(row.name)}</h3>
            <p class="fm-dos-status">${row.routing_on ? "التوزيع شغّال" : "التوزيع مطفي"} · ${escapeHtml(row.range_label || "اليوم")}</p>
            <p class="fm-dos-seen">القوة ${row.score || 0}% · المرتبة ${row.rank || "—"} · آخر طلب ${escapeHtml(row.last_order_label || "—")} · آخر رسالة ${escapeHtml(row.last_message_label || "—")}</p>
          </div>
        </header>
        <section class="fm-dos-hero">
          <span>مبيعات الفترة</span>
          <strong>${escapeHtml(row.sales_label || "0 د.ع")}</strong>
          <p>${escapeHtml(row.avg_ticket_label || "0 د.ع")} متوسط الطلب · ${escapeHtml(row.conversion || "—")} اكتمال · ${row.customers || 0} زبون</p>
        </section>
        <div class="fm-dos-pipe">
          <div><b>${row.orders || 0}</b><span>طلب</span></div>
          <div><b>${row.pending || 0}</b><span>بالطريق</span></div>
          <div><b>${row.completed || 0}</b><span>مكتمل</span></div>
          <div class="${Number(row.returns) > 0 ? "bad" : ""}"><b>${row.returns || 0}</b><span>راجع ${escapeHtml(row.return_rate || "")}</span></div>
          <div><b>${row.cancelled || 0}</b><span>ملغي</span></div>
        </div>
        <section class="fm-dos-block">
          <h4>الرسائل</h4>
          <div class="fm-dos-reply">
            <div><b>${row.messages || 0}</b><span>رسالة</span></div>
            <div><b>${row.waiting_messages || 0}</b><span>بانتظار رد</span></div>
            <div class="${Number(row.late_messages) > 0 ? "bad" : ""}"><b>${row.late_messages || 0}</b><span>متأخر</span></div>
          </div>
          <p class="fm-dos-note">${escapeHtml(row.reply_rate || "—")} تم الرد · متوسط ${escapeHtml(row.avg_response || "—")} · أسرع ${escapeHtml(row.fastest || "—")} · أبطأ ${escapeHtml(row.slowest || "—")}${Number(row.queue) > 0 ? ` · الطابور ${row.queue} بدون موظف` : ""}</p>
        </section>
        <section class="fm-dos-block">
          <h4>الموظفون على هالصفحة</h4>
          ${staff.length ? staff.map((item) => `
            <article class="fm-dos-page">
              <div class="fm-dos-page-row">
                <strong>${escapeHtml(item.name)}</strong>
                <span>${item.orders} طلب · ${escapeHtml(item.sales_label || "0 د.ع")}${item.cap ? ` · ${item.load}/${item.cap}` : ""}</span>
              </div>
              <i style="width:${Math.max(8, Math.round((Number(item.sales) || 0) / maxSales * 100))}%"></i>
            </article>
          `).join("") : `<p class="fm-dos-empty">ماكو موظفين أو طلبات مربوطة بهالصفحة بهالفترة.</p>`}
        </section>
      </div>
    `;
    $("#fm-drawer").hidden = false;
    $("#fm-drawer").classList.add("show");
    $("#fm-drawer-back").classList.add("show");
  }

  async function openAd(id) {
    if (!id) return;
    $("#fm-drawer").dataset.kind = "ad";
    $("#fm-drawer").dataset.employee = "";
    const filterBtn = $("#fm-filter-employee");
    if (filterBtn) filterBtn.hidden = true;
    $("#fm-drawer-body").innerHTML = `<div class="fm-dos"><p class="fm-dos-empty">جاري تحميل تفاصيل الإعلان...</p></div>`;
    $("#fm-drawer").hidden = false;
    $("#fm-drawer").classList.add("show");
    $("#fm-drawer-back").classList.add("show");
    const response = await fetch(`/api/facebook-monitor/ads/${encodeURIComponent(id)}?${query({ ad_id: "", page_id: "", employee_id: "", cursor: "" })}`);
    const data = await response.json().catch(() => ({}));
    const row = data.ad;
    if (!row) {
      $("#fm-drawer-body").innerHTML = `<div class="fm-dos"><p class="fm-dos-empty">${escapeHtml(data.error || "ما لقيت تفاصيل هالإعلان.")}</p></div>`;
      return;
    }
    const staff = row.employees || [];
    const maxSales = Math.max(...staff.map((item) => Number(item.sales) || 0), 1);
    $("#fm-drawer-body").innerHTML = `
      <div class="fm-dos">
        <header class="fm-dos-head">
          <span class="fm-avatar lg">${row.thumbnail ? `<img src="${escapeHtml(row.thumbnail)}" alt="">` : escapeHtml(row.initials || "ع")}</span>
          <div>
            <h3>${escapeHtml(row.name)}</h3>
            <p class="fm-dos-status">${row.active === false ? "متوقف" : "نشطة"} · ${escapeHtml(row.page_name || "حملة فيسبوك")} · ${escapeHtml(row.range_label || "اليوم")}</p>
            <p class="fm-dos-seen">آخر طلب ${escapeHtml(row.last_order_label || "—")} · آخر رسالة ${escapeHtml(row.last_message_label || "—")}</p>
          </div>
        </header>
        <section class="fm-dos-hero">
          <span>مبيعات الفترة</span>
          <strong>${escapeHtml(row.sales_label || "0 د.ع")}</strong>
          <p>${escapeHtml(row.avg_ticket_label || "0 د.ع")} متوسط الطلب · ${escapeHtml(row.conversion || "—")} اكتمال · ${row.customers || 0} زبون</p>
        </section>
        <div class="fm-dos-pipe">
          <div><b>${row.orders || 0}</b><span>طلب</span></div>
          <div><b>${row.pending || 0}</b><span>بالطريق</span></div>
          <div><b>${row.completed || 0}</b><span>مكتمل</span></div>
          <div class="${Number(row.returns) > 0 ? "bad" : ""}"><b>${row.returns || 0}</b><span>راجع ${escapeHtml(row.return_rate || "")}</span></div>
          <div><b>${row.cancelled || 0}</b><span>ملغي</span></div>
        </div>
        <section class="fm-dos-block">
          <h4>الإنفاق</h4>
          <div class="fm-dos-reply">
            <div><b>${escapeHtml(row.spend_label || "—")}</b><span>أنفق</span></div>
            <div><b>${escapeHtml(row.cost_per_message_label || "—")}</b><span>تكلفة الرسالة</span></div>
            <div><b>${escapeHtml(row.cost_per_order_label || "—")}</b><span>تكلفة الطلب</span></div>
          </div>
        </section>
        <section class="fm-dos-block">
          <h4>الرسائل</h4>
          <div class="fm-dos-reply">
            <div><b>${row.messages || 0}</b><span>رسالة</span></div>
            <div><b>${row.waiting_messages || 0}</b><span>بانتظار رد</span></div>
            <div class="${Number(row.late_messages) > 0 ? "bad" : ""}"><b>${row.late_messages || 0}</b><span>متأخر</span></div>
          </div>
          <p class="fm-dos-note">${escapeHtml(row.reply_rate || "—")} تم الرد · متوسط ${escapeHtml(row.avg_response || "—")} · أسرع ${escapeHtml(row.fastest || "—")} · أبطأ ${escapeHtml(row.slowest || "—")}</p>
        </section>
        <section class="fm-dos-block">
          <h4>من باع من هالإعلان</h4>
          ${staff.length ? staff.map((item) => `
            <article class="fm-dos-page">
              <div class="fm-dos-page-row">
                <strong>${escapeHtml(item.name)}</strong>
                <span>${item.orders} طلب · ${escapeHtml(item.sales_label || "0 د.ع")}</span>
              </div>
              <i style="width:${Math.max(8, Math.round((Number(item.sales) || 0) / maxSales * 100))}%"></i>
            </article>
          `).join("") : `<p class="fm-dos-empty">ماكو طلبات مربوطة بهالإعلان بهالفترة.</p>`}
        </section>
      </div>
    `;
  }

  async function saveEmployeeCap() {
    const id = $("#fm-drawer").dataset.employee;
    const cap = Number($("#fm-emp-cap")?.value || 0);
    if (!id || cap < 1) return;
    const response = await fetch(`/api/facebook-routing/employees/${id}/cap`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_active: cap }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      window.alert(data.error || "ما انحفظ الحد");
      return;
    }
    openEmployee(id);
  }

  function closeDrawer() {
    $("#fm-drawer").classList.remove("show");
    $("#fm-drawer").hidden = true;
    $("#fm-drawer-back").classList.remove("show");
  }

  function clearFilters() {
    state.page_id = "";
    state.employee_id = "";
    state.ad_id = "";
    state.status = "ALL";
    state.search = "";
    state.has_order = "";
    $("#fm-search").value = "";
    state.within = "";
    const timeNode = $("#fm-time-filter");
    const statusNode = $("#fm-status-filter");
    if (timeNode) timeNode.value = "";
    if (statusNode) statusNode.value = "ALL";
    resetCursorAndLoad();
  }

  document.querySelectorAll(".fm-tabs button").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".fm-tabs button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      document.querySelectorAll(".fm-col").forEach((col) => col.classList.remove("active"));
      document.querySelector(button.dataset.tab).classList.add("active");
    });
  });

  const scroller = $("#fm-messages");
  scroller.addEventListener("scroll", () => {
    if (!state.next_cursor) return;
    if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 40) {
      state.cursor = state.next_cursor;
      state.next_cursor = "";
      load({ append: true, silent: true });
    }
  });

  const setLeads = {
    routing: "فعّل الصفحة، ثم اختر من يستقبل رسائلها",
    pages: "كل صفحة إلها رمزها. حفظ واحدة ما يمسح الثانية",
    ads: "تطبيق الإعلانات منفصل عن الصفحات",
  };

  let toastTimer = 0;
  function notify(ok, message) {
    const toast = $("#fm-toast");
    const text = $("#fm-toast-text");
    if (toast && text) {
      text.textContent = message;
      toast.classList.toggle("is-ok", Boolean(ok));
      toast.classList.toggle("is-bad", !ok);
      toast.hidden = false;
      toast.classList.remove("show");
      void toast.offsetWidth;
      toast.classList.add("show");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => {
          if (!toast.classList.contains("show")) toast.hidden = true;
        }, 220);
      }, 3400);
    }
    const status = $("#fm-settings-status");
    const error = $("#fm-settings-error");
    if (ok) {
      if (status) {
        status.hidden = false;
        status.textContent = message;
      }
      if (error) {
        error.hidden = true;
        error.textContent = "";
      }
    } else if (error) {
      error.hidden = false;
      error.textContent = message;
      if (status) status.textContent = "";
    }
  }

  function showSetTab(name) {
    document.querySelectorAll("[data-set-tab]").forEach((button) => {
      const on = button.dataset.setTab === name;
      button.classList.toggle("is-on", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll("[data-set-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.setPanel !== name;
    });
    if ($("#fm-set-lead")) $("#fm-set-lead").textContent = setLeads[name] || setLeads.routing;
  }

  function renderPageApis(pages) {
    const box = $("#fm-page-apis");
    if (!box) return;
    box.innerHTML = (pages || []).map((page) => `
      <article class="fm-page-api" data-page-id="${escapeHtml(page.page_id || "")}">
        <div class="fm-page-api-top">
          <strong>${escapeHtml(page.name || page.page_id || "صفحة")}</strong>
          <span>${page.has_token ? "الرمز محفوظ" : "ماكو رمز"}</span>
        </div>
        <p class="fm-sub">${escapeHtml(page.page_id || "")}</p>
        <label>رمز هذه الصفحة
          <input class="fm-page-token" type="text" spellcheck="false" autocomplete="off" placeholder="${page.has_token ? "الصق رمزاً جديداً للاستبدال" : "الصق Page Token"}">
        </label>
        <button type="button" class="fm-primary" data-save-page>حفظ رمز هذه الصفحة</button>
      </article>
    `).join("");
  }

  async function savePageToken(pageId, token, pageName) {
    const errorBox = $("#fm-settings-error");
    if (errorBox) {
      errorBox.textContent = "";
      errorBox.hidden = true;
    }
    const body = settingsBody();
    body.page_id = pageId || "";
    body.page_name = pageName || "";
    body.page_token = token || "";
    const response = await fetch("/api/facebook-monitor/settings/page-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({
      ok: false,
      error: "السيرفر ما رد. الصفحات القديمة باقية.",
    }));
    if (!response.ok || !data.ok) {
      if (data.pages) renderPageApis(data.pages);
      notify(false, data.error || data.message || "ما انربطت الصفحة. فيسبوك رفض الرمز أو الاشتراك.");
      return;
    }
    renderPageApis(data.pages || []);
    notify(true, data.message || "تم ربط الصفحة.");
    if ($("#fm-new-page-token")) $("#fm-new-page-token").value = "";
    if ($("#fm-new-page-id")) $("#fm-new-page-id").value = "";
  }

  let settingsCloseTimer = 0;
  function openSettings() {
    const panel = $("#fm-settings");
    clearTimeout(settingsCloseTimer);
    panel.hidden = false;
    $("#fm-settings-back").classList.add("show");
    requestAnimationFrame(() => requestAnimationFrame(() => panel.classList.add("show")));
    const error = $("#fm-settings-error");
    if (error) {
      error.textContent = "";
      error.hidden = true;
    }
    showSetTab("routing");
    fetch("/api/facebook-monitor/settings")
      .then((response) => response.json())
      .then((data) => {
        const settings = data.settings || {};
        $("#fm-app-id").value = settings.fb_app_id || "";
        $("#fm-app-secret").value = "";
        $("#fm-app-secret").placeholder = settings.has_secret ? "محفوظ — الصق رمزاً جديداً إذا تبي تغيّره" : "الصق App Secret";
        if ($("#fm-user-token")) {
          $("#fm-user-token").value = "";
          $("#fm-user-token").placeholder = settings.has_token ? "محفوظ — الصق رمزاً جديداً إذا تبي تغيّره" : "الصق User Token";
        }
        renderPageApis(settings.pages || []);
        $("#fm-ads-app-id").value = settings.ads_app_id || "";
        $("#fm-ads-secret").value = "";
        $("#fm-ads-token").value = "";
        $("#fm-ads-secret").placeholder = settings.has_ads_secret ? "محفوظ — الصق رمزاً جديداً إذا تبي تغيّره" : "الصق App Secret";
        $("#fm-ads-token").placeholder = settings.has_ads_token ? "محفوظ — الصق رمزاً جديداً إذا تبي تغيّره" : "الصق User Token بصلاحية ads_read";
        $("#fm-ads-account").value = settings.ads_account_id || "";
        $("#fm-api-list").innerHTML = (settings.apis || []).map((api) =>
          `<div><b>${escapeHtml(api.method)}</b> ${escapeHtml(api.path)} <span class="fm-sub">${escapeHtml(api.name)}</span></div>`
        ).join("");
        if ($("#fm-hook-url")) $("#fm-hook-url").value = settings.webhook_url || "";
        if ($("#fm-hook-token")) $("#fm-hook-token").value = settings.verify_token || "";
        if ($("#fm-hook-state")) {
          $("#fm-hook-state").textContent = settings.webhook_verified
            ? "تم التحقق · الرسائل تصل مباشرة"
            : "انسخ الرابط والرمز إلى Meta ثم Verify and save";
        }
        const status = $("#fm-settings-status");
        if (status) {
          status.hidden = false;
          status.textContent = `${settings.app_name || "SUPER MAX"} · ${settings.page_count || 0} صفحة، كل واحدة برمزها`;
        }
        loadRouting();
      })
      .catch(() => notify(false, "تعذر تحميل الإعدادات."));
  }

  function normName(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[أإآ]/g, "ا")
      .replace(/ة/g, "ه")
      .replace(/ى/g, "ي");
  }

  function filterRouting() {
    const query = normName($("#fm-route-q")?.value);
    const box = $("#fm-routing");
    if (!box) return;
    let shown = 0;
    box.querySelectorAll(".fm-route-page").forEach((card) => {
      const pageHit = !query || normName(card.dataset.name).includes(query);
      let staffHit = 0;
      card.querySelectorAll(".fm-route-staff .fm-route-person").forEach((chip) => {
        const hit = !query || pageHit || normName(chip.dataset.name).includes(query);
        chip.classList.toggle("is-hidden", Boolean(query) && !hit);
        if (hit) staffHit += 1;
      });
      const visible = !query || pageHit || staffHit > 0;
      card.classList.toggle("is-hidden", !visible);
      if (visible) shown += 1;
    });
    const empty = $("#fm-route-empty");
    if (empty) empty.hidden = !query || shown > 0 || !box.querySelector(".fm-route-page");
  }

  function staffCount(card) {
    const n = card.querySelectorAll(".fm-route-emp:checked").length;
    const meta = card.querySelector(".fm-route-copy span");
    if (meta) meta.textContent = n ? `${n} موظف يستقبل الرسائل` : "ماكو موظف مفعّل";
  }

  function bindRouteCard(card) {
    const scroller = card.closest(".fm-set-scroll");
    let scrollTop = scroller ? scroller.scrollTop : 0;
    card.addEventListener("pointerdown", () => {
      if (scroller) scrollTop = scroller.scrollTop;
    });
    card.addEventListener("focusin", () => {
      if (!scroller) return;
      requestAnimationFrame(() => { scroller.scrollTop = scrollTop; });
    });
    const sync = () => {
      const on = card.querySelector(".fm-route-on")?.checked;
      card.classList.toggle("is-on", Boolean(on));
      card.classList.toggle("is-off", !on);
      staffCount(card);
      if (scroller) scroller.scrollTop = scrollTop;
    };
    card.querySelector(".fm-route-on")?.addEventListener("change", sync);
    card.querySelectorAll(".fm-route-emp").forEach((input) => input.addEventListener("change", () => {
      staffCount(card);
      if (scroller) scroller.scrollTop = scrollTop;
    }));
    sync();
  }

  function loadRouting() {
    const box = $("#fm-routing");
    if (!box) return;
    box.innerHTML = `<div class="fm-set-empty">جاري تحميل الصفحات…</div>`;
    fetch("/api/facebook-routing/config")
      .then((response) => response.json())
      .then((data) => {
        if (!data.ok) {
          box.innerHTML = `<div class="fm-set-empty"><strong>ما قدرنا نجيب التوزيع</strong>${escapeHtml(data.error || "")}</div>`;
          return;
        }
        const people = (data.employees || []).filter((row) => row.can_inbox !== false);
        const pages = data.pages || [];
        if (!pages.length) {
          box.innerHTML = `
            <div class="fm-set-empty">
              <strong>ماكو صفحات مربوطة</strong>
              اربط الصفحات من تبويب الصفحات، بعدها فعّل التوزيع.
              <button type="button" class="fm-primary" data-goto-tab="pages">فتح تبويب الصفحات</button>
            </div>`;
          return;
        }
        box._pages = pages;
        box.innerHTML = pages.map((page, index) => {
          const on = new Set((page.employees || []).filter((row) => row.enabled).map((row) => String(row.employee_id)));
          const picked = people.filter((emp) => on.has(String(emp.id))).length;
          return `
            <article class="fm-route-page ${page.routing_enabled ? "is-on" : "is-off"}" data-index="${index}" data-name="${escapeHtml(page.name)}">
              <div class="fm-route-top">
                <div class="fm-route-copy">
                  <strong>${escapeHtml(page.name)}</strong>
                  <span>${picked ? `${picked} موظف يستقبل الرسائل` : "ماكو موظف مفعّل"}</span>
                </div>
                <label class="fm-switch" title="تفعيل الصفحة">
                  <input type="checkbox" class="fm-route-on" ${page.routing_enabled ? "checked" : ""}>
                  <span class="fm-switch-ui"></span>
                </label>
              </div>
              <div class="fm-route-staff">
                <div class="fm-route-head">
                  <span>الموظف</span>
                  <span>الحد</span>
                  <span>المهلة</span>
                </div>
                ${people.map((emp) => `
                  <div class="fm-route-person" data-name="${escapeHtml(emp.name)}">
                    <label class="fm-route-who">
                      <input type="checkbox" class="fm-route-emp" value="${emp.id}" ${on.has(String(emp.id)) ? "checked" : ""}>
                      <i class="fm-route-tick"></i>
                      <span>${escapeHtml(emp.name)}</span>
                      <em>${emp.active || 0}/${emp.max_active || 10}</em>
                    </label>
                    <label class="fm-route-field" title="أقصى محادثات مفتوحة">
                      <input type="number" class="fm-route-cap" min="1" max="80" value="${emp.max_active || 10}">
                    </label>
                    <label class="fm-route-field" title="إذا ما رد خلال هذه الدقائق تنتقل الرسالة لموظف ثاني">
                      <input type="number" class="fm-route-timeout" min="1" max="60" value="${emp.reply_timeout_minutes || 3}">
                      <span>د</span>
                    </label>
                  </div>
                `).join("") || `<div class="fm-set-hint">ماكو موظف يقدر يستقبل الرسائل.</div>`}
              </div>
            </article>`;
        }).join("");
        box.querySelectorAll(".fm-route-page").forEach(bindRouteCard);
        filterRouting();
      })
      .catch(() => { box.innerHTML = `<div class="fm-set-empty"><strong>تعذر تحميل التوزيع</strong>أعد المحاولة بعد ثوانٍ.</div>`; });
  }

  async function saveRouting() {
    const box = $("#fm-routing");
    const button = $("#fm-routing-save");
    const pages = box._pages || [];
    if (!pages.length) {
      notify(false, "ماكو صفحات للحفظ.");
      return;
    }
    if (button) button.disabled = true;
    try {
      for (const card of box.querySelectorAll(".fm-route-page")) {
        const page = pages[Number(card.dataset.index)];
        const employees = [...card.querySelectorAll(".fm-route-emp")].map((input) => {
          const person = input.closest(".fm-route-person");
          const cap = person?.querySelector(".fm-route-cap");
          const timeout = person?.querySelector(".fm-route-timeout");
          return {
            employee_id: Number(input.value),
            enabled: input.checked,
            max_active: Number(cap?.value || 10),
            reply_timeout_minutes: Number(timeout?.value || 3),
          };
        });
        const response = await fetch("/api/facebook-routing/pages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            page_id: page.page_id,
            channel_id: page.channel_id,
            routing_enabled: card.querySelector(".fm-route-on").checked,
            default_max: page.default_max || 10,
            employees,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          notify(false, data.error || "فشل حفظ التوزيع.");
          return;
        }
      }
      notify(true, "تم حفظ التوزيع.");
      loadRouting();
      load({ silent: true });
    } catch (err) {
      notify(false, "ما انحفظ التوزيع. تأكد من الاتصال وأعد المحاولة.");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function closeSettings() {
    const panel = $("#fm-settings");
    panel.classList.remove("show");
    $("#fm-settings-back").classList.remove("show");
    clearTimeout(settingsCloseTimer);
    settingsCloseTimer = setTimeout(() => {
      if (!panel.classList.contains("show")) panel.hidden = true;
    }, 320);
  }

  function settingsBody() {
    return {
      fb_app_id: $("#fm-app-id").value.trim(),
      fb_app_secret: $("#fm-app-secret").value.trim(),
      fb_user_token: $("#fm-user-token").value.trim(),
      ads_app_id: $("#fm-ads-app-id").value.trim(),
      ads_app_secret: $("#fm-ads-secret").value.trim(),
      ads_user_token: $("#fm-ads-token").value.trim(),
      ads_account_id: $("#fm-ads-account").value.trim(),
    };
  }

  async function saveSettings(connect) {
    const response = await fetch(connect ? "/api/facebook-monitor/settings/connect" : "/api/facebook-monitor/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settingsBody()),
    });
    const data = await response.json().catch(() => ({
      ok: false,
      error: response.status === 408 || response.status === 502
        ? "فيسبوك أو السيرفر ما ردّ بالوقت (حد الطلبات). الصفحات القديمة باقية. انتظر ساعة ثم أعد الربط."
        : "السيرفر رجّع خطأ. أعد المحاولة بعد قليل.",
    }));
    if (!response.ok || !data.ok) {
      notify(false, data.error || "تعذر حفظ الإعدادات.");
      return;
    }
    if (connect) {
      const names = (data.pages || []).map((page) => page.name).filter(Boolean);
      $("#fm-settings-pages").innerHTML = names.length
        ? names.map((name) => `<div>${escapeHtml(name)}</div>`).join("")
        : "";
      notify(true, `تم ربط ${data.count || 0} صفحة.`);
      fetch("/api/facebook-monitor/settings")
        .then((res) => res.json())
        .then((payload) => renderPageApis((payload.settings || {}).pages || []))
        .catch(() => {});
      load({ silent: true });
    } else {
      notify(true, "تم حفظ الإعدادات.");
    }
  }

  function copyField(id, label) {
    const node = $(id);
    if (!node || !node.value) return;
    navigator.clipboard.writeText(node.value).then(
      () => { notify(true, `تم نسخ ${label}`); },
      () => {
        node.select();
        document.execCommand("copy");
        notify(true, `تم نسخ ${label}`);
      }
    );
  }
  $("#fm-copy-url")?.addEventListener("click", () => copyField("#fm-hook-url", "رابط الويب هوك"));
  $("#fm-copy-token")?.addEventListener("click", () => copyField("#fm-hook-token", "رمز التحقق"));
  $("#fm-fb-pull")?.addEventListener("click", async () => {
    const button = $("#fm-fb-pull");
    const limit = Math.max(8, Math.min(50, Number($("#fm-fb-pull-limit")?.value || 25)));
    if (button) button.disabled = true;
    try {
      const response = await fetch("/api/facebook-monitor/pull-conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit }),
      });
      const data = await response.json().catch(() => ({}));
      renderPull(data);
      if (!response.ok || data.ok === false) {
        if (data.assigned) {
          notify(true, `اتوزع ${data.assigned} محادثة على الموظفين. الجلب من فيسبوك: ${data.error || "فشل"}`);
          load({ silent: true });
          return;
        }
        notify(false, data.error || "ما انجلبت المحادثات.");
        return;
      }
      notify(true, `تم جلب ${data.pulled || 0} محادثة${data.assigned ? ` وتوزيع ${data.assigned} على الموظفين` : ""}.`);
      load({ silent: true });
    } catch (err) {
      notify(false, "انقطع الاتصال أثناء الجلب.");
    } finally {
      if (button) button.disabled = false;
    }
  });
  $("#fm-open-settings").addEventListener("click", openSettings);
  $("#fm-settings-close").addEventListener("click", closeSettings);
  $("#fm-settings-back").addEventListener("click", closeSettings);
  document.querySelectorAll("[data-set-tab]").forEach((button) => {
    button.addEventListener("click", () => showSetTab(button.dataset.setTab));
  });
  $("#fm-route-q")?.addEventListener("input", filterRouting);
  $("#fm-routing")?.addEventListener("click", (event) => {
    const next = event.target.closest("[data-goto-tab]");
    if (next) showSetTab(next.dataset.gotoTab);
  });
  $("#fm-settings-form")?.addEventListener("submit", (event) => event.preventDefault());
  $("#fm-settings-save")?.addEventListener("click", () => saveSettings(false));
  $("#fm-settings-connect")?.addEventListener("click", () => saveSettings(true));
  $("#fm-page-apis")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-save-page]");
    if (!button) return;
    const card = button.closest(".fm-page-api");
    const token = card?.querySelector(".fm-page-token")?.value.trim() || "";
    savePageToken(card?.dataset.pageId || "", token, card?.querySelector("strong")?.textContent || "");
  });
  $("#fm-new-page-save")?.addEventListener("click", () => {
    savePageToken($("#fm-new-page-id")?.value.trim() || "", $("#fm-new-page-token")?.value.trim() || "");
  });
  $("#fm-routing-save")?.addEventListener("click", saveRouting);
  $("#fm-ads-connect").addEventListener("click", async () => {
    const response = await fetch("/api/facebook-monitor/settings/connect-ads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settingsBody()),
    });
    const data = await response.json().catch(() => ({ ok: false, error: "السيرفر رجّع خطأ. أعد تشغيل التطبيق ثم أعد الربط." }));
    if (!response.ok || !data.ok) {
      notify(false, data.error || "تعذر ربط الإعلانات.");
      return;
    }
    const accounts = data.accounts || [];
    $("#fm-ads-accounts").innerHTML = accounts.length
      ? accounts.map((account) => `<div>${escapeHtml(account.name)} · ${escapeHtml(account.id)}</div>`).join("")
      : "<div>لا توجد حسابات إعلان على هذا الرمز.</div>";
    if (accounts[0] && !$("#fm-ads-account").value.trim()) $("#fm-ads-account").value = accounts[0].id;
    notify(true, `تم ربط ${data.count || 0} حساب إعلان.`);
  });

  /* ── Chat stage ─────────────────────────────────────────────────────── */
  const chat = {
    thread_id: "",
    page_id: "",
    customer_psid: "",
    assigned_id: "",
    assigned_name: "",
    page_name: "",
    sending: false,
    file: null,
  };

  function chatError(text) {
    const node = $("#fm-chat-error");
    if (!text) {
      node.hidden = true;
      node.textContent = "";
      return;
    }
    node.hidden = false;
    node.textContent = text;
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

  function renderBubble(message) {
    const att = message.attachment;
    let media = "";
    const kind = att && att.url ? mediaKind(att) : "";
    if (att && att.url && kind === "image") {
      media = `<img class="fm-bubble-media" src="${escapeHtml(att.url)}" alt="">`;
    } else if (att && att.url && kind === "video") {
      media = `<video class="fm-bubble-media" src="${escapeHtml(att.url)}" controls playsinline></video>`;
    } else if (att && att.url && kind === "audio") {
      media = `<audio controls src="${escapeHtml(att.url)}" style="width:100%;margin-bottom:6px"></audio>`;
    } else if (att && att.url) {
      media = `<a class="fm-bubble-file" href="${escapeHtml(att.url)}" target="_blank" rel="noopener">📎 ${escapeHtml(att.name || "ملف")}</a>`;
    } else if (att) {
      media = `<span class="fm-bubble-file">📎 ${escapeHtml(att.name || "وسائط غير متاحة")}</span>`;
    }
    const text = String(message.text || "").trim();
    const showText = text && !(media && MEDIA_LABELS.test(text));
    const dir = message.direction === "out" ? "out" : "in";
    return `
      <div class="fm-row ${dir}">
        <div class="fm-bubble">
          ${media}
          ${showText ? `<div class="fm-bubble-text">${escapeHtml(text)}</div>` : ""}
        </div>
        <span class="fm-bubble-time">${escapeHtml(message.time_label || "")}</span>
      </div>`;
  }

  function renderChatStream(messages) {
    const stream = $("#fm-chat-stream");
    if (!messages.length) {
      stream.innerHTML = `<div class="fm-chat-empty"><strong>ماكو رسائل بهالمحادثة</strong>اكتب أول رد من الأسفل.</div>`;
      return;
    }
    stream.innerHTML = messages.map(renderBubble).join("");
    stream.scrollTop = stream.scrollHeight;
  }

  function appendChatBubble(message) {
    const stream = $("#fm-chat-stream");
    const empty = stream.querySelector(".fm-chat-empty");
    if (empty) empty.remove();
    stream.insertAdjacentHTML("beforeend", renderBubble(message));
    stream.scrollTop = stream.scrollHeight;
  }

  async function openChat(meta) {
    if (!meta.page_id && !meta.thread_id) {
      chatError("ما نقدر نفتح هالمحادة — معرّف الصفحة مفقود.");
      return;
    }
    chat.thread_id = meta.thread_id || "";
    chat.page_id = meta.page_id || "";
    chat.customer_psid = meta.customer_psid || "";
    chat.file = null;
    $("#fm-chat-preview").hidden = true;
    $("#fm-chat-preview").innerHTML = "";
    $("#fm-chat-file").value = "";
    $("#fm-chat-input").value = "";
    chatError("");

    chat.assigned_id = "";
    chat.assigned_name = "";
    chat.page_name = meta.page_name || "";
    closeTransferPop();
    $("#fm-chat-name").textContent = meta.customer_name || "عميل فيسبوك";
    paintChatOwner(meta.page_name || "صفحة فيسبوك");
    $("#fm-chat-meta").textContent = "جاري التحميل…";
    const face = meta.customer_avatar || meta.page_avatar || "";
    $("#fm-chat-avatar").innerHTML = face
      ? `<img src="${escapeHtml(face)}" alt="">`
      : escapeHtml((meta.customer_name || "ف").slice(0, 1));

    const panel = $("#fm-chat");
    const back = $("#fm-chat-back");
    panel.hidden = false;
    back.hidden = false;
    document.body.classList.add("fm-chat-open");
    const aiFab = document.getElementById("finoraAiFab");
    const aiPanel = document.getElementById("finoraAiPanel");
    if (aiFab) aiFab.style.display = "none";
    if (aiPanel) {
      aiPanel.classList.remove("is-open");
      aiPanel.setAttribute("aria-hidden", "true");
      aiPanel.style.display = "none";
    }
    requestAnimationFrame(() => {
      panel.classList.add("show");
      back.classList.add("show");
    });
    $("#fm-chat-stream").innerHTML = `<div class="fm-skeleton"><div></div><div></div><div></div></div>`;
    $("#fm-chat-input").focus();

    const params = new URLSearchParams({
      page_id: chat.page_id,
      thread_id: chat.thread_id,
      customer_psid: chat.customer_psid,
    });
    try {
      const response = await fetch(`/api/facebook-monitor/thread?${params}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        $("#fm-chat-stream").innerHTML = `<div class="fm-chat-empty"><strong>ما قدرنا نجيب المحادثة</strong>${escapeHtml(data.error || "حاول مرة ثانية")}</div>`;
        $("#fm-chat-meta").textContent = "خطأ";
        chatError(data.error || "");
        return;
      }
      const thread = data.thread || {};
      chat.thread_id = thread.thread_id || chat.thread_id;
      chat.page_id = thread.external_page_id || chat.page_id;
      chat.customer_psid = thread.customer_psid || chat.customer_psid;
      chat.assigned_id = thread.assigned_employee_id || "";
      chat.assigned_name = thread.assigned_employee_name || "";
      chat.page_name = thread.page_name || meta.page_name || chat.page_name;
      $("#fm-chat-name").textContent = thread.customer_name || meta.customer_name || "عميل";
      paintChatOwner(chat.page_name);
      $("#fm-chat-meta").textContent = `${thread.count || 0} رسالة`;
      renderChatStream(thread.messages || []);
      if (!thread.can_reply) chatError("ما نقدر نرد بهالمحادثة — معرّف العميل ناقص.");
    } catch (err) {
      $("#fm-chat-stream").innerHTML = `<div class="fm-chat-empty"><strong>انقطع الاتصال</strong>تحقق من الشبكة وأعد المحاولة.</div>`;
      $("#fm-chat-meta").textContent = "خطأ";
    }
  }

  function closeChat() {
    const panel = $("#fm-chat");
    const back = $("#fm-chat-back");
    panel.classList.remove("show");
    back.classList.remove("show");
    document.body.classList.remove("fm-chat-open");
    const aiFab = document.getElementById("finoraAiFab");
    const aiPanel = document.getElementById("finoraAiPanel");
    if (aiFab) aiFab.style.display = "";
    if (aiPanel) aiPanel.style.display = "";
    setTimeout(() => {
      panel.hidden = true;
      back.hidden = true;
    }, 280);
    chat.file = null;
  }

  function clearChatFile() {
    chat.file = null;
    $("#fm-chat-file").value = "";
    $("#fm-chat-preview").hidden = true;
    $("#fm-chat-preview").innerHTML = "";
  }

  function setChatFile(file) {
    if (!file) return clearChatFile();
    chat.file = file;
    const preview = $("#fm-chat-preview");
    preview.hidden = false;
    if (file.type.startsWith("image/")) {
      const url = URL.createObjectURL(file);
      preview.innerHTML = `<img src="${url}" alt=""><span>${escapeHtml(file.name)}</span><button type="button" id="fm-chat-file-clear">إزالة</button>`;
    } else {
      preview.innerHTML = `<span>📎 ${escapeHtml(file.name)}</span><button type="button" id="fm-chat-file-clear">إزالة</button>`;
    }
  }

  async function sendChat(event) {
    event.preventDefault();
    if (chat.sending) return;
    const text = $("#fm-chat-input").value.trim();
    if (!text && !chat.file) return;
    if (!chat.page_id || !chat.customer_psid) {
      chatError("ما نقدر نرسل — افتح المحادثة من جديد.");
      return;
    }
    chat.sending = true;
    $("#fm-chat-send").disabled = true;
    chatError("");
    try {
      if (chat.file) {
        const form = new FormData();
        form.append("file", chat.file);
        form.append("page_id", chat.page_id);
        form.append("customer_psid", chat.customer_psid);
        if (text) form.append("caption", text);
        const response = await fetch("/api/facebook-monitor/thread/media", { method: "POST", body: form });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          chatError(data.error || "فشل إرسال الوسائط");
          return;
        }
        appendChatBubble(data.message || { direction: "out", text: text || "وسائط", time_label: "الآن" });
        clearChatFile();
        $("#fm-chat-input").value = "";
      } else {
        const response = await fetch("/api/facebook-monitor/thread/reply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            page_id: chat.page_id,
            customer_psid: chat.customer_psid,
            text,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          chatError(data.error || "فشل إرسال الرسالة");
          return;
        }
        appendChatBubble(data.message || { direction: "out", text, time_label: "الآن" });
        pulse("replying", $("#fm-chat-name")?.textContent || "");
        clearTimeout(pulse._typing);
        pulse._typing = setTimeout(() => pulse("open"), 8000);
        $("#fm-chat-input").value = "";
      }
      $("#fm-chat-input").style.height = "auto";
      $("#fm-chat-input").focus();
    } finally {
      chat.sending = false;
      $("#fm-chat-send").disabled = false;
    }
  }

  function paintChatOwner(pageName) {
    const owner = chat.assigned_name ? `عند ${chat.assigned_name}` : "غير مسندة";
    $("#fm-chat-page").textContent = pageName ? `${pageName} · ${owner}` : owner;
  }

  function closeTransferPop() {
    const pop = $("#fm-transfer-pop");
    if (!pop) return;
    pop.hidden = true;
  }

  async function openTransferPop() {
    const pop = $("#fm-transfer-pop");
    if (!pop) return;
    if (!pop.hidden) {
      closeTransferPop();
      return;
    }
    if (!chat.page_id || !chat.customer_psid) {
      notify(false, "افتح محادثة فيها عميل معروف حتى تقدر تحوّلها.");
      return;
    }
    pop.hidden = false;
    pop.innerHTML = `<p>جاري جلب الموظفين…</p>`;
    try {
      const response = await fetch(`/api/facebook-routing/teammates?page_id=${encodeURIComponent(chat.page_id)}`);
      const data = await response.json().catch(() => ({}));
      const rows = (data.employees || []).filter((row) => String(row.id) !== String(chat.assigned_id || ""));
      const current = chat.assigned_name ? `الحالية عند ${escapeHtml(chat.assigned_name)}` : "المحادثة غير مسندة";
      pop.innerHTML = `<p>${current}</p>` + (rows.length
        ? rows.map((row) => `<button type="button" data-transfer-emp="${row.id}" data-transfer-name="${escapeHtml(row.name)}">${escapeHtml(row.name)}<span>${row.active || 0} مفتوحة</span></button>`).join("")
        : `<button type="button" disabled>ماكو موظف ثاني بهالصفحة</button>`);
    } catch (err) {
      pop.innerHTML = `<button type="button" disabled>تعذر جلب الموظفين</button>`;
    }
  }

  async function transferChat(employeeId, employeeName) {
    closeTransferPop();
    const response = await fetch("/api/facebook-routing/transfer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_id: chat.page_id,
        customer_psid: chat.customer_psid,
        employee_id: Number(employeeId),
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      notify(false, data.error || "ما تحولت المحادثة.");
      return;
    }
    chat.assigned_id = employeeId;
    chat.assigned_name = employeeName;
    paintChatOwner(chat.page_name);
    notify(true, `تم تحويل المحادثة إلى ${employeeName}.`);
    load({ silent: true });
  }

  $("#fm-transfer-open")?.addEventListener("click", (event) => {
    event.stopPropagation();
    openTransferPop();
  });
  $("#fm-transfer-pop")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-transfer-emp]");
    if (!button) return;
    transferChat(button.dataset.transferEmp, button.dataset.transferName || "الموظف");
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest("#fm-transfer-pop, #fm-transfer-open")) return;
    closeTransferPop();
  });

  $("#fm-chat-close").addEventListener("click", closeChat);
  $("#fm-chat-back").addEventListener("click", closeChat);
  $("#fm-chat-form").addEventListener("submit", sendChat);
  $("#fm-chat-attach").addEventListener("click", () => $("#fm-chat-file").click());
  $("#fm-chat-file").addEventListener("change", (event) => {
    setChatFile(event.target.files && event.target.files[0]);
  });
  document.body.addEventListener("click", (event) => {
    if (event.target.id === "fm-chat-file-clear") clearChatFile();
  });
  $("#fm-chat-input").addEventListener("input", (event) => {
    const node = event.target;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 120)}px`;
  });
  $("#fm-chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("#fm-chat-form").requestSubmit();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const pop = $("#fm-transfer-pop");
    if (pop && !pop.hidden) closeTransferPop();
    else if (!$("#fm-chat").hidden) closeChat();
    else if ($("#fm-settings").classList.contains("show")) closeSettings();
  });

  try {
    load();
  } catch (err) {
    if (list.messages) {
      list.messages.innerHTML = `<div class="fm-empty"><strong>تعذر فتح المراقبة</strong>${escapeHtml(err.message || "")}</div>`;
    }
  }
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
  async function refreshLive() {
    if (!state.employees) return;
    try {
      const response = await fetch("/api/facebook-routing/live");
      const data = await response.json().catch(() => ({}));
      if (!data.ok) return;
      const byId = new Map((data.people || []).map((row) => [String(row.id), row]));
      let changed = false;
      state.employees.forEach((row) => {
        const hit = byId.get(String(row.id));
        const nextLive = hit ? hit.live : (row.live && row.live !== "offline" ? "offline" : row.live || "offline");
        const nextLabel = hit ? (hit.label || "") : "";
        const nextSeen = nextLive === "offline" ? ((hit && hit.seen_label) || row.seen_label || "") : "";
        if (row.live !== nextLive || (row.live_label || "") !== nextLabel || (row.seen_label || "") !== nextSeen) {
          row.live = nextLive;
          row.live_label = nextLabel;
          row.seen_label = nextSeen;
          row.presence = nextLive === "offline" ? "offline" : "online";
          changed = true;
        }
      });
      if (changed) renderEmployees(state.employees);
    } catch (err) {}
  }
  $("#fm-chat-input")?.addEventListener("input", () => {
    const name = $("#fm-chat-name")?.textContent || "";
    pulse("typing", name && name !== "محادثة" ? name : "");
    clearTimeout(pulse._typing);
    pulse._typing = setTimeout(() => pulse("open"), 2500);
  });
  if (document.visibilityState === "visible") pulse("open");
  setInterval(() => {
    if (document.visibilityState === "visible") pulse(pulseMode, pulseLabel);
  }, 12000);
  setInterval(refreshLive, 4000);
  setInterval(() => load({ silent: true }), 90000);
})();
