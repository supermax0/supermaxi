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
  const previewMediaBox = document.getElementById('previewMediaBox');
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
    const isVideo = type.startsWith('video/');
    const isImage = type.startsWith('image/');
    if (!isVideo && !isImage) {
      showError('الرجاء اختيار ملف صورة (jpg, png, webp) أو فيديو (mp4, mov, webm).');
      return;
    }
    const maxBytes = 500 * 1024 * 1024; // 500MB (متطابق مع /api/media/upload)
    if (file.size > maxBytes) {
      showError('حجم الملف أكبر من 500 ميجا.');
      return;
    }

    if (progressShell) progressShell.style.display = 'block';
    if (cancelBtn) cancelBtn.disabled = false;

    const formData = new FormData();
    formData.append('file', file);

    const apiBase = (window.AUTOPOSTER_API_BASE || '/autoposter').replace(/\/+$/, '');
    const uploadUrl = apiBase + '/api/media/upload';

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
      if (xhr.status >= 200 && xhr.status < 300 && (resp.ok || resp.success)) {
        showSuccess(resp.media_type === 'video' || resp.type === 'video' ? 'تم رفع الفيديو بنجاح وحفظه في المكتبة.' : 'تم رفع الصورة بنجاح وحفظها في المكتبة.');
        if (previewShell && previewMeta) {
          const url = resp.url || resp.public_url || '';
          const mediaType = resp.media_type || resp.type || (file.type.startsWith('video/') ? 'video' : 'image');
          const sizeMb = resp.size_mb != null ? resp.size_mb : (resp.file_size != null ? resp.file_size / (1024 * 1024) : file.size / (1024 * 1024));
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
          const blobUrl = URL.createObjectURL(file);
          const src = url || blobUrl;
          if (previewMediaBox) {
            previewMediaBox.innerHTML = '';
            if (mediaType === 'video') {
              const video = document.createElement('video');
              video.controls = true;
              video.playsInline = true;
              video.style.cssText = 'width:100%;max-height:320px';
              video.src = src;
              previewMediaBox.appendChild(video);
            } else {
              const img = document.createElement('img');
              img.src = src;
              img.alt = '';
              img.style.cssText = 'max-width:100%;max-height:320px';
              previewMediaBox.appendChild(img);
            }
          }
          previewShell.style.display = 'block';
        }
        if (useInPostBtn && (resp.url || resp.public_url)) {
          useInPostBtn.style.display = 'inline-flex';
          useInPostBtn.disabled = false;
          const isVideo = resp.media_type === 'video' || resp.type === 'video';
          useInPostBtn.textContent = isVideo ? 'استخدام هذا الفيديو في المنشور' : 'استخدام هذه الصورة في المنشور';
          const mediaUrl = resp.url || resp.public_url || '';
          useInPostBtn.onclick = () => {
            try {
              sessionStorage.setItem('autoposter_last_media_url', mediaUrl);
              sessionStorage.setItem('autoposter_last_media_type', isVideo ? 'video' : 'image');
            } catch (e) {}
            const base = (window.AUTOPOSTER_API_BASE || '/autoposter').replace(/\/+$/, '');
            window.location.href = base + '/create';
          };
        }
        if (typeof window.refreshUploadPageMediaList === 'function') {
          setTimeout(() => window.refreshUploadPageMediaList(), 400);
          setTimeout(() => window.refreshUploadPageMediaList(), 1200);
        }
      } else if (xhr.status === 0) {
        showError('تم إلغاء الرفع.');
      } else {
        // محاولة بديلة: رفع عبر JSON (base64) إن كان الملف أصغر من 50 ميجا
        if (file.size < 50 * 1024 * 1024 && (xhr.status === 413 || xhr.status === 502 || xhr.status === 0)) {
          tryJsonUpload();
        } else {
          const msg = resp.message || resp.error || 'فشل رفع الملف.';
          showError(msg);
        }
      }
    };

    xhr.onerror = () => {
      currentXhr = null;
      if (progressShell) progressShell.style.display = 'none';
      if (cancelBtn) cancelBtn.disabled = true;
      if (file.size < 50 * 1024 * 1024) {
        tryJsonUpload();
      } else {
        showError('فشل الرفع بسبب مشكلة في الاتصال.');
      }
    };

    function tryJsonUpload() {
      if (progressShell) progressShell.style.display = 'block';
      if (progressText) progressText.textContent = 'جاري الرفع (طريقة بديلة)...';
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result;
        const base64 = dataUrl.indexOf(',') >= 0 ? dataUrl.split(',')[1] : dataUrl;
        const apiBase = (window.AUTOPOSTER_API_BASE || '/autoposter').replace(/\/+$/, '');
        fetch(apiBase + '/api/upload/json', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: file.name || (file.type.startsWith('video/') ? 'video.mp4' : 'image.jpg'),
            data: base64,
            content_type: file.type || '',
          }),
        })
          .then((r) => r.json())
          .then((resp) => {
            if (progressShell) progressShell.style.display = 'none';
            if (resp.ok) {
              showSuccess(resp.type === 'video' ? 'تم رفع الفيديو بنجاح (طريقة بديلة).' : 'تم رفع الصورة بنجاح (طريقة بديلة).');
              if (previewShell && previewMediaBox && previewMeta) {
                const url = resp.url || '';
                const mediaType = resp.type || (file.type.startsWith('video/') ? 'video' : 'image');
                const parts = [`الحجم: ${(resp.size_mb || file.size / (1024 * 1024)).toFixed(2)} ميجا`];
                if (resp.width && resp.height) parts.push(`الأبعاد: ${resp.width}×${resp.height}`);
                if (resp.duration_sec) parts.push(`المدة: ${Math.floor(resp.duration_sec / 60)}:${Math.round(resp.duration_sec % 60).toString().padStart(2, '0')} دقيقة`);
                previewMeta.textContent = parts.join(' · ');
                previewMediaBox.innerHTML = '';
                if (mediaType === 'video') {
                  const v = document.createElement('video');
                  v.controls = true;
                  v.playsInline = true;
                  v.style.cssText = 'width:100%;max-height:320px';
                  v.src = url;
                  previewMediaBox.appendChild(v);
                } else {
                  const img = document.createElement('img');
                  img.src = url;
                  img.alt = '';
                  img.style.cssText = 'max-width:100%;max-height:320px';
                  previewMediaBox.appendChild(img);
                }
                previewShell.style.display = 'block';
              }
              if (useInPostBtn && resp.url) {
                useInPostBtn.style.display = 'inline-flex';
                useInPostBtn.disabled = false;
                useInPostBtn.textContent = resp.type === 'video' ? 'استخدام هذا الفيديو في المنشور' : 'استخدام هذه الصورة في المنشور';
                useInPostBtn.onclick = () => {
                  try {
                    sessionStorage.setItem('autoposter_last_media_url', resp.url);
                    sessionStorage.setItem('autoposter_last_media_type', resp.type || 'video');
                  } catch (e) {}
                  window.location.href = ((window.AUTOPOSTER_API_BASE || '/autoposter').replace(/\/+$/, '')) + '/#create';
                };
              }
            } else {
              showError(resp.message || 'فشل الرفع بالطريقة البديلة.');
            }
          })
          .catch(() => {
            if (progressShell) progressShell.style.display = 'none';
            showError('فشل الرفع بالطريقة البديلة.');
          });
      };
      reader.readAsDataURL(file);
    }

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

