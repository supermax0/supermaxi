
    let currentCompany = null;

    // ==================== UI Collapsible & Filter ====================
    function toggleSection(sectionId) {
      const section = document.getElementById(sectionId);
      if (section) {
        section.classList.toggle('collapsed');
      }
    }

    function filterCompanies() {
      const q = document.getElementById("companySearch").value.toLowerCase();
      const rows = document.querySelectorAll("#companiesTable tbody tr");

      rows.forEach(row => {
        // Skip the "No data" row if it exists
        if (row.cells.length === 1) return;

        const text = row.querySelector("td:first-child").innerText.toLowerCase();
        row.style.display = text.includes(q) ? "" : "none";
      });
    }

    function addCompany() {
      const name = document.getElementById("companyName").value.trim();
      const openingBalance = document.getElementById("companyOpeningBalance")?.value || "0";
      if (!name) {
        showToast("⚠️ الرجاء إدخال اسم الشركة", "warning");
        return;
      }

      showLoading();

      fetch("/shipping/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, opening_balance: openingBalance })
      })
        .then(response => response.json())
        .then(data => {
          hideLoading();
          if (data.success) {
            showToast("✅ تم إضافة الشركة بنجاح", "success");
            document.getElementById("companyName").value = "";
            if (document.getElementById("companyOpeningBalance")) {
              document.getElementById("companyOpeningBalance").value = "";
            }

            // عرض بيانات تسجيل الدخول
            if (data.username && data.password) {
              const loginUrl = window.location.origin + (data.login_url || "/delivery/login");
              const messageTemplate = "✅ تم إنشاء شركة النقل بنجاح!\n\nاسم المستخدم: {username}\nكلمة المرور: {password}\n\nرابط تسجيل الدخول: {login_url}\n\nهل تريد نسخ بيانات الدخول؟";
              const message = messageTemplate
                .replace('{username}', data.username)
                .replace('{password}', data.password)
                .replace('{login_url}', loginUrl);

              if (confirm(message)) {
                const credentials = "اسم المستخدم: {username}\nكلمة المرور: {password}\nرابط الدخول: {login_url}"
                  .replace('{username}', data.username)
                  .replace('{password}', data.password)
                  .replace('{login_url}', loginUrl);
                navigator.clipboard.writeText(credentials).then(() => {
                  showToast("✅ تم نسخ بيانات الدخول إلى الحافظة", "success");
                }).catch(() => {
                  prompt("انسخ بيانات الدخول:", credentials);
                });
              }
            }

            setTimeout(() => location.reload(), 2000);
          } else {
            showToast(data.message || "❌ حدث خطأ أثناء الإضافة", "error");
          }
        })
        .catch(error => {
          hideLoading();
          showToast("❌ حدث خطأ أثناء الإضافة", "error");
          console.error(error);
        });
    }

    function deleteCompany(id) {
      if (!confirm("⚠️ هل أنت متأكد من حذف هذه الشركة؟\n\nملاحظة: لا يمكن حذف شركة لديها طلبات")) {
        return;
      }

      showLoading();

      fetch("/shipping/delete/" + id)
        .then(r => r.json())
        .then(data => {
          hideLoading();
          if (data.success) {
            showToast("✅ تم حذف الشركة بنجاح", "success");
            setTimeout(() => location.reload(), 1000);
          } else {
            showToast(data.error === "company has orders" ? "❌ لا يمكن حذف شركة لديها طلبات" : "❌ حدث خطأ أثناء الحذف", "error");
          }
        })
        .catch(error => {
          hideLoading();
          showToast("❌ حدث خطأ أثناء الحذف", "error");
          console.error(error);
        });
    }

    function collectOpeningBalance(companyId, maxAmount, companyName) {
      const formattedMax = Number(maxAmount || 0).toLocaleString("en-US");
      const raw = prompt(`استلام من شركة ${companyName}\nالرصيد الافتتاحي المتبقي: ${formattedMax} د.ع\n\nأدخل مبلغ القبض:`, maxAmount || "");
      if (raw === null) return;

      const amount = Number(String(raw).replaceAll(",", "").trim());
      if (!amount || amount <= 0) {
        showToast("أدخل مبلغ قبض صحيح", "warning");
        return;
      }
      if (amount > Number(maxAmount || 0)) {
        showToast("المبلغ أكبر من الرصيد الافتتاحي المتبقي", "warning");
        return;
      }

      showLoading();
      fetch(`/shipping/collect/${companyId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amount,
          note: `قبض من الرصيد الافتتاحي - ${companyName}`
        })
      })
        .then(r => r.json())
        .then(data => {
          hideLoading();
          if (data.success) {
            showToast(data.message || "تم تسجيل القبض", "success");
            setTimeout(() => location.reload(), 900);
          } else {
            showToast(data.error || "تعذر تسجيل القبض", "error");
          }
        })
        .catch(error => {
          hideLoading();
          showToast("تعذر تسجيل القبض", "error");
          console.error(error);
        });
    }

    function viewOrders(id) {
      currentCompany = id;
      showLoading();

      fetch("/shipping/orders/" + id)
        .then(r => r.json())
        .then(data => {
          hideLoading();
          renderOrders(data);
          document.getElementById("modal").style.display = "flex";
        })
        .catch(error => {
          hideLoading();
          showToast("❌ حدث خطأ أثناء تحميل الطلبات", "error");
          console.error(error);
        });
    }

    function renderOrders(data) {
      let html = `
    <table style="width:100%;">
      <thead>
        <tr>
          <th>#</th>
          <th>اسم الزبون</th>
          <th>رقم الهاتف</th>
          <th>المبلغ</th>
          <th>الحالة</th>
          <th>الإجراءات</th>
        </tr>
      </thead>
      <tbody>
  `;

      if (data.length === 0) {
        html += `
      <tr>
        <td colspan="6" style="text-align:center;padding:40px;color:var(--shipping-muted)">
          لا توجد طلبات لهذه الشركة
        </td>
      </tr>
    `;
      } else {
        data.forEach(o => {
          // تحديد لون الحالة
          let statusColor = "var(--shipping-muted)";
          let statusText = o.status || "غير محدد";
          let statusBadge = "";

          if (o.status === "تم التوصيل") {
            statusColor = "var(--shipping-success)";
            statusBadge = "✅";
          } else if (o.status === "جاري الشحن") {
            statusColor = "var(--shipping-warning)";
            statusBadge = "🚚";
          } else if (o.status === "راجع") {
            statusColor = "var(--shipping-danger)";
            statusBadge = "↩️";
          } else if (o.status === "تم الطلب") {
            statusColor = "var(--shipping-primary)";
            statusBadge = "📦";
          }

          // تحديد حالة الدفع
          let paymentBadge = "";
          if (o.payment === "مسدد") {
            paymentBadge = "💰";
          } else if (o.payment === "مرتجع") {
            paymentBadge = "↩️";
          }

          // تحديد الأزرار المتاحة
          let actionButtons = "";

          if (o.status !== "راجع" && o.status !== "ملغي") {
            if (o.payment !== "مسدد") {
              actionButtons += `
            <button class="btn btn-success" onclick="settle(${o.id})" style="padding:8px 16px;font-size:14px">
              ✅ تسديد
            </button>
          `;
            }

            if (o.status === "تم التوصيل" || o.status === "جاري الشحن") {
              actionButtons += `
            <button class="btn btn-danger" onclick="returnOrder(${o.id})" style="padding:8px 16px;font-size:14px">
              ↩️ ترجيع
            </button>
          `;
            }

            if (o.status === "تم الطلب") {
              actionButtons += `
          <button class="btn btn-danger" onclick="cancelOrder(${o.id})" style="padding:8px 16px;font-size:14px;background:linear-gradient(135deg, #64748b, #475569);">
            ❌ إلغاء
          </button>
        `;
            }
          } else {
            actionButtons = `
          <span style="color:var(--shipping-muted);font-size:13px">لا توجد إجراءات</span>
        `;
          }

          html += `
        <tr style="background:${o.status === "راجع" ? "rgba(239, 68, 68, 0.05)" : o.payment === "مسدد" ? "rgba(16, 185, 129, 0.05)" : ""}">
          <td><strong>${o.id}</strong></td>
          <td>${o.customer}</td>
          <td>${o.phone}</td>
          <td style="color:var(--shipping-success);font-weight:600">${o.total} د.ع</td>
          <td>
            <div style="display:flex;flex-direction:column;gap:4px;align-items:center">
              <span style="color:${statusColor};font-weight:600;font-size:13px">
                ${statusBadge} ${statusText}
              </span>
              ${paymentBadge ? `<span style="color:var(--shipping-muted);font-size:11px">${paymentBadge} ${o.payment}</span>` : ""}
            </div>
          </td>
          <td>
            <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:center">
              ${actionButtons}
            </div>
          </td>
        </tr>
      `;
        });
      }

      html += "</tbody></table>";
      document.getElementById("modalContent").innerHTML = html;
    }

    document.getElementById("searchInput").onkeyup = function () {
      let q = this.value.toLowerCase();
      document.querySelectorAll("#modalContent table tbody tr").forEach((r, i) => {
        if (i === 0 && r.children[0].colSpan === 5) return;
        r.style.display = r.innerText.toLowerCase().includes(q) ? "" : "none";
      });
    }

    function settle(id) {
      if (!confirm("⚠️ هل أنت متأكد من تسديد هذا الطلب؟")) {
        return;
      }

      showLoading();

      fetch("/shipping/settle/" + id, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      })
        .then(r => r.json())
        .then(data => {
          hideLoading();
          if (data.success) {
            showToast("✅ تم تسديد الطلب بنجاح - تم تحديث المستحقات", "success");
            viewOrders(currentCompany);
            updateCompanyDue(); // تحديث المستحقات في الجدول الرئيسي
          } else {
            showToast(data.error || "❌ حدث خطأ أثناء التسديد", "error");
          }
        })
        .catch(error => {
          hideLoading();
          showToast("❌ حدث خطأ أثناء التسديد", "error");
          console.error(error);
        });
    }

    function submitShippingReturn(orderId, barcode, modal) {
      const code = String(barcode || '').trim();
      if (!code) {
        showToast("⚠️ يجب مسح باركود الطلب لتأكيد المرتجع", "warning");
        return;
      }

      showLoading();
      fetch("/shipping/return/" + orderId, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ barcode: code })
      })
        .then(r => r.json())
        .then(data => {
          hideLoading();
          if (data.success) {
            if (modal) modal.remove();
            showToast("✅ تم ترجيع الطلب وإرجاع الكمية للمخزون بنجاح - تم تحديث المستحقات", "success");
            viewOrders(currentCompany);
            updateCompanyDue();
          } else {
            showToast(data.error || data.message || "❌ حدث خطأ أثناء الترجيع", "error");
          }
        })
        .catch(error => {
          hideLoading();
          showToast("❌ حدث خطأ أثناء الترجيع", "error");
          console.error(error);
        });
    }

    function returnOrder(id) {
      const modal = document.createElement('div');
      modal.className = 'modal';
      modal.setAttribute('data-shipping-return-modal', '1');
      modal.setAttribute('data-order-id', String(id));
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999;';

      modal.innerHTML =
        '<div class="modal-box" style="max-width:500px;background:linear-gradient(145deg, rgba(15, 23, 42, 0.98), rgba(30, 41, 59, 0.98));padding:24px;border-radius:24px;border:2px solid rgba(245, 158, 11, 0.3);">' +
        '<div style="text-align:center;">' +
        '<div style="font-size:48px;margin-bottom:16px;">↩️</div>' +
        '<h3 style="color:var(--shipping-text);margin:0 0 12px;font-size:20px;font-weight:700;">تأكيد المرتجع بالباركود</h3>' +
        '<p style="color:var(--shipping-muted);margin:0 0 20px;font-size:14px;">امسح باركود الطلب أو أدخله لتأكيد الإرجاع وإعادة الكمية للمخزون</p>' +
        '<input type="text" id="shippingReturnBarcodeInput" placeholder="امسح أو أدخل باركود الطلب" style="width:100%;padding:14px 16px;border-radius:14px;border:1px solid rgba(255,255,255,0.1);background:rgba(15,23,42,0.6);color:var(--shipping-text);font-size:16px;margin-bottom:20px;text-align:center;direction:ltr;" autocomplete="off" autofocus>' +
        '<div style="display:flex;gap:12px;justify-content:center;">' +
        '<button type="button" class="btn btn-success" id="confirmShippingReturnBtn" style="min-width:120px;">' +
        '<span>✅</span><span>تأكيد المرتجع</span>' +
        '</button>' +
        '<button type="button" class="btn btn-danger" id="closeShippingReturnBtn" style="min-width:120px;">' +
        '<span>❌</span><span>إلغاء</span>' +
        '</button>' +
        '</div></div></div>';

      document.body.appendChild(modal);
      modal.addEventListener('click', function (e) {
        if (e.target === modal) modal.remove();
      });
      modal.querySelector('#closeShippingReturnBtn').addEventListener('click', function () {
        modal.remove();
      });
      modal.querySelector('#confirmShippingReturnBtn').addEventListener('click', function () {
        const input = modal.querySelector('#shippingReturnBarcodeInput');
        submitShippingReturn(id, input ? input.value : '', modal);
      });
      const input = modal.querySelector('#shippingReturnBarcodeInput');
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          submitShippingReturn(id, input.value, modal);
        }
      });
      setTimeout(function () {
        input.focus();
        input.select();
      }, 80);
    }

    function cancelOrder(id) {
      showLoading();

      fetch("/shipping/cancel/" + id, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      })
        .then(r => r.json())
        .then(data => {
          hideLoading();
          if (data.success) {
            showToast("✅ تم إلغاء الطلب بنجاح - تم تحديث المستحقات", "success");
            viewOrders(currentCompany);
            updateCompanyDue();
          } else {
            showToast(data.error || "❌ حدث خطأ أثناء الإلغاء", "error");
          }
        })
        .catch(error => {
          hideLoading();
          showToast("❌ حدث خطأ أثناء الإلغاء", "error");
          console.error(error);
        });
    }

    // تحديث المستحقات في الجدول الرئيسي
    function updateCompanyDue() {
      // إعادة تحميل الصفحة لتحديث المستحقات
      // أو يمكن استخدام AJAX لتحديث القيم فقط
      setTimeout(() => {
        location.reload();
      }, 1500);
    }

    function printModal() {
      const printContent = document.getElementById("modalContent").innerHTML;
      const companyName = document.querySelector(".modal-box h3")?.textContent || "شركة النقل";
      const printDate = new Date().toLocaleDateString("ar-IQ");
      const printTime = new Date().toLocaleTimeString("ar-IQ");

      const printWindow = window.open("", "_blank");
      printWindow.document.write(`
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
      <head>
        <meta charset="UTF-8">
        <title>كشف طلبات الشركة</title>
        <style>
          @page {
            size: A4 landscape;
            margin: 1cm;
          }
          * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
          }
          body { 
            font-family: 'Arial', 'Tahoma', sans-serif; 
            direction: rtl; 
            padding: 20px;
            color: #000;
            background: white;
          }
          .header {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 15px;
            border-bottom: 3px solid #000;
          }
          .header h1 {
            font-size: 24px;
            margin-bottom: 10px;
            color: #000;
          }
          .header-info {
            display: flex;
            justify-content: space-between;
            font-size: 14px;
            color: #666;
            margin-top: 10px;
          }
          table { 
            width: 100%; 
            border-collapse: collapse; 
            margin-top: 20px;
            font-size: 12px;
          }
          th, td { 
            border: 1px solid #000; 
            padding: 10px 8px; 
            text-align: center; 
          }
          th { 
            background: #f0f0f0; 
            font-weight: bold;
            font-size: 13px;
          }
          tbody tr:nth-child(even) {
            background: #f9f9f9;
          }
          .footer {
            margin-top: 30px;
            padding-top: 15px;
            border-top: 2px solid #000;
            text-align: left;
            font-size: 11px;
            color: #666;
          }
          .total-row {
            background: #e8f5e9 !important;
            font-weight: bold;
          }
        </style>
      </head>
      <body>
        <div class="header">
          <h1>كشف طلبات ${companyName}</h1>
          <div class="header-info">
            <span>تاريخ الطباعة: ${printDate} - ${printTime}</span>
            <span>نظام المحاسبة</span>
          </div>
        </div>
        ${printContent}
        <div class="footer">
          <p>تم إنشاء هذا التقرير تلقائياً من نظام المحاسبة</p>
        </div>
      </body>
    </html>
  `);

      printWindow.document.close();
      setTimeout(() => {
        printWindow.print();
      }, 250);
    }

    function closeModal() {
      document.getElementById("modal").style.display = "none";
    }

    // Close modal when clicking outside
    document.getElementById("modal").addEventListener("click", function (e) {
      if (e.target.id === "modal") {
        closeModal();
      }
    });
  