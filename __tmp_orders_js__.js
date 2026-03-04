
// متغيرات عامة
let allOrders = [];
let currentOrderData = null;
let currentOrderId = null;

// ==================== دوال مساعدة ====================
// تم نقل showLoading, hideLoading, showToast, selectedIds إلى script tag الأول في بداية الصفحة

// Custom confirm dialog - التعريف الكامل
function showConfirmFull(message, onConfirm, onCancel = null) {
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.style.display = 'flex';
  modal.style.zIndex = '9998';
  modal.innerHTML = `
    <div class="modal-box" style="max-width: 500px;">
      <div style="text-align: center; padding: 20px;">
        <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
        <div style="font-size: 18px; font-weight: 600; margin-bottom: 24px; color: var(--orders-text); white-space: pre-line;">
          ${message}
        </div>
        <div style="display: flex; gap: 12px; justify-content: center;">
          <button class="btn btn-success" onclick="confirmAction_yes()" style="padding: 12px 24px; border-radius: 12px; border: none; cursor: pointer; font-weight: 600;">
            ✅ نعم
          </button>
          <button class="btn btn-danger" onclick="confirmAction_no()" style="padding: 12px 24px; border-radius: 12px; border: none; cursor: pointer; font-weight: 600;">
            ❌ إلغاء
          </button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  
  // Store callbacks
  window.confirmAction_yes = function() {
    modal.remove();
    delete window.confirmAction_yes;
    delete window.confirmAction_no;
    if (onConfirm) onConfirm();
  };
  
  window.confirmAction_no = function() {
    modal.remove();
    delete window.confirmAction_yes;
    delete window.confirmAction_no;
    if (onCancel) onCancel();
  };
  
  // Close on backdrop click
  modal.addEventListener('click', function(e) {
    if (e.target === modal) {
      modal.remove();
      delete window.confirmAction_yes;
      delete window.confirmAction_no;
      if (onCancel) onCancel();
    }
  });
}

// استبدال الـ stub بالتعريف الكامل
window.showConfirm = showConfirmFull;


// ==================== Toggle All Checkboxes ====================
// تم نقل toggleAll و selectedIds إلى script tag الأول في بداية الصفحة

// ==================== تهيئة Tabulator ====================
let ordersTable = null;

function initTabulator() {
  console.log('initTabulator called');
  const ordersDataElement = document.getElementById("ordersData");
  if (!ordersDataElement) {
    console.error("ordersData element not found");
    return;
  }
  
  const tableElement = document.getElementById("ordersTable");
  if (!tableElement) {
    console.error("ordersTable element not found");
    return;
  }
  
  let ordersData = [];
  try {
    ordersData = JSON.parse(ordersDataElement.textContent);
    console.log('Parsed orders data, count:', ordersData.length);
    // ترتيب البيانات حسب order_id تنازلياً
    ordersData.sort((a, b) => (b.order_id || 0) - (a.order_id || 0));
  } catch (e) {
    console.error("Error parsing orders data:", e);
    return;
  }
  
  if (ordersData.length === 0) {
    console.warn("No orders data to display");
  }
  
  try {
    console.log('Creating Tabulator instance...');
    ordersTable = new Tabulator("#ordersTable", {
    data: ordersData,
    layout: "fitDataFill",
    pagination: true,
    paginationSize: 10,
    paginationSizeSelector: [10, 20, 50, 100],
    paginationCounter: "rows",
    height: "600px",
    minHeight: "400px",
    locale: "ar",
    responsiveLayout: false,
    columnHeaderVertAlign: "bottom",
    headerFilterLiveFilter: true,
    movableColumns: true,
    resizableColumns: true,
    responsiveLayoutCollapseStartOpen: false,
    responsiveLayoutCollapseUseFormatters: true,
    langs: {
      ar: {
        pagination: {
          page_size: "حجم الصفحة",
          page_title: "عرض الصفحة",
          first: "الأولى",
          first_title: "الصفحة الأولى",
          last: "الأخيرة",
          last_title: "الصفحة الأخيرة",
          prev: "السابقة",
          prev_title: "الصفحة السابقة",
          next: "التالية",
          next_title: "الصفحة التالية",
          all: "الكل",
          counter: {
            showing: "عرض",
            of: "من",
            rows: "صف",
            pages: "صفحات"
          }
        }
      }
    },
    columns: [
      {
        title: "",
        field: "checkbox",
        width: 60,
        minWidth: 50,
        headerSort: false,
        frozen: true,
        formatter: function(cell) {
          const rowId = cell.getRow().getData().id;
          return `<input type="checkbox" class="row-checkbox" data-id="${rowId}" onclick="event.stopPropagation()" style="width:18px;height:18px;cursor:pointer;">`;
        },
        headerFormatter: function() {
          return `<input type="checkbox" id="toggleAllCheckbox" onclick="event.stopPropagation(); const cb = this; setTimeout(() => { if(window.toggleAll) window.toggleAll(cb); }, 0);" style="width:18px;height:18px;cursor:pointer;">`;
        }
      },
      {
        title: "#", 
        field: "order_id", 
        width: 80, 
        minWidth: 70,
        headerSort: true, 
        sorter: "number",
        sorterParams: {alignEmptyValues: "bottom"},
        formatter: function(cell) {
          const val = cell.getValue() || 0;
          return `<strong style="color:#0f172a;font-weight:700;font-size:15px;">${val}</strong>`;
        }
      },
      {
        title: "التاريخ",
        field: "date",
        width: 160,
        minWidth: 140,
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const row = cell.getRow().getData();
          let html = `<div style="font-size:13px;">`;
          if (row.scheduled_date) {
            html += `<div style="color:#8b5cf6;font-weight:700;margin-bottom:4px;font-size:13px;">📅 ${row.scheduled_date}</div>`;
          }
          html += `<div style="color:#0f172a;font-size:13px;font-weight:600;">${row.date}</div></div>`;
          return html;
        }
      },
      {
        title: "الباركود", 
        field: "barcode", 
        width: 140, 
        minWidth: 120,
        visible: true, 
        headerSort: true, 
        sorter: "string",
        headerFilter: "input",
        headerFilterPlaceholder: "بحث...",
        formatter: function(cell) {
          const val = cell.getValue() || "—";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "الاسم", 
        field: "customer_name", 
        width: 150, 
        minWidth: 120,
        headerFilter: "input",
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const val = cell.getValue() || "";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "الرقم", 
        field: "phone", 
        width: 130, 
        minWidth: 110,
        headerFilter: "input",
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const val = cell.getValue() || "";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "الكمية", 
        field: "quantity", 
        width: 90, 
        minWidth: 70,
        headerSort: true,
        sorter: "number",
        sorterParams: {alignEmptyValues: "bottom"},
        formatter: function(cell) {
          const val = cell.getValue() || 0;
          return `<span style="color:#0f172a;font-weight:700;font-size:15px;">${val}</span>`;
        }
      },
      {
        title: "المجموع",
        field: "total",
        width: 130,
        minWidth: 110,
        headerSort: true,
        sorter: "number",
        sorterParams: {alignEmptyValues: "bottom"},
        formatter: function(cell) {
          const val = cell.getValue() || 0;
          return `<span style="color:#10b981;font-weight:700;font-size:15px;">${val.toLocaleString()}</span>`;
        }
      },
      {
        title: "المدفوع",
        field: "paid_amount",
        width: 130,
        minWidth: 110,
        headerSort: true,
        sorter: "number",
        sorterParams: {alignEmptyValues: "bottom"},
        formatter: function(cell) {
          const val = cell.getValue() || 0;
          return `<span style="color:#3b82f6;font-weight:700;font-size:15px;">${val.toLocaleString()}</span>`;
        }
      },
      {
        title: "المستحق",
        field: "remaining",
        width: 130,
        minWidth: 110,
        headerSort: true,
        sorter: "number",
        sorterParams: {alignEmptyValues: "bottom"},
        formatter: function(cell) {
          const val = cell.getValue() || 0;
          return `<span style="color:${val > 0 ? '#ef4444' : '#10b981'};font-weight:700;font-size:15px;">${val.toLocaleString()}</span>`;
        }
      },
      {
        title: "الحالة",
        field: "status",
        width: 130,
        minWidth: 110,
        headerSort: true,
        sorter: "string",
        headerFilter: "select",
        headerFilterParams: {values: {"": "الكل", "تم الطلب": "تم الطلب", "جاري الشحن": "جاري الشحن", "تم التوصيل": "تم التوصيل", "مرتجع": "مرتجع", "راجع": "راجع", "ملغي": "ملغي"}},
        formatter: function(cell) {
          const status = cell.getValue() || "";
          let color = "#f59e0b";
          let bg = "rgba(245,158,11,0.2)";
          if (status === "تم التوصيل") {
            color = "#10b981";
            bg = "rgba(16,185,129,0.2)";
          } else if (status === "جاري الشحن") {
            color = "#3b82f6";
            bg = "rgba(59,130,246,0.2)";
          } else if (status === "مرتجع" || status === "راجع") {
            color = "#ef4444";
            bg = "rgba(239,68,68,0.2)";
          }
          return `<span class="status-badge" style="background:${bg};color:${color};padding:6px 12px;border-radius:20px;font-size:13px;font-weight:600">${status}</span>`;
        }
      },
      {
        title: "الدفع",
        field: "payment_status",
        width: 120,
        minWidth: 100,
        headerSort: true,
        sorter: "string",
        headerFilter: "select",
        headerFilterParams: {values: {"": "الكل", "مسدد": "مسدد", "جزئي": "جزئي", "غير مسدد": "غير مسدد"}},
        formatter: function(cell) {
          const payment = cell.getValue() || "غير مسدد";
          const row = cell.getRow().getData();
          let color = "#ef4444";
          if (payment === "مسدد") color = "#10b981";
          else if (payment === "جزئي") color = "#f59e0b";
          let html = `<span style="color:${color};font-weight:600;font-size:13px;">${payment}</span>`;
          if (row.scheduled_date) {
            html += `<div style="margin-top:8px;"><span style="background:rgba(139,92,246,0.2);color:#8b5cf6;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:500">📅 مؤجل إلى: ${row.scheduled_date}</span></div>`;
          }
          return html;
        }
      },
      {
        title: "الموظف", 
        field: "employee", 
        width: 130, 
        visible: true, 
        headerFilter: "input",
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const val = cell.getValue() || "—";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "البيج", 
        field: "page_name", 
        width: 130, 
        visible: true,
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const val = cell.getValue() || "—";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "المحافظة", 
        field: "city", 
        width: 130, 
        visible: true, 
        headerFilter: "select", 
        headerFilterParams: {values: true},
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const val = cell.getValue() || "—";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "العنوان", 
        field: "address", 
        width: 200, 
        visible: true,
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const val = cell.getValue() || "—";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "شركة النقل", 
        field: "shipping_company", 
        width: 150, 
        visible: true, 
        headerFilter: "input",
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const val = cell.getValue() || "—";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "مندوب التوصيل", 
        field: "delivery_agent", 
        width: 150, 
        visible: true, 
        headerFilter: "input",
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const val = cell.getValue() || "—";
          return `<span style="color:#0f172a;font-weight:600;font-size:14px;">${val}</span>`;
        }
      },
      {
        title: "الملاحظات",
        field: "note",
        width: 200,
        visible: true,
        headerSort: true,
        sorter: "string",
        formatter: function(cell) {
          const note = cell.getValue();
          if (note) {
            return `<div style="max-width:200px;font-size:13px;color:#0f172a;font-weight:600;background:rgba(59,130,246,0.1);padding:6px 10px;border-radius:8px;border-left:3px solid #3b82f6;word-wrap:break-word;">${note}</div>`;
          }
          return `<span style="color:#94a3b8;">—</span>`;
        }
      },
      {
        title: "إجراءات",
        field: "actions",
        width: 180,
        minWidth: 150,
        headerSort: false,
        frozen: false,
        formatter: function(cell) {
          const row = cell.getRow().getData();
          let html = '<div style="display: flex; gap: 6px; align-items: center; justify-content: center; flex-wrap: wrap;">';
          if (row.can_pay) {
            html += `<button class="action-btn-small pay-btn" onclick="event.stopPropagation(); window.pay && window.pay(${row.id});" title="تسديد كامل"><span>💰</span><span>تسديد</span></button>`;
          }
          if (row.can_cancel) {
            html += `<button class="action-btn-small cancel-btn" onclick="event.stopPropagation(); window.cancelOrder && window.cancelOrder(${row.id});" title="إلغاء الطلب"><span>❌</span><span>إلغاء</span></button>`;
          }
          html += '</div>';
          return html;
        }
      }
    ],
    rowClick: function(e, row) {
      // تجاهل النقر على checkbox أو الأزرار
      const target = e.target;
      if (target.type === 'checkbox' || 
          target.closest('input[type="checkbox"]') || 
          target.closest('button') ||
          target.closest('.action-btn-small') ||
          target.closest('a')) {
        return;
      }
      
      const orderId = row.getData().id;
      if (!orderId) {
        console.error('Order ID not found');
        return;
      }
      
      // جلب تفاصيل الطلب مباشرة
      console.log('Row clicked, orderId:', orderId);
      fetch("/orders/details/" + orderId)
        .then(r => {
          if (!r.ok) throw new Error("Network response was not ok");
          return r.json();
        })
        .then(d => {
          console.log('Order details fetched:', d);
          if (d && d.order) {
            // التأكد من وجود modal
            let modal = document.getElementById("modal");
            console.log('Modal element:', modal);
            if (!modal) {
              console.error('Modal element not found');
              alert('Modal element not found in DOM');
              return;
            }
            
            // عرض التفاصيل مباشرة في modal
            const detailsDiv = document.getElementById("details");
            if (detailsDiv) {
              // حفظ البيانات للاستخدام لاحقاً
              window.currentOrderData = d;
              window.currentOrderId = orderId;
              
              const orderStatus = d.order.status || '';
              const paymentStatus = d.order.payment || d.order.payment_status || '';
              const isReturned = orderStatus === "راجع" || paymentStatus === "مرتجع";
              const canEdit = orderStatus !== "تم التوصيل" && orderStatus !== "مسدد" && orderStatus !== "راجع" && orderStatus !== "ملغي";
              
              detailsDiv.innerHTML = `
                  <div style="margin-bottom: 32px;">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 28px; padding-bottom: 20px; border-bottom: 2px solid rgba(59, 130, 246, 0.2);">
                      <h2 style="margin: 0; font-size: 28px; font-weight: 700; color: #e2e8f0; display: flex; align-items: center; gap: 12px;">
                        <span style="background: linear-gradient(135deg, #3b82f6, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">📋</span>
                        تفاصيل الطلب #${d.order.id}
                      </h2>
                    </div>
                    
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 32px;">
                      <div style="background: rgba(59, 130, 246, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #3b82f6;">
                        <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">الزبون</div>
                        <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.customer || d.order.customer_name || "—"}</div>
                      </div>
                      
                      <div style="background: rgba(59, 130, 246, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #3b82f6;">
                        <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">الهاتف</div>
                        <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.phone || "—"}</div>
                      </div>
                      
                      <div style="background: rgba(16, 185, 129, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #10b981;">
                        <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">المحافظة</div>
                        <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.city || "—"}</div>
                      </div>
                      
                      <div style="background: rgba(16, 185, 129, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #10b981;">
                        <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">العنوان</div>
                        <div style="font-size: 16px; font-weight: 600; color: #e2e8f0; word-break: break-word;">${d.order.address || "—"}</div>
                      </div>
                      
                      <div style="background: rgba(245, 158, 11, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #f59e0b;">
                        <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">الموظف</div>
                        <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.employee || d.order.employee_name || "—"}</div>
                      </div>
                      
                      <div style="background: rgba(245, 158, 11, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #f59e0b;">
                        <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">حالة الطلب</div>
                        <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${orderStatus}</div>
                      </div>
                      
                      <div style="background: rgba(139, 92, 246, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #8b5cf6;">
                        <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">حالة الدفع</div>
                        <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${paymentStatus || "غير مسدد"}</div>
                      </div>
                      
                      <div style="background: rgba(139, 92, 246, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #8b5cf6;">
                        <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">شركة النقل</div>
                        <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.shipping || d.order.shipping_company || "—"}</div>
                      </div>
                    </div>
                    
                    <div style="margin-bottom: 24px;">
                      <h3 style="margin-bottom: 16px; font-size: 20px; font-weight: 700; color: #e2e8f0; display: flex; align-items: center; gap: 8px;">
                        <span>📦</span>
                        المنتجات
                      </h3>
                      <div style="background: rgba(15, 23, 42, 0.5); border-radius: 16px; overflow: hidden; border: 1px solid rgba(59, 130, 246, 0.2);">
                        <table style="width: 100%; border-collapse: collapse;">
                          <thead>
                            <tr style="background: linear-gradient(135deg, rgba(59, 130, 246, 0.15), rgba(59, 130, 246, 0.1));">
                              <th style="padding: 16px; text-align: right; font-weight: 600; color: #e2e8f0; font-size: 14px;">اسم المنتج</th>
                              <th style="padding: 16px; text-align: center; font-weight: 600; color: #e2e8f0; font-size: 14px; width: 100px;">الكمية</th>
                              <th style="padding: 16px; text-align: center; font-weight: 600; color: #e2e8f0; font-size: 14px; width: 120px;">السعر</th>
                              <th style="padding: 16px; text-align: center; font-weight: 600; color: #e2e8f0; font-size: 14px; width: 140px;">المجموع</th>
                            </tr>
                          </thead>
                          <tbody>
                            ${d.items && d.items.length > 0 ? d.items.map((i, idx) => `
                              <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05); background: ${idx % 2 === 0 ? 'rgba(255, 255, 255, 0.02)' : 'transparent'};">
                                <td style="padding: 16px; color: #e2e8f0; font-weight: 500;">${i.name || i.product_name || "—"}</td>
                                <td style="padding: 16px; text-align: center; color: #e2e8f0;">${i.qty || i.quantity || 0}</td>
                                <td style="padding: 16px; text-align: center; color: #e2e8f0;">${(i.price || 0).toLocaleString()} د.ع</td>
                                <td style="padding: 16px; text-align: center; color: #10b981; font-weight: 600;">${(i.total || 0).toLocaleString()} د.ع</td>
                              </tr>
                            `).join('') : '<tr><td colspan="4" style="padding: 24px; text-align: center; color: rgba(226, 232, 240, 0.5);">لا توجد منتجات</td></tr>'}
                          </tbody>
                          <tfoot>
                            <tr style="background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(59, 130, 246, 0.15)); border-top: 2px solid rgba(59, 130, 246, 0.3);">
                              <td colspan="3" style="padding: 20px; text-align: right; font-size: 18px; font-weight: 700; color: #e2e8f0;">الإجمالي:</td>
                              <td style="padding: 20px; text-align: center; font-size: 20px; font-weight: 700; color: #10b981;">${(d.order.total || 0).toLocaleString()} د.ع</td>
                            </tr>
                          </tfoot>
                        </table>
                      </div>
                    </div>
                  </div>
                  
                  <div style="display: flex; flex-wrap: wrap; gap: 12px; padding: 24px; background: rgba(15, 23, 42, 0.5); border-radius: 16px; border: 1px solid rgba(59, 130, 246, 0.2); margin-top: 32px;">
                    <button class="btn btn-primary" onclick="window.printSingleInvoice && window.printSingleInvoice(${orderId})" style="flex: 1; min-width: 150px;">
                      🖨️ طباعة الفاتورة
                    </button>
                    ${canEdit ? `
                    <button class="btn btn-success" onclick="window.payPartial && window.payPartial(${orderId})" style="flex: 1; min-width: 150px;">
                      💵 تسديد جزئي
                    </button>
                    <button class="btn btn-info" onclick="window.sendWhatsAppSingle && window.sendWhatsAppSingle(${orderId})" style="flex: 1; min-width: 150px;">
                      💬 إرسال واتساب
                    </button>
                    <button class="btn btn-warning" onclick="window.editOrder && window.editOrder(${orderId})" style="flex: 1; min-width: 150px;">
                      ✏️ تعديل الطلب
                    </button>
                    ` : ''}
                    ${isReturned ? `
                    <button class="btn btn-warning" onclick="window.markAsReturned && window.markAsReturned(${orderId})" style="flex: 1; min-width: 150px;">
                      ↩️ تحديد كمرتجع
                    </button>
                    ` : ''}
                  </div>
              `;
              
              // عرض modal
              if (modal) {
                console.log('Showing modal');
                modal.style.display = "flex";
                modal.style.alignItems = "center";
                modal.style.justifyContent = "center";
              } else {
                console.error('Modal is null when trying to show');
              }
            } else {
              console.error('Details div not found');
            }
          } else {
            console.error('Modal not found');
          }
        } else {
          if (typeof showToast === 'function') {
            showToast("❌ لم يتم العثور على بيانات الطلب", "error");
          } else {
            alert("❌ لم يتم العثور على بيانات الطلب");
          }
        }
        })
        .catch(err => {
          console.error('Error fetching order details:', err);
          if (typeof showToast === 'function') {
            showToast("❌ حدث خطأ في جلب تفاصيل الطلب", "error");
          } else {
            alert("❌ حدث خطأ في جلب تفاصيل الطلب");
          }
        });
    },
    dataLoaded: function() {
      // ترتيب البيانات حسب order_id تنازلياً
      if (ordersTable) {
        ordersTable.setSort([
          {column: "order_id", dir: "desc"}
        ]);
      }
      updateStats();
      
      // ربط checkbox في الرأس
      setTimeout(function() {
        const headerCheckbox = document.getElementById("toggleAllCheckbox");
        if (headerCheckbox) {
          headerCheckbox.addEventListener('change', function() {
            if (window.toggleAll) {
              window.toggleAll(this);
            }
          });
        }
      }, 100);
      
      // التأكد من أن showDetails متاحة
      if (typeof window.showDetails !== 'function' && typeof showDetails === 'function') {
        window.showDetails = showDetails;
      }
      
      // التأكد من أن modal موجود
      const modal = document.getElementById("modal");
      if (!modal) {
        console.warn('Modal element not found in DOM');
      }
    }
  });
  
  console.log('Tabulator instance created successfully');
  } catch (error) {
    console.error('Error creating Tabulator instance:', error);
    alert('حدث خطأ في تحميل الجدول. يرجى تحديث الصفحة.');
  }
  
  // تحديث allOrders للتوافق مع الكود الموجود
  allOrders = ordersData.map(order => ({
    element: null,
    id: order.order_id.toString(),
    barcode: order.barcode,
    name: order.customer_name.toLowerCase(),
    phone: order.phone,
    city: order.city,
    status: order.status,
    payment: order.payment_status,
    employee: order.employee,
    shipping: order.shipping_company,
    agentText: order.delivery_agent,
    agentId: order.delivery_agent_id ? order.delivery_agent_id.toString() : "",
    text: `${order.customer_name} ${order.phone} ${order.barcode}`.toLowerCase()
  }));
  
  updateStats();
}

// ==================== تهيئة الطلبات (للتوافق مع الكود الموجود) ====================
function initOrders() {
  // إذا كان Tabulator مستخدم، استخدم initTabulator بدلاً من ذلك
  if (typeof Tabulator !== 'undefined') {
    initTabulator();
    return;
  }
  
  allOrders = [];
  
  document.querySelectorAll("#ordersTable tbody tr").forEach((row, index) => {
    const cells = row.querySelectorAll("td");
    
    // استخراج حالة الطلب من الـ badge
    const statusBadge = row.querySelector(".status-badge");
    const statusText = statusBadge ? statusBadge.textContent.trim() : "";
    
    // استخراج حالة الدفع (الآن في الخلية 9 بعد إضافة عمود الباركود)
    // 0: checkbox, 1: رقم الطلب, 2: التاريخ, 3: الباركود, 4: الاسم, 5: الرقم, 6: الكمية, 7: المجموع, 8: حالة الطلب, 9: حالة الدفع
    const paymentCell = cells[9];
    let paymentText = "";
    if (paymentCell) {
      // البحث عن أول span في الخلية (حالة الدفع)
      const paymentSpan = paymentCell.querySelector("span");
      if (paymentSpan) {
        paymentText = paymentSpan.textContent.trim();
      } else {
        // إذا لم يكن هناك span، أخذ النص الكامل وإزالة أي نص إضافي (مثل التاريخ المؤجل)
        const fullText = paymentCell.textContent.trim();
        // إزالة أي نص يحتوي على "مؤجل" أو "📅" أو أي نص في سطر جديد
        paymentText = fullText.split('\n')[0].trim();
        paymentText = paymentText.replace(/📅.*$/, '').trim();
        paymentText = paymentText.replace(/مؤجل.*$/, '').trim();
      }
      // تنظيف النص من أي مسافات إضافية
      paymentText = paymentText.replace(/\s+/g, ' ').trim();
    }
    
    const barcode = cells[3]?.textContent.trim() || "";
    // مندوب التوصيل في الخلية 14 (بعد شركة النقل) - الآن نص وليس select
    const agentText = cells[14]?.textContent.trim() || "";
    // محاولة الحصول على agentId من data attribute أو من الصف
    const agentIdAttr = row.getAttribute("data-agent-id") || cells[14]?.getAttribute("data-agent-id") || "";
    const agentId = agentIdAttr || (agentText ? agentText.split("|")[0] : "");
    
    allOrders.push({
      element: row,
      id: cells[1]?.textContent.trim() || "",
      barcode: barcode,
      name: cells[4]?.textContent.trim().toLowerCase() || "",
      phone: cells[5]?.textContent.trim() || "",
      city: cells[12]?.textContent.trim() || "", // المحافظة (العمود 12)
      status: statusText,
      payment: paymentText,
      employee: cells[10]?.textContent.trim() || "", // الموظف (العمود 10)
      shipping: cells[13]?.textContent.trim() || "", // شركة النقل (العمود 13)
      agentText: agentText,
      agentId: agentId,
      text: (row.innerText + " " + barcode).toLowerCase()
    });
  });
  
  updateStats();
  applyFilters();
}

// ==================== التصفية والبحث ====================
function applyFilters() {
  // إذا كان Tabulator مستخدم، استخدم فلاتر Tabulator
  if (ordersTable) {
    const searchQuery = document.getElementById("searchInput")?.value || "";
    const cityFilter = document.getElementById("filterCity")?.value || "";
    const statusFilter = document.getElementById("filterStatus")?.value || "";
    const paymentFilter = document.getElementById("filterPayment")?.value || "";
    const employeeFilter = document.getElementById("filterEmployee")?.value || "";
    const shippingFilter = document.getElementById("filterShipping")?.value || "";
    const agentFilterEl = document.getElementById("filterDeliveryAgent");
    const agentFilter = agentFilterEl ? agentFilterEl.options[agentFilterEl.selectedIndex]?.text : "";
    const scheduledDateFilterEl = document.getElementById("filterScheduledDate");
    const scheduledDateFilter = scheduledDateFilterEl ? scheduledDateFilterEl.value : "";
    
    // إذا تم اختيار تاريخ، إعادة تحميل الصفحة مع الفلتر
    if (scheduledDateFilter) {
      const url = new URL(window.location.href);
      url.searchParams.set('scheduled_date', scheduledDateFilter);
      window.location.href = url.toString();
      return;
    } else {
      const url = new URL(window.location.href);
      if (url.searchParams.has('scheduled_date')) {
        url.searchParams.delete('scheduled_date');
        window.location.href = url.toString();
        return;
      }
    }
    
    // تطبيق الفلاتر على Tabulator
    let filters = [];
    
    if (searchQuery) {
      filters.push([
        {field: "customer_name", type: "like", value: searchQuery},
        {field: "phone", type: "like", value: searchQuery},
        {field: "barcode", type: "like", value: searchQuery}
      ]);
    }
    
    if (cityFilter) {
      filters.push({field: "city", type: "=", value: cityFilter});
    }
    
    if (statusFilter) {
      filters.push({field: "status", type: "=", value: statusFilter});
    }
    
    if (paymentFilter) {
      filters.push({field: "payment_status", type: "=", value: paymentFilter});
    }
    
    if (employeeFilter) {
      filters.push({field: "employee", type: "=", value: employeeFilter});
    }
    
    if (shippingFilter) {
      filters.push({field: "shipping_company", type: "=", value: shippingFilter});
    }
    
    if (agentFilter) {
      filters.push({field: "delivery_agent", type: "like", value: agentFilter});
    }
    
    ordersTable.setFilter(filters.length > 0 ? filters : []);
    
    // تحديث الإحصائيات
    const filteredData = ordersTable.getFilteredData();
    let totalSales = 0;
    let pendingCount = 0;
    let returnsCount = 0;
    
    filteredData.forEach(order => {
      totalSales += order.total || 0;
      if (order.status === "تم الطلب" || order.status === "جاري الشحن") {
        pendingCount++;
      }
      if (order.status === "راجع" || order.status === "مرتجع") {
        returnsCount++;
      }
    });
    
    document.getElementById("statTotal").textContent = filteredData.length;
    document.getElementById("statSales").textContent = totalSales.toLocaleString() + " د.ع";
    document.getElementById("statPending").textContent = pendingCount;
    document.getElementById("statReturns").textContent = returnsCount;
    document.getElementById("visibleCount").textContent = filteredData.length;
    document.getElementById("totalCount").textContent = allOrders.length;
    document.getElementById("tableStats").textContent = `(${filteredData.length} طلب)`;
    
    return;
  }
  
  // الكود القديم للجدول HTML
  const searchQuery = document.getElementById("searchInput").value.toLowerCase();
  const cityFilter = document.getElementById("filterCity").value;
  const statusFilter = document.getElementById("filterStatus").value;
  const paymentFilter = document.getElementById("filterPayment").value;
  const employeeFilter = document.getElementById("filterEmployee").value;
  const shippingFilter = document.getElementById("filterShipping").value;
  const agentFilterEl = document.getElementById("filterDeliveryAgent");
  const agentFilter = agentFilterEl ? agentFilterEl.options[agentFilterEl.selectedIndex]?.text : "";
  const scheduledDateFilterEl = document.getElementById("filterScheduledDate");
  const scheduledDateFilter = scheduledDateFilterEl ? scheduledDateFilterEl.value : "";
  
  // إذا تم اختيار تاريخ، إعادة تحميل الصفحة مع الفلتر
  if (scheduledDateFilter) {
    const url = new URL(window.location.href);
    url.searchParams.set('scheduled_date', scheduledDateFilter);
    if (!scheduledDateFilter) {
      url.searchParams.delete('scheduled_date');
    }
    window.location.href = url.toString();
    return;
  } else {
    const url = new URL(window.location.href);
    if (url.searchParams.has('scheduled_date')) {
      url.searchParams.delete('scheduled_date');
      window.location.href = url.toString();
      return;
    }
  }
  
  let visibleCount = 0;
  let totalSales = 0;
  let pendingCount = 0;
  let returnsCount = 0;
  
  allOrders.forEach(order => {
    const matchesSearch = !searchQuery || order.text.includes(searchQuery);
    const orderCity = (order.city || "").trim();
    const matchesCity = !cityFilter || orderCity === cityFilter.trim();
    const orderStatus = (order.status || "").trim();
    const matchesStatus = !statusFilter || orderStatus === statusFilter.trim();
    const orderPayment = (order.payment || "").trim().split('\n')[0].trim();
    const matchesPayment = !paymentFilter || orderPayment === paymentFilter.trim();
    const orderEmployee = (order.employee || "").trim();
    const matchesEmployee = !employeeFilter || orderEmployee === employeeFilter.trim();
    const orderShipping = (order.shipping || "").trim();
    const matchesShipping = !shippingFilter || (orderShipping && orderShipping !== "—" && orderShipping === shippingFilter.trim());
    const orderAgent = (order.agentText || "").trim();
    const matchesAgent = !agentFilter || (orderAgent && orderAgent !== "—" && orderAgent.includes(agentFilter.trim()));
    
    const shouldShow = matchesSearch && matchesCity && matchesStatus && matchesPayment && matchesEmployee && matchesShipping && matchesAgent;
    
    if (order.element) {
      order.element.style.display = shouldShow ? "" : "none";
    }
    
    if (shouldShow) {
      visibleCount++;
      if (order.element) {
        const totalCell = order.element.querySelector("td:nth-child(8) span");
        if (totalCell) {
          const totalText = totalCell.textContent.trim();
          const totalValue = parseInt(totalText.replace(/[^0-9]/g, '')) || 0;
          totalSales += totalValue;
        }
      }
      
      if (order.status === "تم الطلب" || order.status === "جاري الشحن") {
        pendingCount++;
      }
      
      if (order.status === "راجع" || order.status === "مرتجع") {
        returnsCount++;
      }
    }
  });
  
  document.getElementById("statTotal").textContent = visibleCount;
  document.getElementById("statSales").textContent = totalSales.toLocaleString() + " د.ع";
  document.getElementById("statPending").textContent = pendingCount;
  document.getElementById("statReturns").textContent = returnsCount;
  document.getElementById("visibleCount").textContent = visibleCount;
  document.getElementById("totalCount").textContent = allOrders.length;
  document.getElementById("tableStats").textContent = `(${visibleCount} طلب)`;
}

function updateStats() {
  // إذا كان Tabulator مستخدم
  if (ordersTable) {
    const data = ordersTable.getData();
    let totalSales = 0;
    let pendingCount = 0;
    let returnsCount = 0;
    
    data.forEach(order => {
      totalSales += order.total || 0;
      if (order.status === "تم الطلب" || order.status === "جاري الشحن") {
        pendingCount++;
      }
      if (order.status === "راجع" || order.status === "مرتجع") {
        returnsCount++;
      }
    });
    
    document.getElementById("statTotal").textContent = data.length;
    document.getElementById("statSales").textContent = totalSales.toLocaleString() + " د.ع";
    document.getElementById("statPending").textContent = pendingCount;
    document.getElementById("statReturns").textContent = returnsCount;
    document.getElementById("visibleCount").textContent = data.length;
    document.getElementById("totalCount").textContent = data.length;
    return;
  }
  
  // الكود القديم
  let totalSales = 0;
  let pendingCount = 0;
  let returnsCount = 0;
  
  allOrders.forEach(order => {
    if (order.element) {
      const totalCell = order.element.querySelector("td:nth-child(8) span");
      if (totalCell) {
        const totalText = totalCell.textContent.trim();
        const totalValue = parseInt(totalText.replace(/[^0-9]/g, '')) || 0;
        totalSales += totalValue;
      }
    }
    
    if (order.status === "تم الطلب" || order.status === "جاري الشحن") {
      pendingCount++;
    }
    
    if (order.status === "راجع" || order.status === "مرتجع") {
      returnsCount++;
    }
  });
  
  document.getElementById("statTotal").textContent = allOrders.length;
  document.getElementById("statSales").textContent = totalSales.toLocaleString() + " د.ع";
  document.getElementById("statPending").textContent = pendingCount;
  document.getElementById("statReturns").textContent = returnsCount;
  document.getElementById("visibleCount").textContent = allOrders.length;
  document.getElementById("totalCount").textContent = allOrders.length;
}

// Clear Filters - التعريف الكامل
function clearFilters() {
  document.getElementById("searchInput").value = "";
  document.getElementById("filterCity").value = "";
  document.getElementById("filterStatus").value = "";
  document.getElementById("filterPayment").value = "";
  document.getElementById("filterEmployee").value = "";
  document.getElementById("filterShipping").value = "";
  if (document.getElementById("filterDeliveryAgent")) {
    document.getElementById("filterDeliveryAgent").value = "";
  }
  if (document.getElementById("filterScheduledDate")) {
    document.getElementById("filterScheduledDate").value = "";
  }
  
  // إذا كان Tabulator مستخدم، مسح الفلاتر
  if (ordersTable) {
    ordersTable.clearFilter();
    ordersTable.clearHeaderFilter();
  }
  
  // إزالة النشاط من أزرار الإجراءات السريعة
  document.querySelectorAll(".quick-action-btn").forEach(btn => {
    btn.classList.remove("active");
  });
  
  if (typeof applyFilters === 'function') {
    applyFilters();
  }
  if (typeof showToast === 'function') {
    showToast("✅ تم إعادة تعيين الفلاتر", "success");
  }
}
// تحديث التعريف في window
window.clearFilters = clearFilters;

function filterByStatus(status) {
  document.getElementById("filterStatus").value = status;
  
  // تحديث أزرار الإجراءات السريعة
  document.querySelectorAll(".quick-action-btn").forEach(btn => {
    btn.classList.remove("active");
    if (btn.textContent.includes(status)) {
      btn.classList.add("active");
    }
  });
  
  applyFilters();
}

function filterByPayment(payment) {
  document.getElementById("filterPayment").value = payment;
  
  // تحديث أزرار الإجراءات السريعة
  document.querySelectorAll(".quick-action-btn").forEach(btn => {
    btn.classList.remove("active");
    if (btn.textContent.includes(payment)) {
      btn.classList.add("active");
    }
  });
  
  applyFilters();
}

// ==================== القائمة المنسدلة ====================
function toggleDropdown(event, orderId) {
  if (event) {
    event.stopPropagation();
    event.preventDefault();
  }
  
  const dropdown = document.getElementById(`dropdown-${orderId}`);
  if (!dropdown) return;
  
  const button = event ? event.currentTarget : dropdown.previousElementSibling;
  const isOpen = dropdown.classList.contains('show');
  
  // إغلاق جميع القوائم المنسدلة الأخرى
  document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
    if (menu.id !== `dropdown-${orderId}`) {
      menu.classList.remove('show');
    }
  });
  
  // إزالة حالة active من جميع الأزرار
  document.querySelectorAll('.dropdown-btn.active').forEach(btn => {
    if (btn !== button) {
      btn.classList.remove('active');
    }
  });
  
  // تبديل القائمة الحالية
  if (!isOpen) {
    dropdown.classList.add('show');
    if (button) button.classList.add('active');
  } else {
    dropdown.classList.remove('show');
    if (button) button.classList.remove('active');
  }
}
window.toggleDropdown = toggleDropdown;

// إغلاق القوائم المنسدلة عند النقر خارجها
document.addEventListener('click', function(event) {
  if (!event.target.closest('.dropdown-container')) {
    document.querySelectorAll('.dropdown-menu.show').forEach(menu => {
      menu.classList.remove('show');
    });
    document.querySelectorAll('.dropdown-btn.active').forEach(btn => {
      btn.classList.remove('active');
    });
  }
});

// ==================== النقر على الصف ====================
function handleRowClick(event, orderId) {
  if (!event || !orderId) return;
  
  // إذا تم النقر على checkbox أو زر أو dropdown، لا نفعل شيء
  const target = event.target;
  const clickedElement = target.closest('input[type="checkbox"]') || 
                         target.closest('button') || 
                         target.closest('.dropdown-container') ||
                         target.closest('.dropdown-menu') ||
                         target.closest('.action-btn-small') ||
                         target.closest('.dropdown-btn');
  
  if (clickedElement) {
    return;
  }
  
  // عرض التفاصيل
  showDetails(orderId);
}

// Make handleRowClick globally available
window.handleRowClick = handleRowClick;

// ==================== إجراءات الدفع ====================
function pay(id) {
  if (!id) {
    if (typeof showToast === 'function') {
      showToast("⚠️ رقم الطلب غير صحيح", "warning");
    } else {
      alert("⚠️ رقم الطلب غير صحيح");
    }
    return;
  }
  
  if (typeof showConfirm !== 'function') {
    console.error('showConfirm not available');
    return;
  }
  
  showConfirm("⚠️ هل أنت متأكد من تسديد هذا الطلب؟", function() {
    // جلب تفاصيل الطلب للحصول على المجموع
    fetch("/orders/details/" + id)
      .then(r => r.json())
      .then(data => {
        const total = data && data.order ? (parseFloat(data.order.total) || 0) : 0;
        if (typeof showLoading === 'function') showLoading();
        fetch("/orders/payment", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({id: id, payment: "مسدد", paid_amount: total})
        })
          .then(r => {
            if (!r.ok) throw new Error("Network response was not ok");
            return r.json();
          })
          .then(res => {
            if (typeof hideLoading === 'function') hideLoading();
            if (res.success) {
              if (typeof showToast === 'function') {
                showToast("✅ تم تسديد الطلب بنجاح", "success");
              }
              setTimeout(() => location.reload(), 1000);
            } else {
              if (typeof showToast === 'function') {
                showToast(res.error || "❌ حدث خطأ أثناء التسديد", "error");
              }
            }
          })
          .catch(error => {
            if (typeof hideLoading === 'function') hideLoading();
            console.error("Pay error:", error);
            if (typeof showToast === 'function') {
              showToast("❌ حدث خطأ أثناء التسديد: " + error.message, "error");
            }
          });
      })
      .catch(error => {
        if (typeof hideLoading === 'function') hideLoading();
        console.error("Error fetching order details:", error);
        if (typeof showToast === 'function') {
          showToast("❌ حدث خطأ في تحميل بيانات الطلب", "error");
        }
      });
  });
}
window.pay = pay;

// ==================== تسديد جزئي ====================
function payPartial(id) {
  if (!id) {
    showToast("⚠️ رقم الطلب غير صحيح", "warning");
    return;
  }
  
  // جلب تفاصيل الطلب أولاً
  fetch("/orders/details/" + id)
    .then(r => {
      if (!r.ok) throw new Error("Network response was not ok");
      return r.json();
    })
    .then(data => {
      if (!data || !data.order) {
        showToast("❌ لم يتم العثور على بيانات الطلب", "error");
        return;
      }
      
      const total = parseFloat(data.order.total) || 0;
      const currentPayment = data.order.payment || data.order.payment_status || "غير مسدد";
      
      // طلب المبلغ المدفوع
      const paidAmount = prompt(`المبلغ الإجمالي: ${total.toLocaleString()} د.ع\n\nأدخل المبلغ المدفوع:`, "");
      
      if (paidAmount === null) return; // المستخدم ألغى
      
      const paid = parseFloat(paidAmount);
      
      if (isNaN(paid) || paid < 0) {
        showToast("⚠️ المبلغ غير صحيح", "warning");
        return;
      }
      
      if (paid > total) {
        showToast("⚠️ المبلغ المدفوع أكبر من الإجمالي", "warning");
        return;
      }
      
      if (paid === total) {
        // إذا كان المبلغ يساوي الإجمالي، تسديد كامل
        showConfirm("⚠️ المبلغ يساوي الإجمالي. هل تريد تسديد كامل؟", function() {
          proceedWithPayment(id, "مسدد", paid);
        });
      } else if (paid > 0) {
        // تسديد جزئي
        showConfirm(`⚠️ هل أنت متأكد من تسديد ${paid.toLocaleString()} د.ع من إجمالي ${total.toLocaleString()} د.ع؟`, function() {
          proceedWithPayment(id, "جزئي", paid);
        });
      } else {
        showToast("⚠️ المبلغ يجب أن يكون أكبر من صفر", "warning");
      }
    })
    .catch(error => {
      showToast("❌ حدث خطأ في تحميل بيانات الطلب", "error");
      console.error("Error fetching order details:", error);
    });
  
  function proceedWithPayment(orderId, paymentStatus, paidAmount = 0) {
    showLoading();
    fetch("/orders/payment", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: orderId, payment: paymentStatus, paid_amount: paidAmount})
    })
      .then(r => {
        if (!r.ok) throw new Error("Network response was not ok");
        return r.json();
      })
      .then(res => {
        hideLoading();
        if (res.success) {
          showToast(`✅ تم ${paymentStatus === "مسدد" ? "تسديد" : "تسديد جزئي"} الطلب بنجاح`, "success");
          setTimeout(() => location.reload(), 1000);
        } else {
          showToast(res.error || "❌ حدث خطأ أثناء التسديد", "error");
        }
      })
      .catch(error => {
        hideLoading();
        showToast("❌ حدث خطأ أثناء التسديد: " + error.message, "error");
        console.error("Payment error:", error);
      });
  }
}

// Make payPartial globally available
window.payPartial = payPartial;

// ==================== تعديل الطلب ====================
function editOrder(id) {
  if (!id) {
    showToast("⚠️ رقم الطلب غير صحيح", "warning");
    return;
  }
  
  showConfirm("⚠️ هل تريد تعديل هذا الطلب؟\n\nسيتم نقلك إلى صفحة POS لتعديل الطلب.", function() {
    // الانتقال إلى POS مع معرف الطلب
    window.location.href = `/pos?edit_order=${id}`;
  });
}

// Make editOrder globally available
window.editOrder = editOrder;

// ==================== إرسال واتساب لطلب واحد ====================
function sendWhatsAppSingle(id) {
  if (!id) {
    showToast("⚠️ رقم الطلب غير صحيح", "warning");
    return;
  }
  
  // جلب بيانات الطلب
  fetch('/orders/get-selected-orders', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ids: [id]})
  })
    .then(r => r.json())
    .then(data => {
      if (data.success && data.orders && data.orders.length > 0) {
        const order = data.orders[0];
        sendWhatsAppMessage(order, 1, 1);
      } else {
        showToast('❌ ' + (data.error || 'حدث خطأ أثناء جلب بيانات الطلب'), 'error');
      }
    })
    .catch(error => {
      console.error('Error:', error);
      showToast('❌ حدث خطأ أثناء جلب بيانات الطلب', 'error');
    });
}

// Make sendWhatsAppSingle globally available
window.sendWhatsAppSingle = sendWhatsAppSingle;

function cancelOrder(id) {
  if (typeof showConfirm !== 'function') {
    console.error('showConfirm not available');
    return;
  }
  
  showConfirm("⚠️ هل أنت متأكد من إلغاء هذا الطلب؟\n\nملاحظة: سيتم إرجاع الكميات للمخزون", function() {
    proceedWithCancel();
  });
  
  function proceedWithCancel() {
    if (typeof showLoading === 'function') showLoading();
    fetch("/orders/cancel/" + id)
      .then(r => {
        if (!r.ok) throw new Error("Network response was not ok");
        return r.json();
      })
      .then(res => {
        if (typeof hideLoading === 'function') hideLoading();
        if (res.success) {
          if (typeof showToast === 'function') {
            showToast("✅ تم إلغاء الطلب وإرجاع الكميات للمخزون بنجاح", "success");
          }
          setTimeout(() => location.reload(), 1000);
        } else {
          if (typeof showToast === 'function') {
            showToast(res.error || "❌ حدث خطأ أثناء الإلغاء", "error");
          }
        }
      })
      .catch(error => {
        if (typeof hideLoading === 'function') hideLoading();
        console.error(error);
        if (typeof showToast === 'function') {
          showToast("❌ حدث خطأ أثناء الإلغاء: " + error.message, "error");
        }
      });
  }
}
window.cancelOrder = cancelOrder;

function markAsReturned(id) {
  if (!id) {
    showToast("⚠️ رقم الطلب غير صحيح", "warning");
    return;
  }
  
  showConfirm("⚠️ هل أنت متأكد من تحديد هذا الطلب كمرتجع؟", function() {
    proceedWithReturn();
  });
  
  function proceedWithReturn() {
    showLoading();
    fetch("/orders/payment", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: id, payment: "مرتجع"})
    })
      .then(r => {
        if (!r.ok) throw new Error("Network response was not ok");
        return r.json();
      })
      .then(res => {
        hideLoading();
        if (res.success) {
          showToast("✅ تم تحديد الطلب كمرتجع", "success");
          setTimeout(() => location.reload(), 1000);
        } else {
          showToast("❌ حدث خطأ", "error");
        }
      })
      .catch(error => {
        hideLoading();
        showToast("❌ حدث خطأ: " + error.message, "error");
        console.error("Mark as returned error:", error);
      });
  }
}

// Make markAsReturned globally available
window.markAsReturned = markAsReturned;

// ==================== إجراءات جماعية ====================
function applyStatus() {
  const status = document.getElementById("bulkStatus").value;
  const selected = selectedIds();
  
  if (selected.length === 0) {
    showToast("⚠️ الرجاء تحديد طلبات لتطبيق الحالة", "warning");
    return;
  }
  
  showConfirm(`⚠️ هل أنت متأكد من تغيير حالة ${selected.length} طلب إلى "${status}"؟`, function() {
    proceedWithStatus();
  });
  
  function proceedWithStatus() {
    showLoading();
    Promise.all(
      selected.map(id => 
        fetch("/orders/update", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({id: id, status: status})
        })
      )
    )
      .then(() => {
        hideLoading();
        showToast(`✅ تم تحديث ${selected.length} طلب بنجاح`, "success");
        setTimeout(() => location.reload(), 1000);
      })
      .catch(error => {
        hideLoading();
        showToast("❌ حدث خطأ أثناء التحديث", "error");
        console.error(error);
      });
  }
}

// Make applyStatus globally available
window.applyStatus = applyStatus;

function applyShipping() {
  const shipping = document.getElementById("bulkShipping").value;
  const selected = selectedIds();
  
  if (selected.length === 0) {
    showToast("⚠️ الرجاء تحديد طلبات لتطبيق شركة النقل", "warning");
    return;
  }
  
  if (!shipping) {
    showToast("⚠️ الرجاء اختيار شركة النقل أو 'لا أحد'", "warning");
    return;
  }
  
  const shippingValue = shipping === "none" ? null : shipping;
  const confirmMessage = shippingValue === null 
    ? `⚠️ هل أنت متأكد من إلغاء شركة النقل من ${selected.length} طلب؟`
    : `⚠️ هل أنت متأكد من تغيير شركة النقل لـ ${selected.length} طلب؟`;
  
  showConfirm(confirmMessage, function() {
    proceedWithShipping();
  });
  
  function proceedWithShipping() {
    showLoading();
    Promise.all(
      selected.map(id => 
        fetch("/orders/update-shipping", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({order_id: id, shipping_id: shippingValue})
        })
      )
    )
    .then(() => {
      hideLoading();
      const message = shippingValue === null 
        ? `✅ تم إلغاء شركة النقل من ${selected.length} طلب بنجاح`
        : `✅ تم تحديث ${selected.length} طلب بنجاح`;
      showToast(message, "success");
      setTimeout(() => location.reload(), 1000);
    })
    .catch(error => {
      hideLoading();
      showToast("❌ حدث خطأ أثناء التحديث", "error");
      console.error(error);
    });
  }
}

// Make applyShipping globally available
window.applyShipping = applyShipping;

function applyDeliveryAgent() {
  const agentSelect = document.getElementById("bulkDeliveryAgent");
  if (!agentSelect) {
    console.error('bulkDeliveryAgent element not found');
    return;
  }
  const selected = selectedIds();
  
  if (selected.length === 0) {
    if (typeof showToast === 'function') {
      showToast("⚠️ الرجاء تحديد طلبات لتطبيق مندوب التوصيل", "warning");
    }
    return;
  }
  
  const agentId = agentSelect.value;
  if (!agentId) {
    if (typeof showToast === 'function') {
      showToast("⚠️ الرجاء اختيار مندوب التوصيل أو 'لا أحد'", "warning");
    }
    return;
  }
  
  const agentValue = agentId === "none" ? null : agentId;
  const confirmMessage = agentValue === null
    ? `⚠️ هل أنت متأكد من إلغاء مندوب التوصيل لـ ${selected.length} طلب؟`
    : `⚠️ هل أنت متأكد من تغيير مندوب التوصيل لـ ${selected.length} طلب؟`;
  
  if (typeof showConfirm !== 'function') {
    console.error('showConfirm not available');
    return;
  }
  
  showConfirm(confirmMessage, function() {
    proceedWithDeliveryAgent();
  });
  
  function proceedWithDeliveryAgent() {
    if (typeof showLoading === 'function') showLoading();
    Promise.all(
      selected.map(id => 
        fetch("/orders/update-delivery-agent", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({order_id: id, agent_id: agentValue})
        })
      )
    )
      .then(() => {
        if (typeof hideLoading === 'function') hideLoading();
        const message = agentValue === null
          ? `✅ تم إلغاء مندوب التوصيل من ${selected.length} طلب بنجاح`
          : `✅ تم تحديث مندوب التوصيل لـ ${selected.length} طلب بنجاح`;
        if (typeof showToast === 'function') {
          showToast(message, "success");
        }
        setTimeout(() => location.reload(), 1000);
      })
      .catch(error => {
        if (typeof hideLoading === 'function') hideLoading();
        console.error(error);
        if (typeof showToast === 'function') {
          showToast("❌ حدث خطأ أثناء التحديث", "error");
        }
      });
  }
}
window.applyDeliveryAgent = applyDeliveryAgent;

// ==================== عرض التفاصيل ====================
function showDetails(id) {
  if (!id) {
    showToast("⚠️ رقم الطلب غير صحيح", "warning");
    return;
  }
  
  fetch("/orders/details/" + id)
    .then(r => {
      if (!r.ok) throw new Error("Network response was not ok");
      return r.json();
    })
    .then(d => {
      if (d && d.order) {
        currentOrderData = d;
        currentOrderId = id;
        
        const orderStatus = d.order.status || '';
        const paymentStatus = d.order.payment || d.order.payment_status || '';
        const isReturned = orderStatus === "راجع" || paymentStatus === "مرتجع";
        const canEdit = orderStatus !== "تم التوصيل" && orderStatus !== "مسدد" && orderStatus !== "راجع" && orderStatus !== "ملغي";
        
        const detailsDiv = document.getElementById("details");
        detailsDiv.innerHTML = `
          <div style="margin-bottom: 32px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 28px; padding-bottom: 20px; border-bottom: 2px solid rgba(59, 130, 246, 0.2);">
              <h2 style="margin: 0; font-size: 28px; font-weight: 700; color: #e2e8f0; display: flex; align-items: center; gap: 12px;">
                <span style="background: linear-gradient(135deg, #3b82f6, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">📋</span>
                تفاصيل الطلب #${d.order.id}
              </h2>
            </div>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 32px;">
              <div style="background: rgba(59, 130, 246, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #3b82f6;">
                <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">الزبون</div>
                <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.customer || d.order.customer_name || "—"}</div>
              </div>
              
              <div style="background: rgba(59, 130, 246, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #3b82f6;">
                <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">الهاتف</div>
                <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.phone || "—"}</div>
              </div>
              
              <div style="background: rgba(16, 185, 129, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #10b981;">
                <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">المحافظة</div>
                <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.city || "—"}</div>
              </div>
              
              <div style="background: rgba(16, 185, 129, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #10b981;">
                <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">العنوان</div>
                <div style="font-size: 16px; font-weight: 600; color: #e2e8f0; word-break: break-word;">${d.order.address || "—"}</div>
              </div>
              
              <div style="background: rgba(245, 158, 11, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #f59e0b;">
                <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">الموظف</div>
                <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.employee || d.order.employee_name || "—"}</div>
              </div>
              
              <div style="background: rgba(245, 158, 11, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #f59e0b;">
                <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">حالة الطلب</div>
                <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${orderStatus}</div>
              </div>
              
              <div style="background: rgba(139, 92, 246, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #8b5cf6;">
                <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">حالة الدفع</div>
                <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${paymentStatus || "غير مسدد"}</div>
              </div>
              
              <div style="background: rgba(139, 92, 246, 0.08); padding: 16px; border-radius: 12px; border-left: 4px solid #8b5cf6;">
                <div style="font-size: 12px; color: rgba(226, 232, 240, 0.6); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">شركة النقل</div>
                <div style="font-size: 16px; font-weight: 600; color: #e2e8f0;">${d.order.shipping || d.order.shipping_company || "—"}</div>
              </div>
            </div>
            
            <div style="margin-bottom: 24px;">
              <h3 style="margin-bottom: 16px; font-size: 20px; font-weight: 700; color: #e2e8f0; display: flex; align-items: center; gap: 8px;">
                <span>📦</span>
                المنتجات
              </h3>
              <div style="background: rgba(15, 23, 42, 0.5); border-radius: 16px; overflow: hidden; border: 1px solid rgba(59, 130, 246, 0.2);">
                <table style="width: 100%; border-collapse: collapse;">
                  <thead>
                    <tr style="background: linear-gradient(135deg, rgba(59, 130, 246, 0.15), rgba(59, 130, 246, 0.1));">
                      <th style="padding: 16px; text-align: right; font-weight: 600; color: #e2e8f0; font-size: 14px;">اسم المنتج</th>
                      <th style="padding: 16px; text-align: center; font-weight: 600; color: #e2e8f0; font-size: 14px; width: 100px;">الكمية</th>
                      <th style="padding: 16px; text-align: center; font-weight: 600; color: #e2e8f0; font-size: 14px; width: 120px;">السعر</th>
                      <th style="padding: 16px; text-align: center; font-weight: 600; color: #e2e8f0; font-size: 14px; width: 140px;">المجموع</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${d.items && d.items.length > 0 ? d.items.map((i, idx) => `
                      <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05); background: ${idx % 2 === 0 ? 'rgba(255, 255, 255, 0.02)' : 'transparent'};">
                        <td style="padding: 16px; color: #e2e8f0; font-weight: 500;">${i.name || i.product_name || "—"}</td>
                        <td style="padding: 16px; text-align: center; color: #e2e8f0;">${i.qty || i.quantity || 0}</td>
                        <td style="padding: 16px; text-align: center; color: #e2e8f0;">${(i.price || 0).toLocaleString()} د.ع</td>
                        <td style="padding: 16px; text-align: center; color: #10b981; font-weight: 600;">${(i.total || 0).toLocaleString()} د.ع</td>
                      </tr>
                    `).join('') : '<tr><td colspan="4" style="padding: 24px; text-align: center; color: rgba(226, 232, 240, 0.5);">لا توجد منتجات</td></tr>'}
                  </tbody>
                  <tfoot>
                    <tr style="background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(59, 130, 246, 0.15)); border-top: 2px solid rgba(59, 130, 246, 0.3);">
                      <td colspan="3" style="padding: 20px; text-align: right; font-size: 18px; font-weight: 700; color: #e2e8f0;">الإجمالي:</td>
                      <td style="padding: 20px; text-align: center; font-size: 20px; font-weight: 700; color: #10b981;">${(d.order.total || 0).toLocaleString()} د.ع</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          </div>
          
          <div style="display: flex; flex-wrap: wrap; gap: 12px; padding: 24px; background: rgba(15, 23, 42, 0.5); border-radius: 16px; border: 1px solid rgba(59, 130, 246, 0.2); margin-top: 32px;">
            <button class="btn btn-primary" onclick="window.printSingleInvoice && window.printSingleInvoice(${id})" style="flex: 1; min-width: 150px;">
              🖨️ طباعة الفاتورة
            </button>
            ${canEdit ? `
            <button class="btn btn-success" onclick="window.payPartial && window.payPartial(${id})" style="flex: 1; min-width: 150px;">
              💵 تسديد جزئي
            </button>
            <button class="btn btn-info" onclick="window.sendWhatsAppSingle && window.sendWhatsAppSingle(${id})" style="flex: 1; min-width: 150px;">
              💬 إرسال واتساب
            </button>
            <button class="btn btn-warning" onclick="window.editOrder && window.editOrder(${id})" style="flex: 1; min-width: 150px;">
              ✏️ تعديل الطلب
            </button>
            ` : ''}
            ${isReturned ? `
            <button class="btn btn-warning" onclick="window.markAsReturned && window.markAsReturned(${id})" style="flex: 1; min-width: 150px;">
              ↩️ تحديد كمرتجع
            </button>
            ` : ''}
          </div>
        `;
        
        const modal = document.getElementById("modal");
        if (modal) {
          modal.style.display = "flex";
        } else {
          console.error("Modal element not found");
          showToast("❌ حدث خطأ في عرض التفاصيل", "error");
        }
      } else {
        showToast("❌ لم يتم العثور على بيانات الطلب", "error");
      }
    })
    .catch(error => {
      showToast("❌ حدث خطأ في تحميل البيانات", "error");
      console.error("Error fetching order details:", error);
    });
}

// Make showDetails globally available
window.showDetails = showDetails;

function closeModal(e) {
  if (e && e.target.id === "modal") {
    document.getElementById("modal").style.display = "none";
  } else if (!e) {
    document.getElementById("modal").style.display = "none";
  }
}

// ==================== الطباعة ====================
function printInvoice() {
  try {
    if (!currentOrderData) {
      showToast("⚠️ الرجاء عرض تفاصيل الطلب أولاً", "warning");
      return;
    }
    
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      showToast("❌ تم منع النافذة المنبثقة. يرجى السماح بالنوافذ المنبثقة لهذا الموقع.", "error");
      return;
    }
  printWindow.document.write(`
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
      <title>طباعة الطلب #${currentOrderData.order.id}</title>
      <style>
        body { font-family: Arial, sans-serif; direction: rtl; padding: 20px; }
        h1 { text-align: center; color: #000; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { border: 1px solid #000; padding: 8px; text-align: center; }
        th { background: #f0f0f0; }
      </style>
    </head>
    <body>
      <h1>فاتورة الطلب #${currentOrderData.order.id}</h1>
      <div>
        <p><b>الزبون:</b> ${currentOrderData.order.customer}</p>
        <p><b>الهاتف:</b> ${currentOrderData.order.phone}</p>
        <p><b>العنوان:</b> ${currentOrderData.order.city} - ${currentOrderData.order.address}</p>
        <p><b>الموظف:</b> ${currentOrderData.order.employee}</p>
        <p><b>الحالة:</b> ${currentOrderData.order.status}</p>
        <p><b>الدفع:</b> ${currentOrderData.order.payment}</p>
      </div>
      <table>
        <thead>
          <tr>
            <th>المنتج</th>
            <th>الكمية</th>
            <th>السعر</th>
            <th>المجموع</th>
          </tr>
        </thead>
        <tbody>
          ${currentOrderData.items.map(i => `
            <tr>
              <td>${i.name}</td>
              <td>${i.qty}</td>
              <td>${i.price} د.ع</td>
              <td>${i.total} د.ع</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </body>
    </html>
  `);
    printWindow.document.close();
    setTimeout(() => {
      printWindow.print();
    }, 250);
  } catch (error) {
    console.error("Print error:", error);
    showToast("❌ حدث خطأ أثناء الطباعة", "error");
  }
}

// Make printInvoice globally available immediately
window.printInvoice = printInvoice;

// ==================== Print Selected Invoices ====================
// تم نقل التعريف إلى أعلى الملف في النطاق العام
// function printSelectedInvoices موجودة أعلاه

function printSingleInvoice(id) {
  try {
    if (!id) {
      showToast("⚠️ رقم الطلب غير صحيح", "warning");
      return;
    }
    
    const url = `/orders/invoice/${id}`;
    const printWindow = window.open(url, '_blank');
    
    if (!printWindow || printWindow.closed || typeof printWindow.closed === 'undefined') {
      showToast("❌ تم منع النافذة المنبثقة. يرجى السماح بالنوافذ المنبثقة لهذا الموقع.", "error");
      // محاولة فتح في نفس النافذة كبديل
      setTimeout(() => {
        window.location.href = url;
      }, 1000);
      return;
    }
    
    // التركيز على النافذة بعد فتحها
    setTimeout(() => {
      if (printWindow && !printWindow.closed) {
        printWindow.focus();
      }
    }, 500);
  } catch (error) {
    console.error("Print error:", error);
    showToast("❌ حدث خطأ أثناء الطباعة", "error");
  }
}

// Make printSingleInvoice globally available immediately
window.printSingleInvoice = printSingleInvoice;

// Send WhatsApp To Selected - التعريف الكامل
function sendWhatsAppToSelected() {
  if (typeof selectedIds !== 'function') {
    console.error('selectedIds not available');
    return;
  }
  const ids = selectedIds();
  if (ids.length === 0) {
    if (typeof showToast === 'function') {
      showToast('⚠️ يرجى تحديد طلبات لإرسال الرسائل', 'warning');
    }
    return;
  }
  
  if (typeof showConfirm !== 'function') {
    console.error('showConfirm not available');
    return;
  }
  
  showConfirm(`هل تريد إرسال رسالة واتساب إلى ${ids.length} طلب؟\n\nسيتم فتح ${ids.length} محادثة واتساب على حدة`, function() {
    proceedWithWhatsApp();
  });
  
  function proceedWithWhatsApp() {
    if (typeof showLoading === 'function') showLoading();
    fetch('/orders/get-selected-orders', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ids: ids})
    })
      .then(r => r.json())
      .then(data => {
        if (typeof hideLoading === 'function') hideLoading();
        if (data.success && data.orders) {
          if (typeof showToast === 'function') {
            showToast(`🔄 جاري فتح ${data.orders.length} محادثة واتساب...`, 'info');
          }
          
          let openedCount = 0;
          data.orders.forEach((order, index) => {
            setTimeout(() => {
              if (typeof sendWhatsAppMessage === 'function') {
                sendWhatsAppMessage(order, index + 1, data.orders.length);
              }
              openedCount++;
              
              if (openedCount === data.orders.length) {
                setTimeout(() => {
                  if (typeof showToast === 'function') {
                    showToast(`✅ تم فتح ${data.orders.length} محادثة واتساب تلقائياً`, 'success');
                  }
                }, 1000);
              }
            }, index * 4000);
          });
        } else {
          if (typeof showToast === 'function') {
            showToast('❌ ' + (data.error || 'حدث خطأ أثناء جلب بيانات الطلبات'), 'error');
          }
        }
      })
      .catch(error => {
        if (typeof hideLoading === 'function') hideLoading();
        console.error('Error:', error);
        if (typeof showToast === 'function') {
          showToast('❌ حدث خطأ أثناء جلب بيانات الطلبات', 'error');
        }
      });
  }
}
// تحديث التعريف في window
window.sendWhatsAppToSelected = sendWhatsAppToSelected;

