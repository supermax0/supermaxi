(function () {
  function toast(message, isError) {
    if (typeof window.showToast === "function") {
      window.showToast(message, isError ? "error" : "success");
      return;
    }
    alert(message);
  }

  function normalizeWaDigits(phone) {
    var digits = String(phone || "").replace(/\D/g, "");
    if (!digits) return "";
    if (digits.indexOf("0") === 0) return "964" + digits.slice(1);
    if (digits.indexOf("964") !== 0) return "964" + digits;
    return digits;
  }

  function formatNumber(value) {
    var n = Number(value || 0);
    if (!isFinite(n)) n = 0;
    return Math.round(n).toLocaleString("en-US");
  }

  function getPagesFromCard(card) {
    if (!card) return [];
    var node = card.querySelector(".epw-pages-data");
    if (!node) return [];
    try {
      var pages = JSON.parse(node.textContent || "[]");
      return Array.isArray(pages) ? pages : [];
    } catch (err) {
      return [];
    }
  }

  function buildPagesDetails(pages) {
    if (!pages.length) {
      return "لا توجد بيجات معيّنة حالياً";
    }
    return pages
      .map(function (page, index) {
        var name = page.name || ("بيج " + (index + 1));
        var orders = formatNumber(page.orders_count);
        return (index + 1) + ". " + name + " — " + orders + " طلب";
      })
      .join("\n");
  }

  function buildMessage(template, vars) {
    var text = String(template || "");
    Object.keys(vars).forEach(function (key) {
      var token = "{" + key + "}";
      text = text.split(token).join(String(vars[key] == null ? "" : vars[key]));
    });
    return text;
  }

  function getMessageTemplate() {
    var el = document.getElementById("epwMessage");
    return el ? el.value : "";
  }

  function findCard(employeeId) {
    return document.querySelector('.epw-card[data-employee-id="' + employeeId + '"]');
  }

  function getPhoneInput(employeeId) {
    return document.querySelector('.epw-phone-input[data-employee-id="' + employeeId + '"]');
  }

  async function savePhone(employeeId) {
    var input = getPhoneInput(employeeId);
    if (!input) return;
    var phone = input.value.trim();
    try {
      var res = await fetch("/employees/page-warnings/update-phone/" + employeeId, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone: phone }),
      });
      var data = await res.json();
      if (!res.ok || !data.success) {
        toast((data && data.error) || "فشل حفظ الرقم", true);
        return null;
      }
      var card = findCard(employeeId);
      if (card) card.setAttribute("data-wa", data.wa_digits || "");
      input.value = data.phone || "";
      toast(data.message || "تم الحفظ");
      return data;
    } catch (err) {
      toast("خطأ في الاتصال", true);
      return null;
    }
  }

  function sendWhatsApp(employeeId, employeeName) {
    var card = findCard(employeeId);
    var input = getPhoneInput(employeeId);
    var wa = (card && card.getAttribute("data-wa")) || "";
    if (!wa && input) wa = normalizeWaDigits(input.value);
    if (!wa) {
      toast("أضف رقم هاتف الموظف أولاً", true);
      if (input) input.focus();
      return;
    }

    var pages = getPagesFromCard(card);
    var pagesCount = card ? card.getAttribute("data-pages-count") : pages.length;
    var totalOrders = card ? card.getAttribute("data-total-orders") : 0;

    var message = buildMessage(getMessageTemplate(), {
      employee_name: employeeName || "",
      pages_details: buildPagesDetails(pages),
      pages_count: formatNumber(pagesCount),
      total_orders: formatNumber(totalOrders),
      total_sales: "",
    });

    var url = "https://wa.me/" + wa + "?text=" + encodeURIComponent(message);
    window.open(url, "_blank");
  }

  document.addEventListener("click", function (event) {
    var saveBtn = event.target.closest(".epw-save-phone");
    if (saveBtn) {
      event.preventDefault();
      savePhone(saveBtn.getAttribute("data-employee-id"));
      return;
    }
    var sendBtn = event.target.closest(".epw-send-btn");
    if (sendBtn) {
      event.preventDefault();
      sendWhatsApp(
        sendBtn.getAttribute("data-employee-id"),
        sendBtn.getAttribute("data-employee-name")
      );
    }
  });
})();
