(function () {
  const cfg = window.SIGNUP_CONFIG || {};
  const PRICES = cfg.prices || {};
  let currentPlan = cfg.initialPlan || 'free';
  let currentBilling = cfg.initialBilling || 'monthly';
  let emailVerified = false;
  let verifiedEmail = '';

  const emailInput = document.getElementById('email');
  const codeInput = document.getElementById('email_verify_code');
  const btnSend = document.getElementById('btnSendCode');
  const btnVerify = document.getElementById('btnVerifyCode');
  const verifyStatus = document.getElementById('verifyStatus');
  const verifyBox = document.getElementById('emailVerifyBox');
  const btnSubmit = document.getElementById('btnSignupSubmit');
  const signupHint = document.getElementById('signupHint');

  function fmt(n) { return Number(n).toLocaleString('ar-IQ'); }

  function isValidEmail(v) {
    return /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test((v || '').trim());
  }

  function setVerifyStatus(msg, kind) {
    if (!verifyStatus) return;
    verifyStatus.textContent = msg || '';
    verifyStatus.className = 'pf-verify-status show' + (kind ? ' ' + kind : '');
  }

  function updateSubmitState() {
    const canSubmit = emailVerified && emailInput && emailInput.value.trim().toLowerCase() === verifiedEmail;
    if (btnSubmit) btnSubmit.disabled = !canSubmit;
    if (signupHint) {
      signupHint.textContent = canSubmit
        ? 'يمكنك الآن إكمال بياناتك وإنشاء الحساب'
        : 'تحقق من بريدك الإلكتروني أولاً لتفعيل زر التسجيل';
    }
    if (verifyBox) {
      verifyBox.classList.toggle('verified', canSubmit);
    }
    if (emailInput) {
      emailInput.readOnly = canSubmit;
    }
  }

  function resetEmailVerification() {
    emailVerified = false;
    verifiedEmail = '';
    if (codeInput) codeInput.value = '';
    updateSubmitState();
  }

  if (emailInput) {
    emailInput.addEventListener('input', function () {
      const v = emailInput.value.trim().toLowerCase();
      if (emailVerified && v !== verifiedEmail) {
        resetEmailVerification();
        setVerifyStatus('تم تغيير البريد — أعد إرسال رمز التحقق', 'info');
      }
    });
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(body)
    });
    const data = await res.json().catch(function () { return {}; });
    return { ok: res.ok, data: data };
  }

  if (btnSend) {
    btnSend.addEventListener('click', async function () {
      const email = (emailInput && emailInput.value || '').trim();
      if (!isValidEmail(email)) {
        if (emailInput) emailInput.classList.add('invalid');
        setVerifyStatus('أدخل بريداً إلكترونياً صحيحاً', 'err');
        return;
      }
      if (emailInput) emailInput.classList.remove('invalid');
      btnSend.disabled = true;
      setVerifyStatus('جاري إرسال الرمز...', 'info');
      try {
        const { ok, data } = await postJson('/signup/send-verification-code', { email: email });
        if (ok) {
          let msg = data.message || 'تم إرسال الرمز';
          if (data.dev_code) msg += ' (تطوير: ' + data.dev_code + ')';
          setVerifyStatus(msg, 'ok');
          if (codeInput) codeInput.focus();
        } else {
          setVerifyStatus(data.message || 'تعذّر إرسال الرمز', 'err');
        }
      } catch (e) {
        setVerifyStatus('خطأ في الاتصال. حاول مجدداً', 'err');
      } finally {
        btnSend.disabled = false;
      }
    });
  }

  async function verifyCode() {
    const email = (emailInput && emailInput.value || '').trim();
    const code = (codeInput && codeInput.value || '').trim();
    if (!isValidEmail(email)) {
      setVerifyStatus('أدخل بريداً إلكترونياً صحيحاً', 'err');
      return;
    }
    if (!/^\d{6}$/.test(code)) {
      setVerifyStatus('أدخل رمز التحقق المكوّن من 6 أرقام', 'err');
      return;
    }
    btnVerify.disabled = true;
    setVerifyStatus('جاري التحقق...', 'info');
    try {
      const { ok, data } = await postJson('/signup/verify-email', { email: email, code: code });
      if (ok && data.verified) {
        emailVerified = true;
        verifiedEmail = email.toLowerCase();
        setVerifyStatus(data.message || 'تم التحقق بنجاح', 'ok');
        updateSubmitState();
      } else {
        setVerifyStatus(data.message || 'رمز غير صحيح', 'err');
      }
    } catch (e) {
      setVerifyStatus('خطأ في الاتصال. حاول مجدداً', 'err');
    } finally {
      btnVerify.disabled = false;
    }
  }

  if (btnVerify) btnVerify.addEventListener('click', verifyCode);
  if (codeInput) {
    codeInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        verifyCode();
      }
    });
  }

  function updateUI() {
    const yearly = currentBilling === 'yearly';
    Object.keys(PRICES).forEach(function (k) {
      const p = PRICES[k];
      const pr = yearly ? p.yearly : p.monthly;
      const orig = yearly ? p.original_yearly : p.original_monthly;
      const el = document.getElementById('p_' + k);
      const note = document.getElementById('pn_' + k);
      let html = '';
      if (orig != null && orig > pr) {
        html += '<span class="pf-strike">' + fmt(orig) + '</span> ';
      }
      html += fmt(pr) + ' <small>د.ع/' + (yearly ? 'سنة' : 'شهر') + '</small>';
      if (el) el.innerHTML = html;
      if (note) note.textContent = yearly ? 'يُدفع سنوياً — وفّر شهرين!' : 'يُدفع شهرياً';
    });
    const p = PRICES[currentPlan];
    if (!p) return;
    const total = yearly ? p.yearly : p.monthly;
    const sumPlan = document.getElementById('sum_plan');
    const sumBilling = document.getElementById('sum_billing');
    const sumPeriod = document.getElementById('sum_period');
    const sumTotal = document.getElementById('sum_total');
    const billingInput = document.getElementById('billing_input');
    if (sumPlan) sumPlan.textContent = p.name;
    if (sumBilling) sumBilling.textContent = yearly ? 'سنوي' : 'شهري';
    if (sumPeriod) sumPeriod.textContent = yearly ? '12 شهر' : 'شهر واحد';
    if (sumTotal) sumTotal.textContent = fmt(total) + ' د.ع';
    if (billingInput) billingInput.value = currentBilling;
  }

  window.selectPlan = function (key, el) {
    currentPlan = key;
    document.querySelectorAll('.pf-plan-opt').forEach(function (x) { x.classList.remove('selected'); });
    if (el) el.classList.add('selected');
    const inp = document.getElementById('plan_key_input');
    if (inp) inp.value = key;
    updateUI();
  };

  document.querySelectorAll('input[name="billing_ui"]').forEach(function (inp) {
    inp.addEventListener('change', function () {
      currentBilling = inp.value;
      updateUI();
    });
  });

  window.liveCheck = function (el, minLen) {
    if (el.value.trim().length >= minLen) {
      el.classList.add('valid');
      el.classList.remove('invalid');
    } else {
      el.classList.remove('valid');
      el.classList.add('invalid');
    }
  };

  window.checkMatch = function () {
    const p1 = document.getElementById('password');
    const p2 = document.getElementById('password2');
    if (!p2 || !p2.value) return;
    if (p1.value === p2.value) {
      p2.classList.add('valid');
      p2.classList.remove('invalid');
    } else {
      p2.classList.remove('valid');
      p2.classList.add('invalid');
    }
  };

  window.validateForm = function () {
    if (!emailVerified) {
      setVerifyStatus('يجب التحقق من البريد الإلكتروني قبل التسجيل', 'err');
      return false;
    }
    let ok = true;
    [
      { id: 'company_name', min: 1 },
      { id: 'contact_name', min: 1 },
      { id: 'email', min: 3 },
      { id: 'username', min: 3 },
      { id: 'password', min: 6 }
    ].forEach(function (f) {
      const el = document.getElementById(f.id);
      if (!el || el.value.trim().length < f.min) {
        if (el) el.classList.add('invalid');
        ok = false;
      }
    });
    if (!isValidEmail(emailInput && emailInput.value)) {
      if (emailInput) emailInput.classList.add('invalid');
      ok = false;
    }
    const p1 = document.getElementById('password');
    const p2 = document.getElementById('password2');
    if (p1 && p2 && p1.value !== p2.value) {
      p2.classList.add('invalid');
      ok = false;
    }
    return ok;
  };

  updateUI();
  updateSubmitState();
})();
