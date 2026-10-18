(function () {
  const cfg = window.SIGNUP_CONFIG || {};
  const PRICES = cfg.prices || {};
  let currentPlan = cfg.initialPlan || 'free';
  let currentBilling = cfg.initialBilling || 'monthly';
  const welcomeOfferAvailable = Boolean(cfg.welcomeOfferAvailable);
  const freeTrialDays = Math.max(1, Number(cfg.freeTrialDays) || 14);
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
  const codeRow = document.getElementById('codeRow');
  const btnChangeEmail = document.getElementById('btnChangeEmail');
  const emailStepState = document.getElementById('emailStepState');
  const planPicker = document.getElementById('planPicker');
  const phoneInput = document.getElementById('phone');
  const discoverySource = document.getElementById('discovery_source');
  const discoveryOtherWrap = document.getElementById('discoveryOtherWrap');
  const discoveryOtherInput = document.getElementById('discovery_source_other');
  const whatsappConfirmed = document.getElementById('whatsapp_confirmed');
  const whatsappStepState = document.getElementById('whatsappStepState');

  function fmt(n) { return Number(n).toLocaleString('ar-IQ'); }

  function isValidEmail(v) {
    return /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test((v || '').trim());
  }

  function normalizeIraqiPhone(value) {
    let digits = String(value || '').replace(/\D/g, '');
    if (digits.indexOf('00964') === 0) digits = '0' + digits.slice(5);
    else if (digits.indexOf('964') === 0) digits = '0' + digits.slice(3);
    else if (digits.length === 10 && digits.charAt(0) === '7') digits = '0' + digits;
    return digits;
  }

  function validatePhone(showError) {
    if (!phoneInput) return false;
    const normalized = normalizeIraqiPhone(phoneInput.value);
    const valid = /^07\d{9}$/.test(normalized);
    phoneInput.classList.toggle('valid', valid);
    phoneInput.classList.toggle('invalid', Boolean(showError) && !valid);
    phoneInput.setAttribute('aria-invalid', valid ? 'false' : 'true');
    if (valid && phoneInput.value !== normalized) phoneInput.value = normalized;
    return valid;
  }

  if (phoneInput) {
    phoneInput.addEventListener('input', function () {
      phoneInput.value = phoneInput.value.replace(/[^0-9+\s()-]/g, '');
      if (phoneInput.classList.contains('invalid')) validatePhone(true);
    });
    phoneInput.addEventListener('blur', function () { validatePhone(true); });
  }

  function updateDiscoverySource(showError) {
    if (!discoverySource) return false;
    const hasSource = Boolean(discoverySource.value);
    const needsOther = discoverySource.value === 'other';
    const hasOther = !needsOther || Boolean(discoveryOtherInput && discoveryOtherInput.value.trim());

    discoverySource.classList.toggle('valid', hasSource);
    discoverySource.classList.toggle('invalid', Boolean(showError) && !hasSource);
    if (discoveryOtherWrap) discoveryOtherWrap.hidden = !needsOther;
    if (discoveryOtherInput) {
      discoveryOtherInput.required = needsOther;
      discoveryOtherInput.disabled = !needsOther;
      discoveryOtherInput.classList.toggle('invalid', Boolean(showError) && needsOther && !hasOther);
      discoveryOtherInput.classList.toggle('valid', needsOther && hasOther);
    }
    return hasSource && hasOther;
  }

  if (discoverySource) {
    discoverySource.addEventListener('change', function () { updateDiscoverySource(false); });
  }
  if (discoveryOtherInput) {
    discoveryOtherInput.addEventListener('input', function () { updateDiscoverySource(false); });
  }

  function setVerifyStatus(msg, kind) {
    if (!verifyStatus) return;
    verifyStatus.textContent = msg || '';
    verifyStatus.className = 'pf-verify-status show' + (kind ? ' ' + kind : '');
  }

  function updateSubmitState() {
    const canSubmit = Boolean(whatsappConfirmed && whatsappConfirmed.checked);
    if (btnSubmit) btnSubmit.disabled = !canSubmit;
    if (signupHint) {
      signupHint.innerHTML = canSubmit
        ? '<i class="fas fa-circle-check"></i> جاهز لحفظ الحساب وإرسال طلب التفعيل'
        : '<i class="fas fa-lock"></i> أكد أن الرقم مرتبط بواتساب أولاً';
    }
    if (whatsappStepState) {
      whatsappStepState.textContent = canSubmit ? 'تم التأكيد' : 'مطلوب';
      whatsappStepState.classList.toggle('done', canSubmit);
    }
  }

  if (whatsappConfirmed) whatsappConfirmed.addEventListener('change', updateSubmitState);

  function resetEmailVerification() {
    emailVerified = false;
    verifiedEmail = '';
    if (codeInput) codeInput.value = '';
    if (codeRow) codeRow.hidden = true;
    if (btnSend) {
      btnSend.hidden = false;
      btnSend.innerHTML = '<i class="fas fa-paper-plane"></i> إرسال الرمز';
    }
    if (btnChangeEmail) btnChangeEmail.hidden = true;
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

  if (btnChangeEmail) {
    btnChangeEmail.addEventListener('click', function () {
      if (emailInput) {
        emailInput.readOnly = false;
        emailInput.focus();
        emailInput.select();
      }
      resetEmailVerification();
      setVerifyStatus('عدّل البريد ثم أرسل رمز تحقق جديداً.', 'info');
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
          if (codeRow) codeRow.hidden = false;
          btnSend.innerHTML = '<i class="fas fa-rotate"></i> إعادة الإرسال';
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
      if (k === 'free') {
        if (p.original_monthly != null && p.original_monthly > 0) {
          html += '<span class="pf-strike">' + fmt(p.original_monthly * Math.ceil(freeTrialDays / 30)) + '</span> ';
        }
        html += '0 <small>د.ع/' + freeTrialDays + ' يوم</small>';
      } else if (orig != null && orig > pr) {
        html += '<span class="pf-strike">' + fmt(orig) + '</span> ';
      }
      if (!(k === 'free')) {
        html += fmt(pr) + ' <small>د.ع/' + (yearly ? 'سنة' : 'شهر') + '</small>';
      }
      if (el) el.innerHTML = html;
      if (note) {
        note.textContent = k === 'free'
          ? freeTrialDays + ' يوماً للتجربة'
          : (yearly ? 'يُدفع سنوياً' : 'يُدفع شهرياً');
      }
    });
    const p = PRICES[currentPlan];
    if (!p) return;
    const total = yearly ? p.yearly : p.monthly;
    const sumPlan = document.getElementById('sum_plan');
    const sumBilling = document.getElementById('sum_billing');
    const sumPeriod = document.getElementById('sum_period');
    const sumTotal = document.getElementById('sum_total');
    const billingInput = document.getElementById('billing_input');
    const welcomeSelected = currentPlan === 'free';
    if (sumPlan) sumPlan.textContent = welcomeSelected ? 'الخطة المجانية — ' + freeTrialDays + ' يوم' : p.name;
    if (sumBilling) sumBilling.textContent = welcomeSelected ? 'تجربة مجانية' : (yearly ? 'سنوي' : 'شهري');
    if (sumPeriod) sumPeriod.textContent = welcomeSelected ? freeTrialDays + ' يوم' : (yearly ? '12 شهر' : 'شهر واحد');
    if (sumTotal) sumTotal.textContent = fmt(total) + ' د.ع';
    if (billingInput) billingInput.value = currentBilling;
  }

  window.selectPlan = function (key, el) {
    currentPlan = key;
    document.querySelectorAll('.pf-plan-opt').forEach(function (x) {
      const selected = x === el;
      x.classList.toggle('selected', selected);
      x.setAttribute('aria-checked', selected ? 'true' : 'false');
    });
    if (el) el.classList.add('selected');
    const inp = document.getElementById('plan_key_input');
    if (inp) inp.value = key;
    updateUI();
    if (planPicker && window.matchMedia('(max-width: 768px)').matches) {
      planPicker.open = false;
    }
  };

  document.querySelectorAll('.pf-plan-opt').forEach(function (option) {
    option.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        window.selectPlan(option.dataset.plan, option);
      }
    });
  });

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

  document.querySelectorAll('[data-password-toggle]').forEach(function (button) {
    button.addEventListener('click', function () {
      const input = document.getElementById(button.dataset.passwordToggle);
      if (!input) return;
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      button.setAttribute('aria-label', showing ? 'إظهار كلمة المرور' : 'إخفاء كلمة المرور');
      button.innerHTML = showing ? '<i class="fas fa-eye"></i>' : '<i class="fas fa-eye-slash"></i>';
    });
  });

  window.validateForm = function () {
    if (!whatsappConfirmed || !whatsappConfirmed.checked) {
      if (whatsappConfirmed) whatsappConfirmed.focus();
      return false;
    }
    let ok = true;
    [
      { id: 'company_name', min: 1 },
      { id: 'contact_name', min: 1 },
      { id: 'phone', min: 10 },
      { id: 'username', min: 3 },
      { id: 'password', min: 6 }
    ].forEach(function (f) {
      const el = document.getElementById(f.id);
      if (!el || el.value.trim().length < f.min) {
        if (el) el.classList.add('invalid');
        ok = false;
      }
    });
    if (emailInput && emailInput.value.trim() && !isValidEmail(emailInput.value)) {
      if (emailInput) emailInput.classList.add('invalid');
      ok = false;
    } else if (emailInput) {
      emailInput.classList.remove('invalid');
    }
    const p1 = document.getElementById('password');
    const p2 = document.getElementById('password2');
    if (p1 && p2 && p1.value !== p2.value) {
      p2.classList.add('invalid');
      ok = false;
    }
    if (!validatePhone(true)) ok = false;
    if (!updateDiscoverySource(true)) ok = false;
    if (!ok) {
      const firstInvalid = document.querySelector('.pf-signup-form .invalid');
      if (firstInvalid) {
        firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
        firstInvalid.focus({ preventScroll: true });
      }
    }
    return ok;
  };

  updateUI();
  updateSubmitState();
  updateDiscoverySource(false);
})();
