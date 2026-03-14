/* ── media.js — Media Library Upload & Grid ── */

let allMedia = [];
let activeTab = 'all';
let searchQ = '';
let selectedForPost = new Set();

/* ── API helpers ─────────────── */
async function loadMedia() {
    const params = new URLSearchParams();
    if (searchQ) params.set('q', searchQ);
    if (activeTab !== 'all') params.set('type', activeTab);
    const r = await fetch('/publisher/api/media?' + params).then(r => r.json());
    allMedia = r.media || [];
    renderGrid();
}

async function deleteMedia(id) {
    if (!confirm('هل تريد حذف هذا الوسيط؟')) return;
    const r = await fetch('/publisher/api/media/' + id, { method: 'DELETE' }).then(r => r.json());
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
    if (!allMedia.length) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-icon">🖼️</div><p>لا توجد وسائط — ارفع أولاً</p></div>';
        return;
    }
    grid.innerHTML = allMedia.map(m => {
        const isSelected = selectedForPost.has(m.id);
        const thumb = m.media_type === 'image'
            ? '<img src="' + m.url_path + '" alt="' + (m.original_name || '') + '" loading="lazy">'
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
    renderGrid();
    const chip = document.getElementById('selectedChip');
    if (chip) chip.textContent = selectedForPost.size ? '✔ ' + selectedForPost.size + ' مختار' : '';
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

        xhr.upload.addEventListener('progress', e => {
            if (e.lengthComputable) {
                progressBar.style.width = (e.loaded / e.total * 100).toFixed(0) + '%';
            }
        });

        xhr.addEventListener('load', () => {
            progressWrap.style.display = 'none';
            try {
                const r = JSON.parse(xhr.responseText);
                if (r.success) {
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
    initDropZone();
    initTabs();
    initSearch();
    loadMedia();
});
