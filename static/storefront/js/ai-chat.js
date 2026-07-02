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

  if (!fab || !panel || !messagesEl || !form) return;

  const chatHistory = [];
  let greeted = false;

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
    const div = document.createElement("div");
    div.className = "sf-ai-msg user";
    div.textContent = text;
    messagesEl.appendChild(div);
    scrollMessages();
  }

  function addAssistantMessage(text, extraNode) {
    const wrap = document.createElement("div");
    wrap.className = "sf-ai-msg assistant";
    wrap.innerHTML = formatAssistant(text);
    if (extraNode) wrap.appendChild(extraNode);
    messagesEl.appendChild(wrap);
    scrollMessages();
    return wrap;
  }

  function addErrorMessage(text) {
    const div = document.createElement("div");
    div.className = "sf-ai-msg assistant error";
    div.textContent = text;
    messagesEl.appendChild(div);
    scrollMessages();
  }

  function showTyping() {
    const div = document.createElement("div");
    div.className = "sf-ai-msg assistant typing";
    div.innerHTML = '<span class="sf-ai-typing-dots"><span></span><span></span><span></span></span>';
    div.id = "sfAiTyping";
    messagesEl.appendChild(div);
    scrollMessages();
  }

  function hideTyping() {
    const typing = document.getElementById("sfAiTyping");
    if (typing) typing.remove();
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
    wrap.className = "sf-ai-product-cards";

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

        if (gallery.length > 1) {
          const thumbs = document.createElement("div");
          thumbs.className = "sf-ai-product-thumbs";
          gallery.slice(0, 6).forEach((src, index) => {
            const btn = document.createElement("button");
            btn.type = "button";
            if (index === 0) btn.classList.add("active");
            const img = document.createElement("img");
            img.src = src;
            img.alt = "";
            btn.appendChild(img);
            btn.addEventListener("click", () => {
              mainImg.src = src;
              thumbs.querySelectorAll("button").forEach((node) => node.classList.remove("active"));
              btn.classList.add("active");
            });
            thumbs.appendChild(btn);
          });
          media.appendChild(thumbs);
        }
        card.appendChild(media);
      }

      const body = document.createElement("div");
      body.className = "sf-ai-product-body";
      body.innerHTML = `
        <h4>${escapeHtml(product.name || "")}</h4>
        <div class="sf-ai-product-price">${Number(product.price || 0).toLocaleString("ar-IQ")} د.ع</div>
        <div class="sf-ai-product-status ${product.is_available ? "ok" : "out"}">
          ${product.is_available ? `متوفر — الكمية: ${product.stock || 0}` : "غير متوفر حالياً"}
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

      if (product.url) {
        const detail = document.createElement("a");
        detail.className = "ghost";
        detail.href = product.url;
        detail.textContent = "عرض التفاصيل";
        actions.appendChild(detail);
      }

      if (product.is_available) {
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
        videoBtn.textContent = "شاهد الفيديو";
        videoBtn.addEventListener("click", () => openVideo(product.video_url));
        actions.appendChild(videoBtn);
      }

      body.appendChild(actions);
      card.appendChild(body);
      wrap.appendChild(card);
    });

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
      const extra = document.createElement("div");
      const productsNode = buildProductCards(data.products);
      const trackNode = buildTrackTimeline(data.track);
      if (productsNode) extra.appendChild(productsNode);
      if (trackNode) extra.appendChild(trackNode);
      addAssistantMessage(data.reply || "", extra.childNodes.length ? extra : null);
      chatHistory.push({ role: "assistant", content: data.reply || "" });
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
      const extra = document.createElement("div");
      const trackNode = buildTrackTimeline(data.track);
      if (trackNode) extra.appendChild(trackNode);
      addAssistantMessage(data.reply || "", extra.childNodes.length ? extra : null);
      chatHistory.push({ role: "assistant", content: data.reply || "" });
    } catch (err) {
      hideTyping();
      addErrorMessage("تعذّر تتبع الطلب.");
    } finally {
      sendBtn.disabled = false;
    }
  }

  fab.addEventListener("click", openPanel);
  if (closeBtn) closeBtn.addEventListener("click", closePanel);
  if (overlay) overlay.addEventListener("click", closePanel);
  if (videoBackdrop) videoBackdrop.addEventListener("click", closeVideo);
  if (videoClose) videoClose.addEventListener("click", closeVideo);
  if (trackSubmit) trackSubmit.addEventListener("click", submitTrack);
  if (trackCancel) trackCancel.addEventListener("click", hideTrackForm);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = (input.value || "").trim();
    if (!text) return;
    input.value = "";
    hideTrackForm();
    addUserMessage(text);
    chatHistory.push({ role: "user", content: text });
    sendChat(text);
  });

  if (input) {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
  }
})();
