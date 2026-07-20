function __t(k) { return (window.EMP_I18N && window.EMP_I18N[k]) || ''; }

  function getEmployeesModalRoot() {
    return document.querySelector('.employees-page') || document.querySelector('.team-admin-page') || document.body;
  }

  function appendEmployeeModal(modal) {
    getEmployeesModalRoot().appendChild(modal);
    return modal;
  }

  function createActionButton({ icon, title, className, href, target, onClick }) {
    const el = href ? document.createElement('a') : document.createElement('button');
    if (!href) el.type = 'button';
    el.className = 'action-btn' + (className ? ' ' + className : '');
    el.title = title || '';
    if (href) {
      el.href = href;
      if (target) el.target = target;
    }
    el.innerHTML = `<i class="fas ${icon}"></i>`;
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      if (onClick) onClick(e);
    });
    return el;
  }
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

  const empActionDelete = __t('employees_action_delete');
  const empConfirmDelete = __t('employees_confirm_delete');

  async function deleteEmployee(id, name) {
    const msg = empConfirmDelete.replace('{name}', name);
    if (!confirm(msg)) return;

    showLoading();
    try {
      const response = await fetch(`/employees/delete/${id}`, { method: 'POST' });
      const data = await response.json();
      hideLoading();
      if (response.ok && data.success) {
        showToast(data.message || __t('employees_toast_delete_success'), 'success');
        setTimeout(() => location.reload(), 700);
      } else {
        showToast(data.error || __t('employees_err_generic'), 'error');
      }
    } catch (error) {
      hideLoading();
      showToast(__t('employees_err_connection'), 'error');
    }
  }

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
    const phoneField = document.getElementById('editEmpPhoneField');
    const phoneInput = document.getElementById('editEmpPhone');
    if (phoneField && phoneInput) {
      phoneField.style.display = data.is_delivery ? 'none' : '';
      phoneInput.value = data.phone || '';
    }
    document.getElementById('editEmpSalary').value = data.salary || 0;
    const payTypeEl = document.getElementById('editEmpPayType');
    const payDayEl = document.getElementById('editEmpPayDay');
    const payWeekdayEl = document.getElementById('editEmpPayWeekday');
    if (payTypeEl) payTypeEl.value = data.pay_type || 'none';
    if (payDayEl) payDayEl.value = data.pay_day_of_month || 25;
    if (payWeekdayEl) payWeekdayEl.value = String(data.pay_weekday ?? 4);
    const commissionField = document.getElementById('editEmpCommissionField');
    const commissionInput = document.getElementById('editEmpCommission');
    if (commissionField && commissionInput) {
      commissionField.style.display = data.is_delivery ? 'none' : '';
      commissionInput.value = data.commission_rate ?? data.commission ?? 0;
    }
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
      pay_type: document.getElementById('editEmpPayType')?.value,
      pay_day_of_month: document.getElementById('editEmpPayDay')?.value,
      pay_weekday: document.getElementById('editEmpPayWeekday')?.value,
    };
    if (!isDelivery) {
      const phoneInput = document.getElementById('editEmpPhone');
      if (phoneInput) body.phone = phoneInput.value.trim();
      const commissionInput = document.getElementById('editEmpCommission');
      if (commissionInput) {
        body.commission = commissionInput.value;
      }
    }
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

  let gridApi;

  let empActionsMenuEl = null;
  let empActionsActiveTrigger = null;

  function ensureEmpActionsMenu() {
    if (empActionsMenuEl) return empActionsMenuEl;
    empActionsMenuEl = document.createElement('div');
    empActionsMenuEl.className = 'emp-actions-menu';
    empActionsMenuEl.id = 'empActionsMenu';
    empActionsMenuEl.setAttribute('role', 'menu');
    empActionsMenuEl.hidden = true;
    document.body.appendChild(empActionsMenuEl);
    return empActionsMenuEl;
  }

  function closeEmpActionsMenu() {
    const menu = empActionsMenuEl || document.getElementById('empActionsMenu');
    if (menu) menu.hidden = true;
    if (empActionsActiveTrigger) {
      empActionsActiveTrigger.setAttribute('aria-expanded', 'false');
      empActionsActiveTrigger = null;
    }
  }

  function positionEmpActionsMenu(trigger) {
    const menu = ensureEmpActionsMenu();
    const rect = trigger.getBoundingClientRect();
    const gap = 6;
    const viewportPad = 8;

    menu.hidden = false;
    menu.style.visibility = 'hidden';
    menu.style.left = '0px';
    menu.style.top = '0px';

    const menuRect = menu.getBoundingClientRect();
    let left = rect.right - menuRect.width;
    let top = rect.bottom + gap;

    if (left < viewportPad) left = viewportPad;
    if (left + menuRect.width > window.innerWidth - viewportPad) {
      left = Math.max(viewportPad, window.innerWidth - menuRect.width - viewportPad);
    }

    if (top + menuRect.height > window.innerHeight - viewportPad) {
      top = rect.top - menuRect.height - gap;
    }
    if (top < viewportPad) top = viewportPad;

    menu.style.left = Math.round(left) + 'px';
    menu.style.top = Math.round(top) + 'px';
    menu.style.visibility = '';
  }

  function openEmpActionsMenu(trigger) {
    const gridId = trigger.getAttribute('data-grid-id');
    const row = gridApi ? gridApi.getRowNode(String(gridId)) : null;
    const e = row ? row.data : null;
    if (!e) return;

    if (empActionsActiveTrigger === trigger && empActionsMenuEl && !empActionsMenuEl.hidden) {
      closeEmpActionsMenu();
      return;
    }

    closeEmpActionsMenu();
    const menu = ensureEmpActionsMenu();

    if (e.is_delivery) {
      menu.innerHTML = `
        <button type="button" class="emp-actions-menu-item" role="menuitem" data-emp-action="edit">
          <i class="fas fa-pen" aria-hidden="true"></i><span>تعديل الراتب</span>
        </button>
        <a class="emp-actions-menu-item" role="menuitem" href="/delivery-agent/login" target="_blank" rel="noopener">
          <i class="fas fa-truck" aria-hidden="true"></i><span>${__t('employees_action_agent_page')}</span>
        </a>
      `;
    } else {
      const isActive = e.status === 'active';
      const toggleLabel = isActive ? empActionDisable : empActionEnable;
      const toggleIcon = isActive ? 'fa-user-slash' : 'fa-user-check';
      menu.innerHTML = `
        <button type="button" class="emp-actions-menu-item" role="menuitem" data-emp-action="toggle">
          <i class="fas ${toggleIcon}" aria-hidden="true"></i><span>${toggleLabel}</span>
        </button>
        <button type="button" class="emp-actions-menu-item" role="menuitem" data-emp-action="edit">
          <i class="fas fa-pen" aria-hidden="true"></i><span>تعديل</span>
        </button>
        <a class="emp-actions-menu-item" role="menuitem" href="/admin/permissions/employee/${encodeURIComponent(e.id)}/roles">
          <i class="fas fa-user-shield" aria-hidden="true"></i><span>${__t('employees_action_roles')}</span>
        </a>
        <button type="button" class="emp-actions-menu-item" role="menuitem" data-emp-action="view">
          <i class="fas fa-eye" aria-hidden="true"></i><span>${__t('employees_action_view')}</span>
        </button>
        <div class="emp-actions-menu-sep" role="separator"></div>
        <button type="button" class="emp-actions-menu-item is-danger" role="menuitem" data-emp-action="delete">
          <i class="fas fa-trash" aria-hidden="true"></i><span>${empActionDelete}</span>
        </button>
      `;
    }

    menu.onclick = function (event) {
      const item = event.target.closest('[data-emp-action], a.emp-actions-menu-item');
      if (!item || !menu.contains(item)) return;

      const action = item.getAttribute('data-emp-action');
      if (action === 'toggle') {
        event.preventDefault();
        closeEmpActionsMenu();
        toggleEmployeeStatus(e.id, e.name, e.status === 'active');
        return;
      }
      if (action === 'edit') {
        event.preventDefault();
        closeEmpActionsMenu();
        openEditEmployeeModal(e.grid_id);
        return;
      }
      if (action === 'view') {
        event.preventDefault();
        closeEmpActionsMenu();
        viewEmployeeOrders(e.id, e.name);
        return;
      }
      if (action === 'delete') {
        event.preventDefault();
        closeEmpActionsMenu();
        deleteEmployee(e.id, e.name);
        return;
      }
      closeEmpActionsMenu();
    };

    empActionsActiveTrigger = trigger;
    trigger.setAttribute('aria-expanded', 'true');
    positionEmpActionsMenu(trigger);
  }

  document.addEventListener('click', function (event) {
    const trigger = event.target.closest ? event.target.closest('[data-emp-actions-trigger]') : null;
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      openEmpActionsMenu(trigger);
      return;
    }
    if (empActionsMenuEl && !empActionsMenuEl.hidden) {
      if (!empActionsMenuEl.contains(event.target)) closeEmpActionsMenu();
    }
  }, true);

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeEmpActionsMenu();
  });

  window.addEventListener('resize', closeEmpActionsMenu);
  window.addEventListener('scroll', closeEmpActionsMenu, true);

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
      {
        headerName: "البيجات",
        field: "pages_count",
        width: 90,
        sortable: false,
        filter: false,
        cellRenderer: params => {
          if (params.data.is_delivery) return '—';
          const btn = createActionButton({
            icon: 'fa-file-invoice',
            title: __t('employees_action_pages'),
            onClick: () => openPagesModal(params.data.id, params.data.name),
          });
          const wrap = document.createElement('div');
          wrap.style.display = 'flex';
          wrap.style.alignItems = 'center';
          wrap.style.justifyContent = 'center';
          wrap.style.gap = '6px';
          const count = document.createElement('span');
          count.textContent = String(params.value ?? 0);
          wrap.appendChild(count);
          wrap.appendChild(btn);
          return wrap;
        }
      },
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
        width: 120,
        type: 'numericColumn',
        cellRenderer: params => (params.data.is_delivery || params.data.role === 'admin') ? '—' : `${params.value.toLocaleString()} ${__t('employees_currency_iqd')}`
      },
      {
        headerName: __t('employees_col_total_due'),
        field: "total_due",
        width: 120,
        type: 'numericColumn',
        cellRenderer: params => {
          if (params.data.is_delivery || params.data.role === 'admin') return '—';
          return `<span style="color:var(--emp-warning);font-weight:700">${params.value.toLocaleString()} ${__t('employees_currency_iqd')}</span>`;
        }
      },
      {
        headerName: __t('employees_col_actions'),
        field: "actions",
        width: 56,
        sortable: false,
        filter: false,
        suppressMovable: true,
        cellClass: 'actions-col',
        headerClass: 'actions-col',
        cellRenderer: params => {
          const e = params.data;
          const wrap = document.createElement('div');
          wrap.className = 'admin-actions emp-actions-grid';

          const trigger = document.createElement('button');
          trigger.type = 'button';
          trigger.className = 'emp-actions-trigger';
          trigger.setAttribute('data-emp-actions-trigger', '1');
          trigger.setAttribute('data-grid-id', String(e.grid_id));
          trigger.setAttribute('aria-haspopup', 'menu');
          trigger.setAttribute('aria-expanded', 'false');
          trigger.setAttribute('aria-label', __t('employees_col_actions') || 'إجراءات');
          trigger.innerHTML = '&#8942;';

          wrap.appendChild(trigger);
          return wrap;
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

  function updateEmpPagesSelectedCount(modal) {
    const list = modal.querySelector('#empPagesList');
    const counter = modal.querySelector('#empPagesSelectedCount');
    if (!list || !counter) return;
    const count = list.querySelectorAll('.emp-page-checkbox:checked').length;
    counter.textContent = `${count} محدد`;
  }

  function filterEmpPages(modal, query) {
    const list = modal.querySelector('#empPagesList');
    if (!list) return;
    const q = String(query || '').trim().toLowerCase();
    list.querySelectorAll('.emp-page-row').forEach((row) => {
      const name = row.querySelector('.emp-page-name')?.textContent?.toLowerCase() || '';
      row.style.display = !q || name.includes(q) ? '' : 'none';
    });
  }

  function openPagesModal(employeeId, employeeName) {
    fetch(`/employees/pages/${employeeId}`)
      .then(r => r.json())
      .then(data => {
        const currentPages = data.pages.map(p => p.id);
        const pagesTitle = __t('employees_modal_pages_title') || 'إدارة البيجات';
        const cancelLabel = __t('employees_modal_close') || 'إغلاق';

        const modal = document.createElement('div');
        modal.className = 'modal-overlay show';
        modal.innerHTML = `
        <div class="modal-content emp-pages-modal">
          <div class="emp-pages-modal-header">
            <button type="button" class="modal-close emp-pages-close" aria-label="${cancelLabel}">&times;</button>
            <div class="emp-pages-modal-header__text">
              <h3>${pagesTitle}</h3>
              <p class="emp-pages-modal-subtitle">${employeeName ? `الموظف: ${employeeName}` : ''}</p>
            </div>
            <span class="emp-pages-modal-icon" aria-hidden="true"><i class="fas fa-layer-group"></i></span>
          </div>
          <div class="emp-pages-toolbar">
            <input type="search" class="emp-pages-search" placeholder="بحث عن بيج..." aria-label="بحث عن بيج">
            <span class="emp-pages-selected-count" id="empPagesSelectedCount">0 محدد</span>
          </div>
          <div class="emp-pages-list" id="empPagesList"></div>
          <div class="emp-pages-modal-actions">
            <button type="button" class="btn btn-primary emp-pages-save-btn">حفظ</button>
            <button type="button" class="btn btn-light emp-pages-cancel-btn">${cancelLabel}</button>
          </div>
        </div>
      `;

        const list = modal.querySelector('#empPagesList');
        if (!allAvailablePages.length) {
          list.innerHTML = '<div class="emp-pages-list-empty">لا توجد بيجات متاحة</div>';
        } else {
          allAvailablePages.forEach((p) => {
            const isSelected = currentPages.includes(p.id);
            const row = document.createElement('label');
            row.className = 'emp-page-row' + (isSelected ? ' is-selected' : '');

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'emp-page-checkbox';
            checkbox.value = p.id;
            checkbox.checked = isSelected;
            checkbox.addEventListener('change', () => {
              row.classList.toggle('is-selected', checkbox.checked);
              updateEmpPagesSelectedCount(modal);
            });

            const icon = document.createElement('span');
            icon.className = 'emp-page-icon';
            icon.textContent = (p.name || 'ب').trim().charAt(0) || 'ب';

            const name = document.createElement('span');
            name.className = 'emp-page-name';
            name.textContent = p.name;

            row.appendChild(checkbox);
            row.appendChild(icon);
            row.appendChild(name);
            list.appendChild(row);
          });
        }

        appendEmployeeModal(modal);

        modal.querySelector('.emp-pages-close')?.addEventListener('click', () => modal.remove());
        modal.querySelector('.emp-pages-cancel-btn')?.addEventListener('click', () => modal.remove());
        modal.addEventListener('click', function (e) {
          if (e.target === modal) modal.remove();
        });

        const search = modal.querySelector('.emp-pages-search');
        search?.addEventListener('input', () => filterEmpPages(modal, search.value));
        updateEmpPagesSelectedCount(modal);
        search?.focus();

        modal.querySelector('.emp-pages-save-btn')?.addEventListener('click', () => {
          const checkboxes = modal.querySelectorAll('input[type="checkbox"]:checked');
          const pageIds = Array.from(checkboxes).map(cb => parseInt(cb.value, 10));

          fetch(`/employees/manage-pages/${employeeId}`, {
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
            .catch(() => {
              showToast(__t('employees_err_connection'), 'error');
            });
        });
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
        appendEmployeeModal(modal);

        modal.addEventListener('click', function (e) {
          if (e.target === modal) {
            modal.remove();
          }
        });
      })
      .catch(() => {
        showToast(__t('employees_err_fetch_data'), 'error');
      });
  }

  // ==================== Commission Monthly Statement ====================
  let commissionStatementPeriod = { year: null, month: null };
  let lastCommissionStatementData = null;

  function initCommissionStatementMonth() {
    const input = document.getElementById('commissionStmtMonth');
    if (!input) return;
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    input.value = `${y}-${m}`;
  }

  function getCommissionStatementPeriod() {
    const input = document.getElementById('commissionStmtMonth');
    if (!input || !input.value) {
      const now = new Date();
      return { year: now.getFullYear(), month: now.getMonth() + 1 };
    }
    const [year, month] = input.value.split('-').map(v => parseInt(v, 10));
    return { year, month };
  }

  function formatCommissionPeriodLabel(year, month) {
    try {
      const d = new Date(year, month - 1, 1);
      return d.toLocaleDateString('ar-IQ', { year: 'numeric', month: 'long' });
    } catch (e) {
      return `${year}-${String(month).padStart(2, '0')}`;
    }
  }

  function renderCommissionStatement(data) {
    const tbody = document.getElementById('commissionStatementBody');
    const summary = document.getElementById('commissionStatementSummary');
    if (!tbody) return;

    commissionStatementPeriod = { year: data.year, month: data.month };
    lastCommissionStatementData = data;
    const currency = __t('employees_currency_iqd');

    if (summary) {
      if ((data.rows || []).length === 0) {
        summary.textContent = __t('employees_commission_statement_no_due');
      } else {
        summary.textContent = __t('employees_commission_statement_total')
          .replace('{orders}', String(data.total_orders || 0))
          .replace('{amount}', (data.total_amount || 0).toLocaleString());
      }
    }

    if (!data.rows || data.rows.length === 0) {
      tbody.innerHTML = `<tr class="commission-statement-empty"><td colspan="4">${__t('employees_commission_statement_no_due')}</td></tr>`;
      return;
    }

    tbody.innerHTML = data.rows.map(row => `
      <tr>
        <td><strong>${row.employee_name}</strong></td>
        <td>${row.orders}</td>
        <td>${row.amount.toLocaleString()} ${currency}</td>
        <td>
          <button type="button" class="btn-settle-commission" data-employee-id="${row.employee_id}" data-name="${row.employee_name}" data-orders="${row.orders}" data-amount="${row.amount}">
            ${__t('employees_commission_statement_settle')}
          </button>
        </td>
      </tr>
    `).join('');

    tbody.querySelectorAll('.btn-settle-commission').forEach(btn => {
      btn.addEventListener('click', () => {
        settleEmployeeCommission(
          parseInt(btn.dataset.employeeId, 10),
          btn.dataset.name,
          parseInt(btn.dataset.orders, 10),
          parseInt(btn.dataset.amount, 10)
        );
      });
    });
  }

  function printCommissionStatement() {
    if (!lastCommissionStatementData || !(lastCommissionStatementData.rows || []).length) {
      showToast(__t('employees_commission_statement_print_empty') || 'اعرض الكشف أولاً ثم اطبع', 'warning');
      return;
    }

    const data = lastCommissionStatementData;
    const currency = __t('employees_currency_iqd');
    const periodEl = document.getElementById('cspPeriod');
    const printedAtEl = document.getElementById('cspPrintedAt');
    const summaryEl = document.getElementById('cspSummary');
    const bodyEl = document.getElementById('cspBody');
    const footEl = document.getElementById('cspFoot');
    if (!bodyEl) return;

    if (periodEl) {
      periodEl.textContent = formatCommissionPeriodLabel(data.year, data.month);
    }
    if (printedAtEl) {
      printedAtEl.textContent = new Date().toLocaleString('ar-IQ');
    }
    if (summaryEl) {
      summaryEl.textContent = __t('employees_commission_statement_total')
        .replace('{orders}', String(data.total_orders || 0))
        .replace('{amount}', (data.total_amount || 0).toLocaleString());
    }

    const rate = data.fixed_commission_amount || 0;
    bodyEl.innerHTML = (data.rows || []).map((row, index) => `
      <tr>
        <td class="csp-col-index">${index + 1}</td>
        <td class="csp-col-name">${row.employee_name}</td>
        <td class="csp-col-orders">${row.orders}</td>
        <td class="csp-col-rate">${(row.commission_rate ?? rate).toLocaleString()} ${currency}</td>
        <td class="csp-col-amount">${row.amount.toLocaleString()} ${currency}</td>
      </tr>
    `).join('');

    if (footEl) {
      footEl.innerHTML = `
        <tr>
          <td colspan="2">الإجمالي</td>
          <td class="csp-col-orders">${data.total_orders || 0}</td>
          <td></td>
          <td class="csp-col-amount">${(data.total_amount || 0).toLocaleString()} ${currency}</td>
        </tr>
      `;
    }

    requestAnimationFrame(() => window.print());
  }

  function loadCommissionStatement() {
    const { year, month } = getCommissionStatementPeriod();
    showLoading();
    fetch(`/employees/commission-statement?year=${year}&month=${month}`)
      .then(r => r.json())
      .then(data => {
        hideLoading();
        if (!data.success) {
          showToast(data.error || __t('employees_err_fetch_data'), 'error');
          return;
        }
        renderCommissionStatement(data);
      })
      .catch(() => {
        hideLoading();
        showToast(__t('employees_err_connection'), 'error');
      });
  }

  function updateEmployeeGridRow(employeeId, orders, commission) {
    if (!gridApi) return;
    gridApi.forEachNode(node => {
      if (!node.data || node.data.is_delivery || node.data.id !== employeeId) return;
      node.setData({
        ...node.data,
        orders,
        commission,
        total_due: commission,
      });
    });
  }

  function settleEmployeeCommission(employeeId, employeeName, orders, amount) {
    const { year, month } = commissionStatementPeriod.year
      ? commissionStatementPeriod
      : getCommissionStatementPeriod();

    const confirmMsg = __t('employees_commission_statement_confirm')
      .replace('{name}', employeeName)
      .replace('{amount}', amount.toLocaleString())
      .replace('{orders}', String(orders));

    if (!window.confirm(confirmMsg)) return;

    showLoading();
    fetch('/employees/commission-settle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ employee_id: employeeId, year, month }),
    })
      .then(r => r.json())
      .then(data => {
        hideLoading();
        if (!data.success) {
          showToast(data.error || __t('employees_err_generic'), 'error');
          return;
        }
        showToast(__t('employees_toast_settle_success'), 'success');
        loadCommissionStatement();
        updateEmployeeGridRow(employeeId, 0, 0);
        setTimeout(() => location.reload(), 800);
      })
      .catch(() => {
        hideLoading();
        showToast(__t('employees_err_connection'), 'error');
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
    initCommissionStatementMonth();
    if (document.getElementById('employeesTable')) {
      initAgGrid();
    }
  });
