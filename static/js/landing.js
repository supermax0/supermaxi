(function () {
  'use strict';

  var PRICES = {};
  var bootstrapEl = document.getElementById('landingBootstrap');
  if (bootstrapEl) {
    try {
      var data = JSON.parse(bootstrapEl.textContent || '{}');
      PRICES = data.prices || {};
    } catch (e) { /* ignore */ }
  }

  if (Object.keys(PRICES).length === 0) {
    PRICES = {
      free: { monthly: 0, yearly: 0, name: 'الخطة المجانية', original_monthly: 25000, original_yearly: 250000 },
      basic: { monthly: 25000, yearly: 250000, name: 'الأساسية', original_monthly: null, original_yearly: null },
      pro: { monthly: 45000, yearly: 450000, name: 'المتقدمة', original_monthly: null, original_yearly: null },
      enterprise: { monthly: 90000, yearly: 900000, name: 'الشركات', original_monthly: null, original_yearly: null }
    };
  }

  function fmt(n) {
    return (Number(n) || 0).toLocaleString('ar-IQ');
  }

  function setBilling(mode) {
    var yearly = mode === 'yearly';
    var bm = document.getElementById('btn_monthly');
    var by = document.getElementById('btn_yearly');
    if (bm && by) {
      bm.classList.toggle('active', !yearly);
      by.classList.toggle('active', yearly);
    }
    Object.keys(PRICES).forEach(function (key) {
      var p = PRICES[key];
      var prEl = document.getElementById('price_' + key);
      var svEl = document.getElementById('saving_' + key);
      var lnEl = document.getElementById('link_' + key);
      var price = yearly ? p.yearly : p.monthly;
      var orig = yearly ? p.original_yearly : p.original_monthly;
      var unit = yearly ? 'سنة' : 'شهر';
      var html = '';
      if (orig != null && orig > price) {
        html += '<span style="text-decoration:line-through;opacity:0.55;margin-left:6px;font-size:0.8em;color:var(--muted)">' + fmt(orig) + '</span> ';
      }
      html += fmt(price) + ' <small>د.ع / ' + unit + '</small>';
      if (prEl) prEl.innerHTML = html;
      if (svEl) {
        svEl.innerHTML = yearly
          ? '<span style="display:inline-block;margin-top:8px;font-size:12px;background:var(--success-soft);color:var(--success);padding:4px 12px;border-radius:8px;font-weight:700">وفّر ' + fmt(p.monthly * 12 - p.yearly) + ' د.ع سنوياً</span>'
          : '';
      }
      if (lnEl) lnEl.href = lnEl.href.replace(/billing=\w+/, 'billing=' + mode);
    });
  }

  window.setBilling = setBilling;

  // Nav scroll + active section highlight
  var nav = document.getElementById('lNav');
  var navLinks = document.querySelectorAll('.l-nav-links a[href^="#"]');
  if (nav) {
    window.addEventListener('scroll', function () {
      nav.classList.toggle('scrolled', window.scrollY > 24);
      if (!navLinks.length) return;
      var current = '';
      navLinks.forEach(function (link) {
        var id = (link.getAttribute('href') || '').slice(1);
        var section = id ? document.getElementById(id) : null;
        if (section && window.scrollY >= section.offsetTop - 120) {
          current = link.getAttribute('href');
        }
      });
      navLinks.forEach(function (link) {
        link.classList.toggle('is-active', link.getAttribute('href') === current);
      });
    }, { passive: true });
  }

  // Mobile menu
  var menuBtn = document.getElementById('lMenuBtn');
  var mobileNav = document.getElementById('lMobileNav');
  if (menuBtn && mobileNav) {
    menuBtn.addEventListener('click', function () {
      mobileNav.classList.toggle('open');
    });
    mobileNav.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () { mobileNav.classList.remove('open'); });
    });
  }

  // Reveal on scroll
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (n) {
        if (n.isIntersecting) n.target.classList.add('v');
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });
    document.querySelectorAll('.l-reveal').forEach(function (el) { obs.observe(el); });
  } else {
    document.querySelectorAll('.l-reveal').forEach(function (el) { el.classList.add('v'); });
  }

  // FAQ
  document.querySelectorAll('.l-faq-q').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var item = btn.closest('.l-faq-item');
      var wasOpen = item.classList.contains('open');
      document.querySelectorAll('.l-faq-item').forEach(function (i) { i.classList.remove('open'); });
      if (!wasOpen) item.classList.add('open');
    });
  });

  // Product showcase tabs
  document.querySelectorAll('.l-showcase-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      var id = tab.getAttribute('data-panel');
      document.querySelectorAll('.l-showcase-tab').forEach(function (t) { t.classList.remove('active'); });
      document.querySelectorAll('.l-showcase-panel').forEach(function (p) { p.classList.remove('active'); });
      tab.classList.add('active');
      var panel = document.getElementById(id);
      if (panel) panel.classList.add('active');
    });
  });

  // Billing buttons
  var btnMonthly = document.getElementById('btn_monthly');
  var btnYearly = document.getElementById('btn_yearly');
  if (btnMonthly) btnMonthly.addEventListener('click', function () { setBilling('monthly'); });
  if (btnYearly) btnYearly.addEventListener('click', function () { setBilling('yearly'); });

  // Chat widget
  (function () {
    var btn = document.getElementById('landingChatBtn');
    var panel = document.getElementById('landingChatPanel');
    var overlay = document.getElementById('landingChatOverlay');
    var closeBtn = document.getElementById('landingChatClose');
    var messagesEl = document.getElementById('landingChatMessages');
    var form = document.getElementById('landingChatForm');
    var input = document.getElementById('landingChatInput');
    var sendBtn = document.getElementById('landingChatSend');
    var chatHistory = [];

    function openPanel() {
      if (panel) panel.classList.add('show');
      if (overlay) overlay.classList.add('show');
      setTimeout(function () { if (input) input.focus(); }, 300);
    }
    function closePanel() {
      if (panel) panel.classList.remove('show');
      if (overlay) overlay.classList.remove('show');
    }
    if (btn) btn.addEventListener('click', openPanel);
    if (closeBtn) closeBtn.addEventListener('click', closePanel);
    if (overlay) overlay.addEventListener('click', closePanel);

    function addMessage(content, role, isError) {
      var div = document.createElement('div');
      div.className = 'landing-msg ' + (role || 'assistant') + (isError ? ' error' : '');
      if (role === 'assistant' && !isError) {
        div.innerHTML = content
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/g, '<em>$1</em>')
          .replace(/\n\s*-\s/g, '<br>• ')
          .replace(/\n/g, '<br>');
      } else {
        div.textContent = content;
      }
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function removeTyping() {
      var typing = messagesEl.querySelector('.landing-msg.typing');
      if (typing) typing.remove();
    }

    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var text = (input.value || '').trim();
        if (!text) return;
        input.value = '';
        addMessage(text, 'user');
        chatHistory.push({ role: 'user', content: text });
        sendBtn.disabled = true;
        var typingEl = document.createElement('div');
        typingEl.className = 'landing-msg assistant typing';
        typingEl.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
        messagesEl.appendChild(typingEl);
        messagesEl.scrollTop = messagesEl.scrollHeight;

        fetch('/api/landing-chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, history: chatHistory })
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            removeTyping();
            if (data.success && data.reply) {
              addMessage(data.reply, 'assistant');
              chatHistory.push({ role: 'assistant', content: data.reply });
            } else {
              addMessage(data.error || 'حدث خطأ. جرّب لاحقاً.', 'assistant', true);
            }
          })
          .catch(function () {
            removeTyping();
            addMessage('تعذّر الاتصال. تحقق من الشبكة.', 'assistant', true);
          })
          .finally(function () { sendBtn.disabled = false; });
      });
    }
  })();

  setBilling('monthly');
})();
