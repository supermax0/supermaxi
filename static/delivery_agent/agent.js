(function () {
  "use strict";

  var orders = readJson("da-orders");
  var contacts = readJson("da-contacts");
  var agentUserId = Number(document.body.getAttribute("data-user-id") || 0);
  var loadingCount = 0;
  var chatTimer = null;
  var roomTimer = null;
  var activeRoom = null;
  var lastMessageId = 0;
  var renderedMessageIds = new Set();
  var statusFilter = "all";
  var pendingStatus = null;
  var savingOrders = new Set();
  var noteSaving = false;
  var chatSending = false;
  var modalTrigger = null;

  function readJson(id) {
    var node = document.getElementById(id);
    if (!node) return [];
    try { return JSON.parse(node.textContent || "[]"); } catch (e) { return []; }
  }

  function orderById(id) {
    id = Number(id);
    for (var i = 0; i < orders.length; i++) {
      if (Number(orders[i].id) === id) return orders[i];
    }
    return null;
  }

  function money(value) {
    var num = Number(value || 0);
    try {
      return new Intl.NumberFormat("en-US").format(num) + " د.ع";
    } catch (e) {
      return String(num) + " د.ع";
    }
  }

  function toast(message, type) {
    var host = document.getElementById("daToasts");
    if (!host) return;
    var el = document.createElement("div");
    el.className = "da-toast " + (type || "success");
    el.textContent = message;
    host.appendChild(el);
    setTimeout(function () { el.remove(); }, type === "error" ? 5000 : 3000);
  }

  function setLoading(on) {
    var bar = document.getElementById("daLoading");
    if (!bar) return;
    if (on) {
      loadingCount += 1;
      bar.classList.add("is-on");
      bar.classList.remove("is-done");
      return;
    }
    loadingCount = Math.max(0, loadingCount - 1);
    if (loadingCount === 0) {
      bar.classList.remove("is-on");
      bar.classList.add("is-done");
      setTimeout(function () { bar.classList.remove("is-done"); }, 220);
    }
  }

  function api(url, options, silent) {
    if (!silent) setLoading(true);
    return fetch(url, options).then(function (response) {
      return response.json().then(function (data) {
        data._status = response.status;
        return data;
      });
    }).finally(function () {
      if (!silent) setLoading(false);
    });
  }

  function showView(name) {
    var detail = document.getElementById("detailSheet");
    if (detail) detail.hidden = true;
    document.querySelectorAll("[data-view]").forEach(function (view) {
      view.hidden = view.getAttribute("data-view") !== name;
    });
    document.querySelectorAll("[data-tab]").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.getAttribute("data-tab") === name);
    });
    var stats = document.getElementById("daStats");
    if (stats) stats.classList.toggle("is-hidden", name !== "active");
    if (name !== "room") stopRoomPoll();
    if (name === "chat") loadConversations(false);
  }

  function openView(name, state, replace) {
    showView(name);
    var method = replace ? "replaceState" : "pushState";
    history[method](state || { view: name }, "", location.pathname + location.search);
  }

  function badgeHtml(order) {
      return order.applied_status
        ? '<span class="da-badge waiting">' + escapeHtml(order.applied_status) + " — بانتظار المحاسب</span>"
        : (function () {
            var status = order.status || "";
            var kind = "ordered";
            if (status === "جاري الشحن" || status === "قيد الشحن") kind = "shipping";
            if (order.note === "مؤجل") kind = "postponed";
            var label = order.note === "مؤجل" ? "مؤجل" : status;
            return '<span class="da-badge ' + kind + '">' + escapeHtml(label) + "</span>";
          })();
  }

  function finalBadge(status) {
    var kind = "ordered";
    if (status === "واصل") kind = "delivered";
    else if (status === "ملغي") kind = "cancelled";
    else if (status === "مؤجل") kind = "postponed";
    return '<span class="da-badge ' + kind + '">' + escapeHtml(status || "—") + "</span>";
  }

  function syncBadges(order) {
    document.querySelectorAll('[data-badge-for="' + order.id + '"]').forEach(function (node) {
      node.innerHTML = badgeHtml(order);
    });
    document.querySelectorAll('[data-note-for="' + order.id + '"]').forEach(function (node) {
      node.textContent = order.agent_note || "";
    });
    document.querySelectorAll('[data-note-btn="' + order.id + '"]').forEach(function (node) {
      node.classList.toggle("has-note", !!order.agent_note);
    });
    document.querySelectorAll('[data-apply-for="' + order.id + '"]').forEach(function (node) {
      node.textContent = order.applied_status ? "تعديل" : "تطبيق";
    });
  }

  function selectedStatus(orderId) {
    var detail = document.getElementById("detailStatus");
    var sheet = document.getElementById("detailSheet");
    if (sheet && !sheet.hidden && Number(detail && detail.getAttribute("data-order-id")) === Number(orderId)) {
      return detail.value;
    }
    var select = document.querySelector('.da-status[data-order-id="' + orderId + '"]');
    return select ? select.value : "";
  }

  function selectedDate(orderId) {
    var detailDate = document.getElementById("detailDate");
    var sheet = document.getElementById("detailSheet");
    if (sheet && !sheet.hidden && detailDate && Number(document.getElementById("detailStatus").getAttribute("data-order-id")) === Number(orderId)) {
      return detailDate.value;
    }
    var input = document.querySelector('.da-date[data-order-id="' + orderId + '"]');
    return input ? input.value : "";
  }

  function setPostponeVisible(orderId, visible) {
    document.querySelectorAll('[data-postpone="' + orderId + '"]').forEach(function (node) {
      node.hidden = !visible;
    });
    var detailDateWrap = document.getElementById("detailDateWrap");
    var detailStatus = document.getElementById("detailStatus");
    if (detailDateWrap && detailStatus && Number(detailStatus.getAttribute("data-order-id")) === Number(orderId)) {
      detailDateWrap.hidden = !visible;
    }
  }

  function syncModalLock() {
    var visible = document.querySelector('.da-sheet-backdrop:not([hidden])');
    document.body.classList.toggle("has-modal", !!visible);
    document.querySelectorAll(".da-shell, .da-bottom-nav").forEach(function (node) { node.inert = !!visible; });
  }

  function focusSheet(id) {
    modalTrigger = document.activeElement;
    syncModalLock();
    var field = document.querySelector("#" + id + " button, #" + id + " textarea");
    if (field) field.focus({ preventScroll: true });
  }

  function closeStatusConfirm() {
    var wasOpen = !document.getElementById("statusConfirmSheet").hidden;
    document.getElementById("statusConfirmSheet").hidden = true;
    pendingStatus = null;
    syncModalLock();
    if (wasOpen && modalTrigger && modalTrigger.isConnected) modalTrigger.focus({ preventScroll: true });
  }

  function confirmStatus(order, reportId, status, date) {
    if (savingOrders.has(order.id)) return;
    pendingStatus = { order: order, reportId: reportId, status: status, date: date };
    document.getElementById("statusConfirmTitle").textContent = "تأكيد «" + status + "» للطلب #" + order.id;
    document.getElementById("statusConfirmText").textContent = (order.customer_name || "") + " · " +
      (status === "واصل" ? "المبلغ المطلوب تحصيله: " + money(order.remaining) :
       status === "مؤجل" ? "موعد التأجيل: " + date : "تسجيل الطلب كملغي وإحالته للمحاسب.");
    document.getElementById("statusConfirmSave").textContent = "تأكيد " + status;
    document.getElementById("statusConfirmSheet").hidden = false;
    focusSheet("statusConfirmSheet");
  }

  function updateStats(stats) {
    if (!stats) return;
    document.querySelectorAll("[data-stat]").forEach(function (node) {
      var key = node.getAttribute("data-stat");
      if (stats[key] == null) return;
      node.textContent = key.endsWith("count") ? String(stats[key]) : money(stats[key]);
    });
    var hint = document.getElementById("timingHint");
    if (hint) hint.hidden = !stats.undated_count;
  }

  function applyStatus(orderId, reportId) {
    var order = orderById(orderId);
    if (!order) return;
    var status = selectedStatus(orderId);
    if (status === "تم الطلب") {
      toast("اختر نتيجة التوصيل: واصل أو ملغي أو مؤجل", "warning");
      return;
    }
    if (status === "مؤجل") {
      setPostponeVisible(orderId, true);
      var date = selectedDate(orderId);
      if (!date) {
        toast("يرجى تحديد تاريخ التأجيل", "warning");
        var dateInput = document.querySelector('[data-postpone="' + orderId + '"] input, #detailDate');
        if (dateInput) dateInput.focus();
        return;
      }
      if (date < document.body.getAttribute("data-today")) {
        toast("تاريخ التأجيل لا يمكن أن يكون في الماضي", "warning");
        return;
      }
      confirmStatus(order, reportId, status, date);
      return;
    }
    confirmStatus(order, reportId, status, null);
  }

  function sendStatus(order, reportId, status, date) {
    if (savingOrders.has(order.id)) return;
    savingOrders.add(order.id);
    document.querySelectorAll('[data-apply="' + order.id + '"]').forEach(function (button) { button.disabled = true; });
    var body = { order_id: order.id, report_id: reportId || order.report_id || null, status: status };
    if (date) body.scheduled_date = date;
    api("/delivery-agent/update-order-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (data) {
      if (!data.success) {
        toast(data.error || "تعذر حفظ الحالة", "error");
        return;
      }
      order.applied_status = data.applied_status || status;
      document.querySelectorAll('.da-status[data-order-id="' + order.id + '"]').forEach(function (select) { select.value = order.applied_status; });
      order.pending_accountant = true;
      if (data.report_id) order.report_id = data.report_id;
      order.scheduled_date = data.scheduled_date || null;
      if (status === "مؤجل") order.note = order.note || "مؤجل";
      else if (order.note === "مؤجل") order.note = "";
      document.querySelectorAll('.da-date[data-order-id="' + order.id + '"]').forEach(function (input) { input.value = order.scheduled_date || ""; });
      setPostponeVisible(order.id, status === "مؤجل");
      syncBadges(order);
      updateStats(data.stats);
      filterRows("orderSearch", "[data-active-row]");
      var wait = document.querySelector('[data-wait="' + order.id + '"]');
      if (wait) wait.hidden = false;
      fillDetail(order);
      toast("تم حفظ تحديث الطلب بنجاح", "success");
      if (data.all_complete) {
        var banner = document.querySelector('[data-ready="' + (order.report_id || "") + '"]');
        if (banner) banner.hidden = false;
        var number = order.report_number && order.report_number.indexOf("AGT-") === 0 ? order.report_number : "";
        toast(number
          ? "تم تحديث جميع طلبات الكشف " + number + " وتم إشعار المحاسب ليقوم بالتنفيذ."
          : "تم تحديث جميع طلبات الكشف وتم إشعار المحاسب ليقوم بالتنفيذ.", "info");
      }
    }).catch(function () {
      toast("تعذر الاتصال بالخادم؛ لم يتم تأكيد حفظ الحالة", "error");
    }).finally(function () {
      savingOrders.delete(order.id);
      document.querySelectorAll('[data-apply="' + order.id + '"]').forEach(function (button) { button.disabled = false; });
    });
  }

  function openNote(orderId, reportId) {
    var order = orderById(orderId);
    var sheet = document.getElementById("noteSheet");
    document.getElementById("noteOrderId").value = orderId;
    document.getElementById("noteReportId").value = reportId || (order && order.report_id) || "";
    document.getElementById("noteInput").value = (order && order.agent_note) || "";
    sheet.hidden = false;
    focusSheet("noteSheet");
    document.getElementById("noteInput").focus({ preventScroll: true });
  }

  function closeNote() {
    document.getElementById("noteSheet").hidden = true;
    syncModalLock();
  }

  function saveNote() {
    if (noteSaving) return;
    var orderId = document.getElementById("noteOrderId").value;
    var reportId = document.getElementById("noteReportId").value;
    var text = document.getElementById("noteInput").value.trim();
    if (text.length > 1000) {
      toast("الملاحظة طويلة جداً (الحد 1000 حرف)", "warning");
      return;
    }
    noteSaving = true;
    document.getElementById("noteSave").disabled = true;
    api("/delivery-agent/update-order-note", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order_id: Number(orderId), report_id: reportId ? Number(reportId) : null, agent_note: text })
    }).then(function (data) {
      if (!data.success) {
        toast(data.error || "تعذر حفظ الملاحظة", "error");
        return;
      }
      var order = orderById(orderId);
      if (order) {
        order.agent_note = data.agent_note || "";
        syncBadges(order);
        fillDetail(order);
      }
      closeNote();
      toast(text ? "تم حفظ الملاحظة" : "تم مسح الملاحظة", "success");
    }).catch(function () {
      toast("تعذر حفظ الملاحظة", "error");
    }).finally(function () {
      noteSaving = false;
      document.getElementById("noteSave").disabled = false;
    });
  }

  function fillDetail(order) {
    if (!order) return;
    var sheet = document.getElementById("detailSheet");
    if (!sheet || sheet.hidden) return;
    document.getElementById("detailTitle").textContent = "طلب #" + order.id;
    document.getElementById("detailCustomer").textContent = order.customer_name || "—";
    var phone = document.getElementById("detailPhone");
    phone.textContent = order.phone || "لا يوجد رقم";
    phone.href = order.phone ? "tel:" + order.phone : "#";
    document.getElementById("detailAddress").textContent = order.address || "—";
    document.getElementById("detailCity").textContent = order.city || "—";
    document.getElementById("detailTotal").textContent = money(order.total);
    document.getElementById("detailPaid").textContent = money(order.paid_amount);
    document.getElementById("detailRemain").textContent = money(order.remaining);
    var status = document.getElementById("detailStatus");
    status.setAttribute("data-order-id", order.id);
    status.value = order.applied_status || (order.note === "مؤجل" ? "مؤجل" : "تم الطلب");
    document.getElementById("detailDate").value = order.scheduled_date || "";
    document.getElementById("detailDateWrap").hidden = status.value !== "مؤجل";
    document.getElementById("detailApply").textContent = order.applied_status ? "تعديل" : "تطبيق";
    document.getElementById("detailApply").setAttribute("data-apply", order.id);
    document.getElementById("detailApply").setAttribute("data-report-id", order.report_id || "");
    document.getElementById("detailNoteBtn").setAttribute("data-open-note", order.id);
    document.getElementById("detailNoteBtn").setAttribute("data-report-id", order.report_id || "");
    document.getElementById("detailNoteBtn").classList.toggle("has-note", !!order.agent_note);
    document.getElementById("detailNoteText").textContent = order.agent_note || "";
    document.getElementById("detailWait").hidden = !order.applied_status;
    var itemsHost = document.getElementById("detailItems");
    itemsHost.replaceChildren();
    (order.items || []).forEach(function (item) {
      var row = document.createElement("div");
      row.className = "da-item-row";
      var name = document.createElement("span");
      name.textContent = (item.name || "منتج") + (item.color ? " · " + item.color : "");
      var count = document.createElement("strong");
      count.textContent = "× " + item.quantity;
      row.append(name, count);
      itemsHost.appendChild(row);
    });
    if (!itemsHost.childElementCount) itemsHost.textContent = "تفاصيل المنتجات غير متوفرة";
    document.getElementById("detailInstructions").textContent = order.note && order.note !== "مؤجل" ? order.note : "لا توجد تعليمات إضافية";
    var map = document.getElementById("detailMap");
    var openMap = document.getElementById("detailOpenMap");
    if (order.location_lat != null && order.location_lng != null) {
      if (openMap) {
        openMap.hidden = false;
        openMap.setAttribute("data-open-map", order.id);
      }
      if (map) map.hidden = true;
    } else if (order.location_url) {
      if (openMap) openMap.hidden = true;
      if (map) {
        map.hidden = false;
        map.href = order.map_url || "#";
        map.textContent = "فتح الرابط";
      }
    } else if (order.address) {
      if (openMap) openMap.hidden = true;
      if (map) {
        map.hidden = false;
        map.href = order.map_url || "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent([order.city, order.address].filter(Boolean).join(" "));
        map.textContent = "الخريطة";
      }
    } else if (map) {
      map.hidden = true;
      if (openMap) openMap.hidden = true;
    }
  }

  function openOrder(orderId) {
    var order = orderById(orderId);
    if (!order) return;
    document.getElementById("detailSheet").hidden = false;
    fillDetail(order);
    focusSheet("detailSheet");
    history.pushState({ view: "order", id: order.id }, "", location.pathname + location.search);
  }

  function closeDetail() {
    document.getElementById("detailSheet").hidden = true;
    syncModalLock();
  }

  function normalizeSearch(value) {
    return String(value || "").replace(/[٠-٩۰-۹]/g, function (digit) {
      return String("٠١٢٣٤٥٦٧٨٩".indexOf(digit) >= 0 ? "٠١٢٣٤٥٦٧٨٩".indexOf(digit) : "۰۱۲۳۴۵۶۷۸۹".indexOf(digit));
    }).replace(/[\u064B-\u065F\u0670]/g, "").replace(/[أإآ]/g, "ا").replace(/#/g, "").toLowerCase().trim();
  }

  function effectiveStatus(order) {
    return order.applied_status || (order.note === "مؤجل" ? "مؤجل" : "");
  }

  function filterRows(inputId, selector) {
    var input = document.getElementById(inputId);
    if (!input) return;
    var active = inputId === "orderSearch";
    var query = normalizeSearch(input.value).split(/\s+/).filter(Boolean);
    var doneFilter = document.getElementById("doneStatusFilter");
    var filter = active ? statusFilter : (doneFilter ? doneFilter.value : "all");
    var matched = new Map();
    var groups = {};
    document.querySelectorAll(selector).forEach(function (row) {
      var order = active ? orderById(row.getAttribute("data-open-order")) : null;
      var status = order ? effectiveStatus(order) : row.getAttribute("data-final-status");
      if (status === "تم التوصيل" || status === "Delivered") status = "واصل";
      if (["راجع", "مرتجع", "Canceled", "Returned"].indexOf(status) >= 0) status = "ملغي";
      var stateMatch = filter === "all" || (filter === "untouched" ? !status :
        filter === "waiting" ? !!(order && order.applied_status) : status === filter);
      var hay = normalizeSearch(row.getAttribute("data-search"));
      var visible = stateMatch && query.every(function (word) { return hay.indexOf(word) >= 0; });
      row.hidden = !visible;
      row.classList.toggle("is-hidden", !visible);
      if (visible) {
        var id = order ? order.id : row.getAttribute("data-search");
        matched.set(id, order ? Number(order.remaining || 0) : 0);
        if (order) {
          var key = row.getAttribute("data-group");
          if (!groups[key]) groups[key] = new Map();
          groups[key].set(order.id, Number(order.remaining || 0));
        }
      }
    });
    var result = document.getElementById(active ? "activeResults" : "doneResults");
    var total = Array.from(matched.values()).reduce(function (sum, value) { return sum + value; }, 0);
    if (result) result.textContent = matched.size + " طلب" + (active ? " · " + money(total) : " ضمن آخر 100 طلب");
    var empty = document.getElementById(active ? "activeNoResults" : "doneNoResults");
    if (empty) empty.hidden = matched.size !== 0;
    if (!active) return;
    var sort = document.getElementById("orderSort").value;
    document.querySelectorAll("[data-manifest]").forEach(function (heading) {
      var rows = groups[heading.getAttribute("data-manifest")];
      heading.hidden = sort !== "default" || !rows || rows.size === 0;
      if (!rows) return;
      var count = heading.querySelector("[data-group-count]");
      var amount = heading.querySelector("[data-group-total]");
      if (count) count.textContent = rows.size + " طلب";
      if (amount) amount.textContent = money(Array.from(rows.values()).reduce(function (a, b) { return a + b; }, 0));
    });
    document.querySelectorAll("#ordersCards, .da-table tbody").forEach(function (host) {
      var children = Array.from(host.children);
      children.forEach(function (row, index) {
        if (!row.hasAttribute("data-original-index")) row.setAttribute("data-original-index", index);
      });
      children.sort(function (a, b) {
        if (sort === "default") return Number(a.getAttribute("data-original-index")) - Number(b.getAttribute("data-original-index"));
        var first = orderById(a.getAttribute("data-open-order"));
        var second = orderById(b.getAttribute("data-open-order"));
        if (!first || !second) return first ? 1 : second ? -1 : 0;
        var one = sort === "date" ? first.scheduled_date || "9999" : [first.city, first.address].join(" ");
        var two = sort === "date" ? second.scheduled_date || "9999" : [second.city, second.address].join(" ");
        return one.localeCompare(two, "ar", { numeric: true }) || first.id - second.id;
      });
      children.forEach(function (row) { host.appendChild(row); });
    });
  }

  function timeLabel(iso) {
    if (!iso) return "";
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }

  function loadConversations(silent) {
    var list = document.getElementById("chatList");
    var error = document.getElementById("chatError");
    api("/messages/conversations", { headers: { "Accept": "application/json" } }, silent).then(function (data) {
      if (data._status === 403 || data.error) {
        list.replaceChildren();
        error.hidden = false;
        return;
      }
      error.hidden = true;
      var conversations = data.conversations || [];
      var seen = {};
      var html = "";
      conversations.forEach(function (item) {
        if (!contacts.some(function (person) { return Number(person.id) === Number(item.user_id); })) return;
        seen[item.user_id] = true;
        html += chatRow(item.user_id, item.user_name, item.last_message, item.last_message_time, item.unread_count);
      });
      contacts.forEach(function (person) {
        if (!seen[person.id]) html += chatRow(person.id, person.name, "ابدأ المحادثة", "", 0);
      });
      list.innerHTML = html || '<div class="da-empty"><h3>لا توجد محادثات</h3><p>ستظهر هنا مراسلات الإدارة.</p></div>';
    }).catch(function () {
      error.hidden = false;
    });
  }

  function chatRow(id, name, preview, time, unread) {
    return '<button type="button" class="da-chat-item" data-open-room="' + id + '" data-room-name="' + escapeAttr(name || "") + '">' +
      "<div><strong>" + escapeHtml(name || "محادثة") + "</strong><small>" + escapeHtml(preview || "") + "</small></div>" +
      "<div>" + (unread ? '<span class="da-unread">' + (unread > 99 ? "99+" : unread) + "</span>" : "") +
      "<small>" + escapeHtml(timeLabel(time)) + "</small></div></button>";
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function escapeAttr(value) { return escapeHtml(value); }

  function openRoom(userId, name, fromHistory) {
    activeRoom = Number(userId);
    lastMessageId = 0;
    renderedMessageIds = new Set();
    document.getElementById("roomTitle").textContent = name || "محادثة";
    document.getElementById("roomList").innerHTML = '<div class="da-skeleton"></div>';
    showView("room");
    if (!fromHistory) {
      history.pushState({ view: "room", id: activeRoom, name: name }, "", location.pathname + location.search);
    }
    pullRoom(false);
    stopRoomPoll();
    roomTimer = setInterval(function () { pullRoom(true); }, 15000);
  }

  function stopRoomPoll() {
    if (roomTimer) clearInterval(roomTimer);
    roomTimer = null;
  }

  function pullRoom(silent) {
    if (!activeRoom) return;
    var url = "/messages/get/" + activeRoom + (lastMessageId ? "?after_id=" + lastMessageId : "");
    var requestedRoom = activeRoom;
    api(url, {}, silent).then(function (data) {
      if (requestedRoom !== activeRoom) return;
      if (!data.success) { if (!silent) toast(data.error || "تعذر تحميل المحادثة", "error"); return; }
      var box = document.getElementById("roomList");
      var followBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
      var initialLoad = !lastMessageId;
      if (!lastMessageId) box.innerHTML = "";
      var added = 0;
      (data.messages || []).forEach(function (msg) {
        if (renderedMessageIds.has(Number(msg.id))) return;
        renderedMessageIds.add(Number(msg.id));
        added += 1;
        lastMessageId = Math.max(lastMessageId, Number(msg.id) || 0);
        var mine = Number(msg.sender_id) === agentUserId;
        var bubble = document.createElement("div");
        bubble.className = "da-bubble" + (mine ? " mine" : "");
        bubble.innerHTML = "<div>" + escapeHtml(msg.content || "") + "</div><time>" + escapeHtml(msg.sender_name || "") + " · " + escapeHtml(timeLabel(msg.created_at)) + "</time>";
        box.appendChild(bubble);
      });
      if ((initialLoad || followBottom) && added) {
        box.scrollTop = box.scrollHeight;
      }
    }).catch(function () {
      if (!silent) toast("تعذر الاتصال لتحميل المحادثة", "error");
    });
  }

  function sendChat() {
    var input = document.getElementById("roomInput");
    var content = input.value.trim();
    if (!content || !activeRoom || chatSending) return;
    chatSending = true;
    document.getElementById("roomSend").disabled = true;
    var recipient = activeRoom;
    input.value = "";
    api("/messages/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ receiver_id: recipient, content: content })
    }).then(function (data) {
      if (!data.success) {
        toast(data.error || "تعذر إرسال الرسالة", "error");
        if (recipient === activeRoom) input.value = content;
        return;
      }
      if (recipient === activeRoom) pullRoom(true);
    }).catch(function () {
      toast("تعذر إرسال الرسالة", "error");
      if (recipient === activeRoom) input.value = content;
    }).finally(function () {
      chatSending = false;
      document.getElementById("roomSend").disabled = false;
    });
  }

  function refreshUnread() {
    api("/messages/unread-count", {}, true).then(function (data) {
      var count = parseInt(data.unread_count || 0, 10);
      document.querySelectorAll("[data-unread]").forEach(function (badge) {
        if (count > 0) {
          badge.style.display = "grid";
          badge.textContent = count > 99 ? "99+" : String(count);
        } else {
          badge.style.display = "none";
        }
      });
    }).catch(function () {});
  }

  function bind() {
    var sheets = document.querySelectorAll(".da-sheet-backdrop");
    var modalObserver = new MutationObserver(syncModalLock);
    sheets.forEach(function (sheet) { modalObserver.observe(sheet, { attributes: true, attributeFilter: ["hidden"] }); });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Tab") return;
      var open = Array.from(sheets).filter(function (sheet) { return !sheet.hidden; });
      open.sort(function (a, b) { return Number(getComputedStyle(b).zIndex) - Number(getComputedStyle(a).zIndex); });
      if (!open.length) return;
      var fields = Array.from(open[0].querySelectorAll('button:not(:disabled), a[href], input:not([type="hidden"]), select, textarea'))
        .filter(function (field) { return field.getClientRects().length > 0; });
      if (!fields.length) return;
      var first = fields[0], last = fields[fields.length - 1];
      if (event.shiftKey && (document.activeElement === first || !open[0].contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !open[0].contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    });
    document.body.addEventListener("click", function (event) {
      var tab = event.target.closest("[data-tab]");
      if (tab) {
        var name = tab.getAttribute("data-tab");
        openView(name, { view: name });
      }
      var details = event.target.closest("[data-details]");
      if (details) openOrder(details.getAttribute("data-details"));
      var filter = event.target.closest("[data-filter]");
      if (filter) {
        statusFilter = filter.getAttribute("data-filter");
        document.querySelectorAll("[data-filter]").forEach(function (button) {
          var selected = button === filter;
          button.classList.toggle("is-active", selected);
          button.setAttribute("aria-pressed", String(selected));
        });
        filterRows("orderSearch", "[data-active-row]");
      }
      var clear = event.target.closest("[data-clear-search]");
      if (clear) {
        var isActive = clear.getAttribute("data-clear-search") === "active";
        document.getElementById(isActive ? "orderSearch" : "doneSearch").value = "";
        if (isActive) document.querySelector('[data-filter="all"]').click();
        else { document.getElementById("doneStatusFilter").value = "all"; filterRows("doneSearch", "[data-done-row]"); }
      }
      var openOrderBtn = event.target.closest("[data-open-order]");
      if (openOrderBtn && !event.target.closest("a,button,select,input,label")) {
        openOrder(openOrderBtn.getAttribute("data-open-order"));
      }
      var apply = event.target.closest("[data-apply]");
      if (apply) applyStatus(apply.getAttribute("data-apply"), apply.getAttribute("data-report-id"));
      var note = event.target.closest("[data-open-note]");
      if (note) openNote(note.getAttribute("data-open-note"), note.getAttribute("data-report-id"));
      var room = event.target.closest("[data-open-room]");
      if (room) openRoom(room.getAttribute("data-open-room"), room.getAttribute("data-room-name"));
    });

    document.querySelectorAll(".da-date").forEach(function (input) {
      input.addEventListener("change", function () {
        var id = input.getAttribute("data-order-id");
        if (!id) return;
        document.querySelectorAll('.da-date[data-order-id="' + id + '"]').forEach(function (other) {
          other.value = input.value;
        });
      });
    });
    document.querySelectorAll(".da-status").forEach(function (select) {
      select.addEventListener("change", function () {
        var id = select.getAttribute("data-order-id");
        setPostponeVisible(id, select.value === "مؤجل");
        document.querySelectorAll('.da-status[data-order-id="' + id + '"]').forEach(function (other) {
          other.value = select.value;
        });
      });
    });

    var search = document.getElementById("orderSearch");
    if (search) search.addEventListener("input", function () { filterRows("orderSearch", "[data-active-row]"); });
    var sortOrders = document.getElementById("orderSort");
    if (sortOrders) sortOrders.addEventListener("change", function () { filterRows("orderSearch", "[data-active-row]"); });
    var doneFilter = document.getElementById("doneStatusFilter");
    if (doneFilter) doneFilter.addEventListener("change", function () { filterRows("doneSearch", "[data-done-row]"); });
    document.getElementById("statusConfirmCancel").addEventListener("click", closeStatusConfirm);
    document.getElementById("statusConfirmSave").addEventListener("click", function () {
      var pending = pendingStatus;
      closeStatusConfirm();
      if (pending) sendStatus(pending.order, pending.reportId, pending.status, pending.date);
    });
    document.getElementById("refreshOrders").addEventListener("click", function () {
      var dirty = document.getElementById("roomInput").value.trim() || !document.getElementById("noteSheet").hidden || savingOrders.size;
      if (!dirty || window.confirm("توجد كتابة أو عملية حفظ جارية. تريد تحديث الصفحة؟")) location.reload();
    });
    var doneSearch = document.getElementById("doneSearch");
    if (doneSearch) doneSearch.addEventListener("input", function () { filterRows("doneSearch", "[data-done-row]"); });

    document.getElementById("detailStatus").addEventListener("change", function () {
      document.getElementById("detailDateWrap").hidden = this.value !== "مؤجل";
    });
    document.getElementById("detailBack").addEventListener("click", function () { history.back(); });
    document.getElementById("roomBack").addEventListener("click", function () { history.back(); });
    document.getElementById("noteCancel").addEventListener("click", closeNote);
    document.getElementById("noteSave").addEventListener("click", saveNote);
    document.getElementById("noteSheet").addEventListener("click", function (event) {
      if (event.target.id === "noteSheet") closeNote();
    });
    document.getElementById("roomSend").addEventListener("click", sendChat);
    document.getElementById("roomInput").addEventListener("keydown", function (event) {
      if (event.key === "Enter") sendChat();
    });
    document.getElementById("chatRetry").addEventListener("click", function () { loadConversations(false); });
    document.getElementById("offlineRetry").addEventListener("click", function () { location.reload(); });

    var menu = document.getElementById("accountMenu");
    var menuBtn = document.getElementById("accountBtn");
    menuBtn.addEventListener("click", function (event) {
      event.stopPropagation();
      var open = menu.classList.toggle("is-open");
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.getElementById("openAccount").addEventListener("click", function () {
      menu.classList.remove("is-open");
      openView("account", { view: "account" });
    });
    document.addEventListener("click", function (event) {
      if (!menu.contains(event.target)) {
        menu.classList.remove("is-open");
        menuBtn.setAttribute("aria-expanded", "false");
      }
    });

    window.addEventListener("popstate", function (event) {
      var state = event.state || { view: "active" };
      if (state.view === "order") {
        document.getElementById("detailSheet").hidden = false;
        fillDetail(orderById(state.id));
        focusSheet("detailSheet");
        return;
      }
      closeDetail();
      closeNote();
      closeStatusConfirm();
      if (state.view === "room") {
        openRoom(state.id, state.name, true);
        return;
      }
      showView(state.view || "active");
    });

    window.addEventListener("offline", function () {
      document.getElementById("offlineScreen").hidden = false;
    });
    window.addEventListener("online", function () {
      document.getElementById("offlineScreen").hidden = true;
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeStatusConfirm();
        closeNote();
        menu.classList.remove("is-open");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bind();
    filterRows("orderSearch", "[data-active-row]");
    filterRows("doneSearch", "[data-done-row]");
    history.replaceState({ view: "active" }, "", location.pathname + location.search);
    if (!navigator.onLine) document.getElementById("offlineScreen").hidden = false;
    refreshUnread();
    chatTimer = setInterval(refreshUnread, 15000);
    var splash = document.getElementById("daSplash");
    if (splash) {
      setTimeout(function () {
        splash.classList.add("is-hide");
        setTimeout(function () { splash.remove(); }, 220);
      }, 500);
    }
  });
})();
