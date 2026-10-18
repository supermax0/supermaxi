(function () {
  'use strict';

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.text().then(function (text) {
        var data = {};
        try {
          data = text ? JSON.parse(text) : {};
        } catch (e) {
          if (!r.ok) {
            throw new Error('فشل الطلب (' + r.status + ')');
          }
        }
        if (!r.ok || data.error) {
          throw new Error(data.error || data.message || ('فشل الطلب (' + r.status + ')'));
        }
        return data;
      });
    });
  }

  function getJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      return r.text().then(function (text) {
        var data = {};
        try {
          data = text ? JSON.parse(text) : {};
        } catch (e) {
          if (!r.ok) throw new Error('فشل الطلب (' + r.status + ')');
        }
        if (!r.ok || data.error) {
          throw new Error(data.error || data.message || ('فشل الطلب (' + r.status + ')'));
        }
        return data;
      });
    });
  }

  function alertError(err) {
    window.alert(err && err.message ? err.message : 'حدث خطأ');
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function dash(value) {
    return value ? escapeHtml(value) : '—';
  }

  function shortDate(value, len) {
    if (!value) return '—';
    return escapeHtml(String(value).slice(0, len || 16));
  }

  function labelOf(map, code) {
    if (!map) return code || '—';
    return map[code] || code || '—';
  }

  /* ── Lead detail drawer ── */
  var drawerRoot = document.getElementById('lcDrawerRoot');
  var drawerBody = document.getElementById('lcDrawerBody');
  var drawerTitle = document.getElementById('lcDrawerTitle');
  var drawerLocation = document.getElementById('lcDrawerLocation');
  var drawerBadges = document.getElementById('lcDrawerBadges');
  var drawerScore = document.getElementById('lcDrawerScore');
  var drawerFoot = document.getElementById('lcDrawerFoot');
  var drawerFullPage = document.getElementById('lcDrawerFullPage');
  var drawerEdit = document.getElementById('lcDrawerEdit');
  var drawerLeadId = null;
  var drawerCloseTimer = null;
  var drawerClosing = false;

  function closeDrawer(e) {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (!drawerRoot || drawerClosing) return;
    if (drawerRoot.hidden && !drawerRoot.classList.contains('is-open')) return;

    drawerClosing = true;
    drawerRoot.classList.remove('is-open');
    document.body.classList.remove('lc-drawer-open');
    clearTimeout(drawerCloseTimer);
    drawerCloseTimer = setTimeout(function () {
      drawerRoot.hidden = true;
      drawerRoot.style.display = 'none';
      drawerLeadId = null;
      drawerClosing = false;
    }, 260);
  }

  function openDrawerShell() {
    if (!drawerRoot) return;
    clearTimeout(drawerCloseTimer);
    drawerClosing = false;
    drawerRoot.hidden = false;
    drawerRoot.style.display = 'block';
    document.body.classList.add('lc-drawer-open');
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        drawerRoot.classList.add('is-open');
      });
    });
  }

  function bindDrawerActions(leadId) {
    if (!drawerBody) return;
    drawerBody.querySelectorAll('[data-lc-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        runLeadAction(btn.getAttribute('data-lc-action'), leadId, {
          companyName: drawerTitle ? drawerTitle.textContent : '',
          onSuccess: function () { openLeadDrawer(leadId); },
        });
      });
    });
  }

  function renderDrawer(payload) {
    var lead = payload.lead || {};
    var labels = payload.labels || {};
    var timeline = payload.timeline || [];
    var duplicates = payload.duplicates || [];

    drawerLeadId = lead.id;
    if (drawerTitle) drawerTitle.textContent = lead.business_name || 'تفاصيل العميل';
    if (drawerLocation) {
      var locParts = [lead.governorate, lead.city, lead.district].filter(Boolean);
      drawerLocation.innerHTML = locParts.length
        ? '<i class="fas fa-location-dot"></i> ' + escapeHtml(locParts.join(' · '))
        : '';
    }
    if (drawerBadges) {
      drawerBadges.innerHTML =
        '<span class="lc-status" data-status="' + escapeHtml(lead.status || '') + '">' +
        escapeHtml(labelOf(labels.status, lead.status)) + '</span>' +
        '<span class="lc-priority" data-priority="' + escapeHtml(lead.priority || '') + '">' +
        escapeHtml(labelOf(labels.priority, lead.priority)) + '</span>' +
        (lead.activity_name
          ? '<span class="lc-badge lc-badge-muted">' + escapeHtml(lead.activity_name) + '</span>'
          : '');
    }
    if (drawerScore) {
      drawerScore.hidden = false;
      drawerScore.querySelector('span').textContent = lead.lead_score != null ? lead.lead_score : 0;
    }
    if (drawerFullPage) drawerFullPage.href = '/superadmin/leads/' + lead.id;
    if (drawerEdit) drawerEdit.href = '/superadmin/leads/' + lead.id + '/edit';
    if (drawerFoot) drawerFoot.hidden = false;

    var phoneHtml = lead.primary_phone
      ? '<a href="tel:' + escapeHtml(lead.primary_phone) + '">' + escapeHtml(lead.primary_phone) + '</a>'
      : '—';
    var igHtml = lead.instagram_url
      ? '<a href="' + escapeHtml(lead.instagram_url) + '" target="_blank" rel="noopener">فتح الرابط</a>'
      : '—';
    var fbHtml = lead.facebook_url
      ? '<a href="' + escapeHtml(lead.facebook_url) + '" target="_blank" rel="noopener">فتح الرابط</a>'
      : '—';

    var dupHtml = '';
    if (duplicates.length) {
      dupHtml =
        '<div class="lc-drawer-warn"><h4><i class="fas fa-clone"></i> تكرارات محتملة</h4>' +
        duplicates.map(function (d) {
          var other = d.lead_id === lead.id ? d.candidate_lead_id : d.lead_id;
          return '<p>' + escapeHtml(labelOf(labels.duplicate, d.duplicate_level)) +
            ' (' + Math.round(d.duplicate_score || 0) + '%) — عميل #' + escapeHtml(other) + '</p>';
        }).join('') +
        '</div>';
    }

    var timelineHtml = timeline.length
      ? timeline.map(function (item) {
          var title = item.kind === 'interaction'
            ? labelOf(labels.interaction, item.interaction_type)
            : 'ملاحظة';
          var body = item.kind === 'interaction'
            ? (item.note || item.result_status || '')
            : (item.body || '');
          return '<div class="lc-timeline-item">' +
            '<time>' + shortDate(item.at) + '</time>' +
            '<strong>' + escapeHtml(title) + '</strong>' +
            (body ? '<p>' + escapeHtml(body) + '</p>' : '') +
            '</div>';
        }).join('')
      : '<div class="lc-empty-state"><div class="lc-empty-icon"><i class="fas fa-stream"></i></div><p>لا يوجد سجل بعد</p></div>';

    var phonesList = (lead.phones || []).length
      ? '<ul class="lc-status-list">' + lead.phones.map(function (p) {
          return '<li><i class="fas fa-phone"></i> ' +
            escapeHtml(p.display || p.phone_original || '—') +
            (p.is_primary ? ' <span class="lc-badge lc-badge-muted">أساسي</span>' : '') +
            '</li>';
        }).join('') + '</ul>'
      : '<p>—</p>';

    var sourcesList = (lead.sources || []).length
      ? '<ul class="lc-status-list">' + lead.sources.map(function (s) {
          return '<li><i class="fas fa-tag"></i> ' + escapeHtml(s.source_name || '') +
            (s.source_detail ? ' — ' + escapeHtml(s.source_detail) : '') + '</li>';
        }).join('') + '</ul>'
      : '<p>—</p>';

    drawerBody.innerHTML =
      dupHtml +
      '<div class="lc-drawer-meta">' +
        (lead.owner_name ? '<span><i class="fas fa-user"></i> ' + escapeHtml(lead.owner_name) + '</span>' : '') +
        (lead.source_primary ? '<span><i class="fas fa-database"></i> ' + escapeHtml(lead.source_primary) + '</span>' : '') +
        (lead.finora_company_id ? '<span><i class="fas fa-building"></i> شركة #' + escapeHtml(lead.finora_company_id) + '</span>' : '') +
      '</div>' +
      '<section class="lc-drawer-section">' +
        '<h3><i class="fas fa-id-card"></i> بيانات التواصل</h3>' +
        '<div class="lc-drawer-info">' +
          '<div class="lc-info-item"><label>الهاتف</label><p>' + phoneHtml + '</p></div>' +
          '<div class="lc-info-item"><label>Instagram</label><p>' + igHtml + '</p></div>' +
          '<div class="lc-info-item"><label>Facebook</label><p>' + fbHtml + '</p></div>' +
          '<div class="lc-info-item"><label>العنوان</label><p>' + dash(lead.full_address) + '</p></div>' +
          '<div class="lc-info-item"><label>آخر تواصل</label><p>' + shortDate(lead.last_contact_at) + '</p></div>' +
          '<div class="lc-info-item"><label>المتابعة</label><p>' + shortDate(lead.next_follow_up_at) + '</p></div>' +
        '</div>' +
      '</section>' +
      '<section class="lc-drawer-section">' +
        '<h3><i class="fas fa-bolt"></i> إجراءات سريعة</h3>' +
        '<div class="lc-drawer-actions">' +
          '<button type="button" class="sa-btn sa-btn-secondary" data-lc-action="call" data-lead-id="' + lead.id + '"><i class="fas fa-phone"></i> اتصال</button>' +
          '<button type="button" class="sa-btn sa-btn-secondary" data-lc-action="whatsapp" data-lead-id="' + lead.id + '"><i class="fab fa-whatsapp"></i> واتساب</button>' +
          '<button type="button" class="sa-btn sa-btn-secondary" data-lc-action="note" data-lead-id="' + lead.id + '"><i class="fas fa-sticky-note"></i> ملاحظة</button>' +
          '<button type="button" class="sa-btn sa-btn-primary" data-lc-action="trial" data-lead-id="' + lead.id + '"><i class="fas fa-flask"></i> تجربة</button>' +
          '<button type="button" class="sa-btn sa-btn-primary" data-lc-action="subscribe" data-lead-id="' + lead.id + '"><i class="fas fa-crown"></i> اشتراك</button>' +
        '</div>' +
      '</section>' +
      '<section class="lc-drawer-section lc-drawer-timeline">' +
        '<h3><i class="fas fa-stream"></i> السجل الزمني</h3>' +
        '<div class="lc-timeline">' + timelineHtml + '</div>' +
      '</section>' +
      '<section class="lc-drawer-section">' +
        '<h3><i class="fas fa-phone"></i> أرقام الهاتف</h3>' + phonesList +
      '</section>' +
      '<section class="lc-drawer-section">' +
        '<h3><i class="fas fa-link"></i> المصادر</h3>' + sourcesList +
      '</section>';

    bindDrawerActions(lead.id);
  }

  function openLeadDrawer(leadId) {
    if (!drawerRoot || !drawerBody || !leadId) return;
    openDrawerShell();
    if (drawerFoot) drawerFoot.hidden = true;
    if (drawerScore) drawerScore.hidden = true;
    if (drawerBadges) drawerBadges.innerHTML = '';
    if (drawerTitle) drawerTitle.textContent = 'تفاصيل العميل';
    if (drawerLocation) drawerLocation.textContent = '';
    drawerBody.innerHTML =
      '<div class="lc-drawer-loading"><i class="fas fa-spinner fa-spin"></i><span>جاري تحميل التفاصيل...</span></div>';

    getJson('/superadmin/leads/api/leads/' + leadId)
      .then(function (data) {
        renderDrawer(data);
      })
      .catch(function (err) {
        drawerBody.innerHTML =
          '<div class="lc-drawer-error"><i class="fas fa-circle-exclamation"></i><span>' +
          escapeHtml(err.message || 'تعذر تحميل التفاصيل') + '</span></div>';
      });
  }

  if (drawerRoot) {
    if (drawerRoot.parentElement !== document.body) {
      document.body.appendChild(drawerRoot);
    }
    drawerRoot.addEventListener('click', function (e) {
      var closer = e.target.closest('[data-lc-drawer-close]');
      if (closer) closeDrawer(e);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && drawerRoot.classList.contains('is-open')) {
        closeDrawer(e);
      }
    });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-lc-open-lead]');
    if (!btn) return;
    e.preventDefault();
    openLeadDrawer(btn.getAttribute('data-lc-open-lead'));
  });

  /* ── Lead actions (detail page + drawer) ── */
  function runLeadAction(action, leadId, opts) {
    opts = opts || {};
    var note = window.prompt('ملاحظة (اختياري):') || '';
    var done = opts.onSuccess || function () { location.reload(); };
    var companyName = opts.companyName || '';

    if (action === 'call') {
      postJson('/superadmin/leads/api/leads/' + leadId + '/interactions', {
        interaction_type: 'CALL',
        result_status: 'CONTACTED',
        note: note,
        update_lead_status: 'CONTACTED',
      }).then(done).catch(alertError);
    } else if (action === 'whatsapp') {
      postJson('/superadmin/leads/api/leads/' + leadId + '/interactions', {
        interaction_type: 'WHATSAPP',
        note: note,
      }).then(done).catch(alertError);
    } else if (action === 'note') {
      if (!note) return;
      postJson('/superadmin/leads/api/leads/' + leadId + '/notes', { body: note })
        .then(done).catch(alertError);
    } else if (action === 'trial') {
      var slug = window.prompt('Slug للشركة:');
      if (!slug) return;
      postJson('/superadmin/leads/api/leads/' + leadId + '/trial', {
        company_name: companyName || (document.querySelector('.lc-detail-header h2') || {}).textContent || '',
        slug: slug,
      }).then(done).catch(alertError);
    } else if (action === 'subscribe') {
      var val = window.prompt('قيمة الاشتراك الشهري:');
      postJson('/superadmin/leads/api/leads/' + leadId + '/subscribe', {
        monthly_value: parseFloat(val) || 0,
      }).then(done).catch(alertError);
    }
  }

  document.querySelectorAll('[data-lc-action]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      runLeadAction(btn.getAttribute('data-lc-action'), btn.getAttribute('data-lead-id'));
    });
  });

  if (window.LC_PIPELINE) {
    var dragged = null;
    var didDrag = false;
    document.querySelectorAll('.lc-pipeline-card').forEach(function (card) {
      card.addEventListener('dragstart', function () { dragged = card; didDrag = false; });
      card.addEventListener('drag', function () { didDrag = true; });
      card.addEventListener('dragend', function () { dragged = null; });
      card.style.cursor = 'pointer';
      card.addEventListener('click', function () {
        if (didDrag) { didDrag = false; return; }
        openLeadDrawer(card.getAttribute('data-lead-id'));
      });
    });
    document.querySelectorAll('.lc-pipeline-col').forEach(function (col) {
      col.addEventListener('dragover', function (e) { e.preventDefault(); });
      col.addEventListener('drop', function () {
        if (!dragged) return;
        var newStatus = col.getAttribute('data-status');
        var leadId = dragged.getAttribute('data-lead-id');
        postJson('/superadmin/leads/api/pipeline/move', { lead_id: parseInt(leadId, 10), status: newStatus })
          .then(function () {
            col.querySelector('.lc-pipeline-cards').appendChild(dragged);
            dragged.setAttribute('data-status', newStatus);
          }).catch(alertError);
      });
    });
  }

  if (window.LC_IMPORT_WIZARD) {
    var statusEl = document.getElementById('lcImportStatus');

    function collectMapping() {
      var mapping = {};
      document.querySelectorAll('[data-lc-map]').forEach(function (sel) {
        mapping[sel.getAttribute('data-lc-map')] = sel.value;
      });
      return mapping;
    }

    function showStatus(msg, isError) {
      if (!statusEl) return;
      statusEl.hidden = false;
      statusEl.textContent = msg;
      statusEl.style.background = isError ? '#fef2f2' : '#ecfdf5';
      statusEl.style.borderColor = isError ? '#fecaca' : '#6ee7b7';
    }

    function formatImportResult(r) {
      if (r.results) {
        var x = r.results;
        return 'تم: ' + (x.created || 0) + ' جديد، ' + (x.merged || 0) + ' دمج، ' + (x.errors || 0) + ' خطأ';
      }
      if (r.stats) {
        var s = r.stats;
        return 'صالحة: ' + (s.valid || 0) + ' | غير صالحة: ' + (s.invalid || 0);
      }
      return r.ok ? 'تم بنجاح' : JSON.stringify(r);
    }

    function setBusy(btn, busy) {
      if (!btn) return;
      btn.disabled = busy;
      btn.style.opacity = busy ? '0.6' : '1';
    }

    var saveBtn = document.getElementById('lcSaveMapping');
    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        var batchId = saveBtn.getAttribute('data-batch-id');
        setBusy(saveBtn, true);
        postJson('/superadmin/leads/api/imports/' + batchId + '/mapping', { mapping: collectMapping() })
          .then(function () {
            showStatus('تم حفظ ربط الأعمدة');
            setTimeout(function () { location.reload(); }, 600);
          })
          .catch(function (e) { showStatus(e.message, true); setBusy(saveBtn, false); });
      });
    }

    ['lcValidateBatch', 'lcDedupBatch', 'lcCommitBatch'].forEach(function (id) {
      var btn = document.getElementById(id);
      if (!btn) return;
      btn.addEventListener('click', function () {
        var batchId = btn.getAttribute('data-batch-id');
        var path = id === 'lcValidateBatch' ? 'validate' : id === 'lcDedupBatch' ? 'dedup' : 'commit';
        var mapping = collectMapping();
        if (!mapping.business_name) {
          showStatus('يجب ربط عمود اسم الشركة / اسم المحل', true);
          return;
        }
        setBusy(btn, true);
        showStatus('جاري المعالجة...');
        postJson('/superadmin/leads/api/imports/' + batchId + '/' + path, { mapping: mapping })
          .then(function (r) {
            showStatus(formatImportResult(r));
            if (path === 'commit') {
              if (r.results && r.results.created > 0) {
                setTimeout(function () { location.reload(); }, 1200);
              } else if (r.results && r.results.errors > 0) {
                showStatus('فشل استيراد ' + r.results.errors + ' صف — راجع الربط', true);
                setBusy(btn, false);
              } else {
                setTimeout(function () { location.reload(); }, 800);
              }
            } else {
              setTimeout(function () { location.reload(); }, 800);
            }
          })
          .catch(function (e) { showStatus(e.message, true); setBusy(btn, false); });
      });
    });
  }

  document.querySelectorAll('.lc-merge-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var target = btn.getAttribute('data-target');
      var source = btn.getAttribute('data-source');
      if (!window.confirm('دمج #' + source + ' في #' + target + '؟')) return;
      postJson('/superadmin/leads/api/merge', { target_id: parseInt(target, 10), source_id: parseInt(source, 10) })
        .then(function () { location.reload(); }).catch(alertError);
    });
  });

  document.querySelectorAll('.lc-dismiss-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var id = btn.getAttribute('data-id');
      postJson('/superadmin/leads/api/duplicates/' + id + '/dismiss', {})
        .then(function () { location.reload(); }).catch(alertError);
    });
  });
})();
