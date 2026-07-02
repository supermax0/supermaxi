(function () {
  'use strict';

  var state = null;
  var apiBase = '/api/superadmin/landing';
  var alertBox = document.getElementById('landingAdminAlert');

  var labels = {
    site_name: 'اسم الموقع',
    page_title: 'عنوان الصفحة',
    page_subtitle: 'وصف الصفحة',
    default_language: 'اللغة الافتراضية',
    logo_url: 'رابط الشعار',
    favicon_url: 'رابط الأيقونة',
    primary_color: 'اللون الأساسي',
    secondary_color: 'اللون الثانوي',
    accent_color: 'لون التمييز',
    background_color: 'لون الخلفية',
    text_color: 'لون النص',
    font_family: 'الخط',
    whatsapp_number: 'رقم واتساب',
    contact_email: 'البريد',
    login_url: 'رابط الدخول',
    trial_url: 'رابط التجربة',
    demo_booking_url: 'رابط حجز العرض',
    section_key: 'مفتاح القسم',
    section_type: 'نوع القسم',
    title: 'العنوان',
    subtitle: 'العنوان الفرعي',
    description: 'الوصف',
    content: 'محتوى JSON',
    image_url: 'رابط الصورة',
    video_url: 'رابط الفيديو',
    button_primary_text: 'زر رئيسي',
    button_primary_url: 'رابط الزر الرئيسي',
    button_secondary_text: 'زر ثانوي',
    button_secondary_url: 'رابط الزر الثانوي',
    sort_order: 'الترتيب',
    is_visible: 'ظاهر',
    animation_type: 'نوع الحركة',
    background_style: 'الخلفية',
    icon: 'أيقونة Font Awesome',
    feature_key: 'مفتاح الميزة',
    name: 'الاسم',
    short_description: 'وصف قصير',
    long_description: 'وصف طويل',
    screenshot_url: 'رابط السكرينشوت',
    slug: 'Slug',
    price: 'السعر',
    currency: 'العملة',
    billing_period: 'الفترة',
    features: 'المميزات JSON',
    limits: 'الحدود JSON',
    cta_text: 'نص الزر',
    cta_url: 'رابط الزر',
    badge_text: 'شارة الخطة',
    is_popular: 'الأكثر شيوعاً',
    question: 'السؤال',
    answer: 'الإجابة',
    category: 'التصنيف',
    customer_name: 'اسم العميل',
    customer_title: 'صفة العميل',
    company_name: 'الشركة',
    quote: 'الرأي',
    avatar_url: 'الصورة',
    rating: 'التقييم',
    label: 'النص',
    url: 'الرابط',
    cta_type: 'نوع CTA',
    placement_key: 'مكان الظهور',
    meta_title: 'Meta title',
    meta_description: 'Meta description',
    meta_keywords: 'Meta keywords',
    og_title: 'OG title',
    og_description: 'OG description',
    og_image_url: 'OG image',
    twitter_title: 'Twitter title',
    twitter_description: 'Twitter description',
    twitter_image_url: 'Twitter image',
    canonical_url: 'Canonical URL',
    robots: 'Robots',
    schema: 'Schema JSON'
  };

  var fields = {
    settings: ['site_name', 'page_title', 'page_subtitle', 'logo_url', 'favicon_url', 'whatsapp_number', 'contact_email', 'login_url', 'trial_url', 'demo_booking_url'],
    theme: ['primary_color', 'secondary_color', 'accent_color', 'background_color', 'text_color', 'font_family'],
    seo: ['meta_title', 'meta_description', 'meta_keywords', 'og_title', 'og_description', 'og_image_url', 'twitter_title', 'twitter_description', 'twitter_image_url', 'canonical_url', 'robots', 'schema'],
    sections: ['section_key', 'section_type', 'title', 'subtitle', 'description', 'content', 'image_url', 'video_url', 'button_primary_text', 'button_primary_url', 'button_secondary_text', 'button_secondary_url', 'sort_order', 'is_visible', 'animation_type', 'background_style'],
    features: ['title', 'description', 'icon', 'image_url', 'feature_key', 'sort_order', 'is_visible'],
    modules: ['name', 'short_description', 'long_description', 'icon', 'screenshot_url', 'sort_order', 'is_visible'],
    pricing: ['name', 'slug', 'price', 'currency', 'billing_period', 'description', 'features', 'limits', 'cta_text', 'cta_url', 'badge_text', 'is_popular', 'is_visible', 'sort_order'],
    faqs: ['question', 'answer', 'category', 'sort_order', 'is_visible'],
    testimonials: ['customer_name', 'customer_title', 'company_name', 'quote', 'avatar_url', 'rating', 'is_visible', 'sort_order'],
    ctas: ['label', 'url', 'cta_type', 'placement_key', 'is_visible', 'sort_order']
  };

  function showAlert(message, isError) {
    alertBox.hidden = false;
    alertBox.textContent = message;
    alertBox.classList.toggle('error', !!isError);
    clearTimeout(showAlert.timer);
    showAlert.timer = setTimeout(function () { alertBox.hidden = true; }, 4500);
  }

  function request(url, options) {
    return fetch(url, Object.assign({
      headers: { 'Content-Type': 'application/json' }
    }, options || {})).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok || !data.success) throw new Error(data.error || 'حدث خطأ غير متوقع');
        return data;
      });
    });
  }

  function valueFor(item, field) {
    var value = item[field];
    if (field === 'content') value = item.content || {};
    if (field === 'features') value = item.features || [];
    if (field === 'limits') value = item.limits || {};
    if (field === 'schema') value = item.schema || {};
    if (typeof value === 'object' && value !== null) return JSON.stringify(value, null, 2);
    return value == null ? '' : value;
  }

  function inputType(field) {
    if (/color$/.test(field)) return 'color';
    if (['sort_order', 'rating', 'price'].indexOf(field) !== -1) return 'number';
    if (field.indexOf('url') !== -1 || field === 'canonical_url') return 'url';
    if (field === 'contact_email') return 'email';
    return 'text';
  }

  function fieldHtml(field, value) {
    var full = ['description', 'page_subtitle', 'content', 'features', 'limits', 'schema', 'answer', 'quote', 'long_description', 'meta_description', 'og_description', 'twitter_description'].indexOf(field) !== -1;
    var label = labels[field] || field;
    if (['is_visible', 'is_popular'].indexOf(field) !== -1) {
      return '<label class="landing-field"><span>' + label + '</span><select name="' + field + '"><option value="true"' + (value ? ' selected' : '') + '>نعم</option><option value="false"' + (!value ? ' selected' : '') + '>لا</option></select></label>';
    }
    if (full) {
      return '<label class="landing-field full"><span>' + label + '</span><textarea name="' + field + '">' + escapeHtml(value) + '</textarea></label>';
    }
    return '<label class="landing-field"><span>' + label + '</span><input name="' + field + '" type="' + inputType(field) + '" value="' + escapeHtml(value) + '"></label>';
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function collectForm(form) {
    var data = {};
    new FormData(form).forEach(function (value, key) {
      if (['content', 'features', 'limits', 'schema'].indexOf(key) !== -1) {
        try { data[key] = JSON.parse(value || (key === 'features' ? '[]' : '{}')); }
        catch (e) { data[key] = key === 'features' ? [] : {}; }
      } else if (['is_visible', 'is_popular'].indexOf(key) !== -1) {
        data[key] = value === 'true';
      } else {
        data[key] = value;
      }
    });
    return data;
  }

  function renderSingleForm(formId, source, endpoint) {
    var form = document.getElementById(formId);
    var fieldList = formId === 'themeForm' ? fields.theme : fields[formId.replace('Form', '')];
    form.innerHTML = fieldList.map(function (field) {
      return fieldHtml(field, valueFor(source, field));
    }).join('') + '<div class="landing-form-actions"><button class="btn-primary" type="submit"><i class="fas fa-save"></i>حفظ المسودة</button></div>';
    form.onsubmit = function (e) {
      e.preventDefault();
      request(endpoint, { method: 'PUT', body: JSON.stringify(collectForm(form)) })
        .then(function () { showAlert('تم حفظ المسودة'); return load(); })
        .catch(function (err) { showAlert(err.message, true); });
    };
  }

  function titleFor(collection, item) {
    return item.title || item.name || item.question || item.customer_name || item.label || item.slug || ('#' + item.id);
  }

  function renderCollection(collection) {
    var list = document.getElementById(collection + 'List');
    if (!list) return;
    var items = state[collection] || [];
    list.innerHTML = items.map(function (item) {
      return '<article class="landing-edit-card" data-id="' + item.id + '">' +
        '<div class="landing-edit-card-head"><h4>' + escapeHtml(titleFor(collection, item)) + '</h4><span>#' + item.id + '</span></div>' +
        '<form class="landing-item-form">' +
        fields[collection].map(function (field) { return fieldHtml(field, valueFor(item, field)); }).join('') +
        '<div class="landing-item-actions"><button class="btn-primary" type="submit"><i class="fas fa-save"></i>حفظ</button><button class="btn-danger" type="button" data-delete="' + collection + '" data-id="' + item.id + '"><i class="fas fa-trash"></i>حذف</button></div>' +
        '</form></article>';
    }).join('');

    list.querySelectorAll('form').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var id = form.closest('[data-id]').getAttribute('data-id');
        request(apiBase + '/' + collection + '/' + id, { method: 'PUT', body: JSON.stringify(collectForm(form)) })
          .then(function () { showAlert('تم حفظ العنصر'); return load(); })
          .catch(function (err) { showAlert(err.message, true); });
      });
    });
  }

  function renderMedia() {
    var list = document.getElementById('mediaList');
    var items = state.media || [];
    list.innerHTML = items.map(function (item) {
      var preview = item.media_type === 'video'
        ? '<video src="' + escapeHtml(item.file_url) + '" controls></video>'
        : '<img src="' + escapeHtml(item.file_url) + '" alt="' + escapeHtml(item.alt_text || item.title) + '">';
      return '<article class="landing-media-item">' + preview +
        '<strong>' + escapeHtml(item.title || 'وسيط') + '</strong>' +
        '<input readonly value="' + escapeHtml(item.file_url) + '">' +
        '<button class="btn-danger" type="button" data-delete="media" data-id="' + item.id + '"><i class="fas fa-trash"></i>حذف</button>' +
        '</article>';
    }).join('');
  }

  function renderMetrics() {
    var box = document.getElementById('landingMetrics');
    box.innerHTML = [
      ['الأقسام', state.sections.length],
      ['المميزات', state.features.length],
      ['الخطط', state.pricing.length],
      ['FAQ', state.faqs.length]
    ].map(function (m) {
      return '<div class="landing-metric"><strong>' + m[1] + '</strong><span>' + m[0] + '</span></div>';
    }).join('');
  }

  function renderAll() {
    renderMetrics();
    renderSingleForm('settingsForm', state.settings || {}, apiBase + '/settings');
    renderSingleForm('themeForm', state.settings || {}, apiBase + '/settings');
    renderSingleForm('seoForm', state.seo || {}, apiBase + '/seo');
    ['sections', 'features', 'modules', 'pricing', 'faqs', 'testimonials', 'ctas'].forEach(renderCollection);
    renderMedia();
  }

  function load() {
    return request(apiBase, { method: 'GET' }).then(function (data) {
      state = data.data;
      renderAll();
    }).catch(function (err) {
      showAlert(err.message, true);
    });
  }

  document.querySelectorAll('.landing-admin-tabs button').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var tab = btn.getAttribute('data-tab');
      document.querySelectorAll('.landing-admin-tabs button').forEach(function (b) { b.classList.remove('active'); });
      document.querySelectorAll('.landing-panel').forEach(function (p) { p.classList.remove('active'); });
      btn.classList.add('active');
      document.querySelector('[data-panel="' + tab + '"]').classList.add('active');
    });
  });

  document.addEventListener('click', function (e) {
    var addBtn = e.target.closest('[data-add]');
    if (addBtn) {
      var collection = addBtn.getAttribute('data-add');
      request(apiBase + '/' + collection, { method: 'POST', body: JSON.stringify(defaultItem(collection)) })
        .then(function () { showAlert('تمت إضافة عنصر جديد'); return load(); })
        .catch(function (err) { showAlert(err.message, true); });
    }
    var delBtn = e.target.closest('[data-delete]');
    if (delBtn) {
      var col = delBtn.getAttribute('data-delete');
      var id = delBtn.getAttribute('data-id');
      if (!confirm('حذف هذا العنصر من المسودة؟')) return;
      request(apiBase + '/' + col + '/' + id, { method: 'DELETE' })
        .then(function () { showAlert('تم الحذف'); return load(); })
        .catch(function (err) { showAlert(err.message, true); });
    }
  });

  function defaultItem(collection) {
    var order = ((state && state[collection]) ? state[collection].length + 1 : 1) * 10;
    if (collection === 'sections') return { section_key: 'custom_' + Date.now(), section_type: 'custom', title: 'قسم جديد', subtitle: '', description: '', content: {}, sort_order: order, is_visible: true };
    if (collection === 'features') return { title: 'ميزة جديدة', description: '', icon: 'fa-solid fa-circle-check', feature_key: 'feature_' + Date.now(), sort_order: order, is_visible: true };
    if (collection === 'modules') return { name: 'موديل جديد', short_description: '', long_description: '', icon: 'fa-solid fa-layer-group', sort_order: order, is_visible: true };
    if (collection === 'pricing') return { name: 'خطة جديدة', slug: 'plan-' + Date.now(), price: 0, currency: '$', billing_period: 'شهري', description: '', features: [], limits: {}, cta_text: 'ابدأ الآن', cta_url: '/signup', sort_order: order, is_visible: true };
    if (collection === 'faqs') return { question: 'سؤال جديد', answer: '', category: 'عام', sort_order: order, is_visible: true };
    if (collection === 'testimonials') return { customer_name: 'عميل جديد', customer_title: '', company_name: '', quote: '', rating: 5, sort_order: order, is_visible: true };
    if (collection === 'ctas') return { label: 'زر جديد', url: '#', cta_type: 'trial', placement_key: 'hero', sort_order: order, is_visible: true };
    return {};
  }

  document.getElementById('publishLandingBtn').addEventListener('click', function () {
    if (!confirm('نشر المسودة الحالية للزوار؟')) return;
    request(apiBase + '/publish', { method: 'POST', body: '{}' })
      .then(function () { showAlert('تم نشر صفحة الهبوط بنجاح'); return load(); })
      .catch(function (err) { showAlert(err.message, true); });
  });

  document.getElementById('mediaUploadForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var form = e.currentTarget;
    fetch(apiBase + '/media/upload', { method: 'POST', body: new FormData(form) })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (!data.success) throw new Error(data.error || 'تعذر رفع الملف');
        form.reset();
        showAlert('تم رفع الوسيط');
        return load();
      })
      .catch(function (err) { showAlert(err.message, true); });
  });

  load();
})();
