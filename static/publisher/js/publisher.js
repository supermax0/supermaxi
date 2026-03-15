/* ── publisher.js — Dashboard & Posts logic ── */
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

const SELECTED_MEDIA_KEY = 'publisher_selected_media_ids';

const API = {
    base: '/publisher',
    pages: () => apiFetchJson('/publisher/api/pages'),
    posts: (status = '') => apiFetchJson(`/publisher/api/posts${status ? '?status=' + status : ''}`),
};

/* ── Toast ─────────────────────────────────── */
function toast(msg, type = 'info') {
    const wrap = document.getElementById('toastWrap') || (() => {
        const d = document.createElement('div');
        d.id = 'toastWrap';
        d.className = 'pub-toast-wrap';
        document.body.appendChild(d);
        return d;
    })();
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };
    const t = document.createElement('div');
    t.className = 'pub-toast ' + type;
    t.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${msg}</span>`;
    wrap.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

/* ── Status badge ───────────────────────────── */
function statusBadge(status) {
    const map = {
        draft: ['badge-draft', 'مسودة'],
        queued: ['badge-queued', 'في الانتظار'],
        scheduled: ['badge-scheduled', 'مجدول'],
        publishing: ['badge-publishing', 'ينشر…'],
        published: ['badge-published', 'منشور'],
        failed: ['badge-failed', 'فشل'],
        partial: ['badge-partial', 'جزئي'],
    };
    const [cls, label] = map[status] || ['badge-draft', status];
    return `<span class="badge ${cls}">${label}</span>`;
}

/* ── Format date ────────────────────────────── */
function fmtDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('ar-SA', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

/* ── Truncate ───────────────────────────────── */
function trunc(text, n = 60) {
    if (!text) return '—';
    return text.length > n ? text.slice(0, n) + '…' : text;
}

/* ═══════════════════════════════════════════════
   Dashboard
═══════════════════════════════════════════════ */
async function initDashboard() {
    await Promise.all([loadStats(), loadRecentPosts()]);
}

async function loadStats() {
    try {
        const data = await API.posts();
        const posts = data.posts || [];
        const count = s => posts.filter(p => p.status === s).length;
        document.getElementById('statTotal').textContent = posts.length;
        document.getElementById('statScheduled').textContent = count('scheduled');
        document.getElementById('statPublished').textContent = count('published');
        document.getElementById('statFailed').textContent = count('failed');
    } catch (e) { console.error('loadStats', e); }
}

async function loadRecentPosts() {
    const tbody = document.getElementById('postsBody');
    if (!tbody) return;
    try {
        const data = await API.posts();
        const posts = (data.posts || []).slice(0, 20);
        if (!posts.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:40px;color:var(--text-muted)">لا توجد منشورات بعد</td></tr>';
            return;
        }
        tbody.innerHTML = posts.map(p => {
            const pageCount = (p.page_ids || []).length;
            return '<tr>' +
                '<td>' + trunc(p.text, 50) + '</td>' +
                '<td>' + statusBadge(p.status) + '</td>' +
                '<td>' + pageCount + ' صفحة' + '</td>' +
                '<td>' + fmtDate(p.created_at) + '</td>' +
                '</tr>';
        }).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4">خطأ في تحميل البيانات</td></tr>';
    }
}

/* ═══════════════════════════════════════════════
   Create Post
═══════════════════════════════════════════════ */
let selectedMediaIds = [];
let publishMode = 'now';  // 'now' | 'scheduled'

async function initCreatePost() {
    restoreSelectedMediaFromStorage();
    await loadPageSelector();
    initPublishToggle();
    initAiTools();
    updateSelectedMediaChip();
    updatePreview();
    document.getElementById('postForm').addEventListener('submit', submitPost);
    document.getElementById('postText').addEventListener('input', updatePreview);
    document.getElementById('openMediaPicker').addEventListener('click', openMediaPickerModal);
}

async function loadPageSelector() {
    const wrap = document.getElementById('pagesWrap');
    if (!wrap) return;
    try {
        const data = await API.pages();
        const pages = data.pages || [];
        if (!pages.length) {
            wrap.innerHTML = '<p style="color:var(--text-muted);font-size:13px">لا توجد صفحات مربوطة — <a href="/publisher/settings" style="color:#a5b4fc">ربط صفحة</a></p>';
            return;
        }
        wrap.innerHTML = pages.map(p =>
            '<label>' +
            '<input type="checkbox" class="page-checkbox" name="page_ids" value="' + p.page_id + '">' +
            '<span class="page-chip">📄 ' + p.page_name + '</span>' +
            '</label>'
        ).join('');
    } catch (e) { console.error('loadPageSelector', e); }
}

function initPublishToggle() {
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            publishMode = btn.dataset.mode;
            document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const schedField = document.getElementById('scheduleField');
            if (schedField) schedField.style.display = publishMode === 'scheduled' ? 'block' : 'none';
        });
    });
}

function initAiTools() {
    const generateBtn = document.getElementById('aiGenerate');
    const rewriteBtn = document.getElementById('aiRewrite');
    const hashtagsBtn = document.getElementById('aiHashtags');

    if (generateBtn) {
        generateBtn.addEventListener('click', async () => {
            const topic = document.getElementById('aiTopic').value.trim();
            const tone = document.getElementById('aiTone').value;
            const length = document.getElementById('aiLength').value;
            if (!topic) { toast('أدخل موضوع المنشور أولاً', 'error'); return; }
            generateBtn.disabled = true;
            generateBtn.innerHTML = '<span class="spinner"></span> جاري التوليد…';
            try {
                const r = await apiFetchJson('/publisher/api/ai/generate_post', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ topic, tone, length })
                });
                if (r.success) {
                    document.getElementById('postText').value = r.text;
                    updatePreview();
                    toast('تم توليد النص بنجاح', 'success');
                } else { toast(r.message || 'خطأ في التوليد', 'error'); }
            } catch (e) { toast('خطأ في الاتصال', 'error'); }
            finally { generateBtn.disabled = false; generateBtn.innerHTML = '✨ توليد'; }
        });
    }

    if (rewriteBtn) {
        rewriteBtn.addEventListener('click', async () => {
            const text = document.getElementById('postText').value.trim();
            if (!text) { toast('أدخل نصاً لإعادة صياغته', 'error'); return; }
            rewriteBtn.disabled = true;
            rewriteBtn.innerHTML = '<span class="spinner"></span>';
            try {
                const tone = document.getElementById('aiTone').value;
                const r = await apiFetchJson('/publisher/api/ai/rewrite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text, tone })
                });
                if (r.success) {
                    document.getElementById('postText').value = r.text;
                    updatePreview();
                    toast('تمت إعادة الصياغة', 'success');
                } else { toast(r.message, 'error'); }
            } catch (e) { toast('خطأ في الاتصال', 'error'); }
            finally { rewriteBtn.disabled = false; rewriteBtn.innerHTML = '🔄 إعادة صياغة'; }
        });
    }

    if (hashtagsBtn) {
        hashtagsBtn.addEventListener('click', async () => {
            const topic = document.getElementById('aiTopic').value.trim() ||
                document.getElementById('postText').value.trim().slice(0, 60);
            if (!topic) { toast('أدخل موضوعاً أو نصاً أولاً', 'error'); return; }
            hashtagsBtn.disabled = true;
            try {
                const r = await apiFetchJson('/publisher/api/ai/hashtags', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ topic })
                });
                if (r.success) {
                    const area = document.getElementById('postText');
                    area.value = (area.value + '\n\n' + r.hashtags.join(' ')).trim();
                    updatePreview();
                    toast('تم إضافة الهاشتاقات', 'success');
                } else { toast(r.message, 'error'); }
            } catch (e) { toast('خطأ', 'error'); }
            finally { hashtagsBtn.disabled = false; hashtagsBtn.innerHTML = '#️⃣ هاشتاقات'; }
        });
    }
}

function updatePreview() {
    const text = document.getElementById('postText').value;
    const prev = document.getElementById('previewBody');
    if (prev) prev.textContent = text || 'نص المنشور يظهر هنا…';
    const mediaPrev = document.getElementById('previewMedia');
    if (mediaPrev) {
        if (selectedMediaIds.length) {
            mediaPrev.style.display = 'block';
            mediaPrev.innerHTML = '<span>🖼️ وسائط مرفقة: ' + selectedMediaIds.length + '</span>';
        } else {
            mediaPrev.style.display = 'none';
            mediaPrev.innerHTML = '<span>صورة / فيديو</span>';
        }
    }
}

function openMediaPickerModal() {
    persistSelectedMediaToStorage();
    window.location.href = '/publisher/media?returnTo=create';
}

function restoreSelectedMediaFromStorage() {
    try {
        const raw = sessionStorage.getItem(SELECTED_MEDIA_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return;
        selectedMediaIds = parsed.map(v => Number(v)).filter(v => Number.isInteger(v));
    } catch (e) {
        selectedMediaIds = [];
    }
}

function persistSelectedMediaToStorage() {
    try {
        sessionStorage.setItem(SELECTED_MEDIA_KEY, JSON.stringify(selectedMediaIds || []));
    } catch (e) {
        // ignore
    }
}

function updateSelectedMediaChip() {
    const chip = document.getElementById('selectedChip');
    if (!chip) return;
    chip.textContent = selectedMediaIds.length ? ('✔ ' + selectedMediaIds.length + ' وسيط مختار') : '';
}

function setPublishStatus(type, msg) {
    const box = document.getElementById('publishStatusBox');
    if (!box) return;
    box.style.display = 'block';
    box.textContent = msg || '';
    if (type === 'success') {
        box.style.background = 'rgba(16,185,129,0.12)';
        box.style.border = '1px solid rgba(16,185,129,0.35)';
        box.style.color = '#10b981';
    } else if (type === 'error') {
        box.style.background = 'rgba(239,68,68,0.12)';
        box.style.border = '1px solid rgba(239,68,68,0.35)';
        box.style.color = '#ef4444';
    } else {
        box.style.background = 'rgba(59,130,246,0.12)';
        box.style.border = '1px solid rgba(59,130,246,0.35)';
        box.style.color = '#60a5fa';
    }
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForPostFinalStatus(postId, timeoutMs = 30000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
        const list = await API.posts();
        const post = (list.posts || []).find(p => Number(p.id) === Number(postId));
        if (post && ['published', 'failed', 'partial'].includes(post.status)) return post;
        await sleep(2000);
    }
    return null;
}

async function submitPost(e) {
    e.preventDefault();
    const text = document.getElementById('postText').value.trim();
    const pageCheckboxes = document.querySelectorAll('input[name="page_ids"]:checked');
    const page_ids = Array.from(pageCheckboxes).map(c => c.value);

    if (!page_ids.length) { toast('اختر صفحة واحدة على الأقل', 'error'); return; }
    if (!text && !selectedMediaIds.length) { toast('أدخل نصاً أو أرفق وسيطاً', 'error'); return; }

    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> جاري الإرسال…';
    setPublishStatus('info', publishMode === 'scheduled' ? 'جاري حفظ الجدولة…' : 'جاري محاولة النشر الفوري…');

    try {
        let endpoint = '/publisher/api/posts/create';
        let body = { text, page_ids, media_ids: selectedMediaIds };

        if (publishMode === 'scheduled') {
            const dt = document.getElementById('scheduleTime').value;
            if (!dt) { toast('حدد وقت الجدولة', 'error'); btn.disabled = false; btn.textContent = 'إرسال'; return; }
            endpoint = '/publisher/api/posts/schedule';
            body.publish_time = dt;
        }

        const r = await apiFetchJson(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        if (r.success) {
            toast(r.message || 'تمت العملية بنجاح', 'success');
            if (publishMode === 'scheduled') {
                setPublishStatus('success', r.message || 'تمت الجدولة بنجاح');
                document.getElementById('postForm').reset();
                updatePreview();
                selectedMediaIds = [];
                sessionStorage.removeItem(SELECTED_MEDIA_KEY);
                updateSelectedMediaChip();
            } else {
                const post = r.post || {};
                if (post.status === 'published') {
                    setPublishStatus('success', 'تم النشر الفوري بنجاح ✅');
                    document.getElementById('postForm').reset();
                    updatePreview();
                    selectedMediaIds = [];
                    sessionStorage.removeItem(SELECTED_MEDIA_KEY);
                    updateSelectedMediaChip();
                } else if (post.status === 'partial') {
                    setPublishStatus('info', 'تم النشر جزئياً على بعض الصفحات. راجع لوحة التحكم.');
                } else {
                    setPublishStatus('info', 'تم إرسال الطلب، جاري تتبع حالة النشر…');
                    const finalPost = post.id ? await waitForPostFinalStatus(post.id, 30000) : null;
                    if (!finalPost) {
                        setPublishStatus('info', 'تم استلام الطلب لكن لم تكتمل النتيجة بعد. راجع لوحة التحكم خلال دقيقة.');
                    } else if (finalPost.status === 'published') {
                        setPublishStatus('success', 'اكتمل النشر بنجاح ✅');
                    } else if (finalPost.status === 'partial') {
                        setPublishStatus('info', 'تم النشر جزئياً على بعض الصفحات.');
                    } else {
                        setPublishStatus('error', 'فشل النشر: ' + (finalPost.error_message || 'تحقق من التوكن وصلاحيات الصفحة.'));
                    }
                }
            }
        } else {
            const post = r.post || {};
            if (publishMode === 'now' && post.id && ['queued', 'publishing'].includes(post.status)) {
                setPublishStatus('info', r.message || 'تعذر إكمال النشر الفوري، جاري تتبع النشر عبر المجدول…');
                const finalPost = await waitForPostFinalStatus(post.id, 60000);
                if (!finalPost) {
                    setPublishStatus('info', 'المنشور في الانتظار. راجع لوحة التحكم خلال دقيقة.');
                } else if (finalPost.status === 'published') {
                    setPublishStatus('success', 'اكتمل النشر عبر المجدول ✅');
                } else if (finalPost.status === 'partial') {
                    setPublishStatus('info', 'تم النشر جزئياً عبر المجدول.');
                } else {
                    setPublishStatus('error', 'فشل النشر: ' + (finalPost.error_message || 'تحقق من إعدادات الصفحة.'));
                }
            } else {
                setPublishStatus('error', r.message || 'خطأ في النشر');
                toast(r.message || 'خطأ', 'error');
            }
        }
    } catch (err) {
        setPublishStatus('error', 'خطأ في الاتصال بالخادم');
        toast('خطأ في الاتصال بالخادم', 'error');
    }
    finally { btn.disabled = false; btn.innerHTML = publishMode === 'scheduled' ? '📅 جدولة' : '🚀 نشر الآن'; }
}
