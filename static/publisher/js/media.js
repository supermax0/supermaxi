/* ── media.js — Media Library Upload & Grid ── */

let allMedia = [];
let activeTab = 'all';
let searchQ = '';
let selectedForPost = new Set();
const SELECTED_MEDIA_KEY = 'publisher_selected_media_ids';

async function apiFetchJson(url, options = {}) {
    const opts = {
        credentials: 'include',
        ...options,
        headers: {
            Accept: 'application/json',
            ...(options.headers || {}),
        },
    };
    const res = await fetch(url, opts);
    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        return { success: false, message: 'استجابة غير صالحة من الخادم' };
    }
    const data = await res.json();
    if (res.status === 401 && !data.message) {
        data.message = 'Unauthorized';
    }
    return data;
}

/* ── API helpers ─────────────── */
async function loadMedia() {
    const params = new URLSearchParams();
    if (searchQ) params.set('q', searchQ);
    if (activeTab !== 'all') params.set('type', activeTab);
    const r = await apiFetchJson('/publisher/api/media?' + params);
    allMedia = r.media || [];
    syncSelectedFromStorage();
    renderGrid();
}

async function deleteMedia(id) {
    if (!confirm('هل تريد حذف هذا الوسيط؟')) return;
    const r = await apiFetchJson('/publisher/api/media/' + id, { method: 'DELETE' });
    if (r.success) {
        allMedia = allMedia.filter(m => m.id !== id);
        selectedForPost.delete(id);
        renderGrid();
        toast('تم الحذف', 'success');
    } else {
        toast(r.message || 'خطأ في الحذف', 'error');
    }
}

/* ── Toast (shared) ──────────── */
function toast(msg, type = 'info') {
    let wrap = document.getElementById('toastWrap');
    if (!wrap) {
        wrap = document.createElement('div');
        wrap.id = 'toastWrap';
        wrap.className = 'pub-toast-wrap';
        document.body.appendChild(wrap);
    }
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    const t = document.createElement('div');
    t.className = 'pub-toast ' + type;
    t.innerHTML = '<span>' + (icons[type] || 'ℹ️') + '</span><span>' + msg + '</span>';
    wrap.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

/* ── Format helpers ──────────── */
function fmtSize(b) {
    if (!b) return '';
    if (b < 1024) return b + ' B';
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
    return (b / (1024 * 1024)).toFixed(1) + ' MB';
}

/* ── Render Grid ─────────────── */
function renderGrid() {
    const grid = document.getElementById('mediaGrid');
    if (!grid) return;
    const chip = document.getElementById('selectedChip');
    if (chip) chip.textContent = selectedForPost.size ? '✔ ' + selectedForPost.size + ' مختار' : '';
    if (!allMedia.length) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-icon">🖼️</div><p>لا توجد وسائط — ارفع أولاً</p></div>';
        return;
    }
    grid.innerHTML = allMedia.map(m => {
        const isSelected = selectedForPost.has(m.id);
        const mediaUrl = normalizeMediaUrl(m.url_path);
        const thumb = m.media_type === 'image'
            ? '<img src="' + mediaUrl + '" alt="' + (m.original_name || '') + '" loading="lazy">'
            : '<div class="vid-icon">🎬</div>';
        return '<div class="media-card' + (isSelected ? ' selected' : '') + '" data-id="' + m.id + '" onclick="toggleSelect(' + m.id + ')">' +
            '<div class="media-sel-badge">✓</div>' +
            '<div class="media-thumb">' + thumb + '</div>' +
            '<div class="media-info">' +
            '<div class="media-name">' + (m.original_name || m.filename) + '</div>' +
            '<div class="media-size">' + fmtSize(m.size_bytes) + '</div>' +
            '</div>' +
            '<div class="media-actions" onclick="event.stopPropagation()">' +
            '<button class="btn-icon btn-sm" title="حذف" onclick="deleteMedia(' + m.id + ')">🗑️</button>' +
            '</div>' +
            '</div>';
    }).join('');
}

