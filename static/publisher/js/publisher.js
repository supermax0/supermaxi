/* publisher.js — Dashboard + Create Post logic */

const SELECTED_MEDIA_KEY = "publisher_selected_media_ids";
const SELECTED_MEDIA_META_KEY = "publisher_selected_media_meta";
let selectedMediaIds = [];
let selectedMediaMeta = [];
let publishMode = "now";

async function apiFetchJson(url, options = {}) {
    const opts = {
        credentials: "include",
        ...options,
        headers: {
            Accept: "application/json",
            ...(options.headers || {}),
        },
    };
    const res = await fetch(url, opts);
    const contentType = res.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
        return { success: false, message: "استجابة غير صالحة من الخادم" };
    }
    return res.json();
}

const API = {
    pages: () => apiFetchJson("/publisher/api/pages"),
    posts: (status = "") => apiFetchJson(`/publisher/api/posts${status ? "?status=" + status : ""}`),
};

function toast(msg, type = "info") {
    const wrap = document.getElementById("toastWrap");
    if (!wrap) return;
    const t = document.createElement("div");
    t.className = "pub-toast " + type;
    t.textContent = msg || "";
    wrap.appendChild(t);
    setTimeout(() => t.remove(), 3800);
}

function extractItems(payload, legacyKey) {
    if (payload?.data?.items && Array.isArray(payload.data.items)) return payload.data.items;
    if (payload?.data && Array.isArray(payload.data)) return payload.data;
    if (legacyKey && Array.isArray(payload?.[legacyKey])) return payload[legacyKey];
    return [];
}

function extractPost(payload) {
    if (payload?.data && !Array.isArray(payload.data) && payload.data.id) return payload.data;
    if (payload?.post) return payload.post;
    return {};
}

function statusBadge(status) {
    const map = {
        draft: ["badge-draft", "مسودة"],
        queued: ["badge-queued", "في الانتظار"],
        scheduled: ["badge-scheduled", "مجدول"],
        publishing: ["badge-publishing", "قيد النشر"],
        published: ["badge-published", "منشور"],
        failed: ["badge-failed", "فشل"],
        partial: ["badge-partial", "جزئي"],
    };
    const [cls, label] = map[status] || ["badge-draft", status || "—"];
    return `<span class="badge ${cls}">${label}</span>`;
}

