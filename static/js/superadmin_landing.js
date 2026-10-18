(function () {
  'use strict';

  var state = null;
  var freePlanState = null;
  var openCards = {};
  var apiBase = '/api/superadmin/landing';
  var alertBox = document.getElementById('landingAdminAlert');

  var freeFeatureLabels = {
    orders: 'إدارة الطلبات', pos: 'نقطة البيع (POS)', inventory: 'إدارة المخزون',
    customers: 'إدارة الزبائن', cashflow: 'التحصيل والمدفوعات', printing: 'الطباعة والفواتير',
    expenses: 'إدارة المصروفات', suppliers: 'الموردون', purchases: 'المشتريات', shipping: 'شركات النقل',
    reports_adv: 'التقارير المالية المتقدمة', rbac: 'الصلاحيات', agents: 'مناديب التوصيل', accounts: 'دفتر الحسابات',
    ai_assistant: 'المساعد الذكي', ai_workspace: 'مساحة العمل الذكية', messages: 'نظام الرسائل'
  };

  var collectionIcons = {
    sections: 'fa-layer-group', features: 'fa-stars', modules: 'fa-table-cells-large', pricing: 'fa-tags',
    faqs: 'fa-circle-question', testimonials: 'fa-comment-dots', ctas: 'fa-bullhorn'
  };

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
    whatsapp_enabled: 'إظهار زر واتساب',
    whatsapp_message: 'رسالة واتساب الافتراضية',
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
    settings: ['site_name', 'page_title', 'page_subtitle', 'logo_url', 'favicon_url', 'whatsapp_number', 'whatsapp_enabled', 'whatsapp_message', 'contact_email', 'login_url', 'trial_url', 'demo_booking_url'],
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

  function setBusy(button, busy, label) {
    if (!button) return;
    if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
    button.disabled = !!busy;
    button.innerHTML = busy ? '<i class="fas fa-circle-notch fa-spin"></i>' + (label || 'جاري الحفظ…') : button.dataset.originalHtml;
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
    if (['is_visible', 'is_popular', 'whatsapp_enabled'].indexOf(field) !== -1) {
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
      } else if (['is_visible', 'is_popular', 'whatsapp_enabled'].indexOf(key) !== -1) {
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
      var submit = form.querySelector('[type="submit"]');
      setBusy(submit, true);
      request(endpoint, { method: 'PUT', body: JSON.stringify(collectForm(form)) })
        .then(function () { showAlert('تم حفظ المسودة'); return load(); })
        .catch(function (err) { showAlert(err.message, true); setBusy(submit, false); });
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
      var cardKey = collection + ':' + item.id;
      var isOpen = !!openCards[cardKey];
      return '<article class="landing-edit-card' + (isOpen ? ' open' : '') + '" data-id="' + item.id + '" data-card-key="' + cardKey + '">' +
        '<div class="landing-edit-card-head" role="button" tabindex="0" aria-expanded="' + (isOpen ? 'true' : 'false') + '"><div><i class="fas ' + (collectionIcons[collection] || 'fa-pen') + '"></i><div><h4>' + escapeHtml(titleFor(collection, item)) + '</h4><small>#' + item.id + ' · ' + (item.is_visible === false ? 'مخفي' : 'ظاهر') + '</small></div></div><button type="button" class="landing-card-toggle" aria-label="فتح التفاصيل"><i class="fas fa-chevron-down"></i></button></div>' +
        '<form class="landing-item-form">' +
        fields[collection].map(function (field) { return fieldHtml(field, valueFor(item, field)); }).join('') +
        '<div class="landing-item-actions"><button class="btn-primary" type="submit"><i class="fas fa-save"></i>حفظ</button><button class="btn-danger" type="button" data-delete="' + collection + '" data-id="' + item.id + '"><i class="fas fa-trash"></i>حذف</button></div>' +
        '</form></article>';
    }).join('');

    list.querySelectorAll('.landing-edit-card-head').forEach(function (head) {
      function toggleCard() {
        var card = head.closest('.landing-edit-card');
        var open = card.classList.toggle('open');
        openCards[card.dataset.cardKey] = open;
        head.setAttribute('aria-expanded', open ? 'true' : 'false');
      }
      head.addEventListener('click', toggleCard);
      head.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleCard(); }
      });
    });

    list.querySelectorAll('form').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var id = form.closest('[data-id]').getAttribute('data-id');
        var submit = form.querySelector('[type="submit"]');
        setBusy(submit, true);
        request(apiBase + '/' + collection + '/' + id, { method: 'PUT', body: JSON.stringify(collectForm(form)) })
          .then(function () { showAlert('تم حفظ العنصر'); return load(); })
          .catch(function (err) { showAlert(err.message, true); setBusy(submit, false); });
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
      ['الأقسام', state.sections.length, 'fa-layer-group'],
      ['المميزات', state.features.length, 'fa-stars'],
      ['بطاقات الخطط', state.pricing.length, 'fa-tags'],
      ['الأسئلة', state.faqs.length, 'fa-circle-question']
    ].map(function (m) {
      return '<div class="landing-metric"><i class="fas ' + m[2] + '"></i><div><strong>' + m[1] + '</strong><span>' + m[0] + '</span></div></div>';
    }).join('');
  }

  function freePlanPayloadFromForm() {
    var featureValues = {};
    document.querySelectorAll('#freePlanFeatures input[data-feature]').forEach(function (input) {
      featureValues[input.dataset.feature] = input.checked;
    });
    return {
      enabled: document.getElementById('freePlanEnabled').checked,
      trial_days: document.getElementById('freeTrialDays').value,
      name: document.getElementById('freePlanName').value.trim(),
      max_users: document.getElementById('freePlanMaxUsers').value,
      max_orders_monthly: document.getElementById('freePlanMaxOrders').value,
      badge_text: document.getElementById('freePlanBadge').value.trim(),
      description: document.getElementById('freePlanDescription').value.trim(),
      cta_text: document.getElementById('freePlanCta').value.trim(),
      landing_features: document.getElementById('freePlanLandingFeatures').value.split(/\r?\n/).map(function (item) { return item.trim(); }).filter(Boolean),
      system_features: featureValues
    };
  }

  function syncFreePlanPreview() {
    if (!document.getElementById('freePlanForm')) return;
    var data = freePlanPayloadFromForm();
    var days = Math.max(1, Number(data.trial_days) || 1);
    document.getElementById('freePlanEnabledLabel').textContent = data.enabled ? 'مفعّل' : 'متوقف';
    document.getElementById('freePlanPreview').classList.toggle('is-disabled', !data.enabled);
    document.getElementById('freePreviewName').textContent = data.name || 'الخطة المجانية';
    document.getElementById('freePreviewBadge').textContent = data.badge_text || 'تجربة مجانية';
    document.getElementById('freePreviewDescription').textContent = data.description || 'جرّب أساسيات فينورا مجاناً.';
    document.getElementById('freePreviewDuration').textContent = days + (days === 1 ? ' يوم مجاناً' : ' يوماً مجاناً');
    document.getElementById('freePreviewCta').textContent = data.cta_text || 'ابدأ مجاناً';
    document.getElementById('freePreviewFeatures').innerHTML = data.landing_features.slice(0, 6).map(function (feature) {
      return '<li><i class="fas fa-circle-check"></i>' + escapeHtml(feature) + '</li>';
    }).join('') || '<li><i class="fas fa-circle-check"></i>ميزات فينورا الأساسية</li>';
    document.querySelectorAll('[data-trial-days]').forEach(function (button) {
      button.classList.toggle('active', Number(button.dataset.trialDays) === days);
    });
  }

  function renderFreePlan() {
    if (!freePlanState || !document.getElementById('freePlanForm')) return;
    document.getElementById('freePlanEnabled').checked = !!freePlanState.enabled;
    document.getElementById('freeTrialDays').value = freePlanState.trial_days || 14;
    document.getElementById('freePlanName').value = freePlanState.name || 'الخطة المجانية';
    document.getElementById('freePlanMaxUsers').value = freePlanState.max_users == null ? '' : freePlanState.max_users;
    document.getElementById('freePlanMaxOrders').value = freePlanState.max_orders_monthly == null ? '' : freePlanState.max_orders_monthly;
    document.getElementById('freePlanBadge').value = freePlanState.badge_text || '';
    document.getElementById('freePlanDescription').value = freePlanState.description || '';
    document.getElementById('freePlanCta').value = freePlanState.cta_text || '';
    document.getElementById('freePlanLandingFeatures').value = (freePlanState.landing_features || []).join('\n');
    document.getElementById('freePlanFeatures').innerHTML = Object.keys(freeFeatureLabels).map(function (key) {
      var checked = freePlanState.system_features && freePlanState.system_features[key];
      return '<label class="free-feature-toggle"><input type="checkbox" data-feature="' + key + '"' + (checked ? ' checked' : '') + '><span>' + freeFeatureLabels[key] + '</span></label>';
    }).join('');

    document.querySelectorAll('#freePlanForm input, #freePlanForm textarea').forEach(function (input) { input.oninput = syncFreePlanPreview; input.onchange = syncFreePlanPreview; });
    document.querySelectorAll('[data-trial-days]').forEach(function (button) {
      button.onclick = function () { document.getElementById('freeTrialDays').value = button.dataset.trialDays; syncFreePlanPreview(); };
    });
    document.getElementById('freePlanForm').onsubmit = function (event) {
      event.preventDefault();
      var submit = document.getElementById('saveFreePlanBtn');
      setBusy(submit, true, 'جاري الحفظ…');
      request(apiBase + '/free-plan', { method: 'PUT', body: JSON.stringify(freePlanPayloadFromForm()) })
        .then(function (data) {
          freePlanState = data.item;
          showAlert('تم حفظ الاشتراك المجاني. المدة تطبّق فوراً، وانشر لإظهار البطاقة للزوار.');
          renderFreePlan();
          setBusy(submit, false);
        })
        .catch(function (error) { showAlert(error.message, true); setBusy(submit, false); });
    };
    syncFreePlanPreview();
  }

  function renderAll() {
    renderMetrics();
    renderSingleForm('settingsForm', state.settings || {}, apiBase + '/settings');
    renderSingleForm('themeForm', state.settings || {}, apiBase + '/settings');
    renderSingleForm('seoForm', state.seo || {}, apiBase + '/seo');
    ['sections', 'features', 'modules', 'pricing', 'faqs', 'testimonials', 'ctas'].forEach(renderCollection);
    renderMedia();
    renderFreePlan();
  }

  function load() {
    return Promise.all([
      request(apiBase, { method: 'GET' }),
      request(apiBase + '/free-plan', { method: 'GET' })
    ]).then(function (results) {
      state = results[0].data;
      freePlanState = results[1].item;
      renderAll();
    }).catch(function (err) {
      showAlert(err.message, true);
    });
  }

  function activateTab(tab, shouldScroll) {
    var button = document.querySelector('.landing-admin-tabs button[data-tab="' + tab + '"]');
    var panel = document.querySelector('[data-panel="' + tab + '"]');
    if (!button || !panel) return;
    document.querySelectorAll('.landing-admin-tabs button').forEach(function (item) { item.classList.toggle('active', item === button); });
    document.querySelectorAll('.landing-panel').forEach(function (item) { item.classList.toggle('active', item === panel); });
    if (window.history && history.replaceState) history.replaceState(null, '', '#' + tab);
    if (shouldScroll && window.innerWidth < 901) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  document.querySelectorAll('.landing-admin-tabs button[data-tab]').forEach(function (btn) {
    btn.addEventListener('click', function () { activateTab(btn.getAttribute('data-tab'), true); });
  });

  document.querySelectorAll('[data-jump-tab]').forEach(function (card) {
    card.addEventListener('click', function () { activateTab(card.getAttribute('data-jump-tab'), true); });
  });

  var navSearch = document.getElementById('landingNavSearch');
  if (navSearch) navSearch.addEventListener('input', function () {
    var query = navSearch.value.trim().toLowerCase();
    document.querySelectorAll('.landing-admin-tabs button[data-tab]').forEach(function (button) {
      button.hidden = !!query && button.textContent.toLowerCase().indexOf(query) === -1;
    });
  });

  document.addEventListener('click', function (e) {
    var addBtn = e.target.closest('[data-add]');
    if (addBtn) {
      var collection = addBtn.getAttribute('data-add');
      request(apiBase + '/' + collection, { method: 'POST', body: JSON.stringify(defaultItem(collection)) })
        .then(function (data) { if (data.item) openCards[collection + ':' + data.item.id] = true; showAlert('تمت إضافة عنصر جديد'); return load(); })
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
    var freePlanForm = document.getElementById('freePlanForm');
    if (freePlanForm && !freePlanForm.reportValidity()) {
      activateTab('free-plan', true);
      showAlert('راجع بيانات الاشتراك المجاني قبل النشر.', true);
      return;
    }
    if (!confirm('نشر المسودة الحالية للزوار؟')) return;
    var publishButton = document.getElementById('publishLandingBtn');
    setBusy(publishButton, true, 'جاري الحفظ والنشر…');
    var saveFreePlan = freePlanForm
      ? request(apiBase + '/free-plan', { method: 'PUT', body: JSON.stringify(freePlanPayloadFromForm()) }).then(function (data) {
          freePlanState = data.item;
          return data;
        })
      : Promise.resolve();
    saveFreePlan
      .then(function () { return request(apiBase + '/publish', { method: 'POST', body: '{}' }); })
      .then(function () { showAlert('تم حفظ إعدادات الاشتراك ونشر صفحة الهبوط بنجاح'); return load(); })
      .then(function () { setBusy(publishButton, false); })
      .catch(function (err) { showAlert(err.message, true); setBusy(publishButton, false); });
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

  var initialTab = (window.location.hash || '').replace('#', '');
  if (initialTab) activateTab(initialTab, false);
  load();
})();