function sendWhatsAppMessage(order, currentIndex, totalCount) {
  const customerPhone = order.customer_phone || '';
  if (!customerPhone) {
    console.warn('No phone number for order:', order.id);
    showToast(`⚠️ لا يوجد رقم هاتف للطلب #${order.id}`, 'warning');
    return;
  }
  
  // تنظيف رقم الهاتف (إزالة جميع الأحرف غير الرقمية)
  let cleanPhone = customerPhone.replace(/[^0-9]/g, '');
  
  // التحقق من أن الرقم ليس فارغاً
  if (!cleanPhone || cleanPhone.length < 8) {
    showToast(`⚠️ رقم الهاتف غير صحيح للطلب #${order.id}`, 'warning');
    return;
  }
  
  // معالجة رقم الهاتف
  // إذا كان الرقم يبدأ بـ 0، استبدله بـ 964
  if (cleanPhone.startsWith('0')) {
    cleanPhone = '964' + cleanPhone.substring(1);
  } 
  // إذا كان الرقم يبدأ بـ 964، اتركه كما هو
  else if (!cleanPhone.startsWith('964')) {
    // إذا كان الرقم أقل من 9 أرقام، أضف 964
    if (cleanPhone.length < 9) {
      cleanPhone = '964' + cleanPhone;
    } else {
      // إذا كان الرقم 9 أرقام أو أكثر، أضف 964 في البداية
      cleanPhone = '964' + cleanPhone;
    }
  }
  
  // التحقق النهائي من صحة الرقم (يجب أن يكون 12 رقم على الأقل مع 964)
  if (cleanPhone.length < 12 || !cleanPhone.startsWith('964')) {
    showToast(`⚠️ رقم الهاتف غير صحيح للطلب #${order.id}: ${cleanPhone}`, 'warning');
    return;
  }
  
  // نص الرسالة الجديد
  const customerName = order.customer_name || 'عميلنا العزيز';
  const orderId = order.id || '';
  const totalAmount = order.total_amount || 0;
  const formattedAmount = totalAmount.toLocaleString('ar-IQ', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  
  // إنشاء رابط فريد للفاتورة (يمكن استخدام hash أو UUID)
  const invoiceHash = order.invoice_hash || generateInvoiceHash(orderId);
  const invoiceUrl = window.location.origin + '/orders/invoice/' + orderId;
  
  const message = 'مرحبًا ' + customerName + '، تم استلام طلبك بنجاح ورقمه هو ' + orderId + '. المبلغ الكلي: ' + formattedAmount + ' دينار. لمتابعة حالة الطلب أو مشاهدة تفاصيله: ' + invoiceUrl + ' شكراً لاختيارك شركة سوبر ماكس!';
  
  // إنشاء رابط واتساب مع رقم فريد تماماً لكل نافذة
  const uniqueId = 'whatsapp_' + order.id + '_' + cleanPhone + '_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
  const whatsappUrl = 'https://wa.me/' + cleanPhone + '?text=' + encodeURIComponent(message);
  
  // فتح نافذة جديدة مع اسم فريد تماماً لكل نافذة
  // استخدام uniqueId كاسم النافذة لضمان عدم إعادة الاستخدام
  try {
    // محاولة فتح النافذة مع خصائص محددة
    const windowFeatures = 'width=800,height=600,left=' + (100 + currentIndex * 50) + ',top=' + (100 + currentIndex * 50) + ',scrollbars=yes,resizable=yes,toolbar=no,menubar=no';
    const newWindow = window.open(whatsappUrl, uniqueId, windowFeatures);
    
    // التأكد من فتح النافذة
    if (!newWindow || newWindow.closed || typeof newWindow.closed === 'undefined') {
      console.warn('Popup blocked for order:', order.id);
      // إذا تم حظر النافذة المنبثقة، افتح في تبويب جديد مع اسم فريد
      const fallbackWindow = window.open(whatsappUrl, uniqueId + '_tab', '_blank');
      if (!fallbackWindow) {
            showToast('⚠️ تم حظر فتح النوافذ المنبثقة. يرجى السماح بالنوافذ المنبثقة للموقع.', 'warning');
      }
    } else {
      // التركيز على النافذة والانتظار قليلاً
      setTimeout(() => {
        newWindow.focus();
      }, 100);
    }
  } catch (e) {
    console.error('Error opening window:', e);
    // محاولة فتح في تبويب جديد كبديل مع اسم فريد
    window.open(whatsappUrl, uniqueId + '_fallback', '_blank');
  }
  
  console.log(`Opening WhatsApp window ${currentIndex}/${totalCount} for order ${order.id} - Phone: ${cleanPhone} - Window ID: ${uniqueId}`);
}

// دالة لإنشاء hash للفاتورة
function generateInvoiceHash(orderId) {
  // استخدام orderId + timestamp لإنشاء hash بسيط
  const str = orderId + '_' + Date.now();
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32bit integer
  }
  return Math.abs(hash).toString(16);
}

