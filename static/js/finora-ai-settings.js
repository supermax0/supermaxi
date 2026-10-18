(function () {
  'use strict';
  const form = document.getElementById('finoraAiSettingsForm');
  if (!form) return;
  const el = id => document.getElementById(id);
  const fields = el('aiSettingsFields'), status = el('aiSettingsStatus');
  let saved = null, saving = false;
  const flagFields = {mcp_enabled: 'aiMcpEnabled', ai_accounting_tools_enabled: 'aiAccountingEnabled', ai_local_provider_enabled: 'aiLocalEnabled'};
  function notify(text, state) { status.textContent = text; status.dataset.state = state || ''; }
  function hints() {
    const provider = el('aiProvider').value;
    const builtin = provider === 'builtin';
    el('aiModel').disabled = builtin; el('aiEndpoint').disabled = builtin; el('aiKey').disabled = builtin || el('aiClearKey').checked;
    el('aiProviderHint').textContent = builtin ? 'مساعد محدود للقراءة دون نموذج لغوي أو اتصال خارجي. لا يحتاج إلى نموذج أو مفتاح.' : provider === 'automatic' ? 'يختار OpenAI عند توفر مفتاح، وإلا يستخدم المساعد المدمج. لا يوجد تحويل تلقائي عند فشل الطلب.' : ['local', 'ollama', 'lmstudio', 'vllm'].includes(provider) ? 'يجب تشغيل خادم النموذج وإدخال عنوان متوافق مع OpenAI. localhost يشير إلى خادم FINORA، وليس جهاز المستخدم.' : 'تُرسل رسائل المحادثة ونتائج الأدوات اللازمة إلى المزوّد المحدد حسب صلاحيات المستخدم.';
  }
  function fill(settings) {
    saved = settings;
    if (settings.mcp_connection) el('aiMcpUrl').value = settings.mcp_connection.url;
    el('aiEnabled').checked = settings.enabled && settings.feature_flags.finora_ai_enabled !== false;
    el('aiProvider').value = settings.provider;
    el('aiModel').value = settings.model || ''; el('aiEndpoint').value = settings.endpoint || '';
    el('aiTimeout').value = settings.timeout_seconds; el('aiContext').value = settings.context_size || 8192;
    Object.entries(flagFields).forEach(([flag, id]) => { el(id).checked = settings.feature_flags[flag] !== false; });
    el('aiKey').value = ''; el('aiClearKey').checked = false;
    el('aiKeyState').textContent = settings.has_api_key ? 'يوجد مفتاح محفوظ ومشفّر؛ لا يتم إرساله إلى المتصفح.' : 'لا يوجد مفتاح محفوظ للشركة. يمكن لـOpenAI استخدام مفتاح البيئة على الخادم إن وُجد.';
    el('aiChangeState').textContent = 'الإعدادات محفوظة'; hints();
  }
  async function load() {
    fields.disabled = true; form.setAttribute('aria-busy', 'true'); el('aiReload').hidden = true;
    notify('جاري تحميل الإعدادات…');
    try {
      const response = await fetch('/finora-ai/api/settings', {headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error('تعذر تحميل الإعدادات. تحقق من الاتصال والصلاحيات.');
      fill((await response.json()).settings); fields.disabled = false; notify('');
    } catch (error) { notify(error.message, 'error'); el('aiReload').hidden = false; }
    finally { form.setAttribute('aria-busy', 'false'); }
  }
  form.addEventListener('input', () => { el('aiChangeState').textContent = 'تغييرات غير محفوظة'; });
  form.addEventListener('change', () => { hints(); el('aiChangeState').textContent = 'تغييرات غير محفوظة'; });
  el('aiReset').addEventListener('click', () => { if (saved && !saving) { fill(saved); notify('تم التراجع عن التغييرات.'); } });
  el('aiReload').addEventListener('click', load);
  el('aiProfessionalPreset').addEventListener('click', () => {
    el('aiProvider').value = 'openai';
    if (!el('aiModel').value.trim()) el('aiModel').value = 'gpt-4.1-mini';
    el('aiEndpoint').value = 'https://api.openai.com/v1';
    el('aiChangeState').textContent = 'تغييرات غير محفوظة'; hints();
    notify('تمت تهيئة الحقول فقط. تحقق من توفر النموذج والمفتاح على الخادم، ثم احفظ لتفعيل OpenAI. لم يُجرَ أي طلب مدفوع.');
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (saving || !saved) return;
    if (!el('aiLocalEnabled').checked && ['local', 'ollama', 'lmstudio', 'vllm'].includes(el('aiProvider').value)) { notify('فعّل المزوّدات المحلية أو اختر مزوّدًا آخر.', 'error'); return; }
    const flags = {finora_ai_enabled: el('aiEnabled').checked};
    Object.entries(flagFields).forEach(([flag, id]) => { flags[flag] = el(id).checked; });
    const payload = {enabled: el('aiEnabled').checked, provider: el('aiProvider').value, model: el('aiModel').value.trim(), endpoint: el('aiEndpoint').value.trim(), timeout_seconds: Number(el('aiTimeout').value), context_size: Number(el('aiContext').value), feature_flags: flags, clear_api_key: el('aiClearKey').checked};
    if (el('aiKey').value && !payload.clear_api_key) payload.api_key = el('aiKey').value;
    saving = true; fields.disabled = true; form.setAttribute('aria-busy', 'true'); notify('جاري حفظ الإعدادات بأمان…');
    try {
      const response = await fetch('/finora-ai/api/settings', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      if (!response.ok) throw new Error('لم تُحفظ الإعدادات. تحقق من القيم والصلاحيات وحاول مجددًا.');
      const data = await response.json();
      fill({...payload, mcp_connection: saved.mcp_connection, has_api_key: data.has_api_key, feature_flags: {...saved.feature_flags, ...flags}});
      // Never retain a submitted credential in the reset snapshot.
      delete saved.api_key; delete saved.clear_api_key;
      notify('تم حفظ الإعدادات بأمان.', 'success');
    } catch (error) { notify(error.message, 'error'); }
    finally { saving = false; fields.disabled = false; form.setAttribute('aria-busy', 'false'); hints(); }
  });
  let tokenTimer = null, tokenExpiry = 0, generatingToken = false, displayedConnectionId = null;
  const connectStatus = el('aiMcpConnectStatus');
  function clearToken() {
    clearTimeout(tokenTimer); tokenExpiry = 0; displayedConnectionId = null; el('aiMcpToken').value = ''; el('aiMcpTokenBox').hidden = true;
  }
  async function copyField(id, message) {
    const field = el(id);
    try { await navigator.clipboard.writeText(field.value); connectStatus.textContent = message; }
    catch (_) { field.focus(); field.select(); connectStatus.textContent = 'تعذر النسخ التلقائي. الحقل محدد؛ انسخه يدويًا.'; }
  }
  el('aiCopyMcpUrl').addEventListener('click', () => copyField('aiMcpUrl', 'تم نسخ الرابط. ضعه في حقل URL بالتطبيق الخارجي.'));
  el('aiCopyMcpToken').addEventListener('click', () => {
    if (Date.now() >= tokenExpiry) { clearToken(); connectStatus.textContent = 'انتهت صلاحية الرمز. ولّد رمزًا جديدًا.'; return; }
    copyField('aiMcpToken', 'تم نسخ الرمز. ضعه في حقل Bearer token دون إضافة كلمة Bearer.');
  });
  el('aiClearMcpToken').addEventListener('click', () => { clearToken(); connectStatus.textContent = 'تم إخفاؤه من الصفحة فقط؛ المفتاح الدائم يبقى فعالًا حتى إلغاء الرابط، والرمز المؤقت حتى انتهاء مدته.'; });
  el('aiGenerateMcpToken').addEventListener('click', async () => {
    if (generatingToken) return;
    generatingToken = true; el('aiGenerateMcpToken').disabled = true; clearToken(); connectStatus.textContent = 'جاري إصدار رمز الاتصال…';
    try {
      const response = await fetch('/finora-ai/api/mcp/token', {method:'POST', headers:{Accept:'application/json'}});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || 'تعذر إصدار الرمز. تحقق من تفعيل المساعد والصلاحيات.');
      el('aiMcpToken').value = data.access_token; el('aiMcpTokenBox').hidden = false;
      const duration = Number(data.expires_in) * 1000; tokenExpiry = Date.now() + duration;
      tokenTimer = setTimeout(() => { clearToken(); connectStatus.textContent = 'انتهت صلاحية الرمز. ولّد رمزًا جديدًا.'; }, duration);
      connectStatus.textContent = 'الرمز جاهز وصالح لمدة 15 دقيقة. انسخه إلى التطبيق الخارجي.';
    } catch (error) { connectStatus.textContent = error.message; }
    finally { generatingToken = false; el('aiGenerateMcpToken').disabled = false; }
  });
  async function loadConnections() {
    const list = el('aiMcpConnections'); list.replaceChildren();
    try {
      const response = await fetch('/finora-ai/api/mcp/connections', {headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error('تعذر تحميل روابط حسابك.');
      const data = await response.json();
      (data.connections || []).forEach(item => {
        const row = document.createElement('li');
        const label = document.createElement('span'); label.textContent = item.name + (item.revoked ? ' · ملغى' : ' · فعال حتى الإلغاء'); row.appendChild(label);
        if (!item.revoked) {
          const revoke = document.createElement('button'); revoke.type = 'button'; revoke.className = 'ais-secondary'; revoke.textContent = 'إلغاء الرابط';
          revoke.addEventListener('click', async () => {
            revoke.disabled = true;
            try {
              const response = await fetch('/finora-ai/api/mcp/connections/' + encodeURIComponent(item.id) + '/revoke', {method: 'POST'});
              if (!response.ok) throw new Error('تعذر إلغاء الرابط؛ حاول مجددًا.');
              if (displayedConnectionId === item.id) clearToken();
              connectStatus.textContent = 'تم إلغاء الرابط. المفتاح لا يعمل للطلبات الجديدة.'; await loadConnections();
            } catch (error) { connectStatus.textContent = error.message; revoke.disabled = false; }
          }); row.appendChild(revoke);
        }
        list.appendChild(row);
      });
      if (!list.childNodes.length) list.textContent = 'لا توجد روابط دائمة لحسابك.';
    } catch (error) { list.textContent = error.message; }
  }
  el('aiRefreshMcpConnections').addEventListener('click', loadConnections);
  el('aiCreateMcpConnection').addEventListener('click', async () => {
    if (generatingToken) return;
    const name = el('aiMcpConnectionName').value.trim();
    if (!name || !el('aiMcpPersistentConsent').checked) { connectStatus.textContent = 'اذكر اسم التطبيق ووافق على الوصول المستمر أولًا.'; return; }
    generatingToken = true; el('aiCreateMcpConnection').disabled = true; clearToken();
    try {
      const response = await fetch('/finora-ai/api/mcp/connections', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name, acknowledge_persistent_access:true})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || 'تعذر إنشاء المفتاح الدائم.');
      displayedConnectionId = data.id; tokenExpiry = Infinity; el('aiMcpToken').value = data.access_token; el('aiMcpTokenBox').hidden = false;
      el('aiMcpPersistentConsent').checked = false;
      connectStatus.textContent = 'المفتاح الدائم جاهز. انسخه مرة واحدة إلى Bearer token في تطبيقك؛ يبقى فعالًا حتى إلغاء الرابط.';
      await loadConnections();
    } catch (error) { connectStatus.textContent = error.message; }
    finally { generatingToken = false; el('aiCreateMcpConnection').disabled = false; }
  });
  window.addEventListener('pagehide', clearToken);
  loadConnections();
  load();
})();
