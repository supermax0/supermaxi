/* media.js — Media Library interactions */

let allMedia = [];
let activeTab = "all";
let searchQ = "";
let selectedForPost = new Set();
const SELECTED_MEDIA_KEY = "publisher_selected_media_ids";

async function mediaFetchJson(url, options = {}) {
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

function mediaToast(message, type = "info") {
    const wrap = document.getElementById("toastWrap");
    if (!wrap) return;
    const t = document.createElement("div");
    t.className = "pub-toast " + type;
    t.textContent = message || "";
    wrap.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

function mediaExtractItems(payload, legacyKey) {
    if (payload?.data?.items && Array.isArray(payload.data.items)) return payload.data.items;
    if (payload?.data && Array.isArray(payload.data)) return payload.data;
    if (legacyKey && Array.isArray(payload?.[legacyKey])) return payload[legacyKey];
    return [];
}

function escapeHtml(value) {
    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function fmtSize(bytes) {
    if (!bytes) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function normalizeMediaUrl(urlPath) {
    if (!urlPath) return "";
    if (urlPath.startsWith("/media/")) {
        return "/publisher/media-file/" + urlPath.replace(/^\/media\//, "");
    }
    return urlPath;
}

async function loadMedia() {
    const params = new URLSearchParams();
    if (searchQ) params.set("q", searchQ);
    if (activeTab !== "all") params.set("type", activeTab);
    const r = await mediaFetchJson("/publisher/api/media?" + params.toString());
    allMedia = mediaExtractItems(r, "media");
    syncSelectedFromStorage();
    renderGrid();
}

function renderGrid() {
    const grid = document.getElementById("mediaGrid");
    if (!grid) return;
    const chip = document.getElementById("selectedChip");
    if (chip) chip.textContent = selectedForPost.size ? `${selectedForPost.size} مختار` : "";

    if (!allMedia.length) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><p>لا توجد وسائط. ابدأ برفع ملفات جديدة.</p></div>';
        return;
    }

    grid.innerHTML = allMedia
        .map((m) => {
            const mediaUrl = normalizeMediaUrl(m.url_path);
            const isSelected = selectedForPost.has(m.id);
            const thumb =
                m.media_type === "image"
                    ? `<img src="${escapeHtml(mediaUrl)}" alt="${escapeHtml(m.original_name || m.filename)}" loading="lazy">`
                    : '<div class="vid-icon">🎬</div>';
            return (
                `<div class="media-card${isSelected ? " selected" : ""}" data-id="${m.id}" onclick="toggleSelect(${m.id})">` +
                '<div class="media-sel-badge">✓</div>' +
                `<div class="media-thumb">${thumb}</div>` +
                '<div class="media-info">' +
                `<div class="media-name">${escapeHtml(m.original_name || m.filename)}</div>` +
                `<div class="media-size">${fmtSize(m.size_bytes)}</div>` +
                "</div>" +
                '<div class="media-actions" onclick="event.stopPropagation()">' +
                `<button class="btn-icon btn-sm" type="button" title="حذف" onclick="deleteMediaItem(${m.id})">حذف</button>` +
                "</div>" +
                "</div>"
            );
        })
        .join("");
}

function toggleSelect(id) {
    if (selectedForPost.has(id)) selectedForPost.delete(id);
    else selectedForPost.add(id);
    persistSelectedToStorage();
    renderGrid();
}

function persistSelectedToStorage() {
    try {
        sessionStorage.setItem(SELECTED_MEDIA_KEY, JSON.stringify(Array.from(selectedForPost)));
    } catch {
        // ignore
    }
}

function syncSelectedFromStorage() {
    try {
        const raw = sessionStorage.getItem(SELECTED_MEDIA_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return;
        selectedForPost = new Set(parsed.map((v) => Number(v)).filter((v) => Number.isInteger(v)));
    } catch {
        // ignore
    }
}

function goToCreateWithSelectedMedia() {
    persistSelectedToStorage();
    window.location.href = "/publisher/create";
}

async function deleteMediaItem(id) {
    if (!confirm("هل تريد حذف هذا الوسيط؟")) return;
    const r = await mediaFetchJson("/publisher/api/media/" + id, { method: "DELETE" });
    if (r.success) {
        allMedia = allMedia.filter((m) => Number(m.id) !== Number(id));
        selectedForPost.delete(id);
        renderGrid();
        mediaToast("تم حذف الوسيط", "success");
    } else {
        mediaToast(r.message || "خطأ في الحذف", "error");
    }
}

function initDropZone() {
    const zone = document.getElementById("dropZone");
    const input = document.getElementById("fileInput");
    const progressWrap = document.getElementById("progressWrap");
    const progressBar = document.getElementById("progressBar");
    if (!zone || !input || !progressWrap || !progressBar) return;

    zone.addEventListener("dragover", (e) => {
        e.preventDefault();
        zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", (e) => {
        e.preventDefault();
        zone.classList.remove("drag-over");
        uploadFiles(e.dataTransfer.files);
    });
    input.addEventListener("change", () => uploadFiles(input.files));

    function uploadFiles(files) {
        Array.from(files || []).forEach((file) => uploadFile(file));
    }

    function uploadFile(file) {
        const fd = new FormData();
        fd.append("file", file);
        progressWrap.style.display = "block";
        progressBar.style.width = "0%";

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/publisher/api/media/upload");
        xhr.withCredentials = true;
        xhr.setRequestHeader("Accept", "application/json");

        xhr.upload.addEventListener("progress", (e) => {
            if (!e.lengthComputable) return;
            progressBar.style.width = (e.loaded / e.total * 100).toFixed(0) + "%";
        });

        xhr.addEventListener("load", () => {
            progressWrap.style.display = "none";
            try {
                const r = JSON.parse(xhr.responseText || "{}");
                if (xhr.status === 401) {
                    mediaToast("انتهت الجلسة. سجّل الدخول مرة أخرى.", "error");
                } else if (r.success) {
                    mediaToast("تم رفع: " + file.name, "success");
                    loadMedia();
                } else {
                    mediaToast(r.message || "خطأ في الرفع", "error");
                }
            } catch {
                mediaToast("خطأ غير متوقع", "error");
            }
            input.value = "";
        });

        xhr.addEventListener("error", () => {
            progressWrap.style.display = "none";
            mediaToast("خطأ في الاتصال بالخادم", "error");
        });

        xhr.send(fd);
    }
}

function initTabs() {
    document.querySelectorAll(".media-tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            activeTab = tab.dataset.type || "all";
            document.querySelectorAll(".media-tab").forEach((t) => t.classList.remove("active"));
            tab.classList.add("active");
            loadMedia();
        });
    });
}

function initSearch() {
    const input = document.getElementById("mediaSearch");
    if (!input) return;
    let timer = null;
    input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
            searchQ = input.value.trim();
            loadMedia();
        }, 300);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    syncSelectedFromStorage();
    initDropZone();
    initTabs();
    initSearch();

    document.getElementById("useInPostBtn")?.addEventListener("click", () => {
        if (!selectedForPost.size) {
            mediaToast("اختر وسيطاً واحداً على الأقل أولاً", "error");
            return;
        }
        goToCreateWithSelectedMedia();
    });

    loadMedia();
});
