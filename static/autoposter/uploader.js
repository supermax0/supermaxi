(() => {
  'use strict';

  const dropZone = document.getElementById('dropZoneMain');
  const fileInput = document.getElementById('fileInputHidden');
  const selectBtn = document.getElementById('selectFileBtn');
  const cancelBtn = document.getElementById('cancelUploadBtn');
  const progressShell = document.getElementById('progressShell');
  const progressInner = document.getElementById('progressInner');
  const progressText = document.getElementById('progressText');
  const previewShell = document.getElementById('previewShell');
  const previewVideo = document.getElementById('previewVideo');
  const previewMeta = document.getElementById('previewMeta');
  const errorBox = document.getElementById('errorBox');
  const successBox = document.getElementById('successBox');
  const useInPostBtn = document.getElementById('useInPostBtn');

  let currentXhr = null;

  function resetUI() {
    if (progressShell) progressShell.style.display = 'none';
    if (previewShell) previewShell.style.display = 'none';
    if (errorBox) { errorBox.style.display = 'none'; errorBox.textContent = ''; }
    if (successBox) { successBox.style.display = 'none'; successBox.textContent = ''; }
    if (progressInner) progressInner.style.width = '0%';
    if (progressText) progressText.textContent = '0%';
    if (cancelBtn) { cancelBtn.disabled = true; }
  }

  function showError(msg) {
    if (errorBox) {
      errorBox.textContent = msg || 'حدث خطأ أثناء رفع الملف.';
      errorBox.style.display = 'block';
    }
  }

  function showSuccess(msg) {
    if (successBox) {
      successBox.textContent = msg || 'تم رفع الفيديو بنجاح.';
      successBox.style.display = 'block';
    }
  }

  function handleFiles(files) {
    if (!files || !files.length) return;
    const file = files[0];
    resetUI();

    const type = file.type || '';
    if (!type.startsWith('video/')) {
      showError('الرجاء اختيار ملف فيديو (mp4 / mov / webm).');
      return;
    }
    const maxBytes = 200 * 1024 * 1024; // 200MB (متطابق مع الباكند)
    if (file.size > maxBytes) {
      showError('حجم الفيديو أكبر من 2GB.');
      return;
    }

    if (progressShell) progressShell.style.display = 'block';
    if (cancelBtn) cancelBtn.disabled = false;

    const formData = new FormData();
    formData.append('file', file);

    const apiBase = (window.AUTOPOSTER_API_BASE || '/autoposter').replace(/\/+$/, '');
    const uploadUrl = apiBase + '/api/upload';

    const xhr = new XMLHttpRequest();
    currentXhr = xhr;

    const startedAt = Date.now();

    xhr.open('POST', uploadUrl, true);
    xhr.withCredentials = true;

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable || !progressInner || !progressText) return;
      const percent = Math.max(1, Math.min(100, (e.loaded / e.total) * 100));
      progressInner.style.width = `${percent}%`;
      const elapsedSec = Math.max(0.1, (Date.now() - startedAt) / 1000);
      const speedBytesPerSec = e.loaded / elapsedSec;
      const speedMbPerSec = speedBytesPerSec / (1024 * 1024);
      let etaText = '';
      if (speedBytesPerSec > 0) {
        const remaining = e.total - e.loaded;
        const etaSec = remaining / speedBytesPerSec;
        const etaRounded = Math.max(1, Math.round(etaSec));
        etaText = ` — ${etaRounded}s متبقّية تقريباً`;
      }
      progressText.textContent = `${percent.toFixed(0)}% — ${speedMbPerSec.toFixed(2)} MB/s${etaText}`;
    };

    xhr.onreadystatechange = () => {
      if (xhr.readyState !== XMLHttpRequest.DONE) return;
      currentXhr = null;
      if (cancelBtn) cancelBtn.disabled = true;

      if (progressShell) progressShell.style.display = 'none';

      let resp = {};
      try {
        resp = JSON.parse(xhr.responseText || '{}');
      } catch {
        // ignore
      }
      if (xhr.status >= 200 && xhr.status < 300 && resp.ok) {
        showSuccess('تم رفع الفيديو بنجاح.');
        if (previewShell && previewVideo && previewMeta) {
          const url = resp.url || '';
          const sizeMb = resp.size_mb != null ? resp.size_mb : file.size / (1024 * 1024);
          const width = resp.width || null;
          const height = resp.height || null;
          const duration = resp.duration_sec || null;
          const parts = [];
          parts.push(`الحجم: ${sizeMb.toFixed ? sizeMb.toFixed(2) : sizeMb} ميجا`);
          if (width && height) parts.push(`الأبعاد: ${width}×${height}`);
          if (duration) {
            const mins = Math.floor(duration / 60);
            const secs = Math.round(duration % 60);
            parts.push(`المدة: ${mins}:${secs.toString().padStart(2, '0')} دقيقة`);
          }
          previewMeta.textContent = parts.join(' · ');
          if (url) {
            previewVideo.src = url;
          } else {
            const blobUrl = URL.createObjectURL(file);
            previewVideo.src = blobUrl;
          }
          previewShell.style.display = 'block';
        }
        if (useInPostBtn && resp.url) {
          useInPostBtn.style.display = 'inline-flex';
          useInPostBtn.disabled = false;
          useInPostBtn.onclick = () => {
            try {
              sessionStorage.setItem('autoposter_last_video_url', resp.url);
            } catch (e) {
              // ignore
            }
            const base = (window.AUTOPOSTER_API_BASE || '/autoposter').replace(/\/+$/, '');
            window.location.href = `${base}/#create`;
          };
        }
      } else if (xhr.status === 0) {
        showError('تم إلغاء الرفع.');
      } else {
        const msg = resp.message || resp.error || 'فشل رفع الفيديو.';
        showError(msg);
      }
    };

    xhr.onerror = () => {
      currentXhr = null;
      if (progressShell) progressShell.style.display = 'none';
      if (cancelBtn) cancelBtn.disabled = true;
      showError('فشل الرفع بسبب مشكلة في الاتصال.');
    };

    xhr.send(formData);
  }

  if (selectBtn && fileInput) {
    selectBtn.addEventListener('click', () => fileInput.click());
  }

  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      const target = e.target;
      handleFiles(target.files);
    });
  }

  if (dropZone) {
    ['dragenter', 'dragover'].forEach(evt => {
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('dragover');
      });
    });
    ['dragleave', 'drop'].forEach(evt => {
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (evt === 'drop') {
          const dt = e.dataTransfer;
          if (dt && dt.files) {
            handleFiles(dt.files);
          }
        }
        dropZone.classList.remove('dragover');
      });
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      if (currentXhr) {
        currentXhr.abort();
        currentXhr = null;
      }
      if (progressShell) progressShell.style.display = 'none';
      if (cancelBtn) cancelBtn.disabled = true;
    });
  }
})();