function createShippingReport() {
  const selected = selectedIds();
  
  if (selected.length === 0) {
    if (typeof showToast === 'function') {
      showToast("⚠️ الرجاء تحديد طلبات لإنشاء الكشف", "warning");
    }
    return;
  }
  
  const shippingSelect = document.getElementById("reportShippingCompany");
  if (!shippingSelect) {
    console.error('reportShippingCompany element not found');
    return;
  }
  const shippingCompanyId = shippingSelect.value;
  const shippingCompanyName = shippingSelect.options[shippingSelect.selectedIndex]?.getAttribute('data-name') || '';
  
  if (!shippingCompanyId) {
    if (typeof showToast === 'function') {
      showToast("⚠️ الرجاء اختيار شركة النقل", "warning");
    }
    shippingSelect.focus();
    return;
  }
  
  if (typeof showConfirm !== 'function') {
    console.error('showConfirm not available');
    return;
  }
  
  showConfirm(`هل تريد إنشاء كشف لشركة النقل "${shippingCompanyName}" يحتوي على ${selected.length} طلب؟\n\nسيتم حفظ الكشف في الأرشيف وفتحه للطباعة.`, function() {
    proceedWithCreateShippingReport();
  });
  
  function proceedWithCreateShippingReport() {
    if (typeof showLoading === 'function') showLoading();
    
    // التحقق من وجود مندوب في الطلبات المحددة
    const selectedOrders = allOrders.filter(order => selected.includes(order.id.toString()));
    const agentIds = new Set();
    selectedOrders.forEach(order => {
      if (order.agentId) {
        agentIds.add(order.agentId);
      }
    });
    
    fetch("/orders/create-shipping-report", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        order_ids: selected,
        shipping_company_id: parseInt(shippingCompanyId)
      })
    })
      .then(r => {
        if (!r.ok) {
          return r.json().then(err => {
            throw new Error(err.error || "خطأ في الاستجابة من الخادم");
          });
        }
        return r.json();
      })
      .then(data => {
        if (typeof hideLoading === 'function') hideLoading();
        if (data.success && data.report_id) {
          if (typeof showToast === 'function') {
            showToast(`✅ تم إنشاء الكشف #${data.report_number} بنجاح`, "success");
          }
          
          if (data.agent_id) {
            if (typeof showToast === 'function') {
              showToast(`🚚 تم إنشاء الكشف بنجاح - سيظهر الكشف تلقائياً في صفحة المندوب`, "success");
            }
          } else {
            setTimeout(() => {
              const reportUrl = `/delivery/report/${data.report_id}`;
              console.log("Opening report URL:", reportUrl);
              const newWindow = window.open(reportUrl, '_blank');
              if (!newWindow || newWindow.closed || typeof newWindow.closed === 'undefined') {
                if (typeof showToast === 'function') {
                  showToast("⚠️ تم حظر النافذة المنبثقة. يرجى السماح بالنوافذ المنبثقة.", "warning");
                }
                setTimeout(() => {
                  window.location.href = reportUrl;
                }, 1000);
              } else {
                setTimeout(() => {
                  if (newWindow && !newWindow.closed) {
                    newWindow.focus();
                  }
                }, 500);
              }
            }, 1000);
          }
        } else {
          if (typeof showToast === 'function') {
            showToast("❌ " + (data.error || "حدث خطأ أثناء إنشاء الكشف"), "error");
          }
          console.error("Report creation response:", data);
        }
      })
      .catch(error => {
        if (typeof hideLoading === 'function') hideLoading();
        console.error("Error creating report:", error);
        if (typeof showToast === 'function') {
          showToast("❌ حدث خطأ أثناء إنشاء الكشف: " + error.message, "error");
        }
      });
  }
}
window.createShippingReport = createShippingReport;