function fmtDate(value) {
    if (!value) return "—";
    try {
        return new Date(value).toLocaleString("ar-SA", {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    } catch {
        return "—";
    }
}

function trunc(text, n = 70) {
    if (!text) return "—";
    return text.length > n ? text.slice(0, n) + "..." : text;
}

function escapeHtml(value) {
    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/* Dashboard */
async function initDashboard() {
    await Promise.all([loadStats(), loadRecentPosts()]);
}

async function loadStats() {
    try {
        const data = await API.posts();
        const posts = extractItems(data, "posts");
        const count = (s) => posts.filter((p) => p.status === s).length;
        const totalEl = document.getElementById("statTotal");
        const schEl = document.getElementById("statScheduled");
        const pubEl = document.getElementById("statPublished");
        const failedEl = document.getElementById("statFailed");
        if (totalEl) totalEl.textContent = String(posts.length);
        if (schEl) schEl.textContent = String(count("scheduled"));
        if (pubEl) pubEl.textContent = String(count("published"));
        if (failedEl) failedEl.textContent = String(count("failed"));
    } catch (e) {
        console.error("loadStats", e);
    }
}

async function loadRecentPosts() {
    const tbody = document.getElementById("postsBody");
    if (!tbody) return;
    try {
        const data = await API.posts();
        const posts = extractItems(data, "posts").slice(0, 20);
        if (!posts.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="table-loading">لا توجد منشورات بعد</td></tr>';
            return;
        }
        tbody.innerHTML = posts
            .map((p) => {
                const pageCount = (p.page_ids || []).length;
                const text = escapeHtml(trunc(p.text, 70));
                return (
                    "<tr>" +
                    `<td>${text}</td>` +
                    `<td>${statusBadge(p.status)}</td>` +
                    `<td>${pageCount} صفحة</td>` +
                    `<td>${fmtDate(p.created_at)}</td>` +
                    `<td><a class="table-action" href="/publisher/create">إعادة الاستخدام</a></td>` +
                    "</tr>"
                );
            })
            .join("");
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="5" class="table-loading">تعذر تحميل البيانات</td></tr>';
    }
}

/* Create Post */
async function initCreatePost() {
    restoreSelectedMediaFromStorage();
    await loadPageSelector();
    initPublishToggle();
    initAiTools();
    updateSelectedMediaChip();
    updatePreview();

    document.getElementById("postForm")?.addEventListener("submit", submitPost);
    document.getElementById("postText")?.addEventListener("input", updatePreview);
    document.getElementById("openMediaPicker")?.addEventListener("click", openMediaPickerModal);
    document.getElementById("pagesWrap")?.addEventListener("change", updatePreview);
    document.getElementById("scheduleTime")?.addEventListener("input", updatePreview);
}

async function loadPageSelector() {
    const wrap = document.getElementById("pagesWrap");
    if (!wrap) return;
    try {
        const data = await API.pages();
        const pages = extractItems(data, "pages");
        if (!pages.length) {
            wrap.innerHTML =
                '<p style="color:var(--text-secondary);font-size:13px">لا توجد صفحات مربوطة. <a href="/publisher/settings" style="color:#c7d2fe">اربط صفحة</a></p>';
            return;
        }
        wrap.innerHTML = pages
            .map(
                (p) =>
                    '<label>' +
                    `<input type="checkbox" class="page-checkbox" name="page_ids" value="${escapeHtml(p.page_id)}">` +
                    `<span class="page-chip">${escapeHtml(p.page_name || p.page_id)}</span>` +
                    "</label>"
            )
            .join("");
        updatePreview();
    } catch (e) {
        console.error("loadPageSelector", e);
    }
}

function initPublishToggle() {
    document.querySelectorAll(".toggle-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            publishMode = btn.dataset.mode || "now";
            document.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            const schedField = document.getElementById("scheduleField");
            if (schedField) schedField.style.display = publishMode === "scheduled" ? "block" : "none";
            updatePreview();
        });
    });
}

function initAiTools() {
    const generateBtn = document.getElementById("aiGenerate");
    const rewriteBtn = document.getElementById("aiRewrite");
    const hashtagsBtn = document.getElementById("aiHashtags");

    if (generateBtn) {
        generateBtn.addEventListener("click", async () => {
            const topic = (document.getElementById("aiTopic")?.value || "").trim();
            const tone = document.getElementById("aiTone")?.value || "احترافي";
            const length = document.getElementById("aiLength")?.value || "متوسط";
            if (!topic) {
                toast("أدخل موضوع المنشور أولاً", "error");
                return;
            }
            generateBtn.disabled = true;
            generateBtn.textContent = "جاري التوليد...";
            try {
                const r = await apiFetchJson("/publisher/api/ai/generate_post", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ topic, tone, length }),
                });
                if (r.success) {
                    const outText = r.text || r?.data?.text || "";
                    const postText = document.getElementById("postText");
                    if (postText) postText.value = outText;
                    updatePreview();
                    toast("تم توليد النص بنجاح", "success");
                } else {
                    toast(r.message || "خطأ في التوليد", "error");
                }
            } catch (e) {
                toast("خطأ في الاتصال", "error");
            } finally {
                generateBtn.disabled = false;
                generateBtn.textContent = "توليد نص";
            }
        });
    }

    if (rewriteBtn) {
        rewriteBtn.addEventListener("click", async () => {
            const text = (document.getElementById("postText")?.value || "").trim();
            if (!text) {
                toast("أدخل نصاً لإعادة صياغته", "error");
                return;
            }
            rewriteBtn.disabled = true;
            rewriteBtn.textContent = "جاري المعالجة...";
            try {
                const tone = document.getElementById("aiTone")?.value || "احترافي";
                const r = await apiFetchJson("/publisher/api/ai/rewrite", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text, tone }),
                });
                if (r.success) {
                    const outText = r.text || r?.data?.text || "";
                    const postText = document.getElementById("postText");
                    if (postText) postText.value = outText;
                    updatePreview();
                    toast("تمت إعادة الصياغة", "success");
                } else {
                    toast(r.message || "خطأ", "error");
                }
            } catch (e) {
                toast("خطأ في الاتصال", "error");
            } finally {
                rewriteBtn.disabled = false;
                rewriteBtn.textContent = "إعادة صياغة";
            }
        });
    }

    if (hashtagsBtn) {
        hashtagsBtn.addEventListener("click", async () => {
            const topic =
                (document.getElementById("aiTopic")?.value || "").trim() ||
                (document.getElementById("postText")?.value || "").trim().slice(0, 60);
            if (!topic) {
                toast("أدخل موضوعاً أو نصاً أولاً", "error");
                return;
            }
            hashtagsBtn.disabled = true;
            hashtagsBtn.textContent = "جاري الإنشاء...";
            try {
                const r = await apiFetchJson("/publisher/api/ai/hashtags", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ topic }),
                });
                if (r.success) {
                    const tags = (r.hashtags || r?.data?.hashtags || []).join(" ");
                    const area = document.getElementById("postText");
                    if (area) area.value = (area.value + "\n\n" + tags).trim();
                    updatePreview();
                    toast("تمت إضافة الهاشتاقات", "success");
                } else {
                    toast(r.message || "خطأ", "error");
                }
            } catch (e) {
                toast("خطأ في الاتصال", "error");
            } finally {
                hashtagsBtn.disabled = false;
                hashtagsBtn.textContent = "هاشتاقات";
            }
        });
    }
}

