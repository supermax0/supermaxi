(function () {
  const cfg = window.SIGNUP_CONFIG || {};
  const PRICES = cfg.prices || {};
  let currentPlan = cfg.initialPlan || 'free';
  let currentBilling = cfg.initialBilling || 'monthly';

  function fmt(n) { return Number(n).toLocaleString('ar-IQ'); }

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
    let ok = true;
    [
      { id: 'company_name', min: 1 },
      { id: 'contact_name', min: 1 },
      { id: 'username', min: 3 },
      { id: 'password', min: 6 }
    ].forEach(function (f) {
      const el = document.getElementById(f.id);
      if (!el || el.value.trim().length < f.min) {
        if (el) el.classList.add('invalid');
        ok = false;
      }
    });
    const p1 = document.getElementById('password');
    const p2 = document.getElementById('password2');
    if (p1 && p2 && p1.value !== p2.value) {
      p2.classList.add('invalid');
      ok = false;
    }
    return ok;
  };

  updateUI();
})();
