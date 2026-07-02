function __t(k) { return (window.EMP_I18N && window.EMP_I18N[k]) || ''; }
// ==================== Toast Notifications ====================
  function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = {
      success: '✅',
      error: '❌',
      warning: '⚠️',
      info: 'ℹ️'
    };

    toast.innerHTML = `
    <span style="font-size: 18px;">${icons[type] || icons.info}</span>
    <span style="flex: 1;font-size: 14px;line-height: 1.5;">${message}</span>
  `;

    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('fade-out');
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    }, 3000);
  }

  // ==================== Loading Overlay ====================
  function showLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
      overlay.classList.add('show');
    }
  }

  function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
      overlay.classList.remove('show');
    }
  }

  // ==================== Employee Form Submit ====================
  function handleEmployeeSubmit(event) {
    event.preventDefault();

    const btn = document.getElementById('employeeSubmitBtn');
    btn.classList.add('button-loading');

    const form = event.target;
    const formData = new FormData(form);

    fetch('/employees/', {
      method: 'POST',
      body: formData
    })
      .then(response => {
        if (response.ok) {
          showToast(__t('employees_toast_add_success'), 'success');
          setTimeout(() => {
            location.reload();
          }, 1000);
        } else {
          throw new Error(__t('employees_err_add_failed'));
        }
      })
      .catch(error => {
        btn.classList.remove('button-loading');
        showToast(error.message, 'error');
      });
  }

  // ==================== Add Agent Account ====================
  function addAgentAccount(event) {
    event.preventDefault();

    const agentId = document.getElementById('agent_id').value;
    const username = document.getElementById('agent_username').value.trim();
    const password = document.getElementById('agent_password').value.trim();

    if (!agentId || !username || !password) {
      showToast(__t('employees_err_fill_all'), 'warning');
      return;
    }

    showLoading();

    fetch('/employees/add-agent-account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_id: agentId,
        username: username,
        password: password
      })
    })
      .then(r => r.json())
      .then(data => {
        hideLoading();
        if (data.success) {
          showToast(data.message, 'success');
          document.getElementById('agentAccountForm').reset();
          setTimeout(() => {
            location.reload();
          }, 1000);
        } else {
          showToast(data.error || __t('employees_err_generic'), 'error');
        }
      })
      .catch(error => {
        hideLoading();
        showToast(__t('employees_err_add_failed'), 'error');
        console.error(error);
      });
  }

  // ==================== Toggle Employee Status ====================
  const empActionDisable = __t('employees_action_disable');
  const empActionEnable = __t('employees_action_enable');
  const empConfirmDisable = __t('employees_confirm_disable');
  const empConfirmEnable = __t('employees_confirm_enable');

  async function toggleEmployeeStatus(id, name, isActive) {
    const action = isActive ? empConfirmDisable : empConfirmEnable;
    if (!confirm(action.replace('{name}', name))) return;

    showLoading();
    try {
      const response = await fetch(`/employees/toggle/${id}`, { method: 'POST' });
      if (response.ok) {
        showToast(isActive ? 'تم التعطيل' : 'تم التفعيل', 'success');
        setTimeout(() => location.reload(), 700);
      } else {
        throw new Error(__t('employees_err_generic'));
      }
    } catch (error) {
      hideLoading();
      showToast(error.message || __t('employees_err_generic'), 'error');
    }
  }


  function openEditEmployeeModal(gridId) {
    const row = (gridApi ? gridApi.getRowNode(String(gridId)) : null);
    const data = row ? row.data : null;
    if (!data) return;
    const cleanName = String(data.name || '').replace(/^🚚\s*/, '');
    document.getElementById('editEmpId').value = data.id;
    document.getElementById('editEmpIsDelivery').value = data.is_delivery ? '1' : '0';
    document.getElementById('editEmpName').value = cleanName;
    document.getElementById('editEmpSalary').value = data.salary || 0;
    document.getElementById('editEmpPassword').value = '';
    document.getElementById('editEmployeeModalTitle').textContent = data.is_delivery ? 'تعديل مندوب' : 'تعديل موظف';
    document.getElementById('editEmployeeModal').classList.add('is-open');
  }
  function closeEditEmployeeModal() {
    document.getElementById('editEmployeeModal').classList.remove('is-open');
  }
  async function saveEditEmployee() {
    const id = document.getElementById('editEmpId').value;
    const isDelivery = document.getElementById('editEmpIsDelivery').value === '1';
    const body = {
      name: document.getElementById('editEmpName').value,
      salary: document.getElementById('editEmpSalary').value,
    };
    const pwd = document.getElementById('editEmpPassword').value.trim();
    if (pwd) body.password = pwd;
    showLoading();
    const updateUrl = isDelivery ? `/employees/update-agent/${id}` : `/employees/update/${id}`;
    const r1 = await fetch(updateUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d1 = await r1.json();
    if (!d1.success) { hideLoading(); showToast(d1.error || 'فشل التحديث', 'error'); return; }
    if (!isDelivery && pwd) {
      const r2 = await fetch(`/employees/reset-password/${id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: pwd }) });
      const d2 = await r2.json();
      if (!d2.success) { hideLoading(); showToast(d2.error || 'فشل كلمة المرور', 'error'); return; }
    }
    hideLoading();
    showToast('تم الحفظ', 'success');
    setTimeout(() => location.reload(), 700);
  }

  async function saveFixedCommission() {
    const input = document.getElementById('fixedCommissionPercent');
    const percent = parseInt(input.value, 10);
    if (Number.isNaN(percent) || percent < 0 || percent > 100) {
      showToast('أدخل نسبة بين 0 و 100', 'warning');
      return;
    }
    showLoading();
    try {
      const r = await fetch('/employees/fixed-commission', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ percent }),
      });
      const data = await r.json();
      hideLoading();
      if (data.success) {
        showToast(data.message || 'تم الحفظ', 'success');
        setTimeout(() => location.reload(), 700);
      } else {
        showToast(data.error || __t('employees_err_generic'), 'error');
      }
    } catch (e) {
      hideLoading();
      showToast(__t('employees_err_connection'), 'error');
    }
  }

  let gridApi;

  function initAgGrid() {
    const employeesDataElement = document.getElementById("employeesData");
    if (!employeesDataElement) return;

    let rowData = [];
    try {
      const raw = JSON.parse(employeesDataElement.textContent.trim());
      const roleNames = {
        cashier: __t('employees_role_cashier'),
        admin: __t('employees_role_admin'),
        delivery: __t('employees_role_delivery'),
      };
      const statusNames = {
        active: __t('employees_status_active'),
        inactive: __t('employees_status_inactive'),
      };
      rowData = raw.map((r) => ({
        ...r,
        role_name: r.role_name || roleNames[r.role] || r.role,
        status_name: r.status_name || statusNames[r.status] || r.status,
      }));
    } catch (e) {
      console.error("Error parsing employees data:", e);
      return;
    }

    const columnDefs = [
      {
        headerName: __t('employees_col_name'),
        field: "name",
        flex: 1.5,
        minWidth: 150,
        cellRenderer: params => `<strong>${params.value}</strong>`
      },
      { headerName: __t('employees_col_username'), field: "username", width: 120 },
      { headerName: "الأدوار", field: "role_labels", width: 140, valueFormatter: p => (p.value || []).join(', ') || p.data.role_name },
      { headerName: "البيجات", field: "pages_count", width: 90 },
      {
        headerName: __t('employees_col_role'),
        field: "role_name",
        width: 120,
        cellRenderer: params => {
          const role = params.data.role;
          return `<span class="role-badge ${role === 'delivery' ? '' : 'role-' + role}" 
                  style="${role === 'delivery' ? 'background: rgba(16, 185, 129, 0.2); color: var(--emp-success); border: 1px solid rgba(16, 185, 129, 0.3);' : ''}">
                  ${params.value}
                </span>`;
        }
      },
      {
        headerName: __t('employees_col_status'),
        field: "status_name",
        width: 100,
        cellRenderer: params => {
          const cls = params.data.status === 'active' ? 'status-active' : 'status-inactive';
          return `<span class="status-badge ${cls}">${params.value}</span>`;
        }
      },
      { headerName: __t('employees_col_orders'), field: "orders", width: 90, type: 'numericColumn' },
      {
        headerName: __t('employees_col_sales'),
        field: "sales",
        width: 130,
        type: 'numericColumn',
        cellRenderer: params => `<span style="color:var(--emp-success);font-weight:600">${params.value.toLocaleString()} ${__t('employees_currency_iqd')}</span>`
      },
      {
        headerName: __t('employees_col_salary'),
        field: "salary",
        width: 110,
        type: 'numericColumn',
        cellRenderer: params => `${params.value.toLocaleString()} ${__t('employees_currency_iqd')}`
      },
      {
        headerName: __t('employees_col_commission'),
        field: "commission",
        width: 80,
        type: 'numericColumn',
        cellRenderer: params => params.data.is_delivery ? '—' : `${params.value}%`
      },
      {
        headerName: __t('employees_col_total_due'),
        field: "total_due",
        width: 120,
        type: 'numericColumn',
        cellRenderer: params => `<span style="color:var(--emp-warning);font-weight:700">${params.value.toLocaleString()} ${__t('employees_currency_iqd')}</span>`
      },
      {
        headerName: __t('employees_col_actions'),
        field: "actions",
        width: 220,
        sortable: false,
        filter: false,
        suppressMovable: true,
        cellClass: 'actions-col',
        headerClass: 'actions-col',
        cellRenderer: params => {
          const e = params.data;
          const nameEscaped = e.name.replace(/'/g, "\\'");

          if (e.is_delivery) {
            return `
            <div class="admin-actions">
              <button type="button" class="action-btn" onclick="event.stopPropagation(); openEditEmployeeModal('${e.grid_id}')" title="تعديل الراتب"><i class="fas fa-pen"></i></button>
              <a href="/delivery-agent/login" target="_blank" class="action-btn" title="${__t('employees_action_agent_page')}" onclick="event.stopPropagation()">
                <i class="fas fa-truck"></i>
              </a>
            </div>
          `;
          }

          const isActive = e.status === 'active';
          return `
          <div class="admin-actions">
            <button type="button" class="action-btn" onclick="event.stopPropagation(); toggleEmployeeStatus(${e.id}, '${nameEscaped}', ${isActive})" title="${isActive ? empActionDisable : empActionEnable}">
              <i class="fas ${isActive ? 'fa-user-slash' : 'fa-user-check'}"></i>
            </button>
            <button type="button" class="action-btn" onclick="event.stopPropagation(); openEditEmployeeModal('${e.grid_id}')" title="تعديل"><i class="fas fa-pen"></i></button>
            <button type="button" class="action-btn" onclick="event.stopPropagation(); openPagesModal(${e.id}, '${nameEscaped}')" title="${__t('employees_action_pages')}">
              <i class="fas fa-file-invoice"></i>
            </button>
            <a href="/admin/permissions/employee/${e.id}/roles" class="action-btn" title="${__t('employees_action_roles')}" onclick="event.stopPropagation()">
              <i class="fas fa-user-shield"></i>
            </a>
            <button type="button" class="action-btn" onclick="event.stopPropagation(); viewEmployeeOrders(${e.id}, '${nameEscaped}')" title="${__t('employees_action_view')}">
              <i class="fas fa-eye"></i>
            </button>
          </div>
        `;
        }
      }
    ];

    const gridOptions = {
      columnDefs: columnDefs,
      rowData: rowData,
      rowHeight: 60,
      headerHeight: 48,
      suppressRowClickSelection: true,
      pagination: true,
      paginationPageSize: 20,
      paginationPageSizeSelector: [10, 20, 50, 100],
      enableRtl: true,
      animateRows: true,
      localeText: {
        page: 'صفحة',
        to: 'إلى',
        of: 'من',
        next: 'التالي',
        last: 'الأخيرة',
        first: 'الأولى',
        previous: 'السابق',
        pageSizeSelectorLabel: 'حجم الصفحة:',
      },
      getRowId: (params) => String(params.data.grid_id || params.data.id),
      defaultColDef: {
        sortable: true,
        filter: true,
        resizable: true,
        floatingFilter: true
      },
      onGridReady: (params) => {
        gridApi = params.api;
      },
      isExternalFilterPresent: () => {
        const roleFilter = document.getElementById('filterRole').value;
        const statusFilter = document.getElementById('filterStatus').value;
        return roleFilter !== '' || statusFilter !== '';
      },
      doesExternalFilterPass: (node) => {
        const roleFilter = document.getElementById('filterRole').value;
        const statusFilter = document.getElementById('filterStatus').value;
        const matchesRole = !roleFilter || node.data.role === roleFilter;
        const matchesStatus = !statusFilter || node.data.status === statusFilter;
        return matchesRole && matchesStatus;
      }
    };

    const eGridDiv = document.querySelector('#employeesTable');
    agGrid.createGrid(eGridDiv, gridOptions);
    eGridDiv.classList.add('ag-theme-finora');
    eGridDiv.classList.remove('ag-theme-quartz-dark');
  }

  function updateSearch() {
    const searchQuery = document.getElementById('searchInput').value;
    if (gridApi) {
      gridApi.setGridOption('quickFilterText', searchQuery);
    }
  }

  function updateRoleFilter() {
    if (gridApi) gridApi.onFilterChanged();
  }

  function updateStatusFilter() {
    if (gridApi) gridApi.onFilterChanged();
  }

  // ==================== Manage Pages Modal ====================
  let allAvailablePages = [];
  const pagesDataEl = document.getElementById('pagesData');
  if (pagesDataEl) {
    try {
      allAvailablePages = JSON.parse(pagesDataEl.textContent.trim());
    } catch (e) {
      console.error("Error parsing pages data:", e);
    }
  }

  function openPagesModal(employeeId, employeeName) {
    fetch(`/employees/pages/${employeeId}`)
      .then(r => r.json())
      .then(data => {
        const currentPages = data.pages.map(p => p.id);

        const modal = document.createElement('div');
        modal.className = 'modal-overlay show';
        modal.innerHTML = `
        <div class="modal-content">
          <button class="close-btn" onclick="this.closest('.modal-overlay').remove()">×</button>
          <h3>${__t('employees_modal_pages_title')} - ${employeeName}</h3>
          <div id="pagesList">
            ${allAvailablePages.map(p => `
              <label>
                <input type="checkbox" value="${p.id}" ${currentPages.includes(p.id) ? 'checked' : ''}>
                <span>${p.name}</span>
              </label>
            `).join('')}
          </div>
          <button onclick="saveEmployeePages(${employeeId})">${__t('employees_save_button')}</button>
        </div>
      `;
        document.body.appendChild(modal);

        // Close on overlay click
        modal.addEventListener('click', function (e) {
          if (e.target === modal) {
            modal.remove();
          }
        });

        window.currentModal = modal;
        window.saveEmployeePages = function (empId) {
          const checkboxes = modal.querySelectorAll('input[type="checkbox"]:checked');
          const pageIds = Array.from(checkboxes).map(cb => parseInt(cb.value));

          fetch(`/employees/manage-pages/${empId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ page_ids: pageIds })
          })
            .then(r => r.json())
            .then(data => {
              if (data.success) {
                showToast(__t('employees_toast_pages_updated'), 'success');
                modal.remove();
                setTimeout(() => location.reload(), 1000);
              } else {
                showToast(data.error || __t('employees_err_generic'), 'error');
              }
            })
            .catch(err => {
              showToast(__t('employees_err_connection'), 'error');
            });
        };
      })
      .catch(err => {
        showToast(__t('employees_err_fetch_data'), 'error');
      });
  }

  // ==================== View Employee Orders ====================
  const empOrdersTitle = __t('employees_orders_modal_title');
  const empPagesCount = __t('employees_orders_pages_count');
  const empTotalOrders = __t('employees_orders_total_orders');
  const empOrderCount = __t('employees_orders_order_count');
  const empNoPage = __t('employees_orders_no_page');
  const empClose = __t('employees_modal_close');
  const empCurrency = __t('employees_currency_iqd');
  function viewEmployeeOrders(employeeId, employeeName) {
    fetch(`/employees/view-orders/${employeeId}`)
      .then(r => r.json())
      .then(data => {
        let content = `<h3>${empOrdersTitle.replace('{name}', employeeName)}</h3>`;
        content += `<p style="color: var(--emp-muted); margin-bottom: var(--spacing-lg);">${empPagesCount}: ${data.pages_count} | ${empTotalOrders}: ${data.total_orders}</p>`;

        for (let pageId in data.page_stats) {
          const page = data.page_stats[pageId];
          content += `<div style="margin-bottom: var(--spacing-lg); padding: var(--spacing-md); background: rgba(255,255,255,0.03); border-radius: var(--radius-md);">`;
          content += `<h4 style="color: var(--emp-primary-light); margin-bottom: var(--spacing-sm);">${page.name} (${page.orders_count} ${empOrderCount})</h4>`;
          if (page.orders.length > 0) {
            content += `<ul style="list-style: none; padding: 0; margin: 0;">`;
            page.orders.forEach(order => {
              content += `<li style="padding: var(--spacing-xs) var(--spacing-sm); background: rgba(255,255,255,0.02); margin-bottom: var(--spacing-xs); border-radius: var(--radius-sm); color: var(--emp-text);">`;
              content += `#${order.id} - ${order.customer_name} - ${order.total} ${empCurrency}`;
              content += `</li>`;
            });
            content += `</ul>`;
          }
          content += `</div>`;
        }

        if (data.orders_without_page && data.orders_without_page.length > 0) {
          content += `<div style="margin-bottom: var(--spacing-lg); padding: var(--spacing-md); background: rgba(255,255,255,0.03); border-radius: var(--radius-md);">`;
          content += `<h4 style="color: var(--emp-warning); margin-bottom: var(--spacing-sm);">${empNoPage} (${data.orders_without_page.length} ${empOrderCount})</h4>`;
          content += `<ul style="list-style: none; padding: 0; margin: 0;">`;
          data.orders_without_page.forEach(order => {
            content += `<li style="padding: var(--spacing-xs) var(--spacing-sm); background: rgba(255,255,255,0.02); margin-bottom: var(--spacing-xs); border-radius: var(--radius-sm); color: var(--emp-text);">`;
            content += `#${order.id} - ${order.customer_name} - ${order.total} ${empCurrency}`;
            content += `</li>`;
          });
          content += `</ul></div>`;
        }

        const modal = document.createElement('div');
        modal.className = 'modal-overlay show';
        modal.innerHTML = `
        <div class="modal-content">
          <button class="close-btn" onclick="this.closest('.modal-overlay').remove()">×</button>
          ${content}
          <button onclick="this.closest('.modal-overlay').remove()">${empClose}</button>
        </div>
      `;
        document.body.appendChild(modal);

        // Close on overlay click
        modal.addEventListener('click', function (e) {
          if (e.target === modal) {
            modal.remove();
          }
        });
      })
      .catch(err => {
        showToast('حدث خطأ في جلب البيانات', 'error');
      });
  }

  // ==================== Collapsible Sections Logic ====================
  function toggleSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (!section) return;

    const isCollapsed = section.classList.toggle('collapsed');

    // Save state to localStorage
    try {
      const states = JSON.parse(localStorage.getItem('employees_sections_states') || '{}');
      states[sectionId] = isCollapsed;
      localStorage.setItem('employees_sections_states', JSON.stringify(states));
    } catch (e) {
      console.warn('Error saving section state:', e);
    }
  }

  function restoreSectionStates() {
    try {
      const states = JSON.parse(localStorage.getItem('employees_sections_states') || '{}');
      for (const [id, isCollapsed] of Object.entries(states)) {
        const section = document.getElementById(id);
        if (section) {
          if (isCollapsed) {
            section.classList.add('collapsed');
          } else {
            section.classList.remove('collapsed');
          }
        }
      }
    } catch (e) {
      console.warn('Error restoring section states:', e);
    }
  }

  // Initialize on page load
  document.addEventListener('DOMContentLoaded', function () {
    restoreSectionStates();
    if (document.getElementById('employeesTable')) {
      initAgGrid();
    }
  });
