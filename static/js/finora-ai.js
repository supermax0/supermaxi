(function () {
  'use strict';
  const fab = document.getElementById('finoraAiFab');
  const panel = document.getElementById('finoraAiPanel');
  const close = document.getElementById('finoraAiClose');
  const fresh = document.getElementById('finoraAiNew');
  const form = document.getElementById('finoraAiForm');
  const input = document.getElementById('finoraAiInput');
  const messages = document.getElementById('finoraAiMessages');
  const status = document.getElementById('finoraAiStatus');
  const send = document.getElementById('finoraAiSend');
  const stop = document.getElementById('finoraAiStop');
  const historyButton = document.getElementById('finoraAiHistory');
  const historyList = document.getElementById('finoraAiHistoryList');
  const modeLabel = document.getElementById('finoraAiMode');
  if (!fab || !panel || !form) return;

  let conversationId = Number(localStorage.getItem('finora_ai_conversation_id')) || null;
  let controller = null;
  let loaded = false;
  let latestPrompt = '';
  const expand = document.getElementById('finoraAiExpand');
  if (expand) expand.addEventListener('click', () => {
    const expanded = panel.classList.toggle('is-expanded');
    expand.setAttribute('aria-pressed', String(expanded));
    expand.setAttribute('aria-label', expanded ? 'تصغير المحادثة' : 'توسيع المحادثة');
  });
  function submitPrompt(text) {
    if (controller) return;
    input.value = text; form.requestSubmit();
  }
  messages.addEventListener('click', event => {
    const prompt = event.target.closest('[data-ai-prompt]');
    if (prompt) submitPrompt(prompt.dataset.aiPrompt);
  });

  function setOpen(open) {
    panel.classList.toggle('is-open', open);
    panel.setAttribute('aria-hidden', String(!open));
    fab.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('finora-ai-open', open);
    if (open) { loadConversation(); loadMode(); setTimeout(() => input.focus(), 120); }
    else fab.focus({preventScroll: true});
  }
  function showMode(data) {
    if (modeLabel) { modeLabel.textContent = data.notice; modeLabel.dataset.limited = String(!data.language_model); }
  }
  async function loadMode() {
    try {
      const response = await fetch('/finora-ai/api/runtime', {headers: {Accept: 'application/json'}});
      if (!response.ok) throw new Error('unavailable');
      showMode(await response.json());
    } catch (_) { if (modeLabel) modeLabel.textContent = 'تعذر تحديد وضع الفهم · راجع الإعدادات'; }
  }
  fab.addEventListener('click', () => setOpen(!panel.classList.contains('is-open')));
  close.addEventListener('click', () => setOpen(false));
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); setOpen(false); }
  });

  function welcome() {
    messages.innerHTML = '<div class="finora-ai-welcome"><span>✦</span><h3>مساعدك لفهم أعمالك</h3><p>اسأل عن بيانات FINORA، والجواب حسب صلاحياتك.</p><div class="finora-ai-prompts"><button type="button" data-ai-prompt="شنو آخر طلب؟">آخر طلب</button><button type="button" data-ai-prompt="شكد مبيعات اليوم؟">مبيعات اليوم</button><button type="button" data-ai-prompt="شنو المنتجات قليلة المخزون؟">المخزون المنخفض</button><button type="button" data-ai-prompt="شنو المصاريف؟">المصاريف</button></div></div>';
  }
  fresh.addEventListener('click', () => {
    if (controller) controller.abort();
    conversationId = null; loaded = true;
    if (historyList) historyList.hidden = true;
    localStorage.removeItem('finora_ai_conversation_id');
    welcome(); input.focus();
  });
  if (historyButton && historyList) historyButton.addEventListener('click', async () => {
    if (!historyList.hidden) { historyList.hidden = true; return; }
    try {
      const response = await fetch('/finora-ai/api/conversations');
      if (!response.ok) throw new Error('تعذر تحميل المحادثات');
      const data = await response.json(); historyList.replaceChildren();
      (data.conversations || []).forEach(item => {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = item.title;
        button.addEventListener('click', () => {
          if (controller) return;
          conversationId = Number(item.id); localStorage.setItem('finora_ai_conversation_id', String(conversationId));
          loaded = false; historyList.hidden = true; welcome(); loadConversation();
        });
        historyList.appendChild(button);
      });
      if (!historyList.childNodes.length) historyList.textContent = 'لا توجد محادثات سابقة.';
      historyList.hidden = false;
    } catch (error) { addMessage('assistant', error.message, true); }
  });

  function addMessage(role, text, isError) {
    const welcomeEl = messages.querySelector('.finora-ai-welcome');
    if (welcomeEl) welcomeEl.remove();
    const bubble = document.createElement('div');
    bubble.className = 'finora-ai-message ' + role + (isError ? ' error' : '');
    bubble.textContent = text || '';
    if (role === 'assistant' && !isError) renderMarkdown(bubble, text || '');
    if (role === 'assistant' && text && !isError) replyActions(bubble, text);
    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
    return bubble;
  }

  function replyActions(bubble, text, prompt) {
    bubble.querySelector('.finora-ai-reply-actions')?.remove();
    const actions = document.createElement('div'); actions.className = 'finora-ai-reply-actions';
    const copy = document.createElement('button'); copy.type = 'button'; copy.textContent = 'نسخ الرد';
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(text); copy.textContent = 'تم النسخ ✓'; }
      catch (_) { copy.textContent = 'النسخ غير متاح'; }
    });
    actions.appendChild(copy);
    if (prompt) {
      const again = document.createElement('button'); again.type = 'button'; again.textContent = 'إعادة طلب الإجابة';
      again.addEventListener('click', () => submitPrompt(prompt)); actions.appendChild(again);
    }
    const clarify = document.createElement('button'); clarify.type = 'button'; clarify.textContent = 'اطلب توضيحًا';
    clarify.addEventListener('click', () => submitPrompt('وضح أكثر آخر نتيجة، واذكر التفاصيل المؤكدة من الأدوات.'));
    actions.appendChild(clarify); bubble.appendChild(actions);
  }

  // Minimal Markdown renderer using DOM/textContent exclusively: model text
  // can never insert HTML, scripts, event handlers, or javascript URLs.
  function inline(container, text) {
    const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    parts.forEach(part => {
      if (part.startsWith('**') && part.endsWith('**')) {
        const strong = document.createElement('strong'); strong.textContent = part.slice(2, -2); container.appendChild(strong);
      } else if (part.startsWith('`') && part.endsWith('`')) {
        const code = document.createElement('code'); code.textContent = part.slice(1, -1); container.appendChild(code);
      } else container.appendChild(document.createTextNode(part));
    });
  }
  function renderMarkdown(container, text) {
    container.replaceChildren();
    const lines = String(text).split('\n'); let code = false, pre = null, table = null;
    lines.forEach(line => {
      if (line.startsWith('```')) { code = !code; if (code) { pre = document.createElement('pre'); container.appendChild(pre); } return; }
      if (code) { pre.textContent += line + '\n'; return; }
      if (/^\s*\|.+\|\s*$/.test(line)) {
        if (/^[\s|:\-]+$/.test(line)) return;
        if (!table) { table = document.createElement('table'); container.appendChild(table); }
        const tr = document.createElement('tr');
        line.trim().slice(1, -1).split('|').forEach(cell => { const td = document.createElement('td'); inline(td, cell.trim()); tr.appendChild(td); });
        table.appendChild(tr); return;
      }
      table = null;
      const block = document.createElement(/^#{1,3} /.test(line) ? 'strong' : 'div');
      inline(block, line.replace(/^#{1,3} /, '')); if (!line) block.appendChild(document.createElement('br'));
      container.appendChild(block);
    });
  }

  async function loadConversation() {
    if (loaded || !conversationId) { loaded = true; return; }
    loaded = true;
    try {
      const response = await fetch(`/finora-ai/api/conversations/${conversationId}/messages`, {headers: {'Accept': 'application/json'}});
      if (!response.ok) throw new Error('not found');
      const data = await response.json();
      if (!data.messages || !data.messages.length) return;
      messages.innerHTML = '';
      let precedingPrompt = '';
      data.messages.forEach(item => {
        const role = item.role === 'user' ? 'user' : 'assistant';
        const bubble = addMessage(role, item.content);
        if (role === 'user') precedingPrompt = item.content;
        else if (item.content) replyActions(bubble, item.content, precedingPrompt);
      });
    } catch (_) {
      conversationId = null;
      localStorage.removeItem('finora_ai_conversation_id');
      welcome();
    }
  }

  function pageContext() {
    const path = location.pathname;
    const context = {page: path, module: path.split('/').filter(Boolean)[0] || 'dashboard'};
    const patterns = [
      [/\/customers?\/(\d+)/, 'customer_id'], [/\/orders?\/(\d+)/, 'order_id'],
      [/\/suppliers?\/(\d+)/, 'supplier_id'], [/\/inventory\/(?:product\/)?(\d+)/, 'product_id'],
      [/\/agents\/(\d+)\/reports/, 'agent_id']
    ];
    patterns.forEach(([pattern, key]) => { const match = path.match(pattern); if (match) context[key] = Number(match[1]); });
    return context;
  }

  function busy(value) {
    send.disabled = value; input.disabled = value; stop.hidden = !value;
    if (!value) { status.hidden = true; status.textContent = ''; input.focus(); }
  }

  function consumeBlock(block, assistantBubble) {
    const lines = block.split('\n');
    let event = 'message', raw = '';
    lines.forEach(line => { if (line.startsWith('event:')) event = line.slice(6).trim(); if (line.startsWith('data:')) raw += line.slice(5).trim(); });
    if (!raw) return;
    let data; try { data = JSON.parse(raw); } catch (_) { return; }
    if (event === 'mode') showMode(data);
    if (event === 'tool') { status.hidden = false; status.textContent = data.status || 'جاري قراءة بيانات FINORA...'; }
    if (event === 'delta') { assistantBubble.textContent += data.text || ''; messages.scrollTop = messages.scrollHeight; }
    if (event === 'done') {
      conversationId = Number(data.conversation_id) || conversationId;
      if (conversationId) localStorage.setItem('finora_ai_conversation_id', String(conversationId));
      assistantBubble.textContent = data.message || assistantBubble.textContent;
      renderMarkdown(assistantBubble, assistantBubble.textContent);
      replyActions(assistantBubble, data.message || '', latestPrompt);
    }
    if (event === 'conversation') {
      conversationId = Number(data.conversation_id) || conversationId;
      if (conversationId) localStorage.setItem('finora_ai_conversation_id', String(conversationId));
    }
    if (event === 'error') { assistantBubble.textContent = data.message || 'تعذر إكمال الطلب.'; assistantBubble.classList.add('error'); }
  }

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || controller) return;
    latestPrompt = text;
    addMessage('user', text); input.value = ''; input.style.height = 'auto';
    const assistantBubble = addMessage('assistant', '');
    status.hidden = false; status.textContent = 'جاري فهم طلبك...';
    controller = new AbortController(); busy(true);
    try {
      const response = await fetch('/finora-ai/api/chat/stream', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
        body: JSON.stringify({message: text, conversation_id: conversationId, page_context: pageContext()}),
        signal: controller.signal
      });
      if (!response.ok || !response.body) {
        let detail = {}; try { detail = await response.json(); } catch (_) {}
        throw new Error((detail.error && detail.error.message) || 'تعذر الاتصال بخدمة Finora AI');
      }
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
      while (true) {
        const chunk = await reader.read(); if (chunk.done) break;
        buffer += decoder.decode(chunk.value, {stream: true});
        const blocks = buffer.split('\n\n'); buffer = blocks.pop() || '';
        blocks.forEach(block => consumeBlock(block, assistantBubble));
      }
      if (buffer.trim()) consumeBlock(buffer, assistantBubble);
      if (!assistantBubble.textContent) {
        assistantBubble.textContent = 'لم تصل إجابة. حاول مرة أخرى.';
        assistantBubble.classList.add('error');
      }
    } catch (error) {
      assistantBubble.textContent = error.name === 'AbortError' ? 'تم إيقاف الإجابة.' : error.message;
      assistantBubble.classList.add('error');
    } finally {
      controller = null; busy(false);
      if (assistantBubble.classList.contains('error')) {
        const retry = document.createElement('button');
        retry.type = 'button'; retry.className = 'finora-ai-retry'; retry.textContent = 'إعادة المحاولة';
        retry.addEventListener('click', () => {
          if (controller) return;
          retry.remove(); input.value = text; form.requestSubmit();
        });
        assistantBubble.appendChild(document.createElement('br'));
        assistantBubble.appendChild(retry);
      }
    }
  });
  stop.addEventListener('click', () => { if (controller) controller.abort(); });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 120) + 'px'; });
  input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); } });
})();
