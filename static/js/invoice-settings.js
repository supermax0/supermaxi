// تعريف المتغيرات العامة
let previewData = null;
let sortable = null;
let selectedTemplate = {
  id: Number(document.getElementById('selected_template_id')?.value || 0) || null
};

function buildInvoicePreviewUrl() {
  const raw = document.getElementById('selected_template_id')?.value;
  const id = parseInt(raw, 10);
  if (!id || Number.isNaN(id)) return null;
  const p = document.getElementById('primary_color')?.value || '';
  const s = document.getElementById('secondary_color')?.value || '';
  const qs = new URLSearchParams();
  if (/^#[0-9a-fA-F]{6}$/.test(p)) qs.set('primary_color', p);
  if (/^#[0-9a-fA-F]{6}$/.test(s)) qs.set('secondary_color', s);
  const bg = document.getElementById('warranty_card_background')?.value || '';
  if (bg.trim()) qs.set('warranty_bg', bg.trim());
  qs.set('t', String(Date.now()));
  return `/admin/invoice-templates/preview/${id}?${qs.toString()}`;
}

function syncInvoicePreviewIframe() {
  const iframe = document.getElementById('invoice_preview_iframe');
  const errEl = document.getElementById('preview_error');
  if (errEl) {
    errEl.style.display = 'none';
    errEl.textContent = '';
  }
  if (!iframe) return;
  const url = buildInvoicePreviewUrl();
  if (!url) {
    iframe.removeAttribute('src');
    iframe.srcdoc = '<body style="margin:0;font-family:Tajawal,sans-serif;padding:24px;text-align:center;color:#64748b;direction:rtl">اختر قالباً من «اختيار القالب» لعرض المعاينة</body>';
    iframe.style.opacity = '1';
    return;
  }
  iframe.removeAttribute('srcdoc');
  iframe.style.opacity = '1';
  iframe.src = url;
}

// تهيئة الصفحة عند التحميل
document.addEventListener('DOMContentLoaded', function() {
  syncColorInputs();
  loadPreview();
  initSortable();
  syncSelectedTemplateCard();

  const modal = document.getElementById('templatePickerOverlay');
  if (modal) {
    modal.addEventListener('click', function(e) {
      if (e.target === modal) closeTemplatePicker();
    });
  }
});

// تهيئة نظام السحب والإفلات
function initSortable() {
  const layoutItems = document.getElementById('layout_items');
  if (layoutItems) {
    sortable = new Sortable(layoutItems, {
      animation: 150,
      ghostClass: 'sortable-ghost',
      onEnd: function() {
        saveLayoutOrder();
        updatePreview();
      }
    });
  }
}

// حفظ ترتيب العناصر
function saveLayoutOrder() {
  const items = document.querySelectorAll('.layout-item');
  const order = Array.from(items).map(item => item.getAttribute('data-element'));
  
  if (order && order.length > 0) {
    localStorage.setItem('invoice_layout_order', JSON.stringify(order));
    return order;
  }
  return null;
}

// استرجاع ترتيب العناصر المحفوظ
function getLayoutOrder() {
  const saved = localStorage.getItem('invoice_layout_order');
  if (saved) {
    try {
      return JSON.parse(saved);
    } catch(e) {
      console.error('Error parsing layout order:', e);
    }
  }
  
  // الترتيب الافتراضي
  return ['header', 'summary-customer', 'products', 'total', 'footer'];
}

// إعادة تعيين التخطيط
function resetLayout() {
  if (confirm('هل أنت متأكد من إعادة تعيين ترتيب العناصر إلى الوضع الافتراضي؟')) {
    localStorage.removeItem('invoice_layout_order');
    
    // إعادة تحميل المعاينة
    if (previewData) {
      renderPreview(previewData);
    }
    
    showToast('تم إعادة تعيين التخطيط', 'success');
  }
}

// رفع اللوجو
function uploadLogo() {
  const fileInput = document.getElementById('logo_file');
  const file = fileInput.files[0];
  if (!file) return;
  
  // التحقق من نوع الملف
  if (!file.type.match('image.*')) {
    showToast('يرجى اختيار صورة فقط', 'error');
    return;
  }
  
  const formData = new FormData();
  formData.append('logo', file);
  
  // إظهار مؤشر التحميل
  showToast('جاري رفع اللوجو...', 'info');
  
  fetch('/settings/invoice/upload-logo', {
    method: 'POST',
    body: formData
  })
  .then(response => {
    if (!response.ok) {
      throw new Error('Network response was not ok');
    }
    return response.json();
  })
  .then(data => {
    if (data.success) {
      // تحديث معاينة اللوجو
      const logoPreview = document.getElementById('logo_preview');
      const logoContainer = logoPreview.parentNode;
      
      // إنشاء عنصر صورة جديد
      const newLogo = document.createElement('img');
      newLogo.id = 'logo_preview';
      newLogo.src = data.logo_path + '?t=' + Date.now();
      newLogo.alt = 'Logo';
      newLogo.className = 'logo-preview';
      
      // استبدال العنصر القديم
      logoContainer.replaceChild(newLogo, logoPreview);
      
      // إظهار زر الحذف
      document.getElementById('remove_logo_btn').style.display = 'inline-block';
      
      showToast('تم رفع اللوجو بنجاح', 'success');
      updatePreview();
    } else {
      showToast('حدث خطأ: ' + (data.error || 'غير معروف'), 'error');
    }
  })
  .catch(error => {
    console.error('Error uploading logo:', error);
    showToast('حدث خطأ أثناء رفع اللوجو', 'error');
  });
}

// حذف اللوجو
function removeLogo() {
  if (confirm('هل أنت متأكد من حذف اللوجو؟')) {
    fetch('/settings/invoice/remove-logo', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // تحديث معاينة اللوجو
        const logoPreview = document.getElementById('logo_preview');
        const logoContainer = logoPreview.parentNode;
        
        // إنشاء عنصر نائب جديد
        const placeholder = document.createElement('div');
        placeholder.id = 'logo_preview';
        placeholder.className = 'logo-preview-placeholder';
        placeholder.innerHTML = '<i class="fas fa-image"></i> لا يوجد لوجو';
        
        // استبدال العنصر القديم
        logoContainer.replaceChild(placeholder, logoPreview);
        
        // إخفاء زر الحذف
        document.getElementById('remove_logo_btn').style.display = 'none';
        
        showToast('تم حذف اللوجو', 'success');
        updatePreview();
      } else {
        showToast('حدث خطأ: ' + (data.error || 'غير معروف'), 'error');
      }
    })
    .catch(error => {
      console.error('Error removing logo:', error);
      showToast('حدث خطأ أثناء حذف اللوجو', 'error');
    });
  }
}