// ==================== Print Selected Report ====================
// تم نقل التعريف إلى أعلى الملف في النطاق العام
// function printSelectedReport موجودة أعلاه

// تم نقل printReportWindow إلى صفحة HTML منفصلة: templates/print_report.html
// هذا الكود القديم تم حذفه لأنه كان يسبب خلل في الصفحة

// ==================== إجراءات أخرى ====================
// Save Report
function saveReport() {
  if (typeof selectedIds !== 'function') {
    console.error('selectedIds not available');
    return;
  }
  const selected = selectedIds();
  
  if (selected.length === 0) {
    if (typeof showToast === 'function') {
      showToast("⚠️ الرجاء تحديد طلبات لحفظ الكشف", "warning");
    } else {
      alert("⚠️ الرجاء تحديد طلبات لحفظ الكشف");
    }
    return;
  }
  
  const notes = prompt("ملاحظات إضافية (اختياري):", "");
  if (notes === null) return;
  
  fetch("/orders/save-report", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ids: selected, notes: notes || ""})
  })
    .then(r => r.json())
    .then(data => {
      if (typeof showToast === 'function') {
        if (data.success) {
          showToast(`✅ تم حفظ الكشف برقم: ${data.report_number}`, "success");
        } else {
          showToast(data.error || "❌ حدث خطأ أثناء الحفظ", "error");
        }
      }
    })
    .catch(error => {
      console.error("Save report error:", error);
      if (typeof showToast === 'function') {
        showToast("❌ حدث خطأ أثناء الحفظ: " + error.message, "error");
      }
    });
}
window.saveReport = saveReport;

