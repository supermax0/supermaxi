(() => {
  "use strict";

  const app = document.getElementById("salesAiApp");
  if (!app) return;

  const canManage = app.dataset.canManage === "true";
  const state = {
    conversations: [],
    messages: [],
    activeId: null,
    activeConversation: null,
    activeLead: null,
    channels: [],
    employees: [],
    products: [],
    filter: "",
    polling: false,
    pollTimer: null,
    pollFailures: 0,
    metaSyncing: false,
    metaSyncQueued: false,
    metaPausedUntil: 0,
    metaReconnectNotified: false,
    metaCredentialRevision: 0,
    metaSelected: new Set(),
    metaInternalTab: "general",
    settingsLoaded: false,
    unseenMessages: 0,
    mediaDraft: null,
    mediaRecorder: null,
    recordingStream: null,
    recordingChunks: [],
    recordingStartedAt: 0,
    recordingTimer: null,
    editingMessageId: null,
    actionMessageId: null,
    learningEntries: [],
    learningImports: [],
    learningStats: {},
  };

  const $ = id => document.getElementById(id);
  const isMobile = () => window.matchMedia("(max-width: 900px)").matches;
  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[char]);
  const normalizeForSearch = value => String(value || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u064b-\u065f\u0670ـ]/g, "")
    .replace(/[أإآ]/g, "ا")
    .replace(/ة/g, "ه")
    .replace(/ى/g, "ي")
    .replace(/\s+/g, " ")
    .trim();
  const safeHttpUrl = value => {
    try {
      const parsed = new URL(String(value || ""));
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
    } catch (_) {
      return "";
    }
  };
  const linkifyText = value => {
    const source = String(value || "");
    const pattern = /https?:\/\/[^\s<>"']+/gi;
    let output = "";
    let cursor = 0;
    for (const match of source.matchAll(pattern)) {
      const original = match[0];
      const clean = original.replace(/[.,،؛;:!?؟)\]}»]+$/g, "");
      const trailing = original.slice(clean.length);
      const href = safeHttpUrl(clean);
      output += escapeHtml(source.slice(cursor, match.index));
      output += href
        ? `<a class="sales-ai-inline-link" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(clean)}</a>${escapeHtml(trailing)}`
        : escapeHtml(original);
      cursor = Number(match.index) + original.length;
    }
    return output + escapeHtml(source.slice(cursor));
  };
  const linkPreviewsMarkup = previews => (Array.isArray(previews) ? previews : []).map(preview => {
    const href = safeHttpUrl(preview?.url);
    if (!href) return "";
    const isMap = preview.type === "map";
    return `
      <a class="sales-ai-link-preview ${isMap ? "map" : ""}" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">
        <span class="sales-ai-link-icon"><i class="fa-solid ${isMap ? "fa-location-dot" : "fa-link"}"></i></span>
        <span class="sales-ai-link-copy"><strong>${escapeHtml(preview.title || preview.domain || "رابط")}</strong><small>${escapeHtml(preview.domain || "")}</small></span>
        <i class="fa-solid fa-arrow-up-right-from-square sales-ai-link-open"></i>
      </a>`;
  }).join("");
  const api = async (url, options = {}) => {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) {
      const temporaryMessage = [502, 503, 504].includes(response.status)
        ? "انقطع الاتصال بالخادم مؤقتاً، ستتم إعادة المحاولة تلقائياً"
        : "تعذر تنفيذ الطلب";
      const errorText = typeof data.error === "object" ? data.error?.message : data.error;
      const error = new Error(errorText || temporaryMessage);
      error.data = data;
      error.status = response.status;
      error.transient = [0, 408, 425, 429, 502, 503, 504].includes(response.status);
      throw error;
    }
    return data;
  };
  const parseDate = value => {
    if (!value) return null;
    const raw = String(value);
    const normalized = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(raw) ? `${raw}Z` : raw;
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  };
  const time = value => {
    const parsed = parseDate(value);
    if (!parsed) return "";
    const now = new Date();
    const sameDay = parsed.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const clock = parsed.toLocaleTimeString("ar-IQ", { hour: "2-digit", minute: "2-digit" });
    if (sameDay) return clock;
    if (parsed.toDateString() === yesterday.toDateString()) return `أمس ${clock}`;
    return parsed.toLocaleString("ar-IQ", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  };
  const fullTime = value => {
    const parsed = parseDate(value);
    return parsed ? parsed.toLocaleString("ar-IQ", { dateStyle: "full", timeStyle: "short" }) : "";
  };
  const fileSize = value => {
    const bytes = Number(value || 0);
    if (!bytes) return "";
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };
  const number = value => Number(value || 0).toLocaleString("ar-IQ");
  const stageLabels = {
    new: "جديد",
    discovery: "اكتشاف الاحتياج",
    need_identified: "تم تحديد الاحتياج",
    budget_identified: "تم تحديد الميزانية",
    product_selection: "اختيار المنتج",
    comparison: "مقارنة",
    objection: "معالجة اعتراض",
    purchase_intent: "جاهز للشراء",
    collecting_order_data: "جمع بيانات الطلب",
    waiting_confirmation: "بانتظار التأكيد",
    follow_up: "متابعة",
    won: "تم البيع",
    lost: "لم تتم الصفقة",
  };
  const intelligenceDescriptions = {
    fast: "يرد بأقل زمن ممكن، يحتفظ بسياق مختصر، ويعرض حتى خيارين. مناسب للرسائل الكثيرة والأسئلة المباشرة.",
    professional: "يفهم الاحتياج والميزانية ويقدم توصية استشارية متوازنة، ويعمّق التحليل تلقائياً عند ظهور اعتراض.",
    expert: "يستخدم استدلالاً تكيفياً: سريع بالسؤال المباشر وأعمق بالاعتراض والشراء، مع ذاكرة حقائق وترتيب ذكي للمنتجات. المستوى الموصى به.",
    elite: "أعمق تحليل للسياق والاعتراضات وخطوة الإغلاق التالية، ويحتفظ بأوسع سياق للمحادثة. أعلى استهلاك عند الحالات المعقدة.",
  };
  const statusLabels = {
    open: "مفتوحة",
    waiting_employee: "بانتظار موظف",
    human_active: "عند الموظف",
    closed: "مغلقة",
    received: "مستلمة",
    processed: "تمت المعالجة",
    queued: "قيد الإرسال",
    sent: "مرسلة",
    delivered: "تم التسليم",
    read: "مقروءة",
    failed: "فشل الإرسال",
  };
  const temperatureLabels = { hot: "ساخن", warm: "دافئ", cold: "بارد" };

  function toast(message, type = "success") {
    const element = $("toast");
    element.textContent = message;
    element.className = `sales-ai-toast show ${type === "error" ? "error" : ""}`;
    clearTimeout(element._timer);
    element._timer = setTimeout(() => {
      element.className = "sales-ai-toast";
    }, 3800);
  }

  function channelIcon(type) {
    if (type === "instagram") return "fa-brands fa-instagram";
    if (type === "messenger") return "fa-brands fa-facebook-messenger";
    if (type === "whatsapp") return "fa-brands fa-whatsapp";
    return "fa-regular fa-comments";
  }

  function channelClass(type) {
    return ["instagram", "messenger", "whatsapp"].includes(type) ? type : "default";
  }

  function initials(value) {
    const cleaned = String(value || "?").trim();
    return cleaned.slice(0, 1).toUpperCase() || "؟";
  }

  function avatarInner(conversation, displayName) {
    const picture = String(conversation?.contact_profile_picture_url || "").trim();
    return `<span class="sales-ai-avatar-fallback">${escapeHtml(initials(displayName))}</span>${picture ? `<img data-contact-avatar src="${escapeHtml(picture)}" alt="">` : ""}`;
  }

  function avatarTone(displayName) {
    return Array.from(String(displayName || "")).reduce((sum, char) => sum + char.codePointAt(0), 0) % 6;
  }

  function avatarMarkup(conversation, displayName, className = "") {
    return `<span class="sales-ai-avatar tone-${avatarTone(displayName)} ${className}">${avatarInner(conversation, displayName)}<span class="sales-ai-avatar-channel ${channelClass(conversation?.channel_type)}"><i class="${channelIcon(conversation?.channel_type)}"></i></span></span>`;
  }

  function bindAvatarFallbacks(root = document) {
    root.querySelectorAll("[data-contact-avatar]").forEach(image => {
      image.addEventListener("error", () => image.remove(), { once: true });
    });
  }

  function setOverview(overview = {}) {
    const values = {
      metricOpen: overview.open_conversations,
      metricHuman: overview.waiting_employee,
      metricHot: overview.hot_leads,
      metricMessages: overview.messages_today,
      mobileMetricOpen: overview.open_conversations,
      mobileMetricHuman: overview.waiting_employee,
      mobileMetricHot: overview.hot_leads,
      mobileMetricMessages: overview.messages_today,
    };
    Object.entries(values).forEach(([id, value]) => {
      if ($(id)) $(id).textContent = number(value);
    });
  }

  async function loadOverview() {
    const data = await api("/ai-sales/api/overview");
    setOverview(data.overview || {});
  }

  function conversationState(conversation) {
    if (conversation.status === "closed") {
      return { className: "closed", icon: "fa-solid fa-box-archive", label: "مغلقة" };
    }
    if (conversation.human_takeover) {
      return { className: "human", icon: "fa-solid fa-headset", label: conversation.assigned_employee || "عند الموظف" };
    }
    return { className: "ai", icon: "fa-solid fa-robot", label: "AI يعمل" };
  }

  function renderConversations() {
    const term = $("conversationSearch").value.trim().toLowerCase();
    const rows = state.conversations.filter(conversation => {
      const haystack = `${conversation.contact_name} ${conversation.external_phone} ${conversation.external_contact_id} ${conversation.channel_name}`.toLowerCase();
      return !term || haystack.includes(term);
    });
    $("conversationCount").textContent = number(rows.length);
    if (!rows.length) {
      $("conversationList").innerHTML = `
        <div class="sales-ai-empty-state">
          <i class="fa-regular fa-comments"></i>
          <strong>لا توجد محادثات</strong>
          <p>غيّر الفلتر أو انتظر وصول رسالة جديدة.</p>
        </div>`;
      return;
    }
    $("conversationList").innerHTML = rows.map(conversation => {
      const last = conversation.last_message || {};
      const currentState = conversationState(conversation);
      const displayName = conversation.contact_name || conversation.external_phone || conversation.external_contact_id;
      const unread = Number(conversation.unread_count || 0);
      return `
        <button class="sales-ai-conversation ${state.activeId === conversation.id ? "active" : ""}" type="button" data-conversation-id="${conversation.id}">
          ${avatarMarkup(conversation, displayName)}
          <span class="sales-ai-conversation-main">
            <span class="sales-ai-conversation-line">
              <strong><i class="sales-ai-temperature ${escapeHtml(conversation.lead_temperature || "cold")}"></i> ${escapeHtml(displayName)}</strong>
            </span>
            <p>${escapeHtml(last.text_content || last.transcription || "لا توجد رسائل بعد")}</p>
            <span class="sales-ai-conversation-meta">
              <span class="sales-ai-channel-icon ${channelClass(conversation.channel_type)}"><i class="${channelIcon(conversation.channel_type)}"></i></span>
              <span class="sales-ai-channel-label">${escapeHtml(conversation.channel_name || conversation.channel_type)}</span>
              <span>·</span>
              <span class="sales-ai-state-tag ${currentState.className}"><i class="${currentState.icon}"></i>${escapeHtml(currentState.label)}</span>
            </span>
          </span>
          <span class="sales-ai-conversation-side">
            <time>${time(last.created_at || conversation.updated_at)}</time>
            ${unread ? `<span class="sales-ai-unread">${unread > 99 ? "99+" : unread}</span>` : ""}
          </span>
        </button>`;
    }).join("");
    bindAvatarFallbacks($("conversationList"));
  }

  async function loadConversations({ silent = false } = {}) {
    if (!silent) {
      $("conversationList").innerHTML = '<div class="sales-ai-list-skeleton"><span></span><span></span><span></span><span></span></div>';
    }
    const query = state.filter ? `?status=${encodeURIComponent(state.filter)}` : "";
    const data = await api("/ai-sales/api/conversations" + query);
    state.conversations = data.conversations || [];
    renderConversations();
  }

  function updateConversationUrl(conversationId, { replace = false } = {}) {
    const url = new URL(window.location.href);
    if (conversationId) url.searchParams.set("conversation", conversationId);
    else url.searchParams.delete("conversation");
    history[replace ? "replaceState" : "pushState"]({ conversationId: conversationId || null }, "", url);
  }

  function setMobileChat(open) {
    $("workspace").classList.toggle("mobile-chat-open", Boolean(open));
  }

  function isNearBottom() {
    const list = $("messageList");
    return list.scrollHeight - list.scrollTop - list.clientHeight < 120;
  }

  function scrollMessages({ smooth = false } = {}) {
    const list = $("messageList");
    list.scrollTo({ top: list.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    state.unseenMessages = 0;
    $("newMessagesBtn").hidden = true;
  }

  function messageStatus(message) {
    if (message._pending) return { className: "", icon: "fa-solid fa-spinner fa-spin", label: "جاري الإرسال" };
    if (message.status === "failed") return { className: "failed", icon: "fa-solid fa-triangle-exclamation", label: "فشل الإرسال" };
    if (message.read_at || message.status === "read") return { className: "read", icon: "fa-solid fa-check-double", label: "مقروءة" };
    if (message.delivered_at || message.status === "delivered") return { className: "", icon: "fa-solid fa-check-double", label: "تم التسليم" };
    if (message.direction === "outbound") return { className: "", icon: "fa-solid fa-check", label: statusLabels[message.status] || message.status };
    return { className: "", icon: "fa-solid fa-circle-check", label: statusLabels[message.status] || message.status };
  }

  function legacyMessageMarkup(message) {
    const mediaUrl = escapeHtml(message.media_url || "");
    let media = "";
    if (mediaUrl && message.message_type === "image") {
      media = `<img class="sales-ai-chat-media" src="${mediaUrl}" alt="صورة مرفقة" loading="lazy">`;
    } else if (mediaUrl && ["audio", "voice"].includes(message.message_type)) {
      media = `<audio class="sales-ai-chat-media" controls preload="metadata" src="${mediaUrl}"></audio>`;
    } else if (mediaUrl && message.message_type === "video") {
      media = `<video class="sales-ai-chat-media" controls preload="metadata" src="${mediaUrl}"></video>`;
    }
    const text = message.text_content || message.transcription || (!media ? (
      (message.message_type === "referral" || message.thread_opener || message.ad_opener)
        ? "فتح المحادثة من إعلان / الصفحة"
        : ""
    ) : "");
    const delivery = messageStatus(message);
    const sender = message.sender_type === "customer" ? "الزبون" : message.sender_type === "ai" ? "الموظف الذكي" : "الموظف";
    return `
      <div class="sales-ai-message ${message.direction} ${message.status === "failed" ? "failed" : ""} ${message._pending ? "pending" : ""}" data-message-id="${escapeHtml(message.id)}">
        <div class="sales-ai-bubble">
          <div class="sales-ai-sender">${sender}</div>
          ${media}${escapeHtml(text)}
          <footer>
            <span class="sales-ai-status ${delivery.className}" title="${escapeHtml(delivery.label)}"><i class="${delivery.icon}"></i> ${escapeHtml(delivery.label)}</span>
            <span>${time(message.created_at)}</span>
          </footer>
          ${message.failure_message ? `<footer><span class="sales-ai-status failed">${escapeHtml(message.failure_message)}</span></footer>` : ""}
        </div>
      </div>`;
  }

  function messageOriginMarkup(message) {
    const conversationAd = state.activeConversation?.ad_context || {};
    const ad = Object.keys(message.ad_context || {}).length
      ? (message.ad_context || {})
      : (
        (!message.text_content && (message.message_type === "referral" || message.thread_opener || message.ad_opener))
          ? conversationAd
          : {}
      );
    const meta = message.meta_context || {};
    const post = meta.post || {};
    const hasAd = Boolean(ad.ad_id || ad.title || ad.body || ad.image_url || ad.video_url);
    const hasMeta = Boolean(meta.type);
    if (!hasAd && !hasMeta) return "";

    const isAd = hasAd;
    const imageUrl = safeHttpUrl(isAd ? ad.image_url : post.image_url);
    const videoUrl = safeHttpUrl(isAd ? ad.video_url : "");
    const destinationUrl = safeHttpUrl(
      isAd
        ? (String(ad.ref || "").startsWith("http") ? ad.ref : "")
        : (post.permalink_url || meta.url)
    );
    const title = isAd
      ? (ad.title || ad.body || `إعلان Meta ${ad.ad_id || ""}`)
      : (post.title || meta.title || "منشور الصفحة");
    const eyebrow = isAd ? "دخل الزبون من هذا الإعلان" : (meta.title || "مصدر المحادثة");
    const description = isAd ? ad.body : meta.description;

    return `
      <div class="sales-ai-origin-card ${isAd ? "ad" : "meta"}">
        ${imageUrl
          ? `<img src="${escapeHtml(imageUrl)}" alt="${isAd ? "صورة الإعلان" : "صورة المنشور"}" loading="lazy">`
          : `<span class="sales-ai-origin-icon"><i class="fa-solid ${isAd ? "fa-rectangle-ad" : meta.type === "marketing_permission" ? "fa-shield-halved" : "fa-comment-dots"}"></i></span>`}
        <div class="sales-ai-origin-copy">
          <span>${escapeHtml(eyebrow)}</span>
          <strong>${escapeHtml(title)}</strong>
          ${description && description !== title ? `<p>${escapeHtml(description)}</p>` : ""}
          <div class="sales-ai-origin-actions">
            ${destinationUrl ? `<a href="${escapeHtml(destinationUrl)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square"></i>${isAd ? "فتح الإعلان" : "فتح المنشور"}</a>` : ""}
            ${videoUrl ? `<a href="${escapeHtml(videoUrl)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-circle-play"></i>فتح الفيديو</a>` : ""}
          </div>
        </div>
      </div>`;
  }

  function emptyOpenerMarkup(message) {
    const mediaType = String(message.message_type || "text").toLowerCase();
    if (message.text_content || message.transcription || message.media_url) return "";
    if (mediaType === "referral" || message.thread_opener || message.ad_opener) {
      return '<span class="sales-ai-opener-hint"><i class="fa-solid fa-rectangle-ad"></i> فتح المحادثة من إعلان / الصفحة (بدون نص مكتوب)</span>';
    }
    return "";
  }

  function messageMarkup(message) {
    const deleted = Boolean(message.is_deleted);
    const mediaUrl = escapeHtml(message.media_url || "");
    const mediaType = String(message.message_type || "text").toLowerCase();
    let media = "";
    if (!deleted && mediaUrl && mediaType === "image") {
      media = `<a class="sales-ai-media-link" href="${mediaUrl}" target="_blank" rel="noopener"><img class="sales-ai-chat-media" src="${mediaUrl}" alt="صورة مرفقة" loading="lazy"></a>`;
    } else if (!deleted && mediaUrl && ["audio", "voice"].includes(mediaType)) {
      media = `<div class="sales-ai-audio-card"><i class="fa-solid fa-microphone-lines"></i><audio class="sales-ai-chat-media" controls preload="metadata" src="${mediaUrl}"></audio></div>`;
    } else if (!deleted && mediaUrl && mediaType === "video") {
      media = `<video class="sales-ai-chat-media" controls preload="metadata" src="${mediaUrl}"></video>`;
    } else if (!deleted && mediaUrl) {
      media = `<a class="sales-ai-media-link" href="${mediaUrl}" target="_blank" rel="noopener"><i class="fa-solid fa-paperclip"></i> ${escapeHtml(message.original_filename || "فتح المرفق")}</a>`;
    }

    const originMarkup = deleted ? "" : messageOriginMarkup(message);
    const openerHint = deleted ? "" : emptyOpenerMarkup(message);
    const hideMetaNotice = Boolean(message.meta_context && message.meta_context.is_meta_system);
    // Never show raw placeholders like [text] for empty Meta openers.
    const plainText = hideMetaNotice
      ? ""
      : (message.text_content || message.transcription || (!media && !originMarkup && !openerHint ? "" : ""));
    const text = deleted
      ? '<span class="sales-ai-deleted-text"><i class="fa-solid fa-ban"></i> حُذفت هذه الرسالة من الصندوق</span>'
      : (linkifyText(plainText) || openerHint);
    const linkPreviews = deleted || hideMetaNotice ? "" : linkPreviewsMarkup(message.link_previews);
    const delivery = messageStatus(message);
    const sender = message.sender_type === "customer" ? "الزبون" : message.sender_type === "ai" ? "الموظف الذكي" : "الموظف";
    const actions = message.actions || {};
    const canOpenMenu = !message._pending && (actions.can_copy !== false || message.direction === "outbound");
    const statusClass = message.status === "failed" ? "failed" : message._pending ? "pending" : "";
    const exactTime = fullTime(message.created_at);
    const training = message.training || {};
    const trainingActions = canManage && message.sender_type === "ai" && training.training
      ? `<div class="sales-ai-training-actions" data-training-actions="${escapeHtml(message.id)}">
          ${training.rating ? `<span class="sales-ai-training-approved"><i class="fa-solid fa-circle-check"></i>${training.rating === "like" ? "معتمد" : "تم حفظ التصحيح"}</span>` : `
            <button type="button" class="sales-ai-training-like" data-training-feedback="like" data-message-id="${escapeHtml(message.id)}"><i class="fa-solid fa-thumbs-up"></i>اعتماد</button>
            <button type="button" class="sales-ai-training-dislike" data-training-feedback="dislike" data-message-id="${escapeHtml(message.id)}"><i class="fa-solid fa-thumbs-down"></i>تصحيح</button>
          `}
        </div>`
      : "";
    const mediaMeta = message.original_filename && mediaType !== "text"
      ? `<span class="sales-ai-media-meta">${escapeHtml(message.original_filename)}${message.file_size ? ` · ${fileSize(message.file_size)}` : ""}</span>`
      : "";
    return `
      <div class="sales-ai-message ${message.direction} ${statusClass} ${deleted ? "deleted" : ""}" data-message-id="${escapeHtml(message.id)}">
        <div class="sales-ai-bubble">
          <div class="sales-ai-sender">
            <span>${escapeHtml(sender)}</span>
            ${canOpenMenu ? `<button class="sales-ai-bubble-menu" type="button" data-message-menu="${escapeHtml(message.id)}" title="إجراءات الرسالة" aria-label="إجراءات الرسالة"><i class="fa-solid fa-ellipsis-vertical"></i></button>` : ""}
          </div>
          ${originMarkup}${media}${mediaMeta}${text ? `<div class="sales-ai-message-text">${text}</div>` : ""}${linkPreviews}${trainingActions}
          <footer>
            ${message.edited_at ? '<span class="sales-ai-edited-label">معدّلة</span>' : ""}
            <time class="sales-ai-message-time" title="${escapeHtml(exactTime)}">${escapeHtml(time(message.created_at))}</time>
            ${message.direction === "outbound" && !deleted ? `<span class="sales-ai-status ${delivery.className}" title="${escapeHtml(delivery.label)}"><i class="${delivery.icon}"></i></span>` : ""}
          </footer>
          ${message.failure_message && !deleted ? `<div class="sales-ai-message-error"><i class="fa-solid fa-triangle-exclamation"></i>${escapeHtml(message.failure_message)}</div>` : ""}
        </div>
      </div>`;
  }

  function renderMessages({ preserveScroll = false } = {}) {
    const list = $("messageList");
    const previousBottom = list.scrollHeight - list.scrollTop;
    if (!state.messages.length) {
      list.innerHTML = '<div class="sales-ai-empty-state"><i class="fa-regular fa-message"></i><strong>لا توجد رسائل</strong><p>ابدأ الرد من مربع الكتابة.</p></div>';
      return;
    }
    list.innerHTML = state.messages.map(messageMarkup).join("");
    if (preserveScroll) list.scrollTop = Math.max(0, list.scrollHeight - previousBottom);
  }

  function appendMessages(messages) {
    if (!messages.length) return;
    const list = $("messageList");
    const nearBottom = isNearBottom();
    if (!state.messages.length) list.innerHTML = "";
    state.messages.push(...messages);
    list.insertAdjacentHTML("beforeend", messages.map(messageMarkup).join(""));
    if (nearBottom) {
      scrollMessages();
    } else {
      state.unseenMessages += messages.length;
      $("newMessagesBtn").innerHTML = `${number(state.unseenMessages)} رسائل جديدة <i class="fa-solid fa-arrow-down"></i>`;
      $("newMessagesBtn").hidden = false;
    }
  }

  function updateChatHeader() {
    const conversation = state.activeConversation;
    if (!conversation) return;
    const displayName = conversation.contact_name || conversation.external_phone || conversation.external_contact_id;
    const currentState = conversationState(conversation);
    $("chatAvatar").className = `sales-ai-avatar compact tone-${avatarTone(displayName)}`;
    $("chatAvatar").innerHTML = avatarInner(conversation, displayName);
    bindAvatarFallbacks($("chatAvatar"));
    $("chatName").textContent = displayName;
    $("chatStatus").innerHTML = `<i class="${channelIcon(conversation.channel_type)}"></i> ${escapeHtml(conversation.channel_name || "")} · ${escapeHtml(currentState.label)}`;
    const closeButton = $("closeConversationBtn");
    const closed = conversation.status === "closed";
    closeButton.innerHTML = closed ? '<i class="fa-solid fa-box-open"></i>' : '<i class="fa-solid fa-box-archive"></i>';
    closeButton.title = closed ? "إعادة فتح المحادثة" : "إغلاق المحادثة";
    closeButton.setAttribute("aria-label", closeButton.title);
    $("messageInput").disabled = closed;
    $("sendBtn").disabled = closed;
    $("attachmentBtn").disabled = closed;
    $("voiceBtn").disabled = closed || conversation.channel_type === "instagram";
    $("chatMediaInput").accept = conversation.channel_type === "instagram"
      ? "image/jpeg,image/png,image/webp,image/gif"
      : "image/jpeg,image/png,image/webp,image/gif,video/mp4,video/3gpp,video/quicktime,audio/mpeg,audio/mp4,audio/aac,audio/ogg,audio/webm";
    $("voiceBtn").title = conversation.channel_type === "instagram" ? "الرسائل الصوتية غير مدعومة على إنستغرام" : "تسجيل رسالة صوتية";
  }

  function contactMarkup() {
    const conversation = state.activeConversation;
    const lead = state.activeLead || {};
    if (!conversation) return '<div class="sales-ai-detail-empty"><i class="fa-regular fa-address-card"></i><span>لا توجد محادثة محددة</span></div>';
    const displayName = conversation.contact_name || conversation.external_phone || conversation.external_contact_id;
    const score = Math.max(0, Math.min(100, Number(conversation.lead_score || 0)));
    const orderData = conversation.order_customer_data || {};
    const adContext = conversation.ad_context || {};
    const adImage = safeHttpUrl(adContext.image_url);
    const adVideo = safeHttpUrl(adContext.video_url);
    const adTitle = String(adContext.title || adContext.body || "").trim();
    const adMarkup = (adTitle || adImage || adVideo || adContext.ad_id) ? `
      <div class="sales-ai-ad-context">
        ${adImage ? `<img src="${escapeHtml(adImage)}" alt="صورة الإعلان">` : '<i class="fa-solid fa-rectangle-ad"></i>'}
        <div>
          <span>الإعلان المرتبط</span>
          <strong>${escapeHtml(adTitle || `إعلان Meta ${adContext.ad_id || ""}`)}</strong>
          ${adVideo ? `<a href="${escapeHtml(adVideo)}" target="_blank" rel="noopener noreferrer">فتح فيديو الإعلان</a>` : ""}
        </div>
      </div>` : "";
    const orderAddress = [orderData.city, orderData.area, orderData.landmark].filter(Boolean).join(" / ");
    const locationUrl = safeHttpUrl(orderData.location_url);
    const sharedLinks = (Array.isArray(orderData.shared_links) ? orderData.shared_links : []).map(safeHttpUrl).filter(Boolean);
    const latestSharedLink = sharedLinks.length ? sharedLinks[sharedLinks.length - 1] : "";
    const orderId = Number(lead.won_order_id || conversation.created_order_id || 0);
    const currentState = conversationState(conversation);
    const closed = conversation.status === "closed";
    const action = closed
      ? '<button class="sales-ai-btn reopen" type="button" data-contact-action="reopen"><i class="fa-solid fa-box-open"></i>إعادة فتح المحادثة</button>'
      : conversation.human_takeover
        ? '<button class="sales-ai-btn release" type="button" data-contact-action="release"><i class="fa-solid fa-robot"></i>إرجاع للذكاء</button>'
        : '<button class="sales-ai-btn takeover" type="button" data-contact-action="takeover"><i class="fa-solid fa-headset"></i>استلام المحادثة</button>';
    return `
      <div class="sales-ai-contact-card">
        <div class="sales-ai-contact-hero">
          ${avatarMarkup(conversation, displayName)}
          <div><strong>${escapeHtml(displayName)}</strong><span><i class="${channelIcon(conversation.channel_type)}"></i> ${escapeHtml(conversation.channel_name || conversation.channel_type)}</span></div>
        </div>
        <div class="sales-ai-lead-score">
          <div class="sales-ai-score-line"><span>درجة الاهتمام</span><strong>${score}%</strong></div>
          <div class="sales-ai-score-track"><span style="width:${score}%"></span></div>
        </div>
        ${adMarkup}
        <div class="sales-ai-detail-list">
          <div class="sales-ai-detail-row"><span>الحالة</span><strong class="sales-ai-state-tag ${currentState.className}"><i class="${currentState.icon}"></i> ${escapeHtml(currentState.label)}</strong></div>
          <div class="sales-ai-detail-row"><span>مرحلة البيع</span><strong>${escapeHtml(stageLabels[conversation.sales_stage] || conversation.sales_stage || "—")}</strong></div>
          <div class="sales-ai-detail-row"><span>حرارة العميل</span><strong>${escapeHtml(temperatureLabels[conversation.lead_temperature] || conversation.lead_temperature || "—")}</strong></div>
          <div class="sales-ai-detail-row"><span>الموظف</span><strong>${escapeHtml(conversation.assigned_employee || "—")}</strong></div>
          <div class="sales-ai-detail-row"><span>اسم الطلب</span><strong>${escapeHtml(orderData.name || "—")}</strong></div>
          <div class="sales-ai-detail-row"><span>هاتف الطلب</span><strong dir="ltr">${escapeHtml(orderData.phone || "—")}</strong></div>
          <div class="sales-ai-detail-row"><span>عنوان التوصيل</span><strong>${escapeHtml(orderAddress || "—")}</strong></div>
          <div class="sales-ai-detail-row"><span>الموقع</span><strong>${locationUrl ? `<a class="sales-ai-location-link" href="${escapeHtml(locationUrl)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-location-dot"></i> فتح الخريطة</a>` : "—"}</strong></div>
          <div class="sales-ai-detail-row"><span>آخر رابط</span><strong>${latestSharedLink ? `<a class="sales-ai-location-link" href="${escapeHtml(latestSharedLink)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-link"></i> فتح الرابط</a>` : "—"}</strong></div>
          <div class="sales-ai-detail-row"><span>طلب Finora</span><strong>${orderId ? `<a class="sales-ai-location-link" href="/orders/${orderId}"><i class="fa-solid fa-receipt"></i> فتح الطلب #${orderId}</a>` : "—"}</strong></div>
          <div class="sales-ai-detail-row"><span>الميزانية</span><strong>${lead.estimated_budget ? number(lead.estimated_budget) + " د.ع" : "—"}</strong></div>
          <div class="sales-ai-detail-row"><span>الاعتراض</span><strong>${escapeHtml(lead.primary_objection || "—")}</strong></div>
          <div class="sales-ai-detail-row"><span>الخطوة التالية</span><strong>${escapeHtml(lead.next_action || "—")}</strong></div>
          <div class="sales-ai-detail-row"><span>معرف الزبون</span><strong dir="ltr">${escapeHtml(conversation.external_phone || conversation.external_contact_id)}</strong></div>
        </div>
        <div class="sales-ai-detail-actions">${action}</div>
      </div>`;
  }

  function renderContact() {
    const markup = contactMarkup();
    $("contactPanel").innerHTML = markup;
    $("mobileContactPanel").innerHTML = markup;
    bindAvatarFallbacks($("contactPanel"));
    bindAvatarFallbacks($("mobileContactPanel"));
    const temperature = state.activeConversation?.lead_temperature || "cold";
    $("leadDot").className = `sales-ai-live-dot ${temperature}`;
  }

  async function markConversationRead() {
    if (!state.activeId || document.hidden) return;
    try {
      await api(`/ai-sales/api/conversations/${state.activeId}/read`, { method: "POST" });
      const row = state.conversations.find(item => item.id === state.activeId);
      if (row) row.unread_count = 0;
      if (state.filter === "unread") await loadConversations({ silent: true });
      else renderConversations();
    } catch (error) {
      console.warn("Mark read:", error.message);
    }
  }

  async function openConversation(id, { updateHistory = true, preserveScroll = false } = {}) {
    const conversationId = Number(id);
    if (!conversationId) return;
    if (state.activeId && state.activeId !== conversationId) {
      finishRecording(true);
      clearMediaDraft();
      cancelEditing();
      closeMessageActions();
    }
    state.activeId = conversationId;
    state.unseenMessages = 0;
    renderConversations();
    $("chatEmpty").hidden = true;
    $("chatActive").hidden = false;
    $("messageList").innerHTML = '<div class="sales-ai-list-skeleton"><span></span><span></span><span></span></div>';
    setMobileChat(true);
    if (updateHistory) updateConversationUrl(conversationId);
    try {
      const data = await api(`/ai-sales/api/conversations/${conversationId}/messages`);
      if (state.activeId !== conversationId) return;
      state.activeConversation = data.conversation;
      state.activeLead = data.lead;
      state.messages = data.messages || [];
      updateChatHeader();
      renderMessages({ preserveScroll });
      renderContact();
      scrollMessages();
      await markConversationRead();
    } catch (error) {
      $("messageList").innerHTML = `<div class="sales-ai-empty-state"><i class="fa-solid fa-triangle-exclamation"></i><strong>تعذر فتح المحادثة</strong><p>${escapeHtml(error.message)}</p></div>`;
      toast(error.message, "error");
    }
  }

  async function loadNewMessages() {
    if (!state.activeId || !state.activeConversation) return;
    const lastStored = state.messages.filter(message => Number(message.id) > 0).at(-1);
    const afterId = Number(lastStored?.id || 0);
    const data = await api(`/ai-sales/api/conversations/${state.activeId}/messages?after_id=${afterId}`);
    if (Number(data.conversation.id) !== state.activeId) return;
    state.activeConversation = data.conversation;
    state.activeLead = data.lead;
    updateChatHeader();
    renderContact();
    const existingIds = new Set(state.messages.map(message => String(message.id)));
    const incoming = (data.messages || []).filter(message => !existingIds.has(String(message.id)));
    appendMessages(incoming);
    if (incoming.some(message => message.direction === "inbound")) await markConversationRead();
  }

  function backToConversationList({ updateHistory = true } = {}) {
    setMobileChat(false);
    if (updateHistory) updateConversationUrl(null);
  }

  async function setConversationOwner(action) {
    if (!state.activeId) return;
    try {
      const data = await api(`/ai-sales/api/conversations/${state.activeId}/${action}`, { method: "POST" });
      state.activeConversation = data.conversation;
      updateChatHeader();
      renderContact();
      await loadConversations({ silent: true });
      toast(action === "takeover" ? "تم استلام المحادثة" : "رجعت المحادثة للذكاء");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function setConversationClosed(closed) {
    if (!state.activeId) return;
    const action = closed ? "close" : "reopen";
    try {
      const data = await api(`/ai-sales/api/conversations/${state.activeId}/${action}`, { method: "POST" });
      state.activeConversation = data.conversation;
      updateChatHeader();
      renderContact();
      await Promise.all([loadConversations({ silent: true }), loadOverview()]);
      toast(closed ? "تم إغلاق المحادثة ويمكن فتحها لاحقاً" : "تمت إعادة فتح المحادثة");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function replaceMessage(messageId, replacement) {
    const index = state.messages.findIndex(item => String(item.id) === String(messageId));
    if (index >= 0) state.messages[index] = replacement;
    renderMessages();
  }

  function mediaKind(file) {
    const mime = String(file?.type || "").toLowerCase();
    if (mime.startsWith("image/")) return "image";
    if (mime.startsWith("video/")) return "video";
    if (mime.startsWith("audio/")) return "audio";
    return "";
  }

  function clearMediaDraft() {
    if (state.mediaDraft?.previewUrl) URL.revokeObjectURL(state.mediaDraft.previewUrl);
    state.mediaDraft = null;
    $("draftMedia").hidden = true;
    $("draftMedia").innerHTML = "";
    $("chatMediaInput").value = "";
  }

  function setMediaDraft(file, { voiceNote = false } = {}) {
    const kind = mediaKind(file);
    if (!kind) {
      toast("صيغة الملف غير مدعومة", "error");
      return;
    }
    if (state.activeConversation?.channel_type === "instagram" && kind !== "image") {
      toast("إنستغرام يدعم إرسال الصور فقط حالياً", "error");
      return;
    }
    const limit = kind === "image" ? 5 * 1024 * 1024 : 16 * 1024 * 1024;
    if (file.size > limit) {
      toast(`حجم ${kind === "image" ? "الصورة" : "الملف"} يتجاوز ${kind === "image" ? 5 : 16} MB`, "error");
      return;
    }
    clearMediaDraft();
    const previewUrl = URL.createObjectURL(file);
    state.mediaDraft = { file, kind, voiceNote, previewUrl };
    const icon = kind === "video" ? "fa-video" : kind === "audio" ? "fa-microphone-lines" : "fa-image";
    const preview = kind === "image"
      ? `<img src="${previewUrl}" alt="معاينة الصورة">`
      : kind === "video"
        ? `<video src="${previewUrl}" muted></video>`
        : `<i class="fa-solid ${icon}"></i>`;
    $("draftMedia").innerHTML = `
      <span class="sales-ai-draft-media-preview">${preview}</span>
      <span class="sales-ai-draft-media-info"><strong>${escapeHtml(file.name || (voiceNote ? "رسالة صوتية" : "مرفق"))}</strong><span>${voiceNote ? "رسالة صوتية" : kind === "image" ? "صورة" : kind === "video" ? "فيديو" : "ملف صوتي"} · ${fileSize(file.size)}</span></span>
      <button class="sales-ai-icon-btn" type="button" data-remove-media title="إزالة المرفق" aria-label="إزالة المرفق"><i class="fa-solid fa-xmark"></i></button>`;
    $("draftMedia").hidden = false;
    $("messageInput").focus();
  }

  function cancelEditing() {
    state.editingMessageId = null;
    $("editingBar").hidden = true;
    $("editingPreview").textContent = "";
    $("messageInput").value = "";
    resizeComposer();
  }

  function startEditing(message, { correction = false } = {}) {
    clearMediaDraft();
    state.editingMessageId = correction ? null : message.id;
    $("editingTitle").textContent = correction ? "إرسال تصحيح جديد" : "تعديل وإعادة إرسال";
    $("editingPreview").textContent = message.text_content || "";
    $("editingBar").hidden = false;
    $("messageInput").value = correction ? `تصحيح: ${message.text_content || ""}` : (message.text_content || "");
    resizeComposer();
    $("messageInput").focus();
  }

  function stopRecordingTimer() {
    clearInterval(state.recordingTimer);
    state.recordingTimer = null;
  }

  function setRecordingUi(active) {
    $("recordingBar").hidden = !active;
    $("attachmentBtn").disabled = active || state.activeConversation?.status === "closed";
    $("voiceBtn").disabled = active || state.activeConversation?.status === "closed" || state.activeConversation?.channel_type === "instagram";
    $("messageInput").disabled = active || state.activeConversation?.status === "closed";
    $("sendBtn").disabled = active || state.activeConversation?.status === "closed";
  }

  function finishRecording(discard = false) {
    const recorder = state.mediaRecorder;
    if (!recorder || recorder.state === "inactive") return;
    recorder._discard = discard;
    recorder.stop();
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast("المتصفح لا يدعم تسجيل الصوت", "error");
      return;
    }
    if (state.activeConversation?.channel_type === "instagram") {
      toast("إنستغرام يدعم إرسال الصور فقط حالياً", "error");
      return;
    }
    try {
      clearMediaDraft();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
        .find(type => MediaRecorder.isTypeSupported(type));
      const recorder = preferred ? new MediaRecorder(stream, { mimeType: preferred }) : new MediaRecorder(stream);
      state.recordingStream = stream;
      state.mediaRecorder = recorder;
      state.recordingChunks = [];
      state.recordingStartedAt = Date.now();
      recorder.addEventListener("dataavailable", event => {
        if (event.data.size) state.recordingChunks.push(event.data);
      });
      recorder.addEventListener("stop", () => {
        stopRecordingTimer();
        state.recordingStream?.getTracks().forEach(track => track.stop());
        const discard = Boolean(recorder._discard);
        const chunks = state.recordingChunks.slice();
        const mime = recorder.mimeType || "audio/webm";
        state.mediaRecorder = null;
        state.recordingStream = null;
        state.recordingChunks = [];
        setRecordingUi(false);
        $("recordingTime").textContent = "00:00";
        if (!discard && chunks.length) {
          const extension = mime.includes("ogg") ? "ogg" : "webm";
          const file = new File([new Blob(chunks, { type: mime })], `voice-${Date.now()}.${extension}`, { type: mime });
          setMediaDraft(file, { voiceNote: true });
        }
      }, { once: true });
      recorder.start(250);
      setRecordingUi(true);
      state.recordingTimer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - state.recordingStartedAt) / 1000);
        const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
        const seconds = String(elapsed % 60).padStart(2, "0");
        $("recordingTime").textContent = `${minutes}:${seconds}`;
        if (elapsed >= 180) finishRecording(false);
      }, 250);
    } catch (error) {
      toast(error.name === "NotAllowedError" ? "اسمح للمتصفح باستخدام الميكروفون" : "تعذر بدء تسجيل الصوت", "error");
    }
  }

  function closeMessageActions() {
    state.actionMessageId = null;
    $("messageActions").hidden = true;
    $("messageActions").innerHTML = "";
  }

  function openMessageActions(messageId, anchor) {
    const message = state.messages.find(item => String(item.id) === String(messageId));
    if (!message || message.is_deleted) return;
    const actions = message.actions || {};
    const canCopy = actions.can_copy !== false && Boolean(message.text_content || message.transcription);
    const canEdit = Boolean(actions.can_edit);
    const canCorrect = message.direction === "outbound" && message.message_type === "text" && !canEdit;
    state.actionMessageId = message.id;
    const menu = $("messageActions");
    menu.innerHTML = `
      ${canCopy ? '<button type="button" data-message-action="copy"><i class="fa-regular fa-copy"></i>نسخ النص</button>' : ""}
      ${canEdit ? '<button type="button" data-message-action="edit"><i class="fa-solid fa-pen"></i>تعديل وإعادة إرسال</button>' : ""}
      ${canCorrect ? '<button type="button" data-message-action="correct"><i class="fa-solid fa-rotate-left"></i>إرسال تصحيح</button>' : ""}
      <button type="button" data-message-action="delete-local" class="danger"><i class="fa-regular fa-trash-can"></i>حذف من الصندوق</button>
      ${message.direction === "outbound" ? '<button type="button" data-message-action="delete-everyone" class="muted"><i class="fa-solid fa-ban"></i>حذف عند الطرفين (غير مدعوم)</button>' : ""}`;
    menu.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const chatRect = document.querySelector(".sales-ai-chat-pane")?.getBoundingClientRect() || { left: 0, right: window.innerWidth };
    const menuWidth = 210;
    const rightCandidate = rect.right + 6;
    const leftCandidate = rect.left - menuWidth - 6;
    const preferredLeft = rightCandidate + menuWidth <= chatRect.right
      ? rightCandidate
      : leftCandidate >= chatRect.left
        ? leftCandidate
        : rect.left;
    const left = Math.max(chatRect.left + 8, Math.min(chatRect.right - menuWidth - 8, preferredLeft));
    const below = rect.bottom + 5;
    const above = rect.top - menu.offsetHeight - 5;
    const top = below + menu.offsetHeight <= window.innerHeight - 10 ? below : Math.max(10, above);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  async function copyMessageText(message) {
    const value = message.text_content || message.transcription || "";
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch (_) {
      const helper = document.createElement("textarea");
      helper.value = value;
      document.body.appendChild(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
    toast("تم نسخ نص الرسالة");
  }

  async function deleteMessage(message, scope = "local") {
    if (scope === "local" && !window.confirm("حذف الرسالة من صندوق Finora فقط؟")) return;
    try {
      const data = await api(`/ai-sales/api/messages/${message.id}${scope === "everyone" ? "?scope=everyone" : ""}`, { method: "DELETE" });
      replaceMessage(message.id, data.message);
      toast("تم حذف الرسالة من الصندوق");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function handleMessageAction(action) {
    const message = state.messages.find(item => String(item.id) === String(state.actionMessageId));
    closeMessageActions();
    if (!message) return;
    if (action === "copy") await copyMessageText(message);
    else if (action === "edit") startEditing(message);
    else if (action === "correct") startEditing(message, { correction: true });
    else if (action === "delete-local") await deleteMessage(message, "local");
    else if (action === "delete-everyone") await deleteMessage(message, "everyone");
  }

  function resizeComposer() {
    const textarea = $("messageInput");
    textarea.style.height = "44px";
    textarea.style.height = Math.min(textarea.scrollHeight, 132) + "px";
  }

  async function legacySendMessage(event) {
    event.preventDefault();
    if (!state.activeId || state.activeConversation?.status === "closed") return;
    const textarea = $("messageInput");
    const text = textarea.value.trim();
    if (!text) return;
    const temporaryId = `pending-${Date.now()}`;
    const pendingMessage = {
      id: temporaryId,
      conversation_id: state.activeId,
      direction: "outbound",
      sender_type: "employee",
      message_type: "text",
      text_content: text,
      status: "queued",
      created_at: new Date().toISOString(),
      _pending: true,
    };
    textarea.value = "";
    resizeComposer();
    $("sendBtn").disabled = true;
    appendMessages([pendingMessage]);
    scrollMessages({ smooth: true });
    try {
      const data = await api(`/ai-sales/api/conversations/${state.activeId}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const index = state.messages.findIndex(message => message.id === temporaryId);
      if (index >= 0) state.messages[index] = data.message;
      renderMessages();
      scrollMessages();
      await Promise.all([loadConversations({ silent: true }), loadOverview()]);
      state.activeConversation.human_takeover = true;
      state.activeConversation.ai_enabled = false;
      state.activeConversation.status = "human_active";
      updateChatHeader();
      renderContact();
    } catch (error) {
      const pending = state.messages.find(message => message.id === temporaryId);
      if (pending) {
        pending._pending = false;
        pending.status = "failed";
        pending.failure_message = error.message;
      }
      renderMessages();
      scrollMessages();
      toast(error.message, "error");
    } finally {
      $("sendBtn").disabled = state.activeConversation?.status === "closed";
      textarea.focus();
    }
  }

  async function sendMessage(event) {
    event.preventDefault();
    if (!state.activeId || state.activeConversation?.status === "closed") return;
    const textarea = $("messageInput");
    const text = textarea.value.trim();

    if (state.editingMessageId) {
      if (!text) {
        toast("اكتب نص الرسالة", "error");
        return;
      }
      const messageId = state.editingMessageId;
      $("sendBtn").disabled = true;
      try {
        const data = await api(`/ai-sales/api/messages/${messageId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        replaceMessage(messageId, data.message);
        cancelEditing();
        toast("تم تعديل الرسالة وإعادة إرسالها");
        await loadConversations({ silent: true });
      } catch (error) {
        if (error.data?.message) replaceMessage(messageId, error.data.message);
        toast(error.message, "error");
      } finally {
        $("sendBtn").disabled = state.activeConversation?.status === "closed";
      }
      return;
    }

    const draft = state.mediaDraft;
    if (!text && !draft) return;
    const temporaryId = `pending-${Date.now()}`;
    const pendingMessage = {
      id: temporaryId,
      conversation_id: state.activeId,
      direction: "outbound",
      sender_type: "employee",
      message_type: draft?.kind || "text",
      text_content: text,
      media_url: draft?.previewUrl || null,
      original_filename: draft?.file?.name || null,
      file_size: draft?.file?.size || null,
      status: "queued",
      created_at: new Date().toISOString(),
      _pending: true,
    };
    textarea.value = "";
    resizeComposer();
    $("sendBtn").disabled = true;
    appendMessages([pendingMessage]);
    scrollMessages({ smooth: true });

    try {
      let data;
      if (draft) {
        const form = new FormData();
        form.append("file", draft.file);
        form.append("caption", text);
        if (draft.voiceNote) form.append("voice_note", "true");
        data = await api(`/ai-sales/api/conversations/${state.activeId}/send-media`, { method: "POST", body: form });
      } else {
        data = await api(`/ai-sales/api/conversations/${state.activeId}/send`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
      }
      replaceMessage(temporaryId, data.message);
      if (draft) clearMediaDraft();
      if (!state.editingMessageId) $("editingBar").hidden = true;
      await Promise.all([loadConversations({ silent: true }), loadOverview()]);
      state.activeConversation.human_takeover = true;
      state.activeConversation.ai_enabled = false;
      state.activeConversation.status = "human_active";
      updateChatHeader();
      renderContact();
      scrollMessages();
    } catch (error) {
      const failed = error.data?.message || state.messages.find(message => message.id === temporaryId);
      if (failed) {
        failed._pending = false;
        failed.status = "failed";
        failed.failure_message = error.message;
        replaceMessage(temporaryId, failed);
      }
      if (!textarea.value) textarea.value = text;
      resizeComposer();
      toast(error.message, "error");
    } finally {
      $("sendBtn").disabled = state.activeConversation?.status === "closed";
      textarea.focus();
    }
  }

  async function simulate() {
    const text = window.prompt("اكتب رسالة زبون لتجربة موظف المبيعات:", "عندكم شاشة 55 بحدود 300 ألف؟");
    if (!text) return;
    toast("جاري تشغيل التجربة...");
    try {
      const data = await api("/ai-sales/api/training-chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      await Promise.all([loadConversations({ silent: true }), loadOverview()]);
      await openConversation(data.conversation.id);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function trainingProductOptions(selectedId = "") {
    const selected = String(selectedId || "");
    return `<option value="">اختر المنتج</option>${state.products.map(product => `
      <option value="${escapeHtml(product.id)}" ${String(product.id) === selected ? "selected" : ""}>${escapeHtml(product.name || product.sku || product.id)}</option>
    `).join("")}`;
  }

  async function ensureTrainingProducts() {
    if (state.products.length) return;
    const data = await api("/ai-sales/api/products?limit=150");
    state.products = data.products || [];
  }

  async function submitTrainingFeedback(messageId, rating, panel = null) {
    const message = state.messages.find(item => String(item.id) === String(messageId));
    const training = message?.training || {};
    let correctedReply = "";
    let productId = training.product_id || "";
    if (panel) {
      correctedReply = panel.querySelector("[data-training-correction]")?.value?.trim() || "";
      productId = panel.querySelector("[data-training-product]")?.value || productId;
    }
    await api("/ai-sales/api/training-feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message_id: messageId,
        rating,
        product_id: productId || null,
        corrected_reply: correctedReply,
      }),
    });
    toast(rating === "like" ? "تم اعتماد الرد للتدريب" : "تم حفظ التصحيح للتدريب");
    if (state.activeId) await openConversation(state.activeId, { updateHistory: false, preserveScroll: true });
  }

  async function showTrainingCorrection(messageId) {
    await ensureTrainingProducts();
    const message = state.messages.find(item => String(item.id) === String(messageId));
    const training = message?.training || {};
    const actions = document.querySelector(`[data-training-actions="${CSS.escape(String(messageId))}"]`);
    if (!actions) return;
    actions.innerHTML = `
      <div class="sales-ai-training-correction">
        <select data-training-product>${trainingProductOptions(training.product_id || "")}</select>
        <textarea data-training-correction rows="3" placeholder="شلون المفروض يجاوب؟ مثال: الزبون سأل على 7 قدم، جاوبه بهالطريقة وعلى هذا المنتج"></textarea>
        <div>
          <button type="button" class="sales-ai-training-like" data-training-save="${escapeHtml(messageId)}"><i class="fa-solid fa-floppy-disk"></i>حفظ التصحيح</button>
          <button type="button" class="sales-ai-training-dislike" data-training-cancel="${escapeHtml(messageId)}">إلغاء</button>
        </div>
      </div>`;
  }

  function openOverlay(id) {
    $(id).hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeOverlay(id) {
    $(id).hidden = true;
    if (!$("settingsDrawer") || $("settingsDrawer").hidden) document.body.style.overflow = "";
  }

  function renderChannelSummary(channel) {
    const stateValue = channel.connection_status || "draft";
    const stateLabel = { draft: "الإعداد غير مكتمل", ready: "جاهز للتحقق", verified: "Webhook متحقق", connected: "متصل", auth_expired: "انتهت صلاحية الرمز", error: "خطأ بالاتصال" }[stateValue] || stateValue;
    const item = (label, ok, value = "") => `<div class="sales-ai-channel-state ${ok ? "ok" : "missing"}"><span>${label}</span><strong>${ok ? "محفوظ" : "مطلوب"}${value ? " · " + escapeHtml(value) : ""}</strong></div>`;
    const verify = channel.verify_token ? `<strong>Verify Token للنسخ إلى Meta</strong><code>${escapeHtml(channel.verify_token)}</code>` : "";
    const error = channel.last_error ? `<div class="sales-ai-channel-state missing"><span>آخر خطأ</span><strong>${escapeHtml(channel.last_error)}</strong></div>` : "";
    $("channelSummary").innerHTML = `<div class="sales-ai-channel-summary"><div class="sales-ai-channel-grid">${item("حالة القناة", !["draft", "auth_expired", "error"].includes(stateValue), stateLabel)}${item("Phone Number ID", Boolean(channel.phone_number_id))}${item("Access Token", Boolean(channel.has_access_token))}${item("App Secret", Boolean(channel.has_app_secret))}${item("Verify Token", Boolean(channel.has_verify_token))}${item("تشغيل القناة", Boolean(channel.is_active), channel.is_active ? "فعال" : "متوقف")}</div><strong>Webhook URL</strong><code>${escapeHtml(channel.webhook_url || "يظهر بعد أول حفظ")}</code>${verify}${error}</div>`;
    $("channelTokenSaved").classList.toggle("show", Boolean(channel.has_access_token));
    $("channelSecretSaved").classList.toggle("show", Boolean(channel.has_app_secret));
    $("channelVerifySaved").classList.toggle("show", Boolean(channel.has_verify_token));
    renderCallingState(channel);
  }

  function renderCallingState(channel, result = null) {
    const badge = $("channelCallingState");
    if (!badge) return;
    const settings = result?.calling || channel?.calling_settings || {};
    const status = String(result?.calling_status || settings.status || channel?.calling_status || "unknown").toLowerCase();
    badge.className = "sales-ai-calling-state unknown";
    if (status === "auth_expired") {
      badge.textContent = "التوكن منتهي";
      badge.className = "sales-ai-calling-state blocked";
    } else if (status === "enabled") {
      const mediaReady = result?.ready_for_media || String(settings.sip_status || "").toUpperCase() === "ENABLED";
      badge.textContent = mediaReady ? "مفعلة وجاهزة للصوت" : "مفعلة في Meta · بوابة الصوت ناقصة";
      badge.className = `sales-ai-calling-state ${mediaReady ? "ready" : "pending"}`;
    } else if (status === "disabled") {
      badge.textContent = "غير مفعلة في Meta";
      badge.className = "sales-ai-calling-state pending";
    } else if (status === "error") {
      badge.textContent = "فشل الفحص";
      badge.className = "sales-ai-calling-state blocked";
    } else {
      badge.textContent = channel?.calling_last_checked_at ? "تحتاج إعادة فحص" : "لم يتم الفحص";
    }
  }

  async function checkCallingReadiness() {
    const channelId = Number($("channelId").value || 0);
    if (!channelId) {
      toast("احفظ قناة واتساب أولاً", "error");
      return;
    }
    const button = $("checkCallingBtn");
    button.disabled = true;
    button.classList.add("loading");
    try {
      const data = await api(`/ai-sales/api/channels/${channelId}/calling`);
      renderCallingState(state.channels.find(item => Number(item.id) === channelId), data);
      toast(data.ready_for_media ? "رقم واتساب جاهز لمسار المكالمات" : "تم الفحص؛ راجع حالة بوابة الصوت");
      await loadSettings();
    } catch (error) {
      renderCallingState(state.channels.find(item => Number(item.id) === channelId), error.data || { calling_status: "error" });
      toast(error.data?.meta_error_code === 190 ? "توكن واتساب منتهي أو غير صالح؛ حدّثه ثم أعد الفحص" : error.message, "error");
    } finally {
      button.disabled = false;
      button.classList.remove("loading");
    }
  }

  function switchMetaTab(tab) {
    state.metaInternalTab = tab === "pages" ? "pages" : "general";
    document.querySelectorAll("[data-meta-tab]").forEach(button => {
      const active = button.dataset.metaTab === state.metaInternalTab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll("[data-meta-panel]").forEach(panel => {
      panel.hidden = panel.dataset.metaPanel !== state.metaInternalTab;
    });
  }

  function updateMetaSelectionSummary() {
    const visible = [...document.querySelectorAll("[data-meta-select]")];
    const selectedVisible = visible.filter(input => input.checked).length;
    const selectedTotal = state.metaSelected.size;
    $("metaSelectedCount").textContent = selectedTotal
      ? `تم تحديد ${number(selectedTotal)} صفحة`
      : "لم يتم تحديد صفحات";
    $("metaSelectAll").checked = Boolean(visible.length && selectedVisible === visible.length);
    $("metaSelectAll").indeterminate = Boolean(selectedVisible && selectedVisible < visible.length);
    document.querySelectorAll("[data-meta-bulk]").forEach(button => { button.disabled = selectedTotal === 0; });
  }

  function renderMetaSettings() {
    const connector = state.channels.find(channel => channel.channel_type === "meta");
    const pages = state.channels.filter(channel => ["messenger", "instagram"].includes(channel.channel_type) && channel.connection_status !== "removed");
    const pageIds = new Set(pages.map(channel => channel.id));
    state.metaSelected.forEach(id => { if (!pageIds.has(id)) state.metaSelected.delete(id); });

    if (connector) {
      $("metaConnectorId").value = connector.id;
      $("metaName").value = connector.name || "Meta Super Max";
      $("metaAppId").value = connector.external_account_id || "";
      $("metaActive").checked = Boolean(connector.is_active);
      $("metaSecretSaved").classList.toggle("show", Boolean(connector.has_app_secret));
      $("metaVerifySaved").classList.toggle("show", Boolean(connector.has_verify_token));
      const connectedPages = pages.filter(channel => channel.connection_status === "connected").length;
      const connectorError = connector.last_error ? `<div class="sales-ai-channel-state missing"><span>آخر خطأ</span><strong>${escapeHtml(connector.last_error)}</strong></div>` : "";
      $("metaSummary").innerHTML = `<div class="sales-ai-channel-summary"><div class="sales-ai-channel-grid"><div class="sales-ai-channel-state ${connector.has_app_secret ? "ok" : "missing"}"><span>Meta App Secret</span><strong>${connector.has_app_secret ? "محفوظ ومشفّر" : "مطلوب"}</strong></div><div class="sales-ai-channel-state ${connector.has_verify_token ? "ok" : "missing"}"><span>Verify Token</span><strong>${connector.has_verify_token ? "محفوظ ومشفّر" : "يُنشأ عند الحفظ"}</strong></div><div class="sales-ai-channel-state ${connector.is_active ? "ok" : "missing"}"><span>استقبال الرسائل</span><strong>${connector.is_active ? "فعال" : "متوقف"}</strong></div><div class="sales-ai-channel-state ${connectedPages ? "ok" : "missing"}"><span>الصفحات المتصلة</span><strong>${number(connectedPages)} من ${number(pages.length)}</strong></div></div><strong>Webhook URL</strong><code>${escapeHtml(connector.webhook_url || "")}</code>${connectorError}</div>`;
    } else {
      $("metaSummary").innerHTML = '<div class="sales-ai-meta-empty">احفظ إعدادات تطبيق Meta أولاً، ثم انتقل إلى تبويب الصفحات لاستيرادها.</div>';
    }

    $("metaPageCount").textContent = number(pages.length);
    const query = ($("metaPageSearch").value || "").trim().toLowerCase();
    const platform = $("metaPagePlatform").value || "all";
    const status = $("metaPageStatus").value || "all";
    const visiblePages = pages.filter(channel => {
      const searchable = [channel.name, channel.platform_username, channel.external_account_id, channel.page_id].filter(Boolean).join(" ").toLowerCase();
      if (query && !searchable.includes(query)) return false;
      if (platform !== "all" && channel.channel_type !== platform) return false;
      if (status === "active" && !channel.is_active) return false;
      if (status === "inactive" && channel.is_active) return false;
      if (status === "ai" && channel.reply_mode !== "ai") return false;
      if (status === "inbox" && channel.reply_mode !== "inbox") return false;
      if (status === "auth" && !["auth_expired", "unavailable", "error"].includes(channel.connection_status)) return false;
      return true;
    });
    const employeeOptions = '<option value="">بدون موظف محدد</option>' + state.employees.map(employee => `<option value="${employee.id}">${escapeHtml(employee.name)}</option>`).join("");

    $("metaPages").innerHTML = visiblePages.map(channel => {
      const replyMode = ["ai", "inbox", "employee"].includes(channel.reply_mode) ? channel.reply_mode : "inbox";
      const statusLabel = ({ connected: "متصلة", auth_expired: "التوكن منتهي", unavailable: "غير متاحة", error: "خطأ" })[channel.connection_status] || "قيد الإعداد";
      const statusClass = channel.connection_status === "connected" ? "ok" : "warning";
      return `
      <article class="sales-ai-meta-page" data-meta-page="${channel.id}">
        <label class="sales-ai-meta-select" title="تحديد الصفحة"><input type="checkbox" data-meta-select="${channel.id}" ${state.metaSelected.has(channel.id) ? "checked" : ""}><span></span></label>
        <div class="sales-ai-meta-head">
          ${channel.profile_picture_url ? `<img src="${escapeHtml(channel.profile_picture_url)}" alt="">` : `<span class="sales-ai-meta-avatar"><i class="${channelIcon(channel.channel_type)}"></i></span>`}
          <div><strong>${escapeHtml(channel.name)}</strong><small><i class="${channelIcon(channel.channel_type)}"></i> ${channel.channel_type === "instagram" ? "Instagram" : "Messenger"} · ID ${escapeHtml(channel.external_account_id || channel.page_id || "-")}</small></div>
          <span class="sales-ai-meta-status ${statusClass}">${statusLabel}</span>
        </div>
        <div class="sales-ai-meta-controls">
          <div><label>طريقة التعامل</label><select data-meta-mode><option value="inbox" ${replyMode === "inbox" ? "selected" : ""}>استقبال فقط</option><option value="ai" ${replyMode === "ai" ? "selected" : ""}>الذكاء يرد</option><option value="employee" ${replyMode === "employee" ? "selected" : ""}>تحويل لموظف</option></select></div>
          <div data-meta-employee-wrap><label>موظف الصفحة</label><select data-meta-employee>${employeeOptions}</select><small>يشاهد هذه الصفحة ومحادثاتها فقط، بغض النظر عن طريقة الرد.</small></div>
          <label class="sales-ai-switch-row"><span><strong>فعال</strong><small>استقبال الرسائل</small></span><input data-meta-active type="checkbox" ${channel.is_active ? "checked" : ""}><i></i></label>
        </div>
        <div class="sales-ai-meta-buttons"><button class="sales-ai-btn primary" type="button" data-meta-save="${channel.id}"><i class="fa-solid fa-floppy-disk"></i>حفظ</button><button class="sales-ai-btn subtle" type="button" data-meta-import="${channel.id}"><i class="fa-solid fa-download"></i>جلب المحادثات</button><button class="sales-ai-icon-btn danger" type="button" data-meta-delete="${channel.id}" title="إزالة الصفحة من Finora"><i class="fa-solid fa-trash"></i></button></div>
      </article>`;
    }).join("") || '<div class="sales-ai-meta-empty">لا توجد صفحات مطابقة. غيّر البحث أو الفلاتر، أو استورد الصفحات بتوكن مؤقت.</div>';

    visiblePages.forEach(channel => {
      const card = document.querySelector(`[data-meta-page="${channel.id}"]`);
      if (!card) return;
      card.querySelector("[data-meta-employee]").value = channel.default_employee_id || "";
      card.querySelector("[data-meta-select]").addEventListener("change", event => {
        if (event.target.checked) state.metaSelected.add(channel.id);
        else state.metaSelected.delete(channel.id);
        updateMetaSelectionSummary();
      });
    });
    updateMetaSelectionSummary();
    const aiPages = pages.filter(channel => channel.is_active && channel.reply_mode === "ai").length;
    const stopButton = $("stopMetaAiBtn");
    if (stopButton) {
      stopButton.disabled = aiPages === 0;
      stopButton.querySelector("span").textContent = aiPages ? `إيقاف الذكاء عن كل الصفحات (${number(aiPages)})` : "الذكاء متوقف عن كل الصفحات";
    }
    switchMetaTab(state.metaInternalTab);
  }

  async function loadSettings() {
    if (!canManage) return;
    const [profileData, channelData, productData, employeeData, learningData] = await Promise.all([
      api("/ai-sales/api/profile"),
      api("/ai-sales/api/channels"),
      api("/ai-sales/api/products"),
      api("/ai-sales/api/employees"),
      api("/ai-sales/api/learning"),
    ]);
    state.channels = channelData.channels || [];
    state.employees = employeeData.employees || [];
    state.products = productData.products || [];
    const profile = profileData.profile;
    $("agentName").value = profile.name || "";
    $("agentModel").value = profile.text_model || "";
    $("agentTtsModel").value = profile.tts_model || "gpt-4o-mini-tts";
    $("agentTranscribeModel").value = profile.transcription_model || "gpt-4o-mini-transcribe";
    $("agentRealtimeModel").value = profile.realtime_model || "gpt-realtime-2.1";
    $("agentDialect").value = profile.dialect || "iraqi";
    $("agentStyle").value = profile.sales_style || "consultative";
    const intelligence = profile.intelligence_level || "expert";
    const intelligenceInput = document.querySelector(`input[name="agentIntelligence"][value="${intelligence}"]`);
    if (intelligenceInput) intelligenceInput.checked = true;
    $("agentPersuasion").value = profile.persuasion_style || "balanced";
    $("agentMaxProducts").value = String(profile.max_products || 3);
    $("agentLength").value = profile.max_reply_length || 650;
    $("agentHandoff").value = profile.handoff_threshold || 45;
    $("agentContextMessages").value = profile.max_context_messages || 18;
    $("agentResponseDelay").value = profile.ai_response_delay_ms || 0;
    $("agentMaxAudio").value = profile.max_audio_size_mb || 25;
    $("agentHumanPause").value = profile.human_takeover_minutes || 30;
    $("agentInstructions").value = profile.system_instructions || "";
    $("agentVoiceInstructions").value = profile.voice_instructions || "";
    $("agentVoiceEnabled").checked = Boolean(profile.voice_enabled);
    $("agentVoiceMode").value = profile.voice_reply_mode || "match_customer";
    $("agentVoice").value = profile.voice_name || "marin";
    $("agentAudioFormat").value = profile.audio_format || "opus";
    $("agentAudioQuality").value = profile.audio_quality || "professional";
    $("agentVoiceSpeed").value = String(profile.voice_speed || 0.96);
    $("agentVoiceSpeedValue").textContent = `${Number(profile.voice_speed || 0.96).toFixed(2)}×`;
    $("agentAutoEscalation").checked = Boolean(profile.auto_escalation);
    $("agentActive").checked = Boolean(profile.is_active);
    updateIntelligenceDescription();
    const productOptions = state.products.map(product => `<option value="${product.id}">${escapeHtml(product.name)} · معرفة ${number(product.knowledge_score)}%</option>`).join("");
    $("mediaProduct").innerHTML = '<option value="">اختر المنتج</option>' + productOptions;
    $("knowledgeProduct").innerHTML = '<option value="">اختر المنتج</option>' + productOptions;
    $("problemProduct").innerHTML = '<option value="">مشكلة عامة</option>' + state.products.map(product => `<option value="${product.id}">${escapeHtml(product.name)}</option>`).join("");
    $("learningEnabled").checked = profile.continuous_learning_enabled !== false;
    $("learningFromEmployees").checked = profile.learn_from_employee_replies !== false;
    $("learningMinQuality").value = String(profile.learning_min_quality || 76);
    $("learningMinQualityValue").textContent = `${number(profile.learning_min_quality || 76)}%`;
    applyLearningData(learningData);
    const whatsapp = state.channels.find(channel => channel.channel_type === "whatsapp" && channel.name !== "قناة الاختبار المحلية");
    if (whatsapp) {
      $("channelId").value = whatsapp.id;
      $("channelName").value = whatsapp.name || "";
      $("channelPhone").value = whatsapp.phone_number || "";
      $("channelPhoneId").value = whatsapp.phone_number_id || "";
      $("channelWaba").value = whatsapp.waba_id || "";
      $("channelActive").checked = Boolean(whatsapp.is_active);
      renderChannelSummary(whatsapp);
    }
    renderMetaSettings();
    await loadProductMedia();
    state.settingsLoaded = true;
    checkOpenAiHealth().catch(() => {});
  }

  function updateIntelligenceDescription() {
    const selected = document.querySelector('input[name="agentIntelligence"]:checked')?.value || "expert";
    $("agentLevelDescription").textContent = intelligenceDescriptions[selected] || intelligenceDescriptions.expert;
  }

  async function openSettings() {
    const drawer = $("settingsDrawer");
    drawer.hidden = false;
    document.body.style.overflow = "hidden";
    resetSettingsScroll();
    if (!state.settingsLoaded) {
      try {
        await loadSettings();
      } catch (error) {
        toast(error.message, "error");
      }
    }
    resetSettingsScroll();
  }

  function closeSettings() {
    $("settingsDrawer").hidden = true;
    document.body.style.overflow = "";
  }

  function switchSettingsTab(tabName) {
    document.querySelectorAll("[data-tab]").forEach(button => button.classList.toggle("active", button.dataset.tab === tabName));
    document.querySelectorAll("[data-pane]").forEach(pane => { pane.hidden = pane.dataset.pane !== tabName; });
    resetSettingsScroll();
    if (tabName === "media") loadProductMedia().catch(error => toast(error.message, "error"));
    if (tabName === "knowledge") loadProductKnowledge().catch(error => toast(error.message, "error"));
    if (tabName === "learning") loadLearning().catch(error => toast(error.message, "error"));
  }

  function resetSettingsScroll() {
    const drawer = $("settingsDrawer");
    const dialog = drawer?.querySelector(".sales-ai-settings-dialog");
    const layout = drawer?.querySelector(".sales-ai-settings-layout");
    const content = drawer?.querySelector(".sales-ai-settings-content");
    if (dialog) dialog.scrollTop = 0;
    if (layout) layout.scrollTop = 0;
    if (content) content.scrollTop = 0;
  }

  function renderKnowledgeScore(knowledge) {
    const score = Math.max(0, Math.min(Number(knowledge.knowledge_score || 0), 100));
    $("knowledgeScore").textContent = `${number(score)}%`;
    $("knowledgeMeter").style.width = `${score}%`;
    $("knowledgeMeter").dataset.level = score >= 75 ? "good" : score >= 45 ? "medium" : "low";
    $("knowledgeMissing").textContent = (knowledge.missing || []).length
      ? `ناقص: ${(knowledge.missing || []).join("، ")}`
      : "المعرفة الأساسية لهذا المنتج مكتملة.";
  }

  function updateKnowledgeVisibilityButton() {
    const allowRecommendation = $("knowledgeAllowRecommendation")?.checked !== false;
    const panel = $("knowledgeVisibilityPanel");
    const title = $("knowledgeVisibilityTitle");
    const text = $("knowledgeVisibilityText");
    const button = $("knowledgeVisibilityButton");
    if (!panel || !title || !text || !button) return;
    panel.classList.toggle("is-hidden", !allowRecommendation);
    button.classList.toggle("danger", allowRecommendation);
    button.classList.toggle("primary", !allowRecommendation);
    button.innerHTML = allowRecommendation
      ? '<i class="fa-solid fa-eye-slash"></i><span>إخفاء عن الزبائن</span>'
      : '<i class="fa-solid fa-eye"></i><span>إظهار للزبائن</span>';
    title.textContent = allowRecommendation ? "يظهر للزبائن" : "مخفي عن الزبائن";
    text.textContent = allowRecommendation
      ? "الذكاء يكدر يقترح هذا المنتج ويرسل صوره وفيديوهاته."
      : "الذكاء ما راح يعرض هذا المنتج للزبون، وإذا انطلب يحاول يقترح بديل مناسب.";
  }

  async function searchKnowledgeProducts() {
    const term = $("knowledgeSearch").value.trim();
    const currentId = Number($("knowledgeProduct").value || 0);
    const data = await api(`/ai-sales/api/products?limit=150${term ? `&q=${encodeURIComponent(term)}` : ""}`);
    const products = data.products || [];
    $("knowledgeProduct").innerHTML = '<option value="">اختر المنتج</option>' + products.map(product =>
      `<option value="${product.id}">${escapeHtml(product.name)} · معرفة ${number(product.knowledge_score)}%</option>`
    ).join("");
    if (currentId && products.some(product => Number(product.id) === currentId)) {
      $("knowledgeProduct").value = String(currentId);
    } else if (currentId) {
      $("knowledgeEmpty").hidden = false;
      $("knowledgeEditor").hidden = true;
    }
  }

  async function loadProductKnowledge() {
    if (!canManage) return;
    const productId = Number($("knowledgeProduct").value || 0);
    $("knowledgeEmpty").hidden = Boolean(productId);
    $("knowledgeEditor").hidden = !productId;
    if (!productId) return;
    const data = await api(`/ai-sales/api/product-knowledge/${productId}`);
    const knowledge = data.knowledge || {};
    $("knowledgeMarketingName").value = knowledge.marketing_name || "";
    $("knowledgeAliases").value = (knowledge.aliases || []).join("\n");
    $("knowledgeDescription").value = knowledge.description || "";
    $("knowledgeSellingPoints").value = (knowledge.selling_points || []).join("\n");
    $("knowledgeIdealFor").value = (knowledge.ideal_for || []).join("\n");
    $("knowledgeWarranty").value = knowledge.warranty || "";
    $("knowledgeDelivery").value = knowledge.delivery || "";
    $("knowledgeColors").value = (knowledge.colors || []).join("، ");
    $("knowledgeWidth").value = knowledge.width_cm ?? "";
    $("knowledgeHeight").value = knowledge.height_cm ?? "";
    $("knowledgeDepth").value = knowledge.depth_cm ?? "";
    $("knowledgeObjections").value = Object.entries(knowledge.objection_guidance || {}).map(([key, value]) => `${key}: ${value}`).join("\n");
    $("knowledgeNotes").value = knowledge.sales_notes || "";
    $("knowledgeAllowPrice").checked = knowledge.allow_price !== false;
    $("knowledgeAllowRecommendation").checked = knowledge.allow_recommendation !== false;
    $("knowledgeActive").checked = knowledge.is_active !== false;
    renderKnowledgeScore(knowledge);
    updateKnowledgeVisibilityButton();
  }

  async function saveProductKnowledge(event) {
    if (event && typeof event.preventDefault === "function") event.preventDefault();
    const productId = Number($("knowledgeProduct").value || 0);
    if (!productId) {
      toast("اختر منتجاً أولاً", "error");
      return;
    }
    try {
      const data = await api(`/ai-sales/api/product-knowledge/${productId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          marketing_name: $("knowledgeMarketingName").value,
          aliases: $("knowledgeAliases").value,
          description: $("knowledgeDescription").value,
          selling_points: $("knowledgeSellingPoints").value,
          ideal_for: $("knowledgeIdealFor").value,
          warranty: $("knowledgeWarranty").value,
          delivery: $("knowledgeDelivery").value,
          colors: $("knowledgeColors").value,
          width_cm: $("knowledgeWidth").value,
          height_cm: $("knowledgeHeight").value,
          depth_cm: $("knowledgeDepth").value,
          objections: $("knowledgeObjections").value,
          sales_notes: $("knowledgeNotes").value,
          allow_price: $("knowledgeAllowPrice").checked,
          allow_recommendation: $("knowledgeAllowRecommendation").checked,
          is_active: $("knowledgeActive").checked,
        }),
      });
      renderKnowledgeScore(data.knowledge || {});
      if (data.knowledge) {
        $("knowledgeAllowRecommendation").checked = data.knowledge.allow_recommendation !== false;
        $("knowledgeActive").checked = data.knowledge.is_active !== false;
      }
      updateKnowledgeVisibilityButton();
      const product = state.products.find(item => Number(item.id) === productId);
      if (product) product.knowledge_score = Number(data.knowledge?.knowledge_score || 0);
      toast("تم حفظ معرفة المنتج");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function toggleProductRecommendationVisibility() {
    const productId = Number($("knowledgeProduct").value || 0);
    if (!productId) {
      toast("اختر منتجاً أولاً", "error");
      return;
    }
    $("knowledgeAllowRecommendation").checked = !$("knowledgeAllowRecommendation").checked;
    updateKnowledgeVisibilityButton();
    await saveProductKnowledge();
  }

  function applyLearningData(data = {}) {
    state.learningEntries = data.entries || [];
    state.learningImports = data.imports || [];
    state.learningStats = data.stats || {};
    $("learningApproved").textContent = number(state.learningStats.approved);
    $("learningContinuous").textContent = number(state.learningStats.continuous);
    $("learningProblems").textContent = number(state.learningStats.problems);
    $("learningExcelSources").textContent = number(state.learningStats.excel_sources);
    renderProblemEntries();
    renderLearningImports();
  }

  async function loadLearning() {
    if (!canManage) return;
    applyLearningData(await api("/ai-sales/api/learning"));
  }

  function renderProblemEntries() {
    const term = normalizeForSearch($("problemSearch")?.value || "");
    const entries = state.learningEntries.filter(entry => {
      if (!term) return true;
      return normalizeForSearch(`${entry.problem} ${entry.solution} ${entry.product_name} ${(entry.keywords || []).join(" ")}`).includes(term);
    });
    $("problemList").innerHTML = entries.map(entry => `
      <article class="sales-ai-problem-item ${entry.is_active ? "" : "inactive"}">
        <div class="sales-ai-problem-main">
          <strong>${escapeHtml(entry.problem)}</strong>
          <p>${escapeHtml(entry.solution)}</p>
          <span><i class="fa-solid ${entry.source_type === "excel" ? "fa-file-excel" : "fa-pen"}"></i>${escapeHtml(entry.source_type === "excel" ? entry.source_name || "Excel" : "إدخال يدوي")}${entry.product_name ? ` · ${escapeHtml(entry.product_name)}` : " · حل عام"}</span>
        </div>
        <div class="sales-ai-problem-actions">
          <button type="button" data-problem-edit="${entry.id}" title="تعديل"><i class="fa-solid fa-pen"></i></button>
          <button class="danger" type="button" data-problem-delete="${entry.id}" title="حذف"><i class="fa-solid fa-trash"></i></button>
        </div>
      </article>`).join("") || '<div class="sales-ai-meta-empty">لا توجد مشاكل وحلول مطابقة.</div>';
  }

  function renderLearningImports() {
    $("learningImportHistory").innerHTML = state.learningImports.slice(0, 5).map(item => `
      <div class="sales-ai-import-row ${item.status === "failed" ? "failed" : ""}">
        <i class="fa-solid fa-file-excel"></i>
        <span><strong>${escapeHtml(item.file_name)}</strong><small>${number(item.product_rows)} منتج · ${number(item.problem_rows)} مشكلة وحل${item.error_count ? ` · ${number(item.error_count)} ملاحظة` : ""}</small></span>
        <time>${time(item.completed_at || item.created_at)}</time>
      </div>`).join("") || '<div class="sales-ai-meta-empty">لم يُستورد ملف تعلم بعد.</div>';
  }

  function resetProblemForm() {
    $("problemId").value = "";
    $("problemProduct").value = "";
    $("problemText").value = "";
    $("problemKeywords").value = "";
    $("problemQuestions").value = "";
    $("problemSolution").value = "";
    $("problemEscalation").value = "";
    $("problemActive").checked = true;
    $("cancelProblemEdit").hidden = true;
    $("problemSubmitLabel").textContent = "إضافة المشكلة والحل";
  }

  function editProblem(entryId) {
    const entry = state.learningEntries.find(item => Number(item.id) === Number(entryId));
    if (!entry) return;
    $("problemId").value = String(entry.id);
    $("problemProduct").value = entry.product_id || "";
    $("problemText").value = entry.problem || "";
    $("problemKeywords").value = (entry.keywords || []).join("، ");
    $("problemQuestions").value = (entry.diagnostic_questions || []).join("\n");
    $("problemSolution").value = entry.solution || "";
    $("problemEscalation").value = entry.escalation || "";
    $("problemActive").checked = entry.is_active !== false;
    $("cancelProblemEdit").hidden = false;
    $("problemSubmitLabel").textContent = "حفظ التعديل";
    $("problemText").focus();
  }

  async function saveProblem(event) {
    event.preventDefault();
    const entryId = Number($("problemId").value || 0);
    const url = entryId ? `/ai-sales/api/learning/problems/${entryId}` : "/ai-sales/api/learning/problems";
    try {
      await api(url, {
        method: entryId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: Number($("problemProduct").value || 0) || null,
          problem: $("problemText").value,
          keywords: $("problemKeywords").value,
          diagnostic_questions: $("problemQuestions").value,
          solution: $("problemSolution").value,
          escalation: $("problemEscalation").value,
          is_active: $("problemActive").checked,
        }),
      });
      resetProblemForm();
      await loadLearning();
      toast(entryId ? "تم تحديث المشكلة والحل" : "تمت إضافة المشكلة والحل");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteProblem(entryId) {
    if (!window.confirm("حذف هذه المشكلة والحل من معرفة الذكاء؟")) return;
    try {
      await api(`/ai-sales/api/learning/problems/${entryId}`, { method: "DELETE" });
      if (Number($("problemId").value || 0) === Number(entryId)) resetProblemForm();
      await loadLearning();
      toast("تم حذف المشكلة والحل");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function saveLearningSettings(event) {
    event.preventDefault();
    try {
      await api("/ai-sales/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          continuous_learning_enabled: $("learningEnabled").checked,
          learn_from_employee_replies: $("learningFromEmployees").checked,
          learning_min_quality: Number($("learningMinQuality").value || 76),
        }),
      });
      toast("تم حفظ إعدادات التعلم المستمر");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function scanEmployeeReplies() {
    const button = $("scanEmployeeRepliesBtn");
    button.disabled = true;
    try {
      const data = await api("/ai-sales/api/learning/scan-employee-replies", { method: "POST" });
      await loadLearning();
      toast(`تم فحص ${number(data.result?.scanned)} رد واعتماد ${number(data.result?.approved)} رد جديد`);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function importLearningWorkbook(event) {
    event.preventDefault();
    const file = $("learningExcelFile").files?.[0];
    if (!file) return;
    const button = event.submitter || event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    const form = new FormData();
    form.append("file", file);
    try {
      const data = await api("/ai-sales/api/learning/import", { method: "POST", body: form });
      $("learningExcelFile").value = "";
      await Promise.all([loadLearning(), searchKnowledgeProducts()]);
      toast(`تم تعلم ${number(data.import?.product_rows)} منتج و${number(data.import?.problem_rows)} مشكلة وحل`);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function saveAgent(event) {
    event.preventDefault();
    try {
      await api("/ai-sales/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: $("agentName").value,
          text_model: $("agentModel").value,
          tts_model: $("agentTtsModel").value,
          transcription_model: $("agentTranscribeModel").value,
          realtime_model: $("agentRealtimeModel").value,
          dialect: $("agentDialect").value,
          sales_style: $("agentStyle").value,
          intelligence_level: document.querySelector('input[name="agentIntelligence"]:checked')?.value || "expert",
          persuasion_style: $("agentPersuasion").value,
          max_products: Number($("agentMaxProducts").value),
          max_reply_length: Number($("agentLength").value),
          handoff_threshold: Number($("agentHandoff").value),
          max_context_messages: Number($("agentContextMessages").value),
          ai_response_delay_ms: Number($("agentResponseDelay").value),
          max_audio_size_mb: Number($("agentMaxAudio").value),
          human_takeover_minutes: Number($("agentHumanPause").value),
          system_instructions: $("agentInstructions").value,
          voice_instructions: $("agentVoiceInstructions").value,
          voice_enabled: $("agentVoiceEnabled").checked,
          voice_reply_mode: $("agentVoiceMode").value,
          voice_name: $("agentVoice").value,
          audio_format: $("agentAudioFormat").value,
          audio_quality: $("agentAudioQuality").value,
          voice_speed: Number($("agentVoiceSpeed").value),
          auto_escalation: $("agentAutoEscalation").checked,
          is_active: $("agentActive").checked,
        }),
      });
      toast("تم حفظ إعدادات الموظف الذكي");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function checkOpenAiHealth() {
    const status = $("agentOpenAiStatus");
    if (!status) return;
    status.className = "";
    status.textContent = "جاري فحص إعداد OpenAI...";
    try {
      const data = await api("/ai-sales/api/openai/health");
      status.className = data.configured ? "success" : "error";
      status.textContent = data.configured
        ? `OpenAI مضبوط · ${data.models.chat_model} · ${data.models.tts_model}`
        : "مفتاح OpenAI غير مضبوط على الخادم";
    } catch (error) {
      status.className = "error";
      status.textContent = error.message;
    }
  }

  async function testAgentSpeech() {
    const button = $("agentTtsTestBtn");
    const audio = $("agentTtsTestAudio");
    const status = $("agentOpenAiStatus");
    button.disabled = true;
    status.className = "";
    status.textContent = "جاري توليد عينة الصوت...";
    try {
      const data = await api("/ai-sales/api/openai/test-speech", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: $("agentTtsTestText").value,
          tts_model: $("agentTtsModel").value,
          voice: $("agentVoice").value,
          audio_format: $("agentAudioFormat").value,
          audio_quality: $("agentAudioQuality").value,
          voice_speed: Number($("agentVoiceSpeed").value),
          voice_instructions: $("agentVoiceInstructions").value,
        }),
      });
      audio.src = `${data.audio_url}?v=${Date.now()}`;
      audio.hidden = false;
      await audio.play().catch(() => {});
      status.className = "success";
      status.textContent = `نجحت التجربة خلال ${number(data.duration_ms)} ms · ${data.model} · ${data.voice}`;
    } catch (error) {
      status.className = "error";
      status.textContent = error.message;
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function saveChannel(event) {
    event.preventDefault();
    const payload = {
      id: Number($("channelId").value) || null,
      name: $("channelName").value,
      phone_number: $("channelPhone").value,
      phone_number_id: $("channelPhoneId").value,
      waba_id: $("channelWaba").value,
      is_active: $("channelActive").checked,
    };
    if ($("channelToken").value) payload.access_token = $("channelToken").value;
    if ($("channelSecret").value) payload.app_secret = $("channelSecret").value;
    if ($("channelVerify").value) payload.verify_token = $("channelVerify").value;
    try {
      const data = await api("/ai-sales/api/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      $("channelId").value = data.channel.id;
      $("channelToken").value = "";
      $("channelSecret").value = "";
      $("channelVerify").value = "";
      await loadSettings();
      toast("تم حفظ قناة واتساب وبقيت المفاتيح السرية محفوظة");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function saveMetaConnector(event) {
    event.preventDefault();
    const payload = {
      id: Number($("metaConnectorId").value) || null,
      channel_type: "meta",
      name: $("metaName").value || "Meta Super Max",
      external_account_id: $("metaAppId").value,
      is_active: $("metaActive").checked,
    };
    if ($("metaSecret").value) payload.app_secret = $("metaSecret").value;
    if ($("metaVerify").value) payload.verify_token = $("metaVerify").value;
    try {
      const data = await api("/ai-sales/api/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      $("metaConnectorId").value = data.channel.id;
      $("metaSecret").value = "";
      $("metaVerify").value = "";
      state.metaPausedUntil = 0;
      state.metaReconnectNotified = false;
      await loadSettings();
      toast("تم حفظ إعدادات تطبيق Meta والمفاتيح مشفّرة");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function connectMetaPage() {
    const connectorId = Number($("metaConnectorId").value);
    if (!connectorId) {
      toast("احفظ إعدادات تطبيق Meta أولاً", "error");
      switchMetaTab("general");
      return;
    }
    const pageToken = ($("metaPageToken").value || "").trim();
    if (!pageToken) {
      toast("الصق Page Access Token أولاً", "error");
      $("metaPageToken").focus();
      return;
    }
    const button = $("addMetaPageBtn");
    button.disabled = true;
    try {
      const data = await api("/ai-sales/api/meta/pages/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_id: connectorId, page_access_token: pageToken }),
      });
      $("metaPageToken").value = "";
      state.metaReconnectNotified = false;
      await loadSettings();
      switchMetaTab("pages");
      if (data.warning) {
        toast(data.warning, "error");
      } else {
        toast(data.created ? `تم ربط صفحة ${data.channel.name}` : `تم تحديث توكن صفحة ${data.channel.name}`);
      }
    } catch (error) {
      toast(error.message, "error");
    } finally {
      $("metaPageToken").value = "";
      button.disabled = false;
    }
  }

  async function bulkMetaPages(action) {
    const ids = [...state.metaSelected];
    if (!ids.length) return;
    try {
      const data = await api("/ai-sales/api/meta/pages/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, action }),
      });
      state.metaSelected.clear();
      await Promise.all([loadSettings(), loadConversations({ silent: true })]);
      toast(`تم تحديث ${number(data.pages_updated)} صفحة`);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteMetaPage(id) {
    const channel = state.channels.find(item => item.id === Number(id));
    if (!channel) return;
    if (!window.confirm(`إزالة «${channel.name}» من Finora؟ ستبقى المحادثات محفوظة ويمكن استيراد الصفحة مجدداً.`)) return;
    try {
      await api(`/ai-sales/api/meta/pages/${channel.id}`, { method: "DELETE" });
      state.metaSelected.delete(channel.id);
      await Promise.all([loadSettings(), loadConversations({ silent: true })]);
      toast("تمت إزالة الصفحة مع الاحتفاظ بسجل المحادثات");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function saveMetaPage(id) {
    const card = document.querySelector(`[data-meta-page="${id}"]`);
    const channel = state.channels.find(item => item.id === Number(id));
    if (!card || !channel) return;
    const replyMode = card.querySelector("[data-meta-mode]").value;
    const payload = {
      id: channel.id,
      channel_type: channel.channel_type,
      name: channel.name,
      is_active: card.querySelector("[data-meta-active]").checked,
      reply_mode: replyMode,
      default_employee_id: Number(card.querySelector("[data-meta-employee]").value) || null,
    };
    if (payload.reply_mode === "employee" && !payload.default_employee_id) {
      toast("اختر الموظف المسؤول، أو غيّر طريقة التعامل إلى استقبال فقط أو الذكاء", "error");
      card.querySelector("[data-meta-employee]").focus();
      return;
    }
    try {
      await api("/ai-sales/api/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await Promise.all([loadSettings(), loadConversations({ silent: true })]);
      toast("تم حفظ توجيه الصفحة");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function stopMetaAi() {
    const confirmed = window.confirm("سيتم إيقاف رد الذكاء عن جميع صفحات Meta مع استمرار استقبال الرسائل. هل تريد المتابعة؟");
    if (!confirmed) return;
    const button = $("stopMetaAiBtn");
    button.disabled = true;
    try {
      const data = await api("/ai-sales/api/meta/stop-ai", { method: "POST" });
      await Promise.all([loadSettings(), loadConversations({ silent: true }), loadOverview()]);
      if (state.activeId) await openConversation(state.activeId, { updateHistory: false, preserveScroll: true });
      toast(`تم إيقاف الذكاء، والرسائل مستمرة بالوصول من ${number(data.pages_updated)} صفحة`);
    } catch (error) {
      toast(error.message, "error");
      button.disabled = false;
    }
  }

  async function importMetaConversations(id) {
    try {
      const data = await api(`/ai-sales/api/meta/import-conversations/${id}`, { method: "POST" });
      await loadConversations({ silent: true });
      toast(`تم جلب ${number(data.messages_created)} رسالة داخل ${number(data.conversations_created)} محادثة جديدة`);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function loadProductMedia() {
    if (!canManage) return;
    const productId = $("mediaProduct").value;
    const data = await api("/ai-sales/api/product-media" + (productId ? `?product_id=${encodeURIComponent(productId)}` : ""));
    $("mediaList").innerHTML = (data.media || []).map(item => `
      <div class="sales-ai-media-item">
        <div><strong>${escapeHtml(item.title || item.product_name)}</strong><small>${escapeHtml(item.product_name)} · ${escapeHtml(item.media_type)}${item.tags.length ? " · " + escapeHtml(item.tags.join("، ")) : ""}</small></div>
        <button class="sales-ai-icon-btn" type="button" data-media-delete="${item.id}" title="حذف" aria-label="حذف"><i class="fa-solid fa-trash"></i></button>
      </div>`).join("") || '<div class="sales-ai-meta-empty">لا توجد وسائط مضافة.</div>';
  }

  async function saveMedia(event) {
    event.preventDefault();
    const form = new FormData();
    form.append("product_id", $("mediaProduct").value);
    form.append("media_type", $("mediaType").value);
    form.append("title", $("mediaTitle").value);
    form.append("tags", $("mediaTags").value);
    form.append("public_url", $("mediaUrl").value);
    form.append("is_primary", $("mediaPrimary").checked ? "true" : "false");
    if ($("mediaFile").files[0]) form.append("file", $("mediaFile").files[0]);
    try {
      await api("/ai-sales/api/product-media", { method: "POST", body: form });
      $("mediaFile").value = "";
      $("mediaUrl").value = "";
      $("mediaTitle").value = "";
      $("mediaTags").value = "";
      await loadProductMedia();
      toast("تمت إضافة الوسيط للمنتج");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteMedia(id) {
    try {
      await api(`/ai-sales/api/product-media/${id}`, { method: "DELETE" });
      await loadProductMedia();
      toast("تم حذف الوسيط");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function autoSyncMeta(aiOnly = false, options = {}) {
    const force = Boolean(options?.force);
    if (state.metaSyncing) {
      if (force) state.metaSyncQueued = true;
      return;
    }
    if (!force && Date.now() < state.metaPausedUntil) return;
    state.metaSyncing = true;
    const credentialRevision = state.metaCredentialRevision;
    try {
      const url = "/ai-sales/api/meta/auto-sync" + (aiOnly ? "?ai_only=1" : "");
      const data = await api(url, { method: "POST" });
      if (credentialRevision !== state.metaCredentialRevision) return;
      if (data.requires_reconnect) {
        if (Number(data.eligible_channels || 0) === 0 && Number(data.retry_after_seconds || 0) > 0) {
          state.metaPausedUntil = Date.now() + (Number(data.retry_after_seconds) * 1000);
        }
        if (!state.metaReconnectNotified) {
          state.metaReconnectNotified = true;
          toast("انتهت صلاحية اتصال Meta. حدّث رمز الوصول من الإعدادات ثم اجلب الصفحات من جديد.", "error");
        }
      } else if (data.requires_page_refresh) {
        if (!state.metaReconnectNotified) {
          state.metaReconnectNotified = true;
          toast("رمز إحدى الصفحات يحتاج تحديثاً. افتح الإعدادات واضغط «جلب كل الصفحات».", "error");
        }
      } else {
        state.metaReconnectNotified = false;
      }
      if (data.messages_created) {
        await Promise.all([loadConversations({ silent: true }), loadOverview()]);
        if (state.activeId) await loadNewMessages();
      }
    } catch (error) {
      console.warn("Meta auto sync:", error.message);
    } finally {
      state.metaSyncing = false;
      if (state.metaSyncQueued) {
        state.metaSyncQueued = false;
        state.metaPausedUntil = 0;
        setTimeout(() => autoSyncMeta(false, { force: true }), 0);
      }
    }
  }

  async function poll() {
    if (state.polling || document.hidden) return;
    state.polling = true;
    try {
      await Promise.all([loadOverview(), loadConversations({ silent: true })]);
      if (state.activeId) await loadNewMessages();
      state.pollFailures = 0;
    } catch (error) {
      state.pollFailures += 1;
      if (state.pollFailures === 1 || !error.transient) {
        console.warn("Sales AI poll:", error.message);
      }
    } finally {
      state.polling = false;
      schedulePoll();
    }
  }

  function schedulePoll(delay) {
    clearTimeout(state.pollTimer);
    const retryDelay = Math.min(30000, 5000 * (2 ** Math.min(state.pollFailures, 3)));
    state.pollTimer = setTimeout(poll, delay ?? retryDelay);
  }

  document.addEventListener("click", event => {
    const trainingFeedback = event.target.closest("[data-training-feedback]");
    if (trainingFeedback) {
      event.stopPropagation();
      const messageId = trainingFeedback.dataset.messageId;
      const rating = trainingFeedback.dataset.trainingFeedback;
      if (rating === "like") submitTrainingFeedback(messageId, "like").catch(error => toast(error.message, "error"));
      else showTrainingCorrection(messageId).catch(error => toast(error.message, "error"));
      return;
    }

    const trainingSave = event.target.closest("[data-training-save]");
    if (trainingSave) {
      event.stopPropagation();
      const panel = trainingSave.closest(".sales-ai-training-correction");
      submitTrainingFeedback(trainingSave.dataset.trainingSave, "dislike", panel).catch(error => toast(error.message, "error"));
      return;
    }

    const trainingCancel = event.target.closest("[data-training-cancel]");
    if (trainingCancel) {
      event.stopPropagation();
      if (state.activeId) openConversation(state.activeId, { updateHistory: false, preserveScroll: true }).catch(error => toast(error.message, "error"));
      return;
    }

    const messageMenu = event.target.closest("[data-message-menu]");
    if (messageMenu) {
      event.stopPropagation();
      openMessageActions(messageMenu.dataset.messageMenu, messageMenu);
      return;
    }

    const messageAction = event.target.closest("[data-message-action]");
    if (messageAction) {
      event.stopPropagation();
      handleMessageAction(messageAction.dataset.messageAction);
      return;
    }

    const removeMedia = event.target.closest("[data-remove-media]");
    if (removeMedia) {
      clearMediaDraft();
      return;
    }

    if (!event.target.closest("#messageActions")) closeMessageActions();

    const conversationButton = event.target.closest("[data-conversation-id]");
    if (conversationButton) openConversation(conversationButton.dataset.conversationId);

    const filterButton = event.target.closest("[data-filter]");
    if (filterButton) {
      state.filter = filterButton.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach(button => button.classList.toggle("active", button === filterButton));
      loadConversations().catch(error => toast(error.message, "error"));
    }

    const closeOverlayButton = event.target.closest("[data-close-overlay]");
    if (closeOverlayButton) closeOverlay(closeOverlayButton.dataset.closeOverlay);

    const contactAction = event.target.closest("[data-contact-action]");
    if (contactAction) {
      if (contactAction.dataset.contactAction === "reopen") setConversationClosed(false);
      else setConversationOwner(contactAction.dataset.contactAction);
    }

    const settingsTab = event.target.closest("[data-tab]");
    if (settingsTab) switchSettingsTab(settingsTab.dataset.tab);

    const metaTab = event.target.closest("[data-meta-tab]");
    if (metaTab) switchMetaTab(metaTab.dataset.metaTab);

    const metaSave = event.target.closest("[data-meta-save]");
    if (metaSave) saveMetaPage(metaSave.dataset.metaSave);

    const metaImport = event.target.closest("[data-meta-import]");
    if (metaImport) importMetaConversations(metaImport.dataset.metaImport);

    const metaDelete = event.target.closest("[data-meta-delete]");
    if (metaDelete) deleteMetaPage(metaDelete.dataset.metaDelete);

    const metaBulk = event.target.closest("[data-meta-bulk]");
    if (metaBulk) bulkMetaPages(metaBulk.dataset.metaBulk);

    const mediaDelete = event.target.closest("[data-media-delete]");
    if (mediaDelete) deleteMedia(mediaDelete.dataset.mediaDelete);

    const problemEdit = event.target.closest("[data-problem-edit]");
    if (problemEdit) editProblem(problemEdit.dataset.problemEdit);

    const problemDelete = event.target.closest("[data-problem-delete]");
    if (problemDelete) deleteProblem(problemDelete.dataset.problemDelete);
  });

  $("conversationSearch").addEventListener("input", renderConversations);
  $("composeForm").addEventListener("submit", sendMessage);
  $("attachmentBtn").addEventListener("click", () => $("chatMediaInput").click());
  $("chatMediaInput").addEventListener("change", event => {
    const file = event.target.files?.[0];
    if (file) setMediaDraft(file);
  });
  $("voiceBtn").addEventListener("click", startRecording);
  $("stopRecordingBtn").addEventListener("click", () => finishRecording(false));
  $("cancelRecordingBtn").addEventListener("click", () => finishRecording(true));
  $("cancelEditingBtn").addEventListener("click", cancelEditing);
  $("messageInput").addEventListener("input", resizeComposer);
  $("messageInput").addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("composeForm").requestSubmit();
    }
  });
  $("mobileBackBtn").addEventListener("click", () => backToConversationList());
  $("refreshBtn").addEventListener("click", () => poll());
  $("simulateBtn")?.addEventListener("click", simulate);
  $("summaryBtn").addEventListener("click", () => openOverlay("summaryOverlay"));
  $("customerInfoBtn").addEventListener("click", () => openOverlay("customerOverlay"));
  $("toggleDetailsBtn").addEventListener("click", () => {
    const workspace = $("workspace");
    const willOpen = workspace.classList.contains("details-collapsed") || !workspace.classList.contains("details-open");
    workspace.classList.toggle("details-open", willOpen);
    workspace.classList.toggle("details-collapsed", !willOpen);
  });
  $("closeDetailsBtn").addEventListener("click", () => {
    $("workspace").classList.remove("details-open");
    $("workspace").classList.add("details-collapsed");
  });
  $("closeConversationBtn").addEventListener("click", () => setConversationClosed(state.activeConversation?.status !== "closed"));
  $("newMessagesBtn").addEventListener("click", () => scrollMessages({ smooth: true }));
  $("messageList").addEventListener("scroll", closeMessageActions, { passive: true });

  if (canManage) {
    $("settingsBtn").addEventListener("click", openSettings);
    $("closeSettings").addEventListener("click", closeSettings);
    $("closeSettingsBackdrop").addEventListener("click", closeSettings);
    $("agentForm").addEventListener("submit", saveAgent);
    $("agentTtsTestBtn").addEventListener("click", testAgentSpeech);
    $("agentVoiceSpeed").addEventListener("input", event => {
      $("agentVoiceSpeedValue").textContent = `${Number(event.target.value || 0.96).toFixed(2)}×`;
    });
    document.querySelectorAll('input[name="agentIntelligence"]').forEach(input => input.addEventListener("change", updateIntelligenceDescription));
    $("channelForm").addEventListener("submit", saveChannel);
    $("checkCallingBtn").addEventListener("click", checkCallingReadiness);
    $("metaForm").addEventListener("submit", saveMetaConnector);
    $("addMetaPageBtn").addEventListener("click", connectMetaPage);
    $("stopMetaAiBtn").addEventListener("click", stopMetaAi);
    $("metaPageSearch").addEventListener("input", renderMetaSettings);
    $("metaPagePlatform").addEventListener("change", renderMetaSettings);
    $("metaPageStatus").addEventListener("change", renderMetaSettings);
    $("metaSelectAll").addEventListener("change", event => {
      document.querySelectorAll("[data-meta-select]").forEach(input => {
        input.checked = event.target.checked;
        const id = Number(input.dataset.metaSelect);
        if (event.target.checked) state.metaSelected.add(id);
        else state.metaSelected.delete(id);
      });
      updateMetaSelectionSummary();
    });
    $("mediaForm").addEventListener("submit", saveMedia);
    $("mediaProduct").addEventListener("change", () => loadProductMedia().catch(error => toast(error.message, "error")));
    $("knowledgeForm").addEventListener("submit", saveProductKnowledge);
    $("knowledgeProduct").addEventListener("change", () => loadProductKnowledge().catch(error => toast(error.message, "error")));
    $("knowledgeVisibilityButton")?.addEventListener("click", () => toggleProductRecommendationVisibility().catch(error => toast(error.message, "error")));
    $("knowledgeAllowRecommendation")?.addEventListener("change", updateKnowledgeVisibilityButton);
    $("knowledgeSearch").addEventListener("input", () => {
      clearTimeout($("knowledgeSearch")._timer);
      $("knowledgeSearch")._timer = setTimeout(() => searchKnowledgeProducts().catch(error => toast(error.message, "error")), 250);
    });
    $("learningSettingsForm").addEventListener("submit", saveLearningSettings);
    $("scanEmployeeRepliesBtn").addEventListener("click", scanEmployeeReplies);
    $("learningMinQuality").addEventListener("input", event => {
      $("learningMinQualityValue").textContent = `${number(event.target.value)}%`;
    });
    $("problemForm").addEventListener("submit", saveProblem);
    $("cancelProblemEdit").addEventListener("click", resetProblemForm);
    $("problemSearch").addEventListener("input", renderProblemEntries);
    $("learningImportForm").addEventListener("submit", importLearningWorkbook);
  }

  window.addEventListener("popstate", () => {
    const conversationId = Number(new URL(window.location.href).searchParams.get("conversation") || 0);
    if (conversationId && conversationId !== state.activeId) {
      openConversation(conversationId, { updateHistory: false });
    } else if (!conversationId && isMobile()) {
      backToConversationList({ updateHistory: false });
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) poll();
    else clearTimeout(state.pollTimer);
  });

  window.addEventListener("resize", () => {
    closeMessageActions();
    if (!isMobile() && state.activeId) setMobileChat(true);
  });

  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeMessageActions();
  });

  async function initialize() {
    try {
      await Promise.all([loadOverview(), loadConversations()]);
      const initialId = Number(new URL(window.location.href).searchParams.get("conversation") || 0);
      if (initialId) await openConversation(initialId, { updateHistory: false });
    } catch (error) {
      $("conversationList").innerHTML = `<div class="sales-ai-empty-state"><i class="fa-solid fa-triangle-exclamation"></i><strong>تعذر تحميل الصندوق</strong><p>${escapeHtml(error.message)}</p></div>`;
      toast(error.message, "error");
    }
  }

  initialize();
  schedulePoll(5000);
})();
