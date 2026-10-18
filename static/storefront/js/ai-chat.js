(function () {
  const cfg = window.STOREFRONT_CONFIG || {};
  if (!cfg.aiChatEnabled) return;

  const slug = cfg.tenantSlug || "";
  const devQ = cfg.dev ? "?dev=1" : "";

  function apiUrl(path) {
    return `/shop/${encodeURIComponent(slug)}/api/${path}${devQ}`;
  }

  const fab = document.getElementById("sfAiFab");
  const panel = document.getElementById("sfAiPanel");
  const overlay = document.getElementById("sfAiOverlay");
  const closeBtn = document.getElementById("sfAiClose");
  const messagesEl = document.getElementById("sfAiMessages");
  const form = document.getElementById("sfAiForm");
  const input = document.getElementById("sfAiInput");
  const sendBtn = document.getElementById("sfAiSend");
  const statusEl = document.getElementById("sfAiStatus");
  const clearBtn = document.getElementById("sfAiClear");
  const suggestionsEl = document.getElementById("sfAiSuggestions");
  const trackForm = document.getElementById("sfAiTrackForm");
  const trackInvoice = document.getElementById("sfAiTrackInvoice");
  const trackPhone = document.getElementById("sfAiTrackPhone");
  const trackSubmit = document.getElementById("sfAiTrackSubmit");
  const trackCancel = document.getElementById("sfAiTrackCancel");
  const videoModal = document.getElementById("sfAiVideoModal");
  const videoBackdrop = document.getElementById("sfAiVideoBackdrop");
  const videoClose = document.getElementById("sfAiVideoClose");
  const videoBody = document.getElementById("sfAiVideoBody");
  const detailModal = document.getElementById("sfAiDetailModal");
  const detailBackdrop = document.getElementById("sfAiDetailBackdrop");
  const detailClose = document.getElementById("sfAiDetailClose");
  const detailTitle = document.getElementById("sfAiDetailTitle");
  const detailContent = document.getElementById("sfAiDetailContent");

  if (!fab || !panel || !messagesEl || !form) return;

  const chatHistory = [];
  const conversationEntries = [];
  const storageKey = `finora:storefront-chat:v1:${encodeURIComponent(slug || "default")}`;
  let greeted = false;

  const storedProductKeys = [
    "id", "name", "price", "old_price", "discount_percent", "category", "brand",
    "model", "sku", "description", "long_description", "features", "image_url",
    "gallery", "video_url", "specs", "short_specs", "badge", "stock",
    "is_available", "is_reservation", "url", "has_colors", "colors",
    "exchange_sale_price", "has_exchange_sale", "sale_options",
  ];

  function productForStorage(product) {
    const stored = {};
    storedProductKeys.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(product || {}, key)) stored[key] = product[key];
    });
    return stored;
  }

  function persistConversation() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({
        version: 1,
        updatedAt: Date.now(),
        entries: conversationEntries.slice(-30),
      }));
    } catch (error) {
      // Browsing in private mode or a full storage quota should never break chat.
    }
  }

  function rememberEntry(entry) {
    const saved = {
      role: entry.role === "user" ? "user" : "assistant",
      content: String(entry.content || "").slice(0, 1200),
      at: Date.now(),
    };
    if (saved.role === "assistant") {
      saved.products = (entry.products || []).slice(0, 4).map(productForStorage);
      if (entry.track && entry.track.found) saved.track = entry.track;
    }
    conversationEntries.push(saved);
    if (conversationEntries.length > 30) conversationEntries.splice(0, conversationEntries.length - 30);
    persistConversation();
  }

  function savedConversation() {
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (!parsed || parsed.version !== 1 || !Array.isArray(parsed.entries)) return [];
      return parsed.entries.slice(-30).filter((entry) =>
        entry && (entry.role === "user" || entry.role === "assistant") && String(entry.content || "").trim()
      );
    } catch (error) {
      return [];
    }
  }

  function restoreConversation() {
    const entries = savedConversation();
    entries.forEach((entry) => {
      const content = String(entry.content || "");
      if (entry.role === "user") {
        addUserMessage(content);
      } else {
        addAssistantPayload(content, entry.products || [], entry.track || {});
      }
      chatHistory.push({ role: entry.role, content });
      conversationEntries.push(entry);
    });
    return entries.length > 0;
  }

  function clearConversation() {
    if (conversationEntries.length && !window.confirm("تريد تمسح المحادثة وتبدأ من جديد؟")) return;
    try { localStorage.removeItem(storageKey); } catch (error) {}
    conversationEntries.length = 0;
    chatHistory.length = 0;
    messagesEl.innerHTML = "";
    closeProductDetails();
    hideTrackForm();
    addAssistantMessage(cfg.aiGreeting || "أهلاً بك 👋 شلون أگدر أساعدك؟");
    renderSuggestions(cfg.aiSuggestions || []);
  }

  function setAssistantState(isTyping) {
    if (!statusEl) return;
    statusEl.classList.toggle("is-typing", Boolean(isTyping));
    statusEl.innerHTML = isTyping
      ? '<span class="sf-ai-online-dot"></span> يكتب الآن...'
      : '<span class="sf-ai-online-dot"></span> جاهز لمساعدتك';
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatAssistant(text) {
    return escapeHtml(text)
      .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.*?)\*/g, "<em>$1</em>")
      .replace(/\n\s*-\s/g, "<br>• ")
      .replace(/\n/g, "<br>");
  }

  function openPanel() {
    panel.classList.add("show");
    panel.setAttribute("aria-hidden", "false");
    overlay.classList.add("show");
    fab.classList.add("seen");
    if (!greeted) {
      greeted = true;
      addAssistantMessage(cfg.aiGreeting || "مرحباً! كيف يمكنني مساعدتك؟");
      restoreConversation();
      renderSuggestions(cfg.aiSuggestions || []);
    }
    setTimeout(() => input && input.focus(), 250);
  }

  function closePanel() {
    panel.classList.remove("show");
    panel.setAttribute("aria-hidden", "true");
    overlay.classList.remove("show");
    hideTrackForm();
  }

  function hideTrackForm() {
    if (trackForm) trackForm.hidden = true;
  }

  function showTrackForm() {
    if (trackForm) trackForm.hidden = false;
    if (trackInvoice) trackInvoice.focus();
  }

  function scrollMessages() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addUserMessage(text) {
    const row = document.createElement("div");
    row.className = "sf-ai-row user";
    const bubble = document.createElement("div");
    bubble.className = "sf-ai-msg user";
    bubble.textContent = text;
    row.appendChild(bubble);
    messagesEl.appendChild(row);
    scrollMessages();
  }

  function addAssistantMessage(text, extraNode) {
    const row = document.createElement("div");
    row.className = "sf-ai-row assistant";

    const avatar = document.createElement("div");
    avatar.className = "sf-ai-message-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = (cfg.assistantName || "م").trim().slice(0, 1);

    const content = document.createElement("div");
    content.className = "sf-ai-message-content";
    const bubble = document.createElement("div");
    bubble.className = "sf-ai-msg assistant";
    bubble.innerHTML = formatAssistant(text);
    content.appendChild(bubble);
    if (extraNode) content.appendChild(extraNode);

    row.appendChild(avatar);
    row.appendChild(content);
    messagesEl.appendChild(row);
    scrollMessages();
    return bubble;
  }

  function addErrorMessage(text) {
    addAssistantMessage(text).classList.add("error");
  }

  function showTyping() {
    setAssistantState(true);
    const row = document.createElement("div");
    row.className = "sf-ai-row assistant";
    row.id = "sfAiTyping";
    row.innerHTML = `
      <div class="sf-ai-message-avatar" aria-hidden="true">${escapeHtml((cfg.assistantName || "م").trim().slice(0, 1))}</div>
      <div class="sf-ai-msg assistant typing"><span class="sf-ai-typing-dots"><span></span><span></span><span></span></span></div>
    `;
    messagesEl.appendChild(row);
    scrollMessages();
  }

  function hideTyping() {
    const typing = document.getElementById("sfAiTyping");
    if (typing) typing.remove();
    setAssistantState(false);
  }

  function renderSuggestions(items) {
    if (!suggestionsEl) return;
    suggestionsEl.innerHTML = "";
    (items || []).forEach((label) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sf-ai-chip-btn";
      btn.textContent = label;
      btn.addEventListener("click", () => {
        if (label.includes("تتبع")) {
          showTrackForm();
          return;
        }
        input.value = label;
        form.requestSubmit();
      });
      suggestionsEl.appendChild(btn);
    });
  }

  function buildProductCards(products) {
    if (!products || !products.length) return null;
    const wrap = document.createElement("div");
    wrap.className = "sf-ai-product-results";
    const cards = document.createElement("div");
    cards.className = "sf-ai-product-cards";

    products.forEach((product) => {
      const card = document.createElement("article");
      card.className = "sf-ai-product-card";

      const gallery = Array.isArray(product.gallery) && product.gallery.length
        ? product.gallery
        : product.image_url
          ? [product.image_url]
          : [];

      if (gallery.length) {
        const media = document.createElement("div");
        media.className = "sf-ai-product-media";
        const mainImg = document.createElement("img");
        mainImg.src = gallery[0];
        mainImg.alt = product.name || "";
        mainImg.loading = "lazy";
        media.appendChild(mainImg);
        card.appendChild(media);
      }

      const body = document.createElement("div");
      body.className = "sf-ai-product-body";
      body.innerHTML = `
        <h4>${escapeHtml(product.name || "")}</h4>
        <div class="sf-ai-product-price">${Number(product.price || 0).toLocaleString("ar-IQ")} د.ع</div>
        <div class="sf-ai-product-status ${product.is_available || product.is_reservation ? "ok" : "out"}">
          <span></span>${product.is_available ? "متوفر الآن" : (product.is_reservation ? "متاح بالطلب" : "غير متوفر حالياً")}
        </div>
      `;

      if (product.short_specs || (product.specs && product.specs.length)) {
        const specs = document.createElement("div");
        specs.className = "sf-ai-product-specs";
        specs.textContent = product.short_specs || product.specs.slice(0, 3).map((s) => `${s.label}: ${s.value}`).join(" | ");
        body.appendChild(specs);
      }

      const actions = document.createElement("div");
      actions.className = "sf-ai-product-actions";

      const detail = document.createElement("button");
      detail.type = "button";
      detail.className = "ghost";
      detail.textContent = "التفاصيل";
      detail.addEventListener("click", () => openProductDetails(product));
      actions.appendChild(detail);

      if (product.is_available || product.is_reservation) {
        const addBtn = document.createElement("button");
        addBtn.type = "button";
        addBtn.className = "primary";
        addBtn.setAttribute("data-sf-add-cart", String(product.id));
        addBtn.textContent = "أضف للسلة";
        actions.appendChild(addBtn);
      }

      if (product.video_url) {
        const videoBtn = document.createElement("button");
        videoBtn.type = "button";
        videoBtn.className = "video";
        videoBtn.textContent = "فيديو";
        videoBtn.addEventListener("click", () => openVideo(product.video_url));
        actions.appendChild(videoBtn);
      }

      body.appendChild(actions);
      card.appendChild(body);
      cards.appendChild(card);
    });

    wrap.appendChild(cards);
    return wrap;
  }

  function buildTrackTimeline(track) {
    if (!track || !track.found || !Array.isArray(track.steps)) return null;
    const wrap = document.createElement("div");
    wrap.className = "sf-ai-track-timeline";
    track.steps.forEach((step) => {
      const row = document.createElement("div");
      const classes = ["sf-ai-track-step"];
      if (step.done) classes.push("done");
      if (step.active) classes.push("active");
      row.className = classes.join(" ");
      row.innerHTML = `
        <span class="sf-ai-track-dot"></span>
        <div>
          <strong>${escapeHtml(step.label || "")}</strong>
          <div>${escapeHtml(step.hint || "")}</div>
        </div>
      `;
      wrap.appendChild(row);
    });
    if (track.public_url) {
      const link = document.createElement("a");
      link.href = track.public_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.className = "sf-ai-chip-btn primary";
      link.style.display = "inline-flex";
      link.style.marginTop = "8px";
      link.textContent = "عرض تفاصيل الطلب";
      wrap.appendChild(link);
    }
    return wrap;
  }

  function addAssistantPayload(text, products, track) {
    const extra = document.createElement("div");
    const productsNode = buildProductCards(products);
    const trackNode = buildTrackTimeline(track);
    if (productsNode) extra.appendChild(productsNode);
    if (trackNode) extra.appendChild(trackNode);
    addAssistantMessage(text || "", extra.childNodes.length ? extra : null);
  }

  function detailValue(value) {
    return String(value || "").trim();
  }

  function openProductDetails(product) {
    if (!detailModal || !detailContent || !detailTitle || !product) return;
    const gallery = Array.isArray(product.gallery) && product.gallery.length
      ? product.gallery.filter(Boolean).slice(0, 5)
      : product.image_url ? [product.image_url] : [];
    const specs = Array.isArray(product.specs) ? product.specs.filter((row) => row && row.value) : [];
    const features = Array.isArray(product.features) ? product.features.filter(Boolean).slice(0, 8) : [];
    const description = detailValue(product.long_description || product.description);
    const price = Number(product.price || 0).toLocaleString("ar-IQ");
    const oldPrice = Number(product.old_price || 0);
    const available = Boolean(product.is_available || product.is_reservation);
    const status = product.is_available ? "متوفر الآن" : (product.is_reservation ? "متاح بالطلب" : "غير متوفر حالياً");
    const facts = [
      ["العلامة", product.brand],
      ["التصنيف", product.category || product.badge],
      ["الموديل", product.model],
      ["رمز المنتج", product.sku],
    ].filter((row) => detailValue(row[1]));

    detailTitle.textContent = detailValue(product.name) || "تفاصيل المنتج";
    detailContent.innerHTML = `
      <div class="sf-ai-detail-layout">
        <div class="sf-ai-detail-gallery">
          <div class="sf-ai-detail-main-image">
            ${gallery[0]
              ? `<img id="sfAiDetailMainImage" src="${escapeHtml(gallery[0])}" alt="${escapeHtml(product.name || "")}">`
              : '<div class="sf-ai-detail-image-empty">لا توجد صورة حالياً</div>'}
          </div>
          ${gallery.length > 1 ? `<div class="sf-ai-detail-thumbs">${gallery.map((src, index) => `
            <button type="button" class="${index === 0 ? "active" : ""}" data-sf-detail-image="${escapeHtml(src)}" aria-label="عرض الصورة ${index + 1}">
              <img src="${escapeHtml(src)}" alt="">
            </button>`).join("")}</div>` : ""}
        </div>
        <div class="sf-ai-detail-info">
          <div class="sf-ai-detail-badges">
            ${detailValue(product.brand) ? `<span>${escapeHtml(product.brand)}</span>` : ""}
            ${detailValue(product.category || product.badge) ? `<span>${escapeHtml(product.category || product.badge)}</span>` : ""}
          </div>
          <h2>${escapeHtml(product.name || "")}</h2>
          <div class="sf-ai-detail-price-row">
            <strong>${price} د.ع</strong>
            ${oldPrice > Number(product.price || 0) ? `<del>${oldPrice.toLocaleString("ar-IQ")} د.ع</del>` : ""}
          </div>
          <div class="sf-ai-detail-availability ${available ? "ok" : "out"}"><span></span>${status}</div>
          ${description ? `<div class="sf-ai-detail-section"><h4>عن المنتج</h4><p>${escapeHtml(description)}</p></div>` : ""}
          ${features.length ? `<div class="sf-ai-detail-section"><h4>أبرز المميزات</h4><ul>${features.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>` : ""}
          ${specs.length || facts.length ? `<div class="sf-ai-detail-section"><h4>المواصفات</h4><dl class="sf-ai-detail-specs">
            ${facts.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
            ${specs.map((row) => `<div><dt>${escapeHtml(row.label || "مواصفة")}</dt><dd>${escapeHtml(row.value)}</dd></div>`).join("")}
          </dl></div>` : ""}
          ${product.has_colors && Array.isArray(product.colors) && product.colors.length ? `<div class="sf-ai-detail-section"><h4>الألوان المتوفرة</h4><div class="sf-ai-detail-colors">${product.colors.map((color) => `<span>${escapeHtml(color.color_name || color.name || color)}</span>`).join("")}</div></div>` : ""}
          <div class="sf-ai-detail-actions">
            ${available ? `<button type="button" class="primary" data-sf-add-cart="${escapeHtml(product.id)}">أضف للسلة</button>` : ""}
            ${product.url ? `<a href="${escapeHtml(product.url)}">فتح صفحة المنتج</a>` : ""}
          </div>
        </div>
      </div>
    `;

    detailContent.querySelectorAll("[data-sf-detail-image]").forEach((button) => {
      button.addEventListener("click", () => {
        const mainImage = document.getElementById("sfAiDetailMainImage");
        if (mainImage) mainImage.src = button.getAttribute("data-sf-detail-image") || "";
        detailContent.querySelectorAll("[data-sf-detail-image]").forEach((node) => node.classList.remove("active"));
        button.classList.add("active");
      });
    });

    detailModal.hidden = false;
    detailModal.setAttribute("aria-hidden", "false");
    document.documentElement.classList.add("sf-ai-modal-open");
    setTimeout(() => detailClose && detailClose.focus(), 0);
  }

  function closeProductDetails() {
    if (!detailModal) return;
    detailModal.hidden = true;
    detailModal.setAttribute("aria-hidden", "true");
    document.documentElement.classList.remove("sf-ai-modal-open");
    if (detailContent) detailContent.innerHTML = "";
  }

  function openVideo(url) {
    if (!videoModal || !videoBody) return;
    const src = String(url || "").trim();
    if (!src) return;
    videoBody.innerHTML = "";
    if (/youtube\.com|youtu\.be/i.test(src)) {
      let videoId = "";
      const short = src.match(/youtu\.be\/([^?&]+)/i);
      const watch = src.match(/[?&]v=([^?&]+)/i);
      videoId = (short && short[1]) || (watch && watch[1]) || "";
      if (videoId) {
        const iframe = document.createElement("iframe");
        iframe.src = `https://www.youtube.com/embed/${videoId}`;
        iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
        iframe.allowFullscreen = true;
        videoBody.appendChild(iframe);
      }
    } else if (/\.(mp4|webm|ogg)(\?|$)/i.test(src)) {
      const video = document.createElement("video");
      video.src = src;
      video.controls = true;
      video.playsInline = true;
      videoBody.appendChild(video);
    } else {
      const iframe = document.createElement("iframe");
      iframe.src = src;
      iframe.allowFullscreen = true;
      videoBody.appendChild(iframe);
    }
    videoModal.hidden = false;
  }

  function closeVideo() {
    if (!videoModal || !videoBody) return;
    videoModal.hidden = true;
    videoBody.innerHTML = "";
  }

  async function sendChat(message, extraPayload) {
    showTyping();
    sendBtn.disabled = true;
    try {
      const res = await fetch(apiUrl("ai-chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({
          message,
          history: chatHistory,
          ...(extraPayload || {}),
        }),
      });
      const data = await res.json();
      hideTyping();
      if (!res.ok || !data.success) {
        addErrorMessage(data.error || "حدث خطأ. جرّب لاحقاً.");
        return;
      }
      addAssistantPayload(data.reply || "", data.products || [], data.track || {});
      chatHistory.push({ role: "assistant", content: data.reply || "" });
      rememberEntry({
        role: "assistant",
        content: data.reply || "",
        products: data.products || [],
        track: data.track || {},
      });
      if (data.suggestions) renderSuggestions(data.suggestions);
      if (data.cart && typeof data.cart.count === "number") {
        document.querySelectorAll("[data-sf-cart-count]").forEach((node) => {
          node.textContent = String(data.cart.count);
        });
      }
    } catch (err) {
      hideTyping();
      addErrorMessage("تعذّر الاتصال. تحقق من الشبكة.");
    } finally {
      sendBtn.disabled = false;
    }
  }

  async function submitTrack() {
    const invoiceId = (trackInvoice && trackInvoice.value || "").trim();
    const phone = (trackPhone && trackPhone.value || "").trim();
    if (!invoiceId || !phone) {
      addErrorMessage("أدخل رقم الطلب ورقم الهاتف.");
      return;
    }
    hideTrackForm();
    addUserMessage(`تتبع الطلب ${invoiceId}`);
    chatHistory.push({ role: "user", content: `تتبع الطلب ${invoiceId}` });
    rememberEntry({ role: "user", content: `تتبع الطلب ${invoiceId}` });
    showTyping();
    sendBtn.disabled = true;
    try {
      const res = await fetch(apiUrl("ai-chat/track"), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({ invoice_id: invoiceId, phone }),
      });
      const data = await res.json();
      hideTyping();
      addAssistantPayload(data.reply || "", [], data.track || {});
      chatHistory.push({ role: "assistant", content: data.reply || "" });
      rememberEntry({ role: "assistant", content: data.reply || "", track: data.track || {} });
    } catch (err) {
      hideTyping();
      addErrorMessage("تعذّر تتبع الطلب.");
    } finally {
      sendBtn.disabled = false;
    }
  }

  fab.addEventListener("click", openPanel);
  if (closeBtn) closeBtn.addEventListener("click", closePanel);
  if (clearBtn) clearBtn.addEventListener("click", clearConversation);
  if (overlay) overlay.addEventListener("click", closePanel);
  if (detailBackdrop) detailBackdrop.addEventListener("click", closeProductDetails);
  if (detailClose) detailClose.addEventListener("click", closeProductDetails);
  if (videoBackdrop) videoBackdrop.addEventListener("click", closeVideo);
  if (videoClose) videoClose.addEventListener("click", closeVideo);
  if (trackSubmit) trackSubmit.addEventListener("click", submitTrack);
  if (trackCancel) trackCancel.addEventListener("click", hideTrackForm);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = (input.value || "").trim();
    if (!text) return;
    input.value = "";
    input.style.height = "auto";
    hideTrackForm();
    addUserMessage(text);
    chatHistory.push({ role: "user", content: text });
    rememberEntry({ role: "user", content: text });
    sendChat(text);
  });

  if (input) {
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 96)}px`;
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (detailModal && !detailModal.hidden) {
      closeProductDetails();
      return;
    }
    if (videoModal && !videoModal.hidden) closeVideo();
  });
})();