function exportExcel() {
  window.location.href = "/orders/export";
}

// Print Agent Report - التعريف الكامل
function printAgentReport() {
  try {
    const agentSelect = document.getElementById("printAgentReport");
    if (!agentSelect) {
      console.error('printAgentReport element not found');
      return;
    }
    const agentId = agentSelect.value;
    
    if (!agentId) {
      if (typeof showToast === 'function') {
        showToast("⚠️ الرجاء اختيار مندوب", "warning");
      }
      return;
    }
  
    const agentName = agentSelect.options[agentSelect.selectedIndex]?.text || "";
    const tableRows = document.querySelectorAll("#ordersTable tbody tr");
    const agentOrderIds = [];
    
    tableRows.forEach(row => {
      const cells = row.querySelectorAll("td");
      if (cells.length > 0) {
        const rowAgentId = row.getAttribute("data-agent-id") || 
                          cells[14]?.getAttribute("data-agent-id") || 
                          "";
        
        if (rowAgentId && rowAgentId.toString() === agentId.toString()) {
          const orderIdCell = cells[1];
          if (orderIdCell) {
            const orderId = orderIdCell.textContent.trim();
            if (orderId) {
              agentOrderIds.push(orderId);
            }
          }
        }
      }
    });
    
    if (agentOrderIds.length === 0) {
      if (typeof showToast === 'function') {
        showToast("⚠️ لا توجد طلبات لهذا المندوب في الجدول المرئي", "warning");
      }
      return;
    }
    
    const orderIds = agentOrderIds;
    
    if (typeof showConfirm !== 'function') {
      console.error('showConfirm not available');
      return;
    }
    
    showConfirm(`هل تريد إنشاء كشف للمندوب "${agentName}" يحتوي على ${orderIds.length} طلب؟\n\nسيتم حفظ الكشف في صفحة المندوب وفتحه للطباعة.`, function() {
      proceedWithPrintAgentReport();
    });
    
    function proceedWithPrintAgentReport() {
      if (typeof showLoading === 'function') showLoading();
      
      fetch("/orders/create-agent-report", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          order_ids: orderIds,
          agent_id: agentId
        })
      })
        .then(r => {
          if (!r.ok) {
            return r.json().then(err => {
              throw new Error(err.error || "خطأ في الاستجابة من الخادم");
            });
          }
          return r.json();
        })
        .then(data => {
          if (typeof hideLoading === 'function') hideLoading();
          if (data.success && data.report_id) {
            if (typeof showToast === 'function') {
              showToast(`✅ تم إنشاء الكشف #${data.report_number} بنجاح - سيظهر الكشف تلقائياً في صفحة المندوب`, "success");
            }
            
            setTimeout(() => {
              const url = `/orders/print-report-page?ids=${orderIds.join(",")}&agent_id=${agentId}`;
              const printWindow = window.open(url, "_blank");
              if (!printWindow || printWindow.closed || typeof printWindow.closed === 'undefined') {
                if (typeof showToast === 'function') {
                  showToast("❌ تم منع النافذة المنبثقة. يرجى السماح بالنوافذ المنبثقة لهذا الموقع.", "error");
                }
                setTimeout(() => {
                  window.location.href = url;
                }, 1000);
              } else {
                setTimeout(() => {
                  if (printWindow && !printWindow.closed) {
                    printWindow.focus();
                  }
                }, 500);
              }
            }, 500);
          } else {
            if (typeof showToast === 'function') {
              showToast("❌ " + (data.error || "حدث خطأ أثناء إنشاء الكشف"), "error");
            }
            console.error("Report creation response:", data);
          }
        })
        .catch(error => {
          if (typeof hideLoading === 'function') hideLoading();
          console.error("Error creating report:", error);
          if (typeof showToast === 'function') {
            showToast("❌ حدث خطأ أثناء إنشاء الكشف: " + error.message, "error");
          }
        });
    }
  } catch (error) {
    console.error("Print agent report error:", error);
    if (typeof showToast === 'function') {
      showToast("❌ حدث خطأ أثناء طباعة كشف المندوب", "error");
    }
  }
}
window.printAgentReport = printAgentReport;