function updatePreview() {
    const text = document.getElementById("postText")?.value || "";
    const prev = document.getElementById("previewBody");
    if (prev) prev.textContent = text || "ابدأ الكتابة لعرض المعاينة...";

    const selectedPageLabels = Array.from(document.querySelectorAll('input[name="page_ids"]:checked'))
        .map((checkbox) => checkbox.closest("label")?.querySelector(".page-chip")?.textContent?.trim())
        .filter(Boolean);

    const previewPageName = document.getElementById("previewPageName");
    if (previewPageName) {
        previewPageName.textContent = selectedPageLabels[0] || "اسم صفحتك";
    }

    const scheduleValue = document.getElementById("scheduleTime")?.value || "";
    const previewMetaLine = document.getElementById("previewMetaLine");
    if (previewMetaLine) {
        if (publishMode === "scheduled" && scheduleValue) {
            previewMetaLine.textContent = "مجدول · " + fmtDate(scheduleValue);
        } else if (publishMode === "scheduled") {
            previewMetaLine.textContent = "مجدول · بانتظار تحديد الوقت";
        } else {
            previewMetaLine.textContent = "الآن · Public";
        }
    }

    const selectedPagesWrap = document.getElementById("previewSelectedPages");
    if (selectedPagesWrap) {
        selectedPagesWrap.innerHTML = selectedPageLabels
            .map((label) => `<span class="prev-page-chip">${escapeHtml(label)}</span>`)
            .join("");
    }

    const charCount = text.length;
    const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
    const hashCount = (text.match(/#[\w\u0600-\u06FF]+/g) || []).length;

    const charCountEl = document.getElementById("previewCharCount");
    const wordCountEl = document.getElementById("previewWordCount");
    const hashCountEl = document.getElementById("previewHashCount");
    if (charCountEl) charCountEl.textContent = `${charCount} حرف`;
    if (wordCountEl) wordCountEl.textContent = `${wordCount} كلمة`;
    if (hashCountEl) hashCountEl.textContent = `${hashCount} هاشتاق`;

    const mediaPrev = document.getElementById("previewMedia");
    const mediaGrid = document.getElementById("previewMediaGrid");
    if (!mediaPrev || !mediaGrid) return;
    if (selectedMediaIds.length === 0) {
        mediaPrev.style.display = "none";
        mediaGrid.innerHTML = "";
        return;
    }
    mediaPrev.style.display = "block";
    mediaGrid.innerHTML = buildPreviewMediaHtml();
}

function buildPreviewMediaHtml() {
    const metaMap = new Map(
        (selectedMediaMeta || []).map((item) => [Number(item.id), item])
    );
    const topThree = selectedMediaIds.slice(0, 3).map((id) => metaMap.get(Number(id)));
    const rendered = topThree
        .map((item) => {
            if (!item) {
                return '<div class="prev-media-item">IMG</div>';
            }
            if (item.media_type === "image" && item.url_path) {
                return `<div class="prev-media-item"><img src="${escapeHtml(item.url_path)}" alt="${escapeHtml(item.original_name || item.filename || "media")}"></div>`;
            }
            if (item.media_type === "video") {
                return '<div class="prev-media-item">VIDEO</div>';
            }
            return '<div class="prev-media-item">MEDIA</div>';
        })
        .join("");
    const more = selectedMediaIds.length > 3
        ? `<div class="prev-media-more">+${selectedMediaIds.length - 3}</div>`
        : "";
    return rendered + more;
}

function openMediaPickerModal() {
    persistSelectedMediaToStorage();
    window.location.href = "/publisher/media?returnTo=create";
}

function restoreSelectedMediaFromStorage() {
    try {
        const raw = sessionStorage.getItem(SELECTED_MEDIA_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return;
        selectedMediaIds = parsed.map((v) => Number(v)).filter((v) => Number.isInteger(v));
        const metaRaw = sessionStorage.getItem(SELECTED_MEDIA_META_KEY);
        if (metaRaw) {
            const metaParsed = JSON.parse(metaRaw);
            if (Array.isArray(metaParsed)) {
                selectedMediaMeta = metaParsed.map((item) => ({
                    id: Number(item.id),
                    media_type: item.media_type,
                    url_path: item.url_path,
                    original_name: item.original_name,
                    filename: item.filename,
                }));
            }
        }
    } catch {
        selectedMediaIds = [];
        selectedMediaMeta = [];
    }
}

function persistSelectedMediaToStorage() {
    try {
        sessionStorage.setItem(SELECTED_MEDIA_KEY, JSON.stringify(selectedMediaIds || []));
        sessionStorage.setItem(SELECTED_MEDIA_META_KEY, JSON.stringify(selectedMediaMeta || []));
    } catch {
        // ignore
    }
}

function updateSelectedMediaChip() {
    const chip = document.getElementById("selectedChip");
    if (!chip) return;
    chip.textContent = selectedMediaIds.length ? `${selectedMediaIds.length} وسيط مختار` : "";
}

function setPublishStatus(type, message) {
    const box = document.getElementById("publishStatusBox");
    if (!box) return;
    box.style.display = "block";
    box.textContent = message || "";
    if (type === "success") {
        box.style.borderColor = "rgba(16,185,129,0.45)";
        box.style.color = "#6ee7b7";
    } else if (type === "error") {
        box.style.borderColor = "rgba(239,68,68,0.45)";
        box.style.color = "#fda4af";
    } else {
        box.style.borderColor = "rgba(56,189,248,0.45)";
        box.style.color = "#93c5fd";
    }
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForPostFinalStatus(postId, timeoutMs = 30000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
        const list = await API.posts();
        const posts = extractItems(list, "posts");
        const post = posts.find((p) => Number(p.id) === Number(postId));
        if (post && ["published", "failed", "partial"].includes(post.status)) return post;
        await sleep(2000);
    }
    return null;
}

async function submitPost(e) {
    e.preventDefault();
    const text = document.getElementById("postText")?.value || "";
    const textForValidation = text.trim();
    const pageCheckboxes = document.querySelectorAll('input[name="page_ids"]:checked');
    const page_ids = Array.from(pageCheckboxes).map((c) => c.value);

    if (!page_ids.length) {
        toast("اختر صفحة واحدة على الأقل", "error");
        return;
    }
    if (!textForValidation && !selectedMediaIds.length) {
        toast("أدخل نصاً أو أرفق وسيطاً", "error");
        return;
    }

    const btn = document.getElementById("submitBtn");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "جاري الإرسال...";
    }
    setPublishStatus(
        "info",
        publishMode === "scheduled" ? "جاري حفظ الجدولة..." : "جاري محاولة النشر الفوري..."
    );

    try {
        let endpoint = "/publisher/api/posts/create";
        const body = { text, page_ids, media_ids: selectedMediaIds };
        if (publishMode === "scheduled") {
            const dt = document.getElementById("scheduleTime")?.value || "";
            if (!dt) {
                toast("حدد وقت الجدولة", "error");
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = "جدولة المنشور";
                }
                return;
            }
            endpoint = "/publisher/api/posts/schedule";
            body.publish_time = dt;
            body.timezone_offset_minutes = new Date().getTimezoneOffset();
        }

        const r = await apiFetchJson(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        if (r.success) {
            toast(r.message || "تمت العملية بنجاح", "success");
            const post = extractPost(r);
            if (publishMode === "scheduled") {
                setPublishStatus("success", r.message || "تمت الجدولة بنجاح");
                document.getElementById("postForm")?.reset();
                selectedMediaIds = [];
                selectedMediaMeta = [];
                sessionStorage.removeItem(SELECTED_MEDIA_KEY);
                sessionStorage.removeItem(SELECTED_MEDIA_META_KEY);
                updateSelectedMediaChip();
                updatePreview();
            } else if (post.status === "published") {
                setPublishStatus("success", "تم النشر الفوري بنجاح");
                document.getElementById("postForm")?.reset();
                selectedMediaIds = [];
                selectedMediaMeta = [];
                sessionStorage.removeItem(SELECTED_MEDIA_KEY);
                sessionStorage.removeItem(SELECTED_MEDIA_META_KEY);
                updateSelectedMediaChip();
                updatePreview();
            } else if (post.status === "partial") {
                setPublishStatus("info", "تم النشر جزئياً على بعض الصفحات.");
            } else if (post.id) {
                setPublishStatus("info", "تم إرسال الطلب، جاري تتبع الحالة...");
                const finalPost = await waitForPostFinalStatus(post.id, 30000);
                if (!finalPost) {
                    setPublishStatus("info", "تم استلام الطلب، راجع لوحة التحكم خلال دقيقة.");
                } else if (finalPost.status === "published") {
                    setPublishStatus("success", "اكتمل النشر بنجاح");
                } else if (finalPost.status === "partial") {
                    setPublishStatus("info", "تم النشر جزئياً.");
                } else {
                    setPublishStatus("error", "فشل النشر: " + (finalPost.error_message || "تحقق من الإعدادات."));
                }
            }
        } else {
            const post = extractPost(r);
            if (publishMode === "now" && post.id && ["queued", "publishing"].includes(post.status)) {
                setPublishStatus("info", r.message || "تعذر الإكمال الفوري، جاري التتبع عبر المجدول...");
                const finalPost = await waitForPostFinalStatus(post.id, 60000);
                if (!finalPost) {
                    setPublishStatus("info", "المنشور في الانتظار. راجع لوحة التحكم خلال دقيقة.");
                } else if (finalPost.status === "published") {
                    setPublishStatus("success", "اكتمل النشر عبر المجدول");
                } else if (finalPost.status === "partial") {
                    setPublishStatus("info", "تم النشر جزئياً عبر المجدول.");
                } else {
                    setPublishStatus("error", "فشل النشر: " + (finalPost.error_message || "تحقق من الإعدادات."));
                }
            } else {
                setPublishStatus("error", r.message || "خطأ في النشر");
                toast(r.message || "خطأ", "error");
            }
        }
    } catch (err) {
        setPublishStatus("error", "خطأ في الاتصال بالخادم");
        toast("خطأ في الاتصال بالخادم", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = publishMode === "scheduled" ? "جدولة المنشور" : "نشر الآن";
        }
    }
}
