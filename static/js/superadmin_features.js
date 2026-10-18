/* Super Admin: Finora AI Tutor feature controls (list filters, bulk, per-tenant panel, kill switch). */
(function () {
    'use strict';

    var FEATURE = 'clinic_ai_tutor';
    var BASE = '/superadmin/features';

    function $(id) { return document.getElementById(id); }

    function api(method, url, body) {
        return fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: body === undefined ? undefined : JSON.stringify(body)
        }).then(function (res) {
            return res.json().then(function (data) {
                if (!res.ok || data.ok === false) {
                    throw new Error(data.error || ('HTTP ' + res.status));
                }
                return data;
            });
        });
    }

    function fmt(iso) {
        return iso ? iso.replace('T', ' ').slice(0, 16) : '—';
    }

    function stateLabel(state) {
        return { enabled: 'مفعّل', disabled: 'غير مفعّل', expired: 'منتهي' }[state] || state;
    }

    // ---- list: search, filter, selection, bulk -------------------------------
    var rows = Array.prototype.slice.call(document.querySelectorAll('tr.tenant-row'));
    var search = $('ft-search');
    var filter = $('ft-filter');
    var selectAll = $('ft-select-all');
    var counter = $('ft-selected');
    var bulkEnable = $('ft-bulk-enable');
    var bulkDisable = $('ft-bulk-disable');
    var killSwitch = $('ft-kill-switch');
    var toolbar = $('aiTutorToolbar');

    function visibleRows() {
        return rows.filter(function (row) { return row.style.display !== 'none'; });
    }

    function selectedSlugs() {
        return rows
            .filter(function (row) { return row.querySelector('.ft-row-select').checked && row.style.display !== 'none'; })
            .map(function (row) { return row.dataset.slug; });
    }

    function refreshSelection() {
        var count = selectedSlugs().length;
        if (counter) { counter.textContent = count + ' حسابات محددة'; }
        if (bulkEnable) { bulkEnable.disabled = count === 0; }
        if (bulkDisable) { bulkDisable.disabled = count === 0; }
    }

    function applyFilters() {
        var needle = (search && search.value || '').trim().toLowerCase();
        var state = filter ? filter.value : 'all';
        rows.forEach(function (row) {
            var text = (row.dataset.name + ' ' + row.dataset.slug).toLowerCase();
            var okText = !needle || text.indexOf(needle) !== -1;
            var okState = state === 'all' || row.dataset.aiTutorState === state;
            row.style.display = okText && okState ? '' : 'none';
        });
        refreshSelection();
    }

    function setRowState(slug, state) {
        rows.forEach(function (row) {
            if (row.dataset.slug !== slug) { return; }
            row.dataset.aiTutorState = state;
            var badge = row.querySelector('.ft-state-badge');
            if (badge) {
                badge.textContent = state === 'enabled' ? 'ON' : (state === 'expired' ? 'EXPIRED' : 'OFF');
                badge.classList.toggle('status-active', state === 'enabled');
                badge.classList.toggle('status-expired', state !== 'enabled');
            }
        });
    }

    function bulk(enabled) {
        var slugs = selectedSlugs();
        if (!slugs.length) { return; }
        var title = enabled ? 'تفعيل Finora AI Tutor؟' : 'إيقاف Finora AI Tutor؟';
        var detail = enabled
            ? 'سيتم السماح لهذه الحسابات باستخدام المساعد التعليمي والجولات التعليمية والتوجيه داخل الصفحات وتتبع تقدم التعليم.'
            : 'لن يتم حذف تقدم المستخدمين، ولكن لن يستطيعوا الوصول إلى أدوات التعليم.';
        if (!window.confirm(title + '\n\n' + slugs.length + ' حسابات محددة\n\n' + detail)) { return; }
        var payload = { slugs: slugs, enabled: enabled };
        if (enabled) { payload.expires_at = null; }
        api('POST', BASE + '/' + FEATURE + '/bulk', payload)
            .then(function (data) {
                slugs.forEach(function (slug, index) { setRowState(slug, data.statuses[index].state); });
                applyFilters();
            })
            .catch(function (err) { window.alert('تعذر تنفيذ العملية: ' + err.message); });
    }

    function renderKillSwitch(globalEnabled) {
        if (!killSwitch) { return; }
        killSwitch.dataset.enabled = globalEnabled ? 'true' : 'false';
        killSwitch.textContent = globalEnabled ? 'إيقاف طارئ عام' : 'إعادة التشغيل العام';
        killSwitch.style.color = globalEnabled ? '#ef4444' : '#10b981';
    }

    function toggleKillSwitch() {
        var enable = killSwitch.dataset.enabled !== 'true';
        var msg = enable
            ? 'إعادة تشغيل Finora AI Tutor للحسابات المفعّلة؟'
            : 'إيقاف Finora AI Tutor فوراً لجميع الحسابات؟ (للطوارئ فقط)';
        if (!window.confirm(msg)) { return; }
        api('PUT', BASE + '/' + FEATURE + '/global', { enabled: enable })
            .then(function (data) { renderKillSwitch(data.global_enabled); })
            .catch(function (err) { window.alert('تعذر تنفيذ العملية: ' + err.message); });
    }

    if (toolbar) {
        renderKillSwitch(toolbar.dataset.globalEnabled === 'true');
        if (search) { search.addEventListener('input', applyFilters); }
        if (filter) { filter.addEventListener('change', applyFilters); }
        if (bulkEnable) { bulkEnable.addEventListener('click', function () { bulk(true); }); }
        if (bulkDisable) { bulkDisable.addEventListener('click', function () { bulk(false); }); }
        if (killSwitch) { killSwitch.addEventListener('click', toggleKillSwitch); }
        rows.forEach(function (row) {
            row.querySelector('.ft-row-select').addEventListener('change', refreshSelection);
        });
        if (selectAll) {
            selectAll.addEventListener('change', function () {
                visibleRows().forEach(function (row) {
                    row.querySelector('.ft-row-select').checked = selectAll.checked;
                });
                refreshSelection();
            });
        }
    }

    // ---- per-tenant panel -----------------------------------------------------
    var currentSlug = null;
    var untilInput = $('ft-m-until');

    function duration() {
        var checked = document.querySelector('input[name="ft-duration"]:checked');
        return checked ? checked.value : 'permanent';
    }

    function showMessage(text, ok) {
        var box = $('ft-m-message');
        if (!box) { return; }
        box.textContent = text || '';
        box.style.color = ok ? '#10b981' : '#ef4444';
    }

    function renderTenant(status) {
        $('ft-m-state').textContent = stateLabel(status.state) + (status.global_enabled ? '' : ' (متوقف عالمياً)');
        $('ft-m-enabled-at').textContent = fmt(status.enabled_at);
        $('ft-m-enabled-by').textContent = status.enabled_by || '—';
        $('ft-m-expires').textContent = status.expires_at ? fmt(status.expires_at) : (status.enabled ? 'دائم' : '—');
        var until = document.querySelector('input[name="ft-duration"][value="until"]');
        var permanent = document.querySelector('input[name="ft-duration"][value="permanent"]');
        if (status.expires_at) {
            until.checked = true;
            untilInput.value = status.expires_at.slice(0, 10);
        } else {
            permanent.checked = true;
            untilInput.value = '';
        }
        $('ft-m-disable').disabled = !status.enabled;
        setRowState(currentSlug, status.state);
        applyFilters();
    }

    function loadTenant(slug) {
        currentSlug = slug;
        showMessage('', true);
        api('GET', BASE + '/tenants/' + encodeURIComponent(slug))
            .then(function (data) {
                var status = data.features.filter(function (f) { return f.feature_key === FEATURE; })[0];
                if (status) { renderTenant(status); }
            })
            .catch(function (err) { showMessage('تعذر تحميل حالة الميزة: ' + err.message, false); });
    }

    function saveTenant(enabled) {
        if (!currentSlug) { return; }
        var body = { enabled: enabled };
        if (enabled) {
            if (duration() === 'until') {
                if (!untilInput.value) { showMessage('اختر تاريخ الانتهاء.', false); return; }
                body.expires_at = untilInput.value;
            } else {
                body.expires_at = null;
            }
        }
        var msg = enabled
            ? 'تفعيل Finora AI Tutor؟\n\nسيتم السماح لهذا الحساب باستخدام المساعد التعليمي والجولات التعليمية والتوجيه داخل الصفحات وتتبع تقدم التعليم.'
            : 'إيقاف Finora AI Tutor؟\n\nلن يتم حذف تقدم المستخدم، ولكن لن يستطيع المستخدم الوصول إلى أدوات التعليم.';
        if (!window.confirm(msg)) { return; }
        api('PATCH', BASE + '/tenants/' + encodeURIComponent(currentSlug) + '/' + FEATURE, body)
            .then(function (data) {
                renderTenant(data.status);
                showMessage('تم الحفظ.', true);
            })
            .catch(function (err) { showMessage('تعذر الحفظ: ' + err.message, false); });
    }

    var enableBtn = $('ft-m-enable');
    var disableBtn = $('ft-m-disable');
    if (enableBtn) { enableBtn.addEventListener('click', function () { saveTenant(true); }); }
    if (disableBtn) { disableBtn.addEventListener('click', function () { saveTenant(false); }); }

    window.FinoraFeatureAdmin = { loadTenant: loadTenant };
})();