// ==================== تهيئة الصفحة ====================
document.addEventListener("DOMContentLoaded", function() {
  // تطبيق الفلاتر من URL قبل تهيئة الطلبات
  const urlParams = new URLSearchParams(window.location.search);
  
  // تطبيق فلتر البحث
  const searchParam = urlParams.get('search');
  if (searchParam && document.getElementById("searchInput")) {
    document.getElementById("searchInput").value = searchParam;
  }
  
  // تطبيق فلتر المحافظة
  const cityParam = urlParams.get('city');
  if (cityParam && document.getElementById("filterCity")) {
    document.getElementById("filterCity").value = cityParam;
  }
  
  // تطبيق فلتر الحالة
  const statusParam = urlParams.get('status');
  if (statusParam && document.getElementById("filterStatus")) {
    document.getElementById("filterStatus").value = statusParam;
  }
  
  // تطبيق فلتر حالة الدفع
  const paymentParam = urlParams.get('payment');
  if (paymentParam && document.getElementById("filterPayment")) {
    document.getElementById("filterPayment").value = paymentParam;
  }
  
  // تطبيق فلتر الموظف
  const employeeParam = urlParams.get('employee');
  if (employeeParam && document.getElementById("filterEmployee")) {
    document.getElementById("filterEmployee").value = employeeParam;
  }
  
  // تطبيق فلتر شركة النقل (البحث عن الاسم)
  const shippingParam = urlParams.get('shipping');
  if (shippingParam && document.getElementById("filterShipping")) {
    const shippingSelect = document.getElementById("filterShipping");
    // محاولة البحث عن القيمة المطابقة (قد يكون ID أو اسم)
    let found = false;
    for (let i = 0; i < shippingSelect.options.length; i++) {
      const option = shippingSelect.options[i];
      // إذا كانت القيمة أو النص يطابق
      if (option.value === shippingParam || option.textContent.trim() === shippingParam.trim()) {
        shippingSelect.value = option.value;
        found = true;
        break;
      }
    }
    // إذا لم يتم العثور على تطابق، قد يكون ID، نحتاج للبحث في الخادم
    // لكن في هذه الحالة سنتركه فارغاً لأن البيانات المحملة ستكون صحيحة
  }
  
  // تطبيق فلتر التاريخ المؤجل
  const scheduledDate = urlParams.get('scheduled_date');
  if (scheduledDate && document.getElementById("filterScheduledDate")) {
    document.getElementById("filterScheduledDate").value = scheduledDate;
  }
  
  // تهيئة Tabulator إذا كان متاحاً
  function initializeTable() {
    if (typeof Tabulator !== 'undefined') {
      console.log('Tabulator is available, initializing...');
      initTabulator();
    } else {
      console.log('Tabulator not available, using fallback...');
      // انتظار قليلاً ثم المحاولة مرة أخرى
      setTimeout(function() {
        if (typeof Tabulator !== 'undefined') {
          console.log('Tabulator loaded, initializing...');
          initTabulator();
        } else {
          console.log('Tabulator still not available, using old table...');
          initOrders();
        }
      }, 500);
    }
  }
  
  initializeTable();
  updatePrintDate();
  
  // إضافة مستمعي الأحداث
  document.getElementById("searchInput").addEventListener("keyup", applyFilters);
  document.getElementById("filterCity").addEventListener("change", applyFilters);
  document.getElementById("filterStatus").addEventListener("change", applyFilters);
  document.getElementById("filterPayment").addEventListener("change", applyFilters);
  document.getElementById("filterEmployee").addEventListener("change", applyFilters);
  document.getElementById("filterShipping").addEventListener("change", applyFilters);
  if (document.getElementById("filterDeliveryAgent")) {
    document.getElementById("filterDeliveryAgent").addEventListener("change", applyFilters);
  }
  if (document.getElementById("filterScheduledDate")) {
    document.getElementById("filterScheduledDate").addEventListener("change", applyFilters);
  }
  
  // Barcode Scanner Support - تبسيط وتحسين
  (function() {
    let barcodeBuffer = '';
    let barcodeTimeout = null;
    let lastKeyTime = 0;
    const BARCODE_TIMEOUT = 100; // ms بين المفاتيح
    const BARCODE_COMPLETE_TIMEOUT = 300; // ms لاعتبار الباركود مكتمل
    
    function resetBarcodeBuffer() {
      barcodeBuffer = '';
      if (barcodeTimeout) {
        clearTimeout(barcodeTimeout);
        barcodeTimeout = null;
      }
    }
    
    function processBarcode(barcode) {
      if (!barcode || barcode.length < 1) return;
      
      const trimmedBarcode = barcode.trim();
      console.log('Processing barcode:', trimmedBarcode);
      
      // البحث عن الفاتورة بالباركود المقرأ
      fetch(`/orders/search-by-barcode?barcode=${encodeURIComponent(trimmedBarcode)}`)
        .then(r => {
          if (!r.ok) throw new Error("Network response was not ok");
          return r.json();
        })
        .then(data => {
          if (data.success && data.invoice) {
            showBarcodeInputModal(data.invoice, trimmedBarcode);
          } else {
            // إذا لم تجد الفاتورة، جرب البحث برقم الفاتورة
            const invoiceId = parseInt(trimmedBarcode, 10);
            if (!isNaN(invoiceId) && invoiceId > 0) {
              fetch(`/orders/details/${invoiceId}`)
                .then(r => {
                  if (!r.ok) throw new Error("Network response was not ok");
                  return r.json();
                })
                .then(invoiceData => {
                  if (invoiceData && invoiceData.order) {
                    showBarcodeInputModal({
                      id: invoiceId,
                      customer_name: invoiceData.order.customer,
                      total: invoiceData.order.total
                    }, trimmedBarcode);
                  } else {
                    showToast('⚠️ لم يتم العثور على فاتورة برقم: ' + trimmedBarcode, 'warning');
                  }
                })
                .catch(() => {
                  showToast('⚠️ لم يتم العثور على فاتورة برقم: ' + trimmedBarcode, 'warning');
                });
            } else {
              showToast('⚠️ لم يتم العثور على فاتورة بهذا الباركود: ' + trimmedBarcode, 'warning');
            }
          }
        })
        .catch(() => {
          showToast('❌ حدث خطأ أثناء البحث عن الباركود', 'error');
        });
    }
    
    document.addEventListener('keydown', function(e) {
      // تجاهل إذا كان المستخدم يكتب في حقل input أو textarea
      const activeElement = document.activeElement;
      if (activeElement && (
          activeElement.tagName === 'INPUT' || 
          activeElement.tagName === 'TEXTAREA' ||
          activeElement.isContentEditable
        )) {
        resetBarcodeBuffer();
        return;
      }
      
      const currentTime = Date.now();
      const timeSinceLastKey = currentTime - lastKeyTime;
      
      // إذا مر أكثر من BARCODE_TIMEOUT منذ آخر مفتاح، ابدأ باركود جديد
      if (timeSinceLastKey > BARCODE_TIMEOUT && barcodeBuffer.length > 0) {
        resetBarcodeBuffer();
      }
      
      lastKeyTime = currentTime;
      
      // إذا كان المفتاح Enter، اعتبر أن الباركود اكتمل
      if (e.key === 'Enter') {
        e.preventDefault();
        if (barcodeBuffer.length > 0) {
          const barcode = barcodeBuffer;
          resetBarcodeBuffer();
          processBarcode(barcode);
        }
        return;
      }
      
      // إذا كان حرفاً أو رقماً، أضفه للباركود
      if (e.key.length === 1 && /[0-9a-zA-Z]/.test(e.key)) {
        barcodeBuffer += e.key;
        
        // إلغاء timeout السابق
        if (barcodeTimeout) {
          clearTimeout(barcodeTimeout);
        }
        
        // إذا لم يضغط Enter خلال BARCODE_COMPLETE_TIMEOUT، اعتبر أن الباركود اكتمل
        barcodeTimeout = setTimeout(function() {
          if (barcodeBuffer.length > 0) {
            const barcode = barcodeBuffer;
            resetBarcodeBuffer();
            processBarcode(barcode);
          }
        }, BARCODE_COMPLETE_TIMEOUT);
      }
    });
    
    // جعل handleBarcodeScan متاحاً عالمياً
    window.handleBarcodeScan = processBarcode;
  })();
  
  // جعل showBarcodeInputModal متاحاً عالمياً
  window.showBarcodeInputModal = function(invoice, scannedBarcode) {
    // إزالة أي نافذة منبثقة موجودة مسبقاً
    const existingModal = document.querySelector('.barcode-input-modal');
    if (existingModal) {
      existingModal.remove();
    }
    
    const modal = document.createElement('div');
    modal.className = 'barcode-input-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:10000;';
    modal.innerHTML = `
      <div style="background:var(--orders-card);padding:32px;border-radius:20px;max-width:500px;width:90%;border:1px solid rgba(59,130,246,0.3)">
        <h3 style="color:var(--orders-text);margin:0 0 24px;font-size:24px">📦 فاتورة #${invoice.id}</h3>
        <div style="margin-bottom:20px">
          <p style="color:var(--orders-muted);margin:0 0 8px">الزبون:</p>
          <p style="color:var(--orders-text);margin:0;font-size:18px;font-weight:600">${invoice.customer_name || '—'}</p>
        </div>
        <div style="margin-bottom:20px">
          <p style="color:var(--orders-muted);margin:0 0 8px">المبلغ:</p>
          <p style="color:var(--orders-success);margin:0;font-size:20px;font-weight:600">${invoice.total || 0} د.ع</p>
        </div>
        <div style="margin-bottom:24px">
          <label style="display:block;color:var(--orders-text);margin-bottom:8px;font-weight:600">باركود الفاتورة:</label>
          <input type="text" id="barcodeInput" placeholder="أدخل باركود الفاتورة" value="${scannedBarcode || ''}" style="width:100%;padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);background:rgba(15,23,42,0.6);color:var(--orders-text);font-size:16px" autocomplete="off">
        </div>
        <div style="display:flex;gap:12px">
          <button onclick="if(typeof saveBarcode === 'function') saveBarcode(${invoice.id}, this.closest('.barcode-input-modal')); else alert('دالة الحفظ غير متاحة');" style="flex:1;padding:12px;border-radius:8px;background:var(--orders-success);color:#fff;border:none;font-weight:600;cursor:pointer">💾 حفظ</button>
          <button onclick="this.closest('.barcode-input-modal').remove()" style="flex:1;padding:12px;border-radius:8px;background:rgba(255,255,255,0.1);color:var(--orders-text);border:1px solid rgba(255,255,255,0.1);font-weight:600;cursor:pointer">إلغاء</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    const input = document.getElementById('barcodeInput');
    if (input) {
      input.focus();
      input.select();
      
      // إغلاق عند الضغط على Enter أو Escape
      input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          if (typeof saveBarcode === 'function') {
            saveBarcode(invoice.id, modal);
          }
        } else if (e.key === 'Escape') {
          e.preventDefault();
          modal.remove();
        }
      });
    }
    
    // إغلاق عند النقر خارج النافذة
    modal.addEventListener('click', function(e) {
      if (e.target === modal) {
        modal.remove();
      }
    });
  };
})();

// ==================== حفظ الباركود ====================
function saveBarcode(invoiceId, modal) {
  const barcode = document.getElementById('barcodeInput').value.trim();
  
  if (!barcode) {
    showToast('⚠️ يرجى إدخال باركود', 'warning');
    return;
  }
  
  fetch(`/orders/update-barcode/${invoiceId}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({barcode: barcode})
  })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        showToast('✅ تم حفظ الباركود بنجاح', 'success');
        if (modal && modal.remove) {
          modal.remove();
        }
        setTimeout(() => location.reload(), 1000);
      } else {
        showToast('❌ ' + (data.error || 'حدث خطأ أثناء الحفظ'), 'error');
      }
    })
    .catch(error => {
      console.error('Save barcode error:', error);
      showToast('❌ حدث خطأ أثناء الحفظ', 'error');
    });
}