function toggleSelect(id) {
    if (selectedForPost.has(id)) {
        selectedForPost.delete(id);
    } else {
        selectedForPost.add(id);
    }
    persistSelectedToStorage();
    renderGrid();
}

function normalizeMediaUrl(urlPath) {
    if (!urlPath) return '';
    if (urlPath.startsWith('/media/')) {
        // Legacy rows in DB
        return '/publisher/media-file/' + urlPath.replace(/^\/media\//, '');
    }
    return urlPath;
}

function persistSelectedToStorage() {
    try {
        const ids = Array.from(selectedForPost);
        sessionStorage.setItem(SELECTED_MEDIA_KEY, JSON.stringify(ids));
    } catch (e) {
        // ignore
    }
}

function syncSelectedFromStorage() {
    try {
        const raw = sessionStorage.getItem(SELECTED_MEDIA_KEY);
        if (!raw) return;
        const ids = JSON.parse(raw);
        if (!Array.isArray(ids)) return;
        selectedForPost = new Set(ids.map(v => Number(v)).filter(v => Number.isInteger(v)));
    } catch (e) {
        // ignore
    }
}

function goToCreateWithSelectedMedia() {
    persistSelectedToStorage();
    window.location.href = '/publisher/create';
}

/* ── Drag & Drop Upload ──────── */
function initDropZone() {
    const zone = document.getElementById('dropZone');
    const input = document.getElementById('fileInput');
    const progressWrap = document.getElementById('progressWrap');
    const progressBar = document.getElementById('progressBar');

    if (!zone || !input) return;

    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('drag-over');
        uploadFiles(e.dataTransfer.files);
    });
    input.addEventListener('change', () => uploadFiles(input.files));

    function uploadFiles(files) {
        Array.from(files).forEach(file => uploadFile(file));
    }

    function uploadFile(file) {
        const fd = new FormData();
        fd.append('file', file);

        progressWrap.style.display = 'block';
        progressBar.style.width = '0%';

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/publisher/api/media/upload');
        xhr.withCredentials = true;
        xhr.setRequestHeader('Accept', 'application/json');

        xhr.upload.addEventListener('progress', e => {
            if (e.lengthComputable) {
                progressBar.style.width = (e.loaded / e.total * 100).toFixed(0) + '%';
            }
        });

        xhr.addEventListener('load', () => {
            progressWrap.style.display = 'none';
            try {
                const r = JSON.parse(xhr.responseText);
                if (xhr.status === 401) {
                    toast('انتهت الجلسة. سجّل الدخول مرة أخرى.', 'error');
                } else if (r.success) {
                    toast('تم رفع: ' + file.name, 'success');
                    loadMedia();
                } else {
                    toast(r.message || 'خطأ في الرفع', 'error');
                }
            } catch (e) { toast('خطأ غير متوقع', 'error'); }
            input.value = '';
        });

        xhr.addEventListener('error', () => {
            progressWrap.style.display = 'none';
            toast('خطأ في الاتصال بالخادم', 'error');
        });

        xhr.send(fd);
    }
}

/* ── Tabs ────────────────────── */
function initTabs() {
    document.querySelectorAll('.media-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            activeTab = tab.dataset.type || 'all';
            document.querySelectorAll('.media-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            loadMedia();
        });
    });
}

/* ── Search ──────────────────── */
function initSearch() {
    const input = document.getElementById('mediaSearch');
    if (!input) return;
    let timer;
    input.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(() => { searchQ = input.value.trim(); loadMedia(); }, 350);
    });
}

/* ── Init ────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    syncSelectedFromStorage();
    initDropZone();
    initTabs();
    initSearch();
    const useBtn = document.getElementById('useInPostBtn');
    if (useBtn) {
        useBtn.addEventListener('click', () => {
            if (!selectedForPost.size) {
                toast('اختر وسيطاً واحداً على الأقل أولاً', 'error');
                return;
            }
            goToCreateWithSelectedMedia();
        });
    }
    loadMedia();
});
