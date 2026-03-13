(() => {
  'use strict';

  const API_BASE = (window.PUBLISHER_API_BASE || '/publisher').replace(/\/+$/, '');

  const channelsList = document.getElementById('channelsList');
  const contentInput = document.getElementById('contentInput');
  const mediaDrop = document.getElementById('mediaDrop');
  const mediaInput = document.getElementById('mediaInput');
  const mediaPreview = document.getElementById('mediaPreview');
  const scheduleAt = document.getElementById('scheduleAt');
  const createJobBtn = document.getElementById('createJobBtn');
  const clearBtn = document.getElementById('clearBtn');
  const jobsTable = document.getElementById('jobsTable');
  const refreshJobsBtn = document.getElementById('refreshJobsBtn');
  const toastContainer = document.getElementById('toastContainer');

  let selectedChannels = new Set();
  let selectedFile = null;

  function toast(message, type = 'info', timeout = 4000) {
    if (!toastContainer) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    toastContainer.appendChild(el);
    setTimeout(() => {
      el.remove();
    }, timeout);
  }

  async function apiGet(path) {
    const res = await fetch(API_BASE + path, { credentials: 'include' });
    if (res.status === 401) {
      toast('انتهت الجلسة. يرجى تسجيل الدخول مرة أخرى.', 'error');
      return null;
    }
    return res;
  }

  async function apiPostForm(path, formData) {
    const res = await fetch(API_BASE + path, {
      method: 'POST',
      body: formData,
      credentials: 'include',
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
    if (!channels || !channels.length) {
      channelsList.innerHTML = '<span style="font-size:0.8rem;color:#9ca3af;">لا توجد قنوات متاحة بعد.</span>';
      return;
    }
    channels.forEach(ch => {
      const chip = document.createElement('div');
      chip.className = 'channel-chip';
      chip.dataset.id = ch.id;
      chip.innerHTML = `<span>${ch.name}</span><span class="channel-type">${ch.type}</span>`;
      chip.addEventListener('click', () => {
        if (selectedChannels.has(ch.id)) {
          selectedChannels.delete(ch.id);
          chip.classList.remove('selected');
        } else {
          selectedChannels.add(ch.id);
          chip.classList.add('selected');
        }
      });
      channelsList.appendChild(chip);
    });
  }

  async function loadChannels() {
    const res = await apiGet('/channels');
    if (!res) return;
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.success) {
      toast(data.error || 'فشل تحميل القنوات', 'error');
      return;
    }
    renderChannels(data.channels || []);
  }

  function resetMedia() {
    selectedFile = null;
    if (mediaInput) mediaInput.value = '';
    if (mediaPreview) {
      mediaPreview.innerHTML = '';
      mediaPreview.style.display = 'none';
    }
  }

  function handleFile(file) {
    if (!file) return;
    selectedFile = file;
    if (!mediaPreview) return;
    mediaPreview.innerHTML = '';
    const isVideo = (file.type || '').startsWith('video/');
    const url = URL.createObjectURL(file);
    const el = document.createElement(isVideo ? 'video' : 'img');
    if (isVideo) {
      el.src = url;
      el.controls = true;
      el.muted = true;
    } else {
      el.src = url;
    }
    mediaPreview.appendChild(el);
    mediaPreview.style.display = 'block';
  }

  if (mediaDrop && mediaInput) {
    mediaDrop.addEventListener('click', () => mediaInput.click());
    mediaDrop.addEventListener('dragenter', (e) => {
      e.preventDefault(); e.stopPropagation();
      mediaDrop.classList.add('dragover');
    });
    mediaDrop.addEventListener('dragover', (e) => {
      e.preventDefault(); e.stopPropagation();
      mediaDrop.classList.add('dragover');
    });
    ['dragleave', 'drop'].forEach(evt => {
      mediaDrop.addEventListener(evt, (e) => {
        e.preventDefault(); e.stopPropagation();
        if (evt === 'drop') {
          const dt = e.dataTransfer;
          if (dt && dt.files && dt.files[0]) {
            handleFile(dt.files[0]);
          }
        }
        mediaDrop.classList.remove('dragover');
      });
    });
    mediaInput.addEventListener('change', (e) => {
      const f = e.target.files && e.target.files[0];
      handleFile(f);
    });
  }

  async function loadJobs() {
    if (!jobsTable) return;
    // لا يوجد بعد API jobs GET في الباكند الجديد، لذا نُظهر placeholder
    // يمكن لاحقاً إضافة /publisher/jobs?limit=20 لجلب آخر المهام.
  }

  async function createJob() {
    if (!createJobBtn) return;
    const btn = createJobBtn;
    const text = (contentInput && contentInput.value || '').trim();
    if (!selectedChannels.size) {
      toast('اختر قناة واحدة على الأقل.', 'error');
      return;
    }
    if (!text && !selectedFile) {
      toast('أدخل محتوى نصي أو ارفع صورة/فيديو.', 'error');
      return;
    }

    const formData = new FormData();
    formData.append('text', text);
    Array.from(selectedChannels).forEach(id => formData.append('channel_ids', id));
    if (scheduleAt && scheduleAt.value) {
      const d = new Date(scheduleAt.value);
      if (!isNaN(d.getTime())) {
        formData.append('scheduled_at', d.toISOString());
      }
    }
    if (selectedFile) {
      formData.append('media', selectedFile);
    }

    btn.classList.add('loading');
    btn.disabled = true;

    const res = await apiPostForm('/jobs', formData);
    const data = await res?.json().catch(() => ({}));

    btn.classList.remove('loading');
    btn.disabled = false;

    if (!res || !res.ok || !data?.success) {
      toast(data?.error || 'فشل إنشاء مهمة النشر.', 'error');
      return;
    }
    toast('تم إنشاء مهمة النشر بنجاح. سيتم التنفيذ تلقائياً.', 'success');
    if (contentInput) contentInput.value = '';
    if (scheduleAt) scheduleAt.value = '';
    selectedChannels.clear();
    document.querySelectorAll('.channel-chip.selected').forEach(el => el.classList.remove('selected'));
    resetMedia();
    loadJobs();
  }

  if (createJobBtn) {
    createJobBtn.addEventListener('click', createJob);
  }
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      if (contentInput) contentInput.value = '';
      if (scheduleAt) scheduleAt.value = '';
      selectedChannels.clear();
      document.querySelectorAll('.channel-chip.selected').forEach(el => el.classList.remove('selected'));
      resetMedia();
    });
  }
  if (refreshJobsBtn) {
    refreshJobsBtn.addEventListener('click', loadJobs);
  }

  loadChannels();
  loadJobs();
})();

