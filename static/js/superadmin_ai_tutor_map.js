/* Super Admin: AI Tutor System Map. All text is inserted with textContent (scan data is never HTML). */
(function () {
  'use strict';

  var BASE = '/superadmin/ai-tutor/system-map';
  var STATUS_LABEL = {
    verified: 'verified', discovered: 'discovered', knowledge_missing: 'knowledge_missing', tutorial_missing: 'tutorial_missing',
    broken: 'broken', stale: 'stale', disabled: 'disabled'
  };
  var FILTERS = [
    ['all', 'All'], ['knowledge_missing', 'Missing Knowledge'], ['tutorial_missing', 'Missing Tutorial'],
    ['broken', 'Broken'], ['verified', 'Verified'], ['new', 'Newly Discovered'], ['stale', 'Stale']
  ];
  var TABS = [['action', 'Actions'], ['field', 'Fields'], ['section', 'Sections'], ['page', 'Pages'], ['tutorial', 'Tutorials']];

  var state = { data: null, tab: 'action', filter: 'all', category: 'all', query: '' };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text !== undefined && text !== null) { n.textContent = text; }
    return n;
  }
  function mark(ok, hint) {
    var n = el('span', ok ? 'sm-yes' : 'sm-no', ok ? '✓' : '✗');
    if (hint) { n.title = hint; }
    return n;
  }
  function pct(value) { return value === null || value === undefined ? '—' : value + '%'; }

  function request(method, url, body) {
    return fetch(url, {
      method: method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok || data.ok === false) { throw new Error(data.error || ('HTTP ' + res.status)); }
        return data;
      });
    });
  }

  // ---- rendering -----------------------------------------------------------

  function renderMeta(payload) {
    var box = $('smMeta');
    box.replaceChildren();
    var snap = payload.snapshot;
    if (!snap) { box.append(el('span', 'sm-pill sm-pill--warn', 'لا يوجد فحص بعد — اضغط «تشغيل الفحص»')); return; }
    var m = snap.meta;
    var parts = [['version', m.app_version], ['commit', m.git_commit || 'n/a'], ['scanned', m.created_at.replace('T', ' ').slice(0, 19) + ' UTC'],
      ['files', m.files_scanned]];
    parts.forEach(function (p) {
      var s = el('span');
      s.append(el('span', '', p[0] + ': '), el('b', '', String(p[1])));
      box.append(s);
    });
    box.append(el('span', 'sm-pill ' + (m.runtime ? 'sm-pill--ok' : 'sm-pill--info'), m.runtime ? 'static + runtime' : 'static only'));
    if (payload.stale) { box.append(el('span', 'sm-pill sm-pill--warn', 'قديم: تغيّرت الملفات بعد هذا الفحص')); }
    var banner = $('smBanner');
    banner.hidden = !payload.simulated;
    banner.textContent = payload.simulated ? 'محاكاة اختبار فقط: اختفى ' + m.simulated.join(', ') + ' — لم يُحفظ شيء ولم يتأثر المستخدمون.' : '';
  }

  function renderCards(snap) {
    var box = $('smCards');
    box.replaceChildren();
    if (!snap) { return; }
    var c = snap.coverage;
    [['Pages', c.counts.pages], ['Actions', c.counts.actions], ['Fields', c.counts.fields], ['Sections', c.counts.sections], ['Tutorials', c.tutorials.total]]
      .forEach(function (row) {
        var card = el('div', 'sm-card');
        card.dataset.card = row[0].toLowerCase();
        card.append(el('small', '', row[0]), el('strong', '', String(row[1])));
        box.append(card);
      });
  }

  function coverageBlock(title, main, sub, percent) {
    var b = el('div', 'sm-card');
    var num = el('div', 'sm-num', main);
    var note = el('small', '', sub);
    num.setAttribute('dir', 'auto');   // mixed Arabic/Latin numbers must keep their reading order
    note.setAttribute('dir', 'auto');
    b.append(el('h4', '', title), num, note);
    var bar = el('div', 'sm-bar');
    var fill = el('i');
    fill.style.width = (percent || 0) + '%';
    bar.append(fill);
    b.append(bar);
    return b;
  }

  function renderCoverage(snap) {
    var box = $('smCoverage');
    box.replaceChildren();
    if (!snap) { return; }
    var c = snap.coverage, all = c.actions.all, feat = c.actions.feature, d = c.discovery;
    var disc = coverageBlock('System Discovery Coverage', d.pages_instrumented + ' / ' + d.pages_total + ' pages instrumented',
      'صفحات فيها عناصر data-finora (' + pct(d.pages_instrumented_pct) + ')' + (d.runtime_available ? ' · ' + d.actions_confirmed_runtime + '/' + d.actions_discovered + ' actions seen at runtime' : ' · no runtime scan'), d.pages_instrumented_pct);
    var know = coverageBlock('Knowledge Coverage', all.knowledge + ' / ' + all.discovered + ' actions (' + pct(all.knowledge_pct) + ')',
      'ميزات فقط: ' + feat.knowledge + '/' + feat.discovered + ' (' + pct(feat.knowledge_pct) + ')', all.knowledge_pct);
    var tut = coverageBlock('Tutorial Coverage', all.tutorial + ' / ' + all.discovered + ' actions (' + pct(all.tutorial_pct) + ')',
      'ميزات فقط: ' + feat.tutorial + '/' + feat.discovered + ' (' + pct(feat.tutorial_pct) + ')', all.tutorial_pct);
    var ver = coverageBlock('Verified Tutorial Coverage', all.verified + ' / ' + all.discovered + ' actions (' + pct(all.verified_pct) + ')',
      'Tutorials verified: ' + c.tutorials.verified + ' / ' + c.tutorials.total + ' · broken: ' + c.tutorials.broken, all.verified_pct);
    [[disc, 'discovery'], [know, 'knowledge'], [tut, 'tutorial'], [ver, 'verified']].forEach(function (row) {
      row[0].dataset.coverage = row[1];
      box.append(row[0]);
    });
  }

  function renderDiff(snap) {
    var panel = $('smDiffPanel');
    var list = $('smDiff');
    list.replaceChildren();
    var diff = snap && snap.diff;
    if (!diff || diff.first_scan) { panel.hidden = true; return; }
    var rows = [];
    diff.added.forEach(function (a) { rows.push(['+ ' + a.id + ' (' + a.kind + (a.page ? ', ' + a.page : '') + ')', 'ok']); });
    diff.removed.forEach(function (r) { rows.push(['- ' + r.id + ' (' + r.kind + ')', 'bad']); });
    diff.changed.forEach(function (c) { rows.push(['! ' + c.id + ' changed: ' + Object.keys(c.change).join(', '), 'warn']); });
    diff.broken_tutorials.forEach(function (t) { rows.push(['! tutorial ' + t + ' is now broken', 'bad']); });
    diff.fixed_tutorials.forEach(function (t) { rows.push(['✓ tutorial ' + t + ' is working again', 'ok']); });
    diff.pages_changed.forEach(function (p) { rows.push(['~ page ' + p.page + ': +' + p.added.length + ' / -' + p.removed.length, 'info']); });
    panel.hidden = false;
    if (!rows.length) { list.append(el('li', '', 'لا تغييرات.')); return; }
    rows.forEach(function (row) {
      var li = el('li');
      li.append(el('span', 'sm-pill sm-pill--' + row[1], row[0]));
      list.append(li);
    });
  }

  function renderTabs() {
    var box = $('smTabs');
    box.replaceChildren();
    TABS.forEach(function (t) {
      var b = el('button', 'sm-chip' + (state.tab === t[0] ? ' is-active' : ''), t[1]);
      b.type = 'button';
      b.dataset.tab = t[0];
      b.addEventListener('click', function () { state.tab = t[0]; render(); });
      box.append(b);
    });
    var filters = $('smFilters');
    filters.replaceChildren();
    FILTERS.forEach(function (f) {
      var b = el('button', 'sm-chip' + (state.filter === f[0] ? ' is-active' : ''), f[1]);
      b.type = 'button';
      b.dataset.filter = f[0];
      b.hidden = state.tab === 'page' || state.tab === 'tutorial';
      b.addEventListener('click', function () { state.filter = f[0]; render(); });
      filters.append(b);
    });
    $('smCategory').hidden = state.tab !== 'action';
  }

  function matches(item) {
    if (state.category !== 'all' && item.category !== state.category) { return false; }
    if (state.filter === 'new') { if (!item.new) { return false; } }
    else if (state.filter === 'knowledge_missing' && item.status !== 'knowledge_missing') { return false; }
    else if (state.filter === 'tutorial_missing' && item.status !== 'tutorial_missing') { return false; }
    else if (['broken', 'verified', 'stale'].indexOf(state.filter) >= 0 && item.status !== state.filter) { return false; }
    var q = state.query.trim().toLowerCase();
    return !q || (item.id + ' ' + (item.page || '') + ' ' + (item.label_ar || '')).toLowerCase().indexOf(q) >= 0;
  }

  function setHead(columns) {
    var head = $('smTable').tHead;
    head.replaceChildren();
    var tr = el('tr');
    columns.forEach(function (c) { tr.append(el('th', '', c)); });
    head.append(tr);
  }

  function statusCell(status, isNew) {
    var td = el('td');
    var badge = el('span', 'sm-status', STATUS_LABEL[status] || status);
    badge.dataset.status = status;
    td.append(badge);
    if (isNew) { td.append(el('span', 'sm-pill sm-pill--info sm-new', 'new')); }
    return td;
  }

  function renderItems(snap) {
    setHead(['Action', 'Page', 'Knowledge', 'Tutorial', 'Verified', 'Permission', 'Status']);
    var body = $('smTable').tBodies[0];
    var rows = snap.items.filter(function (i) { return i.kind === state.tab && matches(i); });
    rows.forEach(function (item) {
      var tr = el('tr');
      tr.dataset.id = item.id;
      tr.dataset.status = item.status;
      var name = el('td');
      name.append(el('code', '', item.id));
      if (item.label_ar) { name.append(el('div', '', item.label_ar)); }
      var tutorials = el('td');
      tutorials.append(mark(item.tutorial_registered, item.tutorials.join(', ')));
      var perm = el('td');
      if (item.permission_mapped === null) { perm.append(el('span', 'sm-no', 'n/a')); }
      else { perm.append(mark(item.permission_mapped, item.permission || ''), document.createTextNode(' ' + (item.permission || ''))); }
      var knowledge = el('td'); knowledge.append(mark(item.knowledge_registered));
      var verified = el('td'); verified.append(mark(item.verified, item.discovered_runtime ? 'seen at runtime' : 'static only'));
      tr.append(name, el('td', '', item.page || '—'), knowledge, tutorials, verified, perm, statusCell(item.status, item.new));
      body.append(tr);
    });
    return rows.length;
  }

  function renderPages(snap) {
    setHead(['Page', 'Route', 'Permission', 'Knowledge', 'Instrumented', 'Actions', 'Fields', 'Runtime']);
    var body = $('smTable').tBodies[0];
    var q = state.query.trim().toLowerCase();
    var rows = snap.pages.filter(function (p) { return !q || (p.id + ' ' + p.title_ar).toLowerCase().indexOf(q) >= 0; });
    rows.forEach(function (p) {
      var tr = el('tr');
      tr.dataset.id = p.id;
      var name = el('td'); name.append(el('code', '', p.id), el('div', '', p.title_ar));
      var know = el('td'); know.append(mark(p.knowledge_registered));
      var inst = el('td'); inst.append(mark(p.instrumented));
      var rt = el('td');
      if (p.runtime_seen) { rt.append(mark(p.runtime_accessible, p.runtime_accessible ? 'seen' : 'not accessible for the scan account')); } else { rt.append(el('span', 'sm-no', '—')); }
      tr.append(name, el('td', '', p.route), el('td', '', p.permission), know, inst, el('td', '', String(p.actions)), el('td', '', String(p.fields)), rt);
      body.append(tr);
    });
    return rows.length;
  }

  function renderTutorials(snap) {
    setHead(['Tutorial', 'Declared', 'Status', 'Targets', 'Dependencies', 'Problems']);
    var body = $('smTable').tBodies[0];
    snap.tutorials.forEach(function (t) {
      var tr = el('tr');
      tr.dataset.id = t.id;
      tr.dataset.status = t.status;
      var name = el('td'); name.append(el('code', '', t.id + ' v' + t.version), el('div', '', t.title_ar));
      var deps = el('td');
      if (!t.dependencies.length) { deps.append(el('span', 'sm-no', '—')); }
      t.dependencies.forEach(function (d) {
        var line = el('div');
        line.append(el('code', '', t.id + ' → ' + d.tutorial), document.createTextNode(' '), mark(d.exists && d.runnable, d.exists ? 'dependency exists' : 'dependency missing'));
        deps.append(line);
      });
      var problems = el('td');
      if (!t.problems.length) { problems.append(el('span', 'sm-yes', '✓')); }
      else {
        var list = el('ul', 'sm-problems');
        t.problems.forEach(function (p) { var li = el('li', '', '[' + p.severity + '] ' + p.code + ': ' + p.message); li.setAttribute('dir', 'ltr'); list.append(li); });
        problems.append(list);
      }
      tr.append(name, el('td', '', t.declared_status), statusCell(t.status, false), el('td', '', t.targets_found + '/' + t.targets_total), deps, problems);
      body.append(tr);
    });
    return snap.tutorials.length;
  }

  function render() {
    var payload = state.data;
    renderMeta(payload);
    renderCards(payload.snapshot);
    renderCoverage(payload.snapshot);
    renderDiff(payload.snapshot);
    renderTabs();
    var table = $('smTable');
    table.tBodies[0].replaceChildren();
    var count = 0;
    if (payload.snapshot) {
      if (state.tab === 'page') { count = renderPages(payload.snapshot); }
      else if (state.tab === 'tutorial') { count = renderTutorials(payload.snapshot); }
      else { count = renderItems(payload.snapshot); }
    }
    $('smEmpty').hidden = count > 0;
    $('smSimulateBox').hidden = !payload.simulation_enabled;
  }

  // ---- actions -------------------------------------------------------------

  function load(payloadPromise) {
    return payloadPromise.then(function (payload) { state.data = payload; render(); })
      .catch(function (err) { var b = $('smBanner'); b.hidden = false; b.textContent = 'تعذر التنفيذ: ' + err.message; })
      .then(function () { $('smScan').disabled = false; $('smSimulate').disabled = false; });
  }

  $('smScan').addEventListener('click', function () {
    $('smScan').disabled = true;
    load(request('POST', BASE + '/scan', {}));
  });
  $('smSimulate').addEventListener('click', function () {
    var id = $('smSimId').value.trim();
    if (!id) { return; }
    $('smSimulate').disabled = true;
    load(request('POST', BASE + '/scan', { simulate_missing: [id] }));
  });
  $('smSearch').addEventListener('input', function (event) { state.query = event.target.value; render(); });
  $('smCategory').addEventListener('change', function (event) { state.category = event.target.value; render(); });

  load(request('GET', BASE + '/data'));
})();
