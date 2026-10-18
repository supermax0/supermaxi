(function () {
  var splash = document.getElementById("daSplash");
  if (splash) {
    setTimeout(function () {
      splash.classList.add("is-hide");
      setTimeout(function () { splash.remove(); }, 220);
    }, 600);
  }

  var toggle = document.getElementById("togglePassword");
  var password = document.getElementById("password");
  if (toggle && password) {
    toggle.addEventListener("click", function () {
      var show = password.type === "password";
      password.type = show ? "text" : "password";
      toggle.setAttribute("aria-label", show ? "إخفاء كلمة المرور" : "إظهار كلمة المرور");
      toggle.innerHTML = show ? "إخفاء" : "إظهار";
    });
  }

  var form = document.getElementById("loginForm");
  if (!form) return;
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var error = document.getElementById("errorMessage");
    var errorText = document.getElementById("errorText");
    var button = document.getElementById("loginBtn");
    var username = document.getElementById("username").value.trim();
    var pass = password.value;
    var tenantInput = document.getElementById("tenant_slug");
    var tenant = tenantInput ? tenantInput.value.trim().toLowerCase() : "";
    function fail(message) {
      errorText.textContent = message;
      error.hidden = false;
    }
    error.hidden = true;
    if (!tenant) return fail("يرجى إدخال معرف الشركة");
    if (!username || !pass) return fail("يرجى إدخال اسم المستخدم وكلمة المرور");
    button.disabled = true;
    var bar = document.getElementById("daLoading");
    if (bar) bar.classList.add("is-on");
    fetch("/delivery-agent/login/" + encodeURIComponent(tenant), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username, password: pass, tenant_slug: tenant })
    }).then(function (response) {
      return response.json();
    }).then(function (data) {
      if (data.success) {
        window.location.href = data.redirect || "/delivery-agent/dashboard";
        return;
      }
      fail(data.error || "فشل تسجيل الدخول");
    }).catch(function () {
      fail("حدث خطأ أثناء تسجيل الدخول. حاول مرة أخرى.");
    }).finally(function () {
      button.disabled = false;
      if (bar) bar.classList.remove("is-on");
    });
  });
})();
