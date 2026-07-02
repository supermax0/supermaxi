(function () {
  var bootstrapEl = document.getElementById('landingBootstrap');
  var bootstrap = {};
  try {
    bootstrap = bootstrapEl ? JSON.parse(bootstrapEl.textContent) : {};
  } catch (e) {
    bootstrap = {};
  }

  var PRICES = bootstrap.prices || {};
  if (!Object.keys(PRICES).length) {
    PRICES = {
      free: { monthly: 0, yearly: 0, name: 'المجانية' },
      basic: { monthly: 25000, yearly: 250000, name: 'الأساسية' },
      pro: { monthly: 45000, yearly: 450000, name: 'المتقدمة' },
      enterprise: { monthly: 90000, yearly: 900000, name: 'الشركات' }
    };
  }

  var currentPlan = 'free';
  var currentBilling = 'monthly';
  var emailVerified = false;
  var verifiedEmail = '';

  var emailInput = document.getElementById('email');
  var codeInput = document.getElementById('email_verify_code');
  var btnSend = document.getElementById('btnSendCode');
  var btnVerify = document.getElementById('btnVerifyCode');
  var verifyStatus = document.getElementById('verifyStatus');
  var verifyBox = document.getElementById('emailVerifyBox');
  var btnSubmit = document.getElementById('btnSignupSubmit');
  var signupHint = document.getElementById('signupHint');

  function isValidEmail(v) {
    return /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test((v || '').trim());
  }

  function setVerifyStatus(msg, kind) {
    if (!verifyStatus) return;
    verifyStatus.textContent = msg || '';
    verifyStatus.className = 'l-verify-status show' + (kind ? ' ' + kind : '');
  }

  function updateSubmitState() {
    var canSubmit = emailVerified && emailInput && emailInput.value.trim().toLowerCase() === verifiedEmail;
    if (btnSubmit) btnSubmit.disabled = !canSubmit;
    if (signupHint) {
      signupHint.textContent = canSubmit
        ? 'يمكنك الآن إكمال بياناتك وإنشاء الحساب'
        : 'تحقق من بريدك الإلكتروني أولاً لتفعيل زر التسجيل';
    }
    if (verifyBox) verifyBox.classList.toggle('verified', canSubmit);
    if (emailInput) emailInput.readOnly = canSubmit;
  }

  function resetEmailVerification() {
    emailVerified = false;
    verifiedEmail = '';
    if (codeInput) codeInput.value = '';
    updateSubmitState();
  }

  if (emailInput) {
    emailInput.addEventListener('input', function () {
      var v = emailInput.value.trim().toLowerCase();
      if (emailVerified && v !== verifiedEmail) {
        resetEmailVerification();
        setVerifyStatus('تم تغيير البريد — أعد إرسال رمز التحقق', 'info');
      }
    });
  }

  async function postJson(url, body) {
    var res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(body)
    });
    var data = await res.json().catch(function () { return {}; });
    return { ok: res.ok, data: data };
  }

  if (btnSend) {
    btnSend.addEventListener('click', async function () {
      var email = (emailInput && emailInput.value || '').trim();
      if (!isValidEmail(email)) {
        setVerifyStatus('أدخل بريداً إلكترونياً صحيحاً', 'err');
        return;
      }
      btnSend.disabled = true;
      setVerifyStatus('جاري إرسال الرمز...', 'info');
      try {
        var result = await postJson('/signup/send-verification-code', { email: email });
        if (result.ok) {
          var msg = result.data.message || 'تم إرسال الرمز';
          if (result.data.dev_code) msg += ' (تطوير: ' + result.data.dev_code + ')';
          setVerifyStatus(msg, 'ok');
          if (codeInput) codeInput.focus();
        } else {
          setVerifyStatus(result.data.message || 'تعذّر إرسال الرمز', 'err');
        }
      } catch (e) {
        setVerifyStatus('خطأ في الاتصال. حاول مجدداً', 'err');
      } finally {
        btnSend.disabled = false;
      }
    });
  }

  async function verifyCode() {
    var email = (emailInput && emailInput.value || '').trim();
    var code = (codeInput && codeInput.value || '').trim();
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
      var result = await postJson('/signup/verify-email', { email: email, code: code });
      if (result.ok && result.data.verified) {
        emailVerified = true;
        verifiedEmail = email.toLowerCase();
        setVerifyStatus(result.data.message || 'تم التحقق بنجاح', 'ok');
        updateSubmitState();
      } else {
        setVerifyStatus(result.data.message || 'رمز غير صحيح', 'err');
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

  window.landingSelectPlan = function (key, el) {
    currentPlan = key;
    document.querySelectorAll('.l-signup-plan').forEach(function (x) { x.classList.remove('active'); });
    if (el) el.classList.add('active');
    var inp = document.getElementById('plan_key_input');
    if (inp) inp.value = key;
  };

  document.querySelectorAll('input[name="billing_ui"]').forEach(function (inp) {
    inp.addEventListener('change', function () {
      currentBilling = inp.value;
      var billingInput = document.getElementById('billing_input');
      if (billingInput) billingInput.value = currentBilling;
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
    var p1 = document.getElementById('password');
    var p2 = document.getElementById('password2');
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
    var ok = true;
    [
      { id: 'company_name', min: 1 },
      { id: 'contact_name', min: 1 },
      { id: 'email', min: 3 },
      { id: 'username', min: 3 },
      { id: 'password', min: 6 }
    ].forEach(function (f) {
      var el = document.getElementById(f.id);
      if (!el || el.value.trim().length < f.min) {
        if (el) el.classList.add('invalid');
        ok = false;
      }
    });
    var p1 = document.getElementById('password');
    var p2 = document.getElementById('password2');
    if (p1 && p2 && p1.value !== p2.value) {
      p2.classList.add('invalid');
      ok = false;
    }
    return ok;
  };

  updateSubmitState();
})();