// رفع لوجو التقرير
function uploadReportLogo() {
  const fileInput = document.getElementById('report_logo_file');
  const file = fileInput.files[0];
  if (!file) return;
  if (!file.type.match('image.*')) {
    showToast('يرجى اختيار صورة فقط', 'error');
    return;
  }
  const formData = new FormData();
  formData.append('logo', file);
  showToast('جاري رفع لوجو التقرير...', 'info');
  fetch('/settings/invoice/upload-report-logo', { method: 'POST', body: formData })
    .then(response => { if (!response.ok) throw new Error('Network error'); return response.json(); })
    .then(data => {
      if (data.success) {
        const preview = document.getElementById('report_logo_preview');
        const container = preview.parentNode;
        const newLogo = document.createElement('img');
        newLogo.id = 'report_logo_preview';
        newLogo.src = data.logo_path + '?t=' + Date.now();
        newLogo.alt = 'Report Logo';
        newLogo.className = 'logo-preview';
        container.replaceChild(newLogo, preview);
        document.getElementById('remove_report_logo_btn').style.display = 'inline-block';
        showToast('تم رفع لوجو التقرير بنجاح', 'success');
      } else {
        showToast('حدث خطأ: ' + (data.error || 'غير معروف'), 'error');
      }
    })
    .catch(error => { console.error('Error uploading report logo:', error); showToast('حدث خطأ أثناء رفع اللوجو', 'error'); });
}

// حذف لوجو التقرير
function removeReportLogo() {
  if (!confirm('هل أنت متأكد من حذف لوجو التقرير؟')) return;
  fetch('/settings/invoice/remove-report-logo', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        const preview = document.getElementById('report_logo_preview');
        const container = preview.parentNode;
        const placeholder = document.createElement('div');
        placeholder.id = 'report_logo_preview';
        placeholder.className = 'logo-preview-placeholder';
        placeholder.innerHTML = '<i class="fas fa-image"></i> لا يوجد لوجو للتقرير';
        container.replaceChild(placeholder, preview);
        document.getElementById('remove_report_logo_btn').style.display = 'none';
        showToast('تم حذف لوجو التقرير', 'success');
      } else {
        showToast('حدث خطأ: ' + (data.error || 'غير معروف'), 'error');
      }
    })
    .catch(error => { console.error('Error removing report logo:', error); showToast('حدث خطأ أثناء حذف اللوجو', 'error'); });
}

