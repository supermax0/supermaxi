(function () {
  'use strict';

  const API_BASE = (window.PUBLISH_API_BASE || '/publish/api').replace(/\/+$/, '');

  const channelsList = document.getElementById('channelsList');
  const jobsTable = document.getElementById('jobsTable');
  const addChannelBtn = document.getElementById('addChannelBtn');
  const fbConnectBtn = document.getElementById('fbConnectBtn');
  const refreshJobsBtn = document.getElementById('refreshJobsBtn');
  const createJobBtn = document.getElementById('createJobBtn');
  const clearJobBtn = document.getElementById('clearJobBtn');

  const jobTitle = document.getElementById('jobTitle');
  const jobText = document.getElementById('jobText');
  const mediaUrl = document.getElementById('mediaUrl');
  const mediaType = document.getElementById('mediaType');
  const scheduledAt = document.getElementById('scheduledAt');
  const uploadMediaBtn = document.getElementById('uploadMediaBtn');
  const mediaFileInput = document.getElementById('mediaFile');
  const uploadProgressWrapper = document.getElementById('uploadProgressWrapper');
  const uploadProgressBar = document.getElementById('uploadProgressBar');
  const uploadProgressLabel = document.getElementById('uploadProgressLabel');
  const mediaPreviewWrapper = document.getElementById('mediaPreviewWrapper');
  const mediaPreviewPlaceholder = document.getElementById('mediaPreviewPlaceholder');
  const mediaPreviewImg = document.getElementById('mediaPreviewImg');
  const mediaPreviewVideo = document.getElementById('mediaPreviewVideo');

  const toastContainer = document.getElementById('publishToastContainer');

  let selectedChannelIds = new Set();
  let previewObjectUrl = null;

  function toast(message, type = 'info', timeout = 4000) {
    if (!toastContainer) return;
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = message;
    toastContainer.appendChild(el);
    setTimeout(() => {
      el.remove();
    }, timeout);
  }

  async function apiGet(path) {
    const res = await fetch(API_BASE + path, {
      credentials: 'include'
    });
    if (res.status === 401) {
      toast('انتهت الجلسة. يرجى تسجيل الدخول مرة أخرى.', 'error');
      return null;
    }
    return res;
  }

  async function apiPost(path, body) {
    const res = await fetch(API_BASE + path, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body || {})
    });
    if (res.status === 401) {
      toast('انتهت الجلسة. يرجى تسجيل الدخول مرة أخرى.', 'error');
      return null;
    }
    return res;
  }

  async function apiPatch(path, body) {
    const res = await fetch(API_BASE + path, {
      method: 'PATCH',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body || {})
    });
    if (res.status === 401) {
      toast('انتهت الجلسة. يرجى تسجيل الدخول مرة أخرى.', 'error');
      return null;
    }
    return res;
  }

  function renderChannels(channels) {
    if (!channelsList) return;
    channelsList.innerHTML = '';
    selectedChannelIds.clear();

    if (!channels || !channels.length) {
      channelsList.innerHTML = '<div style="color:#9ca3af;">لا توجد قنوات بعد. اضغط على \"إضافة قناة\".</div>';
      return;
    }

    channels.forEach(ch => {
      const row = document.createElement('div');
      row.className = 'channel-row';
      row.dataset.id = ch.id;

      row.innerHTML = [
        '<div class="channel-main">',
        `<div class="channel-name">${ch.name}</div>`,
        `<div class="channel-meta">${ch.type} · ${ch.external_id}</div>`,
        '</div>',
        `<div class="channel-status ${ch.is_active ? 'active' : 'inactive'}">${ch.is_active ? 'فعّالة' : 'موقوفة'}</div>`
      ].join('');

      row.addEventListener('click', () => {
        const id = ch.id;
        if (selectedChannelIds.has(id)) {
          selectedChannelIds.delete(id);
          row.classList.remove('selected');
        } else {
          selectedChannelIds.add(id);
          row.classList.add('selected');
        }
      });

      channelsList.appendChild(row);
    });
  }

  async function loadChannels() {
    const res = await apiGet('/channels');
    const data = await res?.json().catch(() => ({}));
    if (!res || !res.ok || !data?.success) {
      toast(data?.error || 'فشل تحميل القنوات.', 'error');
      return;
    }
    renderChannels(data.channels || []);
  }

  function renderJobs(jobs) {
    if (!jobsTable) return;
    const tbody = jobsTable.querySelector('tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!jobs || !jobs.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 4;
      td.style.padding = '8px 10px';
      td.style.color = '#9ca3af';
      td.style.textAlign = 'center';
      td.textContent = 'لا توجد مهام بعد.';
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    jobs.forEach(j => {
      const tr = document.createElement('tr');
      const status = j.status || 'pending';
      const statusClass = 'badge-status ' + status;
      let resultCell = '';
      if (status === 'published') {
        resultCell = '<span style="color:#22c55e;">تم النشر</span>';
      } else if (status === 'pending' || status === 'processing') {
        resultCell = '<span style="color:#94a3b8;">—</span>';
      } else if (status === 'failed' && j.error_message) {
        resultCell = '<span style="color:#ef4444;font-size:0.75rem;">' + (j.error_message || '').replace(/</g, '&lt;').substring(0, 80) + '</span>';
      } else {
        resultCell = '<span style="color:#94a3b8;">—</span>';
      }
      const contentHint = (j.text && j.text.trim()) ? (j.text.trim().substring(0, 40) + (j.text.length > 40 ? '…' : '')) : (j.media_type === 'video' ? 'فيديو' : j.media_type === 'image' ? 'صورة' : '—');
      const titleText = (status === 'failed' && j.error_message) ? j.error_message : contentHint;
      const titleEscaped = (titleText || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
      tr.innerHTML = [
        `<td style="padding:6px 8px;border-bottom:1px solid rgba(31,41,55,0.9);">${j.channel_id}</td>`,
        `<td style="padding:6px 8px;border-bottom:1px solid rgba(31,41,55,0.9);"><span class="${statusClass}">${status}</span></td>`,
        `<td style="padding:6px 8px;border-bottom:1px solid rgba(31,41,55,0.9);font-size:0.75rem;color:#9ca3af;">${j.scheduled_at || ''}</td>`,
        `<td style="padding:6px 8px;border-bottom:1px solid rgba(31,41,55,0.9);font-size:0.75rem;" title="${titleEscaped}">${resultCell}</td>`
      ].join('');

      tbody.appendChild(tr);
    });
  }

  async function loadJobs() {
    const res = await apiGet('/jobs');
    const data = await res?.json().catch(() => ({}));
    if (!res || !res.ok || !data?.success) {
      toast(data?.error || 'فشل تحميل المهام.', 'error');
      return;
    }
    renderJobs(data.jobs || []);
  }

  async function promptNewChannel() {
    const type = prompt('نوع القناة (مثلاً facebook_page, telegram_chat):');
    if (!type) return;
    const name = prompt('اسم القناة (للواجهة):');
    if (!name) return;
    const externalId = prompt('المعرّف الخارجي (page id, chat id, ...):');
    if (!externalId) return;

    const res = await apiPost('/channels', {
      type,
      name,
      external_id: externalId
    });
    const data = await res?.json().catch(() => ({}));
    if (!res || !res.ok || !data?.success) {
      toast(data?.error || 'فشل إنشاء القناة.', 'error');
      return;
    }
    toast('تم إنشاء القناة بنجاح.', 'success');
    loadChannels();
  }

  async function connectFacebook() {
    const res = await apiGet('/facebook/login-url');
    const data = await res?.json().catch(() => ({}));
    if (!res || !res.ok || !data?.success || !data.login_url) {
      toast(data?.error || 'فشل تجهيز تسجيل الدخول إلى فيسبوك.', 'error');
      return;
    }
    window.location.href = data.login_url;
  }

  async function uploadMediaFile(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);

    if (uploadProgressWrapper && uploadProgressBar && uploadProgressLabel) {
      uploadProgressWrapper.style.display = 'block';
      uploadProgressBar.style.width = '0%';
      uploadProgressLabel.textContent = '0%';
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', API_BASE + '/media/upload', true);
    xhr.withCredentials = true;

    xhr.upload.onprogress = function (evt) {
      if (!evt.lengthComputable || !uploadProgressBar || !uploadProgressLabel) return;
      const percent = Math.round((evt.loaded / evt.total) * 100);
      uploadProgressBar.style.width = percent + '%';
      uploadProgressLabel.textContent = percent + '%';
    };

    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;

      if (uploadProgressWrapper) {
        setTimeout(() => {
          uploadProgressWrapper.style.display = 'none';
        }, 700);
      }

      let data = {};
      try {
        data = JSON.parse(xhr.responseText || '{}');
      } catch (e) {
        data = {};
      }

      if (xhr.status < 200 || xhr.status >= 300 || !data.success) {
        toast(data.error || 'فشل رفع الملف.', 'error');
        return;
      }

      if (mediaUrl && data.url) {
        mediaUrl.value = data.url;
      }
      if (mediaType && data.media_type) {
        mediaType.value = data.media_type;
      }
      showMediaPreviewFromUrl(data.url, data.media_type);

      toast('تم رفع الملف إلى السيرفر. اضغط «إنشاء مهمة» للنشر إلى فيسبوك.', 'success');
    };

    xhr.onerror = function () {
      if (uploadProgressWrapper) {
        uploadProgressWrapper.style.display = 'none';
      }
      toast('فشل الاتصال بالخادم أثناء رفع الملف.', 'error');
    };

    xhr.send(fd);
  }

  const MAX_FILE_MB = 500;
  const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

  function createJobWithFormData(formData) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', API_BASE + '/jobs');
      xhr.withCredentials = true;

      const uploadProgressText = document.getElementById('uploadProgressText');
      if (uploadProgressWrapper && uploadProgressBar && uploadProgressLabel) {
        uploadProgressWrapper.style.display = 'block';
        uploadProgressBar.style.width = '0%';
        uploadProgressLabel.textContent = '0%';
        if (uploadProgressText) uploadProgressText.textContent = 'جاري رفع الملف وإنشاء المهمة...';
        xhr.upload.onprogress = function (e) {
          if (e.lengthComputable) {
            const pct = Math.min(100, Math.round((e.loaded / e.total) * 100));
            uploadProgressBar.style.width = pct + '%';
            uploadProgressLabel.textContent = pct + '%';
          }
        };
      }

      xhr.onload = function () {
        if (uploadProgressWrapper) uploadProgressWrapper.style.display = 'none';
        try {
          const data = JSON.parse(xhr.responseText || '{}');
          if (xhr.status >= 200 && xhr.status < 300) resolve({ ok: true, data });
          else resolve({ ok: false, data });
        } catch (_) {
          resolve({ ok: false, data: {} });
        }
      };
      xhr.onerror = function () {
        if (uploadProgressWrapper) uploadProgressWrapper.style.display = 'none';
        resolve({ ok: false, data: {} });
      };
      xhr.send(formData);
    });
  }

  async function createJob() {
    if (!selectedChannelIds.size) {
      toast('اختر قناة واحدة على الأقل.', 'error');
      return;
    }

    const text = (jobText && jobText.value || '').trim();
    const title = (jobTitle && jobTitle.value || '').trim();
    const mUrl = (mediaUrl && mediaUrl.value || '').trim();
    const mType = (mediaType && mediaType.value) || '';
    const file = mediaFileInput && mediaFileInput.files && mediaFileInput.files[0];

    if (!text && !file && !mUrl) {
      toast('أدخل نصاً أو اختر ملف صورة/فيديو.', 'error');
      return;
    }

    if (file && !mUrl) {
      if (file.size > MAX_FILE_BYTES) {
        toast('حجم الملف يتجاوز ' + MAX_FILE_MB + ' ميجابايت.', 'error');
        return;
      }
      const type = (file.type || '').toLowerCase();
      const isImage = type.startsWith('image/');
      const isVideo = type.startsWith('video/');
      if (!isImage && !isVideo) {
        toast('الملف يجب أن يكون صورة أو فيديو.', 'error');
        return;
      }
    }

    if (createJobBtn) {
      createJobBtn.disabled = true;
      createJobBtn.classList.add('loading');
    }

    let res;
    let data = {};

    if (mUrl) {
      // الملف مرفوع مسبقاً إلى السيرفر، نرسل الرابط فقط ثم النشر إلى فيسبوك
      const payload = {
        title: title || null,
        text,
        media_url: mUrl,
        media_type: mType || null,
        channel_ids: Array.from(selectedChannelIds),
      };
      if (scheduledAt && scheduledAt.value) {
        const d = new Date(scheduledAt.value);
        if (!isNaN(d.getTime())) payload.scheduled_at = d.toISOString();
      }
      res = await apiPost('/jobs', payload);
      data = await res?.json().catch(() => ({}));
    } else if (file) {
      const formData = new FormData();
      formData.append('text', text);
      formData.append('title', title || '');
      formData.append('channel_ids', JSON.stringify(Array.from(selectedChannelIds)));
      if (mType) formData.append('media_type', mType);
      if (scheduledAt && scheduledAt.value) {
        const d = new Date(scheduledAt.value);
        if (!isNaN(d.getTime())) formData.append('scheduled_at', d.toISOString());
      }
      formData.append('file', file);
      const result = await createJobWithFormData(formData);
      res = result.ok ? { ok: true, status: 200 } : { ok: false, status: 400 };
      data = result.data || {};
    } else {
      const payload = {
        title: title || null,
        text,
        media_url: null,
        media_type: null,
        channel_ids: Array.from(selectedChannelIds),
      };
      if (scheduledAt && scheduledAt.value) {
        const d = new Date(scheduledAt.value);
        if (!isNaN(d.getTime())) payload.scheduled_at = d.toISOString();
      }
      res = await apiPost('/jobs', payload);
      data = await res?.json().catch(() => ({}));
    }

    if (createJobBtn) {
      createJobBtn.disabled = false;
      createJobBtn.classList.remove('loading');
    }

    const ok = res && (res.ok === true || (res.status >= 200 && res.status < 300));
    if (!ok || !data.success) {
      toast(data.error || 'فشل إنشاء مهمة النشر.', 'error');
      return;
    }

    toast('تم إنشاء مهمة النشر بنجاح.', 'success');
    if (jobText) jobText.value = '';
    if (jobTitle) jobTitle.value = '';
    if (mediaUrl) mediaUrl.value = '';
    if (mediaType) mediaType.value = '';
    if (scheduledAt) scheduledAt.value = '';
    if (mediaFileInput) mediaFileInput.value = '';
    clearMediaPreview();
    loadJobs();
  }

  function clearMediaPreview() {
    if (previewObjectUrl) {
      try { URL.revokeObjectURL(previewObjectUrl); } catch (_) {}
      previewObjectUrl = null;
    }
    if (mediaPreviewImg) {
      mediaPreviewImg.src = '';
      mediaPreviewImg.style.display = 'none';
    }
    if (mediaPreviewVideo) {
      mediaPreviewVideo.src = '';
      mediaPreviewVideo.pause();
      mediaPreviewVideo.style.display = 'none';
    }
    if (mediaPreviewPlaceholder) mediaPreviewPlaceholder.style.display = '';
    if (mediaPreviewWrapper) mediaPreviewWrapper.style.display = '';
  }

  function showMediaPreviewFromUrl(url, kind) {
    if (!url || !url.trim()) {
      clearMediaPreview();
      return;
    }
    if (previewObjectUrl) {
      try { URL.revokeObjectURL(previewObjectUrl); } catch (_) {}
      previewObjectUrl = null;
    }
    const k = (kind || '').toLowerCase();
    const isVideo = k === 'video' || /\.(mp4|webm|ogg|mov|avi|mkv)(\?|$)/i.test(url);
    if (mediaPreviewPlaceholder) mediaPreviewPlaceholder.style.display = 'none';
    if (mediaPreviewImg && mediaPreviewVideo) {
      mediaPreviewImg.style.display = 'none';
      mediaPreviewVideo.style.display = 'none';
      if (isVideo) {
        mediaPreviewVideo.src = url;
        mediaPreviewVideo.style.display = 'block';
      } else {
        mediaPreviewImg.src = url;
        mediaPreviewImg.style.display = 'block';
      }
    }
  }

  function showMediaPreviewFromFile(file) {
    if (!file) {
      clearMediaPreview();
      return;
    }
    if (previewObjectUrl) {
      try { URL.revokeObjectURL(previewObjectUrl); } catch (_) {}
      previewObjectUrl = null;
    }
    previewObjectUrl = URL.createObjectURL(file);
    const type = (file.type || '').toLowerCase();
    const isVideo = type.startsWith('video/');
    if (mediaPreviewPlaceholder) mediaPreviewPlaceholder.style.display = 'none';
    if (mediaPreviewImg && mediaPreviewVideo) {
      mediaPreviewImg.style.display = 'none';
      mediaPreviewVideo.style.display = 'none';
      if (isVideo) {
        mediaPreviewVideo.src = previewObjectUrl;
        mediaPreviewVideo.style.display = 'block';
      } else {
        mediaPreviewImg.src = previewObjectUrl;
        mediaPreviewImg.style.display = 'block';
      }
    }
  }

  function clearJobForm() {
    if (jobText) jobText.value = '';
    if (jobTitle) jobTitle.value = '';
    if (mediaUrl) mediaUrl.value = '';
    if (mediaType) mediaType.value = '';
    if (scheduledAt) scheduledAt.value = '';
    if (mediaFileInput) mediaFileInput.value = '';
    clearMediaPreview();
  }

  if (addChannelBtn) {
    addChannelBtn.addEventListener('click', promptNewChannel);
  }

  if (fbConnectBtn) {
    fbConnectBtn.addEventListener('click', connectFacebook);
  }

  if (uploadMediaBtn && mediaFileInput) {
    uploadMediaBtn.addEventListener('click', () => {
      mediaFileInput.click();
    });
  }

  // عند اختيار ملف: معاينة + رفع فوري إلى السيرفر. عند «إنشاء مهمة» يُنشر الرابط إلى فيسبوك.
  window.__publishOnMediaChange = function (fileList) {
    const file = fileList && fileList[0];
    if (file) {
      showMediaPreviewFromFile(file);
      uploadMediaFile(file);
    }
  };

  if (mediaUrl) {
    mediaUrl.addEventListener('input', function () {
      const url = (this.value || '').trim();
      if (url) showMediaPreviewFromUrl(url, mediaType && mediaType.value);
      else clearMediaPreview();
    });
    mediaUrl.addEventListener('blur', function () {
      const url = (this.value || '').trim();
      if (url) showMediaPreviewFromUrl(url, mediaType && mediaType.value);
    });
  }
  if (mediaType) {
    mediaType.addEventListener('change', function () {
      const url = (mediaUrl && mediaUrl.value || '').trim();
      if (url) showMediaPreviewFromUrl(url, this.value);
    });
  }

  if (refreshJobsBtn) {
    refreshJobsBtn.addEventListener('click', loadJobs);
  }

  if (createJobBtn) {
    createJobBtn.addEventListener('click', createJob);
  }

  if (clearJobBtn) {
    clearJobBtn.addEventListener('click', clearJobForm);
  }

  // Initial load
  loadChannels();
  loadJobs();
})();

