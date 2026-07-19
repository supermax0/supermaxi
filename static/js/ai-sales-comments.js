(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const app = $("commentsApp");
  if (!app) return;
  const state = { channels: [], posts: [], activePostId: null, searchTimer: null };
  const canManage = app.dataset.canManage === "true";

  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", ...options });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok || data.success === false) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }
  function escapeHtml(value) { return String(value || "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c])); }
  function formatTime(value) { if (!value) return ""; const date = new Date(value); return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("ar-IQ", { dateStyle:"medium", timeStyle:"short" }).format(date); }
  function initial(name) { return String(name || "م").trim().charAt(0).toUpperCase(); }
  function toast(message, type = "") { const el = $("commentsToast"); el.textContent = message; el.className = `comments-toast ${type}`; el.hidden = false; clearTimeout(el._timer); el._timer = setTimeout(() => { el.hidden = true; }, 4500); }
  function selectedChannel() { return state.channels.find(row => row.id === Number($("pageSelect").value)) || null; }

  function renderChannels() {
    const current = $("pageSelect").value;
    $("pageSelect").innerHTML = `<option value="">كل الصفحات</option>${state.channels.map(row => `<option value="${row.id}">${escapeHtml(row.name)}</option>`).join("")}`;
    if (state.channels.some(row => String(row.id) === current)) $("pageSelect").value = current;
    if (!$("pageSelect").value && state.channels.length === 1) $("pageSelect").value = String(state.channels[0].id);
    renderPolicy();
  }
  function renderPolicy() {
    const channel = selectedChannel();
    $("commentsPolicy").hidden = !channel;
    $("syncCommentsBtn").disabled = !channel;
    if (!channel) return;
    $("policyPageName").textContent = channel.name;
    $("policyStatus").textContent = channel.comments_enabled ? (channel.comments_reply_mode === "ai" ? "الذكاء يرد" : "استقبال فقط") : "متوقف";
    $("commentsEnabled").checked = !!channel.comments_enabled;
    $("commentsMode").value = channel.comments_reply_mode || "inbox";
    $("commentsPrivate").checked = channel.comments_private_reply !== false;
    $("commentsPublicText").value = channel.comments_public_text || "تم الرد على الخاص";
    [...$("commentsPolicy").querySelectorAll("input,select,button")].forEach(el => { el.disabled = !canManage; });
  }
  function renderPosts() {
    $("postCount").textContent = state.posts.length;
    if (!state.posts.length) {
      $("postsList").innerHTML = `<div class="comments-empty"><i class="fa-regular fa-newspaper"></i><strong>لا توجد منشورات مخزنة</strong><span>اختر صفحة واضغط جلب المنشورات.</span></div>`;
      return;
    }
    $("postsList").innerHTML = state.posts.map(post => {
      const text = post.message || post.story || "منشور بدون نص";
      const media = post.media_url ? `<img src="${escapeHtml(post.media_url)}" alt="">` : `<span class="post-thumb-placeholder"><i class="fa-regular fa-image"></i></span>`;
      return `<button class="post-card ${post.id === state.activePostId ? "active" : ""}" type="button" data-post-id="${post.id}">${media}<span class="post-card-body"><p>${escapeHtml(text)}</p><span class="post-card-meta"><span>${escapeHtml(post.channel_name)} · ${formatTime(post.published_at)}</span><span class="post-card-badges">${post.new_comments ? `<b class="new">${post.new_comments}</b>` : ""}${post.failed_comments ? `<b class="failed">${post.failed_comments}</b>` : ""}</span></span></span></button>`;
    }).join("");
  }
  async function loadPosts({ silent = false } = {}) {
    if (!silent) $("postsList").innerHTML = `<div class="comments-loading"><i class="fa-solid fa-circle-notch fa-spin"></i><span>جاري تحميل المنشورات</span></div>`;
    const params = new URLSearchParams();
    if ($("pageSelect").value) params.set("channel_id", $("pageSelect").value);
    if ($("postSearch").value.trim()) params.set("q", $("postSearch").value.trim());
    try {
      const data = await api(`/ai-sales/api/comments/posts?${params}`);
      state.channels = data.channels || [];
      state.posts = data.posts || [];
      renderChannels(); renderPosts();
      if (state.activePostId && !state.posts.some(row => row.id === state.activePostId)) closePost();
    } catch (error) { $("postsList").innerHTML = `<div class="comments-empty"><strong>تعذر تحميل المنشورات</strong><span>${escapeHtml(error.message)}</span></div>`; }
  }
  function statusLabel(status) { return ({new:"جديد",processing:"جاري الرد",replied:"تم الرد",failed:"فشل",ignored:"متروك"})[status] || status; }
  function renderComments(comments) {
    $("selectedCommentCount").textContent = comments.length;
    if (!comments.length) { $("postComments").innerHTML = `<div class="comments-empty"><strong>لا توجد تعليقات</strong><span>التعليقات الجديدة ستظهر تلقائياً بعد اشتراك feed.</span></div>`; return; }
    $("postComments").innerHTML = comments.map(row => {
      const avatar = row.user_picture_url ? `<img src="${escapeHtml(row.user_picture_url)}" alt="">` : `<span class="comment-avatar">${escapeHtml(initial(row.user_name))}</span>`;
      const privateReply = row.private_reply_text ? `<div class="comment-reply"><strong>الخاص ${row.private_reply_status === "sent" ? "· مرسل" : ""}</strong>${escapeHtml(row.private_reply_text)}</div>` : "";
      const publicReply = row.public_reply_text ? `<div class="comment-reply public"><strong>العام ${row.public_reply_status === "sent" ? "· منشور" : ""}</strong>${escapeHtml(row.public_reply_text)}</div>` : "";
      const retry = (row.status === "failed" || row.status === "new") ? `<button type="button" data-retry-comment="${row.id}"><i class="fa-solid fa-wand-magic-sparkles"></i> ${row.status === "failed" ? "إعادة المحاولة" : "رد الآن"}</button>` : "";
      const displayName = row.user_name || "مستخدم فيسبوك";
      return `<article class="comment-card"><header class="comment-head">${avatar}<div><strong>${escapeHtml(displayName)}</strong>${!row.external_user_id ? `<small class="identity-note">Meta لم يرسل اسم صاحب التعليق</small>` : ""}<time>${formatTime(row.commented_at)}</time></div><span class="comment-status ${escapeHtml(row.status)}">${escapeHtml(statusLabel(row.status))}</span></header><p class="comment-body">${escapeHtml(row.message || "[تعليق بمرفق]")}</p>${row.attachment_url ? `<a class="comment-body" href="${escapeHtml(row.attachment_url)}" target="_blank" rel="noopener">فتح المرفق</a>` : ""}<div class="comment-replies">${privateReply}${publicReply}</div>${row.failure_message ? `<div class="comment-error">${escapeHtml(row.failure_message)}</div>` : ""}<div class="comment-actions">${retry}${row.permalink_url ? `<a href="${escapeHtml(row.permalink_url)}" target="_blank" rel="noopener">فتح على فيسبوك</a>` : ""}</div></article>`;
    }).join("");
  }
  function renderPost(post) {
    if (!post) return;
    $("postPageName").textContent = post.channel_name || "Facebook"; $("postTime").textContent = formatTime(post.published_at); $("postText").textContent = post.message || post.story || "منشور بدون نص";
    $("postPageImage").src = post.channel_picture_url || ""; $("postPageImage").hidden = !post.channel_picture_url;
    $("postPermalink").href = post.permalink_url || "#"; $("postPermalink").hidden = !post.permalink_url;
    $("postMedia").src = post.media_url || ""; $("postMedia").hidden = !post.media_url;
  }
  async function openPost(id) {
    state.activePostId = Number(id); renderPosts();
    $("postEmpty").hidden = true; $("postDetail").hidden = false; $("postDetail").classList.add("is-open"); $("postComments").innerHTML = `<div class="comments-loading"><i class="fa-solid fa-circle-notch fa-spin"></i></div>`;
    document.querySelector(".comments-workspace").classList.add("show-detail");
    renderPost(state.posts.find(row => Number(row.id) === Number(id)));
    try {
      const data = await api(`/ai-sales/api/comments/posts/${id}`); const post = data.post;
      renderPost(post);
      renderComments(data.comments || []);
    } catch (error) { $("postComments").innerHTML = `<div class="comments-empty"><strong>تعذر تحميل التعليقات</strong><span>${escapeHtml(error.message)}</span></div>`; toast(error.message, "error"); }
  }
  function closePost() { state.activePostId = null; $("postDetail").classList.remove("is-open"); $("postDetail").hidden = true; $("postEmpty").hidden = false; document.querySelector(".comments-workspace").classList.remove("show-detail"); renderPosts(); }
  async function syncPosts() {
    const channel = selectedChannel(); if (!channel) return toast("اختر الصفحة أولاً", "error");
    const button = $("syncCommentsBtn"); button.disabled = true;
    try { const data = await api("/ai-sales/api/comments/sync", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({channel_id:channel.id}) }); toast(`تم جلب ${data.posts} منشور و${data.new_comments} تعليق جديد`); await loadPosts({silent:true}); }
    catch (error) { toast(error.message, "error"); } finally { button.disabled = false; }
  }
  async function savePolicy() {
    const channel = selectedChannel(); if (!channel) return;
    const payload = { id:channel.id, channel_type:channel.channel_type, name:channel.name, comments_enabled:$("commentsEnabled").checked, comments_reply_mode:$("commentsMode").value, comments_private_reply:$("commentsPrivate").checked, comments_public_text:$("commentsPublicText").value.trim() || "تم الرد على الخاص" };
    try { await api("/ai-sales/api/channels", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); toast("تم حفظ إعدادات التعليقات"); await loadPosts({silent:true}); }
    catch (error) { toast(error.message, "error"); }
  }
  async function retryComment(id) { try { await api(`/ai-sales/api/comments/${id}/reply`, {method:"POST"}); toast("تم إرسال التعليق للمعالجة"); setTimeout(() => state.activePostId && openPost(state.activePostId), 1800); } catch (error) { toast(error.message,"error"); } }

  $("pageSelect").addEventListener("change", () => { renderPolicy(); closePost(); loadPosts(); });
  $("refreshCommentsBtn").addEventListener("click", () => loadPosts()); $("syncCommentsBtn").addEventListener("click", syncPosts); $("saveCommentsPolicyBtn").addEventListener("click", savePolicy);
  $("postSearch").addEventListener("input", () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(() => loadPosts(), 300); });
  $("postsList").addEventListener("click", event => { const button = event.target.closest("[data-post-id]"); if (button) openPost(button.dataset.postId); });
  $("postBackBtn").addEventListener("click", closePost);
  $("postComments").addEventListener("click", event => { const button = event.target.closest("[data-retry-comment]"); if (button) retryComment(button.dataset.retryComment); });
  loadPosts(); setInterval(() => { loadPosts({silent:true}); if (state.activePostId) openPost(state.activePostId); }, 15000);
})();