// Make saveBarcode globally available
window.saveBarcode = saveBarcode;

function updatePrintDate() {
  const printDate = new Date().toLocaleDateString("ar-IQ");
  const card = document.querySelector(".orders-card");
  if (card) {
    card.setAttribute("data-print-date", printDate);
  }
}

// Make all functions globally available to prevent errors
// التأكد من أن جميع الدوال الأساسية متاحة عالمياً
document.addEventListener("DOMContentLoaded", function() {
  // تحديث تاريخ الطباعة كل دقيقة
  setInterval(updatePrintDate, 60000);
  
  const essentialFunctions = {
    selectedIds: typeof selectedIds === 'function' ? selectedIds : null,
    showLoading: typeof showLoading === 'function' ? showLoading : null,
    hideLoading: typeof hideLoading === 'function' ? hideLoading : null,
    showToast: typeof showToast === 'function' ? showToast : null,
    showConfirm: typeof showConfirm === 'function' ? showConfirm : null,
    toggleDropdown: typeof toggleDropdown === 'function' ? toggleDropdown : null,
    handleRowClick: typeof handleRowClick === 'function' ? handleRowClick : null,
    pay: typeof pay === 'function' ? pay : null,
    payPartial: typeof payPartial === 'function' ? payPartial : null,
    cancelOrder: typeof cancelOrder === 'function' ? cancelOrder : null,
    markAsReturned: typeof markAsReturned === 'function' ? markAsReturned : null,
    printSingleInvoice: typeof printSingleInvoice === 'function' ? printSingleInvoice : null,
    printSelectedInvoices: typeof printSelectedInvoices === 'function' ? printSelectedInvoices : null,
    editOrder: typeof editOrder === 'function' ? editOrder : null,
    sendWhatsAppSingle: typeof sendWhatsAppSingle === 'function' ? sendWhatsAppSingle : null,
    sendWhatsAppMessage: typeof sendWhatsAppMessage === 'function' ? sendWhatsAppMessage : null,
    saveBarcode: typeof saveBarcode === 'function' ? saveBarcode : null,
    showBarcodeInputModal: typeof showBarcodeInputModal === 'function' ? showBarcodeInputModal : null,
    handleBarcodeScan: typeof handleBarcodeScan === 'function' ? handleBarcodeScan : null,
    applyFilters: typeof applyFilters === 'function' ? applyFilters : null,
    clearFilters: typeof clearFilters === 'function' ? clearFilters : null,
    toggleAll: typeof toggleAll === 'function' ? toggleAll : null,
    showDetails: typeof showDetails === 'function' ? showDetails : null,
    closeModal: typeof closeModal === 'function' ? closeModal : null
  };
  
  // تصدير الدوال إلى window
  Object.keys(essentialFunctions).forEach(funcName => {
    if (essentialFunctions[funcName] && typeof window[funcName] === 'undefined') {
      window[funcName] = essentialFunctions[funcName];
    }
  });
});