// حفظ الإعدادات
function saveSettings() {
  const settings = {
    company_name: document.getElementById('company_name').value,
    company_subtitle: document.getElementById('company_subtitle').value,
    company_address: document.getElementById('company_address').value,
    company_phone: document.getElementById('company_phone').value,
    return_policy_notes: document.getElementById('return_policy_notes').value,
    warranty_notes: document.getElementById('warranty_notes').value,
    warranty_card_background: document.getElementById('warranty_card_background').value,
    logo_circle_text: document.getElementById('logo_circle_text').value,
    use_logo_image: document.getElementById('use_logo_image').checked,
    report_company_name: document.getElementById('report_company_name').value,
    report_address: document.getElementById('report_address').value,
    report_phone: document.getElementById('report_phone').value,
    report_footer_text: document.getElementById('report_footer_text').value,
    report_show_logo: document.getElementById('report_show_logo').checked,
    show_returned_count: document.getElementById('show_returned_count').checked,
    show_barcode: document.getElementById('show_barcode').checked,
    show_qrcode: document.getElementById('show_qrcode').checked,
    show_discount_column: document.getElementById('show_discount_column').checked,
    show_tax_column: document.getElementById('show_tax_column').checked,
    show_unit_price_with_tax: document.getElementById('show_unit_price_with_tax').checked,
    selected_template_id: document.getElementById('selected_template_id').value,
    primary_color: document.getElementById('primary_color').value,
    secondary_color: document.getElementById('secondary_color').value,
    custom_css: document.getElementById('custom_css').value
  };
  
  // إضافة ترتيب التخطيط إذا وجد
  const layoutOrder = getLayoutOrder();
  if (layoutOrder) {
    settings.layout_settings = JSON.stringify({ order: layoutOrder });
  }
  
  // إظهار مؤشر الحفظ
  showToast('جاري حفظ الإعدادات...', 'info');
  
  // تحويل الإعدادات إلى FormData
  const formData = new FormData();
  Object.keys(settings).forEach(key => {
    const value = settings[key];
    if (value === true || value === false) {
      formData.append(key, value ? 'true' : 'false');
    } else {
      formData.append(key, value || '');
    }
  });
  
  fetch('/settings/invoice/update', {
    method: 'POST',
    body: formData
  })
  .then(async response => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      showToast(data.error || ('فشل الحفظ (' + response.status + ')'), 'error');
      return null;
    }
    return data;
  })
  .then(data => {
    if (!data) return;
    if (data.success) {
      showToast('تم حفظ الإعدادات بنجاح', 'success');
      refreshPreview();
    } else {
      showToast('حدث خطأ: ' + (data.error || 'غير معروف'), 'error');
    }
  })
  .catch(error => {
    console.error('Error saving settings:', error);
    showToast('حدث خطأ أثناء حفظ الإعدادات', 'error');
  });
}

function openTemplatePicker() {
  const modal = document.getElementById('templatePickerOverlay');
  if (modal) modal.classList.add('active');
}

function closeTemplatePicker() {
  const modal = document.getElementById('templatePickerOverlay');
  if (modal) modal.classList.remove('active');
}

function selectTemplateOption(button) {
  const canSelect = button.dataset.canSelect === '1';
  if (!canSelect) {
    showToast('هذا القالب غير متاح حالياً. يجب شراؤه أو انتظار الموافقة أولاً.', 'warning');
    return;
  }

  document.querySelectorAll('.template-option-card').forEach(card => card.classList.remove('is-active'));
  button.classList.add('is-active');

  selectedTemplate = {
    id: Number(button.dataset.templateId),
    name: button.dataset.templateName,
    description: button.dataset.templateDescription,
    price: Number(button.dataset.templatePrice || 0)
  };

  document.getElementById('selected_template_id').value = selectedTemplate.id;
  syncSelectedTemplateCard();
  closeTemplatePicker();
  syncInvoicePreviewIframe();
  showToast('تم اختيار القالب. اضغط حفظ الإعدادات لتطبيقه.', 'success');
}

function syncSelectedTemplateCard() {
  const selectedId = Number(document.getElementById('selected_template_id')?.value || 0);
  const selectedCard = document.querySelector(`.template-option-card[data-template-id="${selectedId}"]`);
  const box = document.getElementById('selected_template_box');
  if (!box || !selectedCard) return;

  const name = selectedCard.dataset.templateName || 'بدون اسم';
  const desc = selectedCard.dataset.templateDescription || '';
  const price = Number(selectedCard.dataset.templatePrice || 0);

  box.innerHTML = `
    <div class="selected-template-name">${name}</div>
    <div class="selected-template-meta">${desc}</div>
    <div class="selected-template-badges">
      <span class="template-badge active">المحدد حالياً</span>
      ${price === 0
        ? '<span class="template-badge free">مجاني</span>'
        : `<span class="template-badge premium">${new Intl.NumberFormat().format(price)} د.ع</span>`}
    </div>
  `;
}

function openSelectedTemplatePreview() {
  const selectedId = document.getElementById('selected_template_id')?.value;
  if (!selectedId) {
    showToast('اختر قالباً أولاً', 'warning');
    return;
  }
  window.open(`/admin/invoice-templates/preview/${selectedId}`, '_blank');
}

function syncColorInputs() {
  const p = document.getElementById('primary_color');
  const pText = document.getElementById('primary_color_text');
  const s = document.getElementById('secondary_color');
  const sText = document.getElementById('secondary_color_text');
  if (p && pText) pText.value = p.value;
  if (s && sText) sText.value = s.value;
}

function syncColorFromText(type) {
  const picker = document.getElementById(type);
  const text = document.getElementById(`${type}_text`);
  if (!picker || !text) return;
  const v = (text.value || '').trim();
  if (/^#([0-9a-fA-F]{6})$/.test(v)) {
    picker.value = v;
    updatePreview();
  } else {
    showToast('صيغة اللون يجب أن تكون مثل #2563eb', 'warning');
    text.value = picker.value;
  }
}

function applyColorPreset(primary, secondary) {
  const p = document.getElementById('primary_color');
  const s = document.getElementById('secondary_color');
  if (p) p.value = primary;
  if (s) s.value = secondary;
  syncColorInputs();
  updatePreview();
}

function applyWarrantyBackground(value) {
  const bg = document.getElementById('warranty_card_background');
  if (bg) bg.value = value;
  updatePreview();
}

// تحميل معاينة الفاتورة
function loadPreview() {
  fetch('/settings/invoice/preview', {
    method: 'POST'
  })
  .then(response => {
    if (!response.ok) {
      throw new Error('Network response was not ok');
    }
    return response.json();
  })
  .then(data => {
    if (data.success) {
      // دمج visibility_settings مع settings
      if (data.settings && data.settings.visibility_settings) {
        Object.assign(data.settings, data.settings.visibility_settings);
      }
      if (data.settings) {
        if (data.settings.primary_color) {
          const p = document.getElementById('primary_color');
          if (p) p.value = data.settings.primary_color;
        }
        if (data.settings.secondary_color) {
          const s = document.getElementById('secondary_color');
          if (s) s.value = data.settings.secondary_color;
        }
        if (typeof data.settings.custom_css === 'string') {
          const c = document.getElementById('custom_css');
          if (c) c.value = data.settings.custom_css;
        }
        syncColorInputs();
      }
      previewData = data;
      renderPreview(data);
    } else {
      const errEl = document.getElementById('preview_error');
      if (errEl) {
        errEl.style.display = 'block';
        errEl.textContent = data.error || 'حدث خطأ في تحميل المعاينة';
      }
      const iframe = document.getElementById('invoice_preview_iframe');
      if (iframe) iframe.style.opacity = '1';
    }
  })
  .catch(error => {
    console.error('Error loading preview:', error);
    const errEl = document.getElementById('preview_error');
    if (errEl) {
      errEl.style.display = 'block';
      errEl.textContent = 'حدث خطأ أثناء تحميل المعاينة. تأكد من اتصالك بالإنترنت.';
    }
    const iframe = document.getElementById('invoice_preview_iframe');
    if (iframe) iframe.style.opacity = '1';
  });
}

// تحديث المعاينة
function refreshPreview() {
  const iframe = document.getElementById('invoice_preview_iframe');
  if (iframe) iframe.style.opacity = '0.45';
  loadPreview();
}

// تحديث المعاينة مع القيم الحالية
function updatePreview() {
  if (!previewData) return;
  
  const s = previewData.settings;
  s.company_name = document.getElementById('company_name').value;
  s.company_subtitle = document.getElementById('company_subtitle').value;
  s.company_address = document.getElementById('company_address').value;
  s.company_phone = document.getElementById('company_phone').value;
  s.return_policy_notes = document.getElementById('return_policy_notes').value;
  s.warranty_notes = document.getElementById('warranty_notes').value;
  s.warranty_card_background = document.getElementById('warranty_card_background').value;
  s.logo_circle_text = document.getElementById('logo_circle_text').value;
  s.use_logo_image = document.getElementById('use_logo_image').checked;
  s.show_returned_count = document.getElementById('show_returned_count').checked;
  s.show_barcode = document.getElementById('show_barcode').checked;
  s.show_qrcode = document.getElementById('show_qrcode').checked;
  s.show_discount_column = document.getElementById('show_discount_column').checked;
  s.show_tax_column = document.getElementById('show_tax_column').checked;
  s.show_unit_price_with_tax = document.getElementById('show_unit_price_with_tax').checked;
  s.primary_color = document.getElementById('primary_color').value;
  s.secondary_color = document.getElementById('secondary_color').value;
  s.custom_css = document.getElementById('custom_css').value;
  syncColorInputs();
  
  renderPreview(previewData);
}

// معاينة الفاتورة في نافذة جديدة
function previewInvoice() {
  const url = buildInvoicePreviewUrl();
  if (!url) {
    showToast('اختر قالباً لعرض المعاينة', 'warning');
    return;
  }
  window.open(url, '_blank');
}

// عرض المعاينة (القالب الحقيقي عبر iframe — يتبع اختيار القالب والألوان)
function renderPreview(data) {
  if (!data) return;
  if (data.settings && data.settings.visibility_settings) {
    Object.assign(data.settings, data.settings.visibility_settings);
  }
  syncInvoicePreviewIframe();
}

// تحميل مكتبات الباركود وQR Code
function loadBarcodeLibs() {
  if (!previewData || !previewData.settings) return;
  
  const s = previewData.settings;
  
  // تحميل JsBarcode إذا كان مفعلاً
  if (s.show_barcode) {
    if (typeof JsBarcode === 'undefined') {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/jsbarcode@3.11.5/dist/JsBarcode.all.min.js';
      script.onload = function() {
        try {
          const barcodeEl = document.querySelector("#preview_barcode");
          if (barcodeEl) {
            JsBarcode("#preview_barcode", "TEST-001", {
              format: "CODE128",
              width: 2,
              height: 50,
              displayValue: true,
              fontSize: 12
            });
          }
        } catch(e) {
          console.error('Error loading JsBarcode:', e);
        }
      };
      document.head.appendChild(script);
    } else {
      try {
        const barcodeEl = document.querySelector("#preview_barcode");
        if (barcodeEl) {
          JsBarcode("#preview_barcode", "TEST-001", {
            format: "CODE128",
            width: 2,
            height: 50,
            displayValue: true,
            fontSize: 12
          });
        }
      } catch(e) {
        console.error('Error using JsBarcode:', e);
      }
    }
  }
  
  // تحميل QRCode إذا كان مفعلاً
  if (s.show_qrcode) {
    if (typeof QRCode === 'undefined') {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js';
      script.onload = function() {
        try {
          const qrContainer = document.getElementById("preview_qrcode");
          if (qrContainer) {
            qrContainer.innerHTML = '';
            new QRCode(qrContainer, {
              text: window.location.origin + '/orders/invoice/TEST-001',
              width: 100,
              height: 100,
              colorDark: "#000000",
              colorLight: "#ffffff"
            });
          }
        } catch(e) {
          console.error('Error loading QRCode:', e);
        }
      };
      document.head.appendChild(script);
    } else {
      try {
        const qrContainer = document.getElementById("preview_qrcode");
        if (qrContainer) {
          qrContainer.innerHTML = '';
          new QRCode(qrContainer, {
            text: window.location.origin + '/orders/invoice/TEST-001',
            width: 100,
            height: 100,
            colorDark: "#000000",
            colorLight: "#ffffff"
          });
        }
      } catch(e) {
        console.error('Error using QRCode:', e);
      }
    }
  }
}
