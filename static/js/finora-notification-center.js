(function (window, document) {
  "use strict";

  var STORAGE_KEY = "finora_app_notifications";
  var LEGACY_KEYS = ["finora_dashboard_notifications", "finora_cash_notifications"];
  var MAX_ITEMS = 100;
  var panels = [];
  var migrated = false;

  function loadRaw() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch (_) {
      return [];
    }
  }

  function saveRaw(items) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)));
  }

  function migrateLegacy() {
    if (migrated) return;
    migrated = true;
    var merged = loadRaw();
    var seen = {};
    merged.forEach(function (n) {
      if (n && n.sourceId) seen[n.sourceId] = true;
    });
    LEGACY_KEYS.forEach(function (key) {
      try {
        var legacy = JSON.parse(localStorage.getItem(key) || "[]");
        if (!Array.isArray(legacy)) return;
        legacy.forEach(function (n) {
          if (!n || !n.message) return;
          if (n.sourceId && seen[n.sourceId]) return;
          merged.push(n);
          if (n.sourceId) seen[n.sourceId] = true;
        });
        localStorage.removeItem(key);
      } catch (_) { /* ignore */ }
    });
    merged.sort(function (a, b) {
      return new Date(b.time || 0) - new Date(a.time || 0);
    });
    saveRaw(merged);
  }

  function formatNumber(num) {
    if (num === null || num === undefined || isNaN(num)) return "0";
    return Number(num).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function formatTime(iso) {
    try {
      var d = new Date(iso);
      var diffMin = Math.floor((Date.now() - d) / 60000);
      if (diffMin < 1) return "الآن";
      if (diffMin < 60) return "منذ " + diffMin + " د";
      var diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24) return "منذ " + diffHr + " س";
      return d.toLocaleDateString("ar-IQ", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return "";
    }
  }

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function cleanName(value) {
    var name = String(value || "").trim();
    return name || "";
  }

  function parseEmployeeFromMessage(message) {
    var text = String(message || "");
    var match = text.match(/(?:—\s*)?الموظف\s*:\s*(.+)$/);
    if (!match) return { message: text, employeeName: "" };
    return {
      message: text.replace(/\s*(?:—\s*)?الموظف\s*:\s*.+$/, "").trim(),
      employeeName: cleanName(match[1]),
    };
  }

  function kindMeta(kind, category) {
    var k = kind || "general";
    if (k === "order") return { icon: "fa-box", label: "طلب", tone: "order" };
    if (k === "agent_report") return { icon: "fa-truck", label: "كشف مندوب", tone: "agent" };
    if (k === "audit") return { icon: "fa-clipboard-check", label: "تدقيق", tone: "success" };
    if (category === "error") return { icon: "fa-circle-exclamation", label: "تنبيه", tone: "error" };
    if (category === "warning") return { icon: "fa-triangle-exclamation", label: "تنبيه", tone: "warning" };
    if (category === "order") return { icon: "fa-box", label: "طلب", tone: "order" };
    return { icon: "fa-bell", label: "إشعار", tone: "info" };
  }

  function normalizeItem(n) {
    if (!n) return n;
    var parsed = (!n.employeeName && n.message) ? parseEmployeeFromMessage(n.message) : null;
    var employeeName = cleanName(n.employeeName || (parsed && parsed.employeeName) || "");
    var message = parsed ? parsed.message : String(n.message || "").trim();
    var title = cleanName(n.title);
    var detail = cleanName(n.detail);
    if (!title && !detail) {
      title = message;
    }
    return Object.assign({}, n, {
      message: message,
      title: title,
      detail: detail,
      employeeName: employeeName,
    });
  }

  function unreadCount(items) {
    return items.filter(function (n) { return !n.read; }).length;
  }

  function notifyPanels(items) {
    panels.forEach(function (panel) {
      if (panel && typeof panel.render === "function") panel.render(items);
    });
    document.dispatchEvent(new CustomEvent("finora:notifications-changed", {
      detail: { items: items, unread: unreadCount(items) },
    }));
  }

  function addEntry(entry, items) {
    var list = items || loadRaw();
    if (!entry || (!entry.message && !entry.title)) return list;
    if (entry.sourceId && list.some(function (n) { return n.sourceId === entry.sourceId; })) {
      return list;
    }
    list.unshift(entry);
    list.sort(function (a, b) {
      return new Date(b.time || 0) - new Date(a.time || 0);
    });
    saveRaw(list);
    notifyPanels(list);
    return list;
  }

  var boundPrefixes = {};

  var FinoraNotificationCenter = {
    load: function () {
      migrateLegacy();
      return loadRaw();
    },

    save: function (items) {
      saveRaw(items);
      notifyPanels(items);
      return items;
    },

    add: function (message, category, options) {
      migrateLegacy();
      options = options || {};
      var parsed = parseEmployeeFromMessage(message);
      var employeeName = cleanName(options.employeeName || parsed.employeeName);
      var title = cleanName(options.title);
      var detail = cleanName(options.detail);
      var body = cleanName(parsed.message || message);
      if (!title) title = body;
      var entry = {
        id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
        message: body,
        title: title,
        detail: detail,
        employeeName: employeeName,
        category: category || "success",
        kind: options.kind || "general",
        sourceId: options.sourceId || null,
        href: options.href || null,
        time: new Date().toISOString(),
        read: false,
      };
      return addEntry(entry);
    },

    addOrder: function (order) {
      if (!order || !order.id) return loadRaw();
      var total = formatNumber(order.total || 0);
      var customer = order.customer || "زبون";
      var employee = cleanName(order.employee || order.employee_name);
      var title = "طلب جديد #" + order.id;
      var detail = customer + " — " + total + " د.ع";
      return this.add(title + " — " + detail, "order", {
        kind: "order",
        title: title,
        detail: detail,
        employeeName: employee,
        sourceId: "order:" + order.id,
        href: "/orders/",
      });
    },

    addAgentReport: function (report) {
      if (!report) return loadRaw();
      var agent = cleanName(report.agent_name) || "مندوب";
      var reportNo = report.report_number || ("#" + report.id);
      var employee = cleanName(report.employee_name || report.created_by || report.employee);
      var title = "كشف المندوب جاهز للتنفيذ";
      var detail = reportNo + " — المندوب: " + agent;
      return this.add(title + " — " + detail, "order", {
        kind: "agent_report",
        title: title,
        detail: detail,
        employeeName: employee,
        sourceId: "agent_report:" + report.id,
        href: "/agents/pending-execution",
      });
    },

    ingestFlash: function (flashDataId) {
      migrateLegacy();
      var el = flashDataId ? document.getElementById(flashDataId) : null;
      if (!el) return loadRaw();
      var items = loadRaw();
      try {
        JSON.parse(el.textContent || "[]").forEach(function (pair) {
          if (!Array.isArray(pair) || pair.length < 2) return;
          var raw = String(pair[1] || "");
          var parsed = parseEmployeeFromMessage(raw);
          var kind = "general";
          var title = parsed.message;
          var detail = "";
          if (/تدقيق/.test(parsed.message)) {
            kind = "audit";
            var parts = parsed.message.split(":");
            title = cleanName(parts[0]) || "تدقيق";
            detail = cleanName(parts.slice(1).join(":"));
          }
          items = FinoraNotificationCenter.add(parsed.message, pair[0] || "success", {
            kind: kind,
            title: title,
            detail: detail,
            employeeName: parsed.employeeName,
            sourceId: "flash:" + raw,
          });
        });
      } catch (_) { /* ignore */ }
      return items;
    },

    bindPanel: function (config) {
      migrateLegacy();
      config = config || {};
      var prefix = config.prefix || "dash";
      if (boundPrefixes[prefix]) return boundPrefixes[prefix];

      var ids = {
        btn: prefix + "NotifBtn",
        badge: prefix + "NotifBadge",
        overlay: prefix + "NotifOverlay",
        panel: prefix + "NotifPanel",
        list: prefix + "NotifList",
        subtitle: prefix + "NotifSubtitle",
        markRead: prefix + "NotifMarkRead",
        clear: prefix + "NotifClear",
        close: prefix + "NotifClose",
      };
      var itemClass = config.itemClass || (prefix + "-notif-item");
      var emptyClass = config.emptyClass || (prefix + "-notif-empty");
      var bodyClass = config.bodyClass || (prefix + "-notif-open");
      var flashDataId = config.flashDataId || null;

      var els = {};
      Object.keys(ids).forEach(function (k) {
        els[k] = document.getElementById(ids[k]);
      });
      if (!els.btn || !els.panel) return null;

      function render(items) {
        var count = unreadCount(items);
        if (els.badge) {
          els.badge.hidden = count <= 0;
          if (count > 0) els.badge.textContent = count > 99 ? "99+" : String(count);
        }
        if (els.subtitle) {
          if (!items.length) els.subtitle.textContent = "لا توجد إشعارات جديدة";
          else if (count > 0) els.subtitle.textContent = count + " غير مقروء · " + items.length + " إجمالي";
          else els.subtitle.textContent = items.length + " إشعار · الكل مقروء";
        }
        if (els.markRead) els.markRead.disabled = count <= 0;
        if (els.clear) els.clear.disabled = items.length <= 0;
        if (!els.list) return;
        if (!items.length) {
          els.list.innerHTML =
            '<div class="' + emptyClass + '"><i class="fas fa-bell-slash"></i><div>لا توجد إشعارات</div></div>';
          return;
        }
        var sorted = items.slice().sort(function (a, b) {
          return new Date(b.time || 0) - new Date(a.time || 0);
        });
        els.list.innerHTML = sorted.map(function (raw) {
          var n = normalizeItem(raw);
          var meta = kindMeta(n.kind, n.category);
          var clickAttr = n.href
            ? ' data-href="' + escapeHtml(n.href) + '" style="cursor:pointer;"'
            : "";
          var detailHtml = n.detail
            ? '<div class="' + prefix + '-notif-detail">' + escapeHtml(n.detail) + "</div>"
            : "";
          var employeeHtml = n.employeeName
            ? '<div class="' + prefix + '-notif-employee"><i class="fas fa-user"></i><span>الموظف: ' +
              escapeHtml(n.employeeName) + "</span></div>"
            : "";
          return (
            '<div class="' + itemClass + (n.read ? "" : " unread") + " tone-" + meta.tone + '"' +
            clickAttr + ' data-id="' + escapeHtml(String(n.id || "")) + '">' +
            '<div class="' + prefix + "-notif-icon " + meta.tone + '"><i class="fas ' + meta.icon + '"></i></div>' +
            '<div class="' + prefix + '-notif-msg">' +
            '<div class="' + prefix + '-notif-title">' + escapeHtml(n.title || n.message || "") + "</div>" +
            detailHtml +
            employeeHtml +
            '<div class="' + prefix + '-notif-time">' + formatTime(n.time) + "</div>" +
            "</div></div>"
          );
        }).join("");
      }

      function openPanel() {
        if (!els.panel) return;
        if (config.positionPanel) config.positionPanel(els);
        els.panel.classList.add("open");
        if (els.overlay) els.overlay.classList.add("open");
        els.btn.setAttribute("aria-expanded", "true");
        document.body.classList.add(bodyClass);
        if (config.positionPanel) {
          requestAnimationFrame(function () { config.positionPanel(els); });
        }
      }

      function closePanel() {
        if (!els.panel) return;
        var items = loadRaw().map(function (n) {
          return Object.assign({}, n, { read: true });
        });
        saveRaw(items);
        render(items);
        els.panel.classList.remove("open");
        if (els.overlay) els.overlay.classList.remove("open");
        els.btn.setAttribute("aria-expanded", "false");
        document.body.classList.remove(bodyClass);
      }

      els.btn.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (els.panel.classList.contains("open")) closePanel();
        else openPanel();
      });
      if (els.overlay) els.overlay.addEventListener("click", closePanel);
      if (els.close) els.close.addEventListener("click", closePanel);
      if (els.markRead) {
        els.markRead.addEventListener("click", function () {
          render(FinoraNotificationCenter.save(loadRaw().map(function (n) {
            return Object.assign({}, n, { read: true });
          })));
        });
      }
      if (els.clear) {
        els.clear.addEventListener("click", function () {
          if (!confirm("مسح جميع الإشعارات؟")) return;
          render(FinoraNotificationCenter.save([]));
        });
      }
      if (els.list) {
        els.list.addEventListener("click", function (e) {
          var item = e.target.closest("[data-href]");
          if (item && item.getAttribute("data-href")) {
            window.location.href = item.getAttribute("data-href");
          }
        });
      }

      var panelApi = {
        render: render,
        open: openPanel,
        close: closePanel,
      };
      panels.push(panelApi);
      boundPrefixes[prefix] = panelApi;

      var initial = flashDataId
        ? FinoraNotificationCenter.ingestFlash(flashDataId)
        : loadRaw();
      render(initial);
      return panelApi;
    },
  };

  function positionAnchoredPanel(els) {
    if (!els.panel || !els.btn || window.innerWidth < 768) {
      if (els.panel) {
        els.panel.style.top = "";
        els.panel.style.right = "";
        els.panel.style.left = "";
      }
      return;
    }
    var rect = els.btn.getBoundingClientRect();
    var panelWidth = Math.min(400, window.innerWidth - 24);
    var gap = 10;
    var top = rect.bottom + gap;
    var right = window.innerWidth - rect.right;
    if (top + 420 > window.innerHeight) top = Math.max(gap, rect.top - 420 - gap);
    if (right + panelWidth > window.innerWidth - 12) right = window.innerWidth - panelWidth - 12;
    if (right < 12) right = 12;
    els.panel.style.top = top + "px";
    els.panel.style.right = right + "px";
    els.panel.style.left = "auto";
  }

  function autoBindKnownPanels() {
    if (document.getElementById("dashNotifBtn")) {
      FinoraNotificationCenter.bindPanel({
        prefix: "dash",
        flashDataId: "dashFlashData",
      });
    }
    if (document.getElementById("cashNotifBtn")) {
      FinoraNotificationCenter.bindPanel({
        prefix: "cash",
        flashDataId: "cashFlashData",
        positionPanel: positionAnchoredPanel,
      });
    }
  }

  var lastOrderId = null;
  var knownReadyAgentReportIds = null;
  var orderPollTimer = null;

  function checkNewOrders() {
    fetch("/api/index/new-orders")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (lastOrderId === null) {
          lastOrderId = data.last_order_id;
          return;
        }
        if (data.last_order_id && data.last_order_id > lastOrderId) {
          var fresh = (data.new_orders || []).filter(function (order) {
            return order && order.id > lastOrderId;
          });
          fresh.forEach(function (order) {
            FinoraNotificationCenter.addOrder(order);
          });
          if (fresh.length && typeof window.showToast === "function") {
            if (fresh.length === 1) {
              var order = fresh[0];
              var emp = order.employee || order.employee_name || "";
              window.showToast(
                "طلب جديد #" + order.id + "\n" +
                (order.customer || "زبون") + " — " + formatNumber(order.total || 0) + " د.ع" +
                (emp ? "\nالموظف: " + emp : ""),
                "order",
                4000,
                { soundType: "order", href: "/orders/", groupKey: "new-orders" }
              );
            } else {
              window.showToast(
                fresh.length + " طلبات جديدة\nاضغط لعرض الطلبات",
                "order",
                4500,
                { soundType: "order", href: "/orders/", groupKey: "new-orders" }
              );
            }
          }
          lastOrderId = data.last_order_id;
          document.dispatchEvent(new CustomEvent("finora:new-orders", { detail: data }));
        }
      })
      .catch(function (err) {
        console.error("Error checking new orders:", err);
      });
  }

  function checkAgentReportsReady() {
    fetch("/api/index/agent-reports-pending")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var ids = data.ready_report_ids || [];
        document.dispatchEvent(new CustomEvent("finora:agent-reports-changed", { detail: data }));
        if (knownReadyAgentReportIds === null) {
          knownReadyAgentReportIds = new Set(ids);
          return;
        }
        var newlyReady = [];
        ids.forEach(function (id) {
          if (!knownReadyAgentReportIds.has(id)) {
            var report = (data.ready_reports || []).find(function (r) { return r.id === id; });
            FinoraNotificationCenter.addAgentReport(report || { id: id });
            newlyReady.push(report || { id: id });
          }
        });
          if (newlyReady.length && typeof window.showToast === "function") {
            if (newlyReady.length === 1) {
              var report = newlyReady[0];
              var agentLabel = report.agent_name || "";
              var reportLabel = report.report_number || ("#" + report.id);
              var empLabel = report.employee_name || report.created_by || "";
              window.showToast(
                "كشف المندوب جاهز للتنفيذ\n" + reportLabel +
                (agentLabel ? " — المندوب: " + agentLabel : "") +
                (empLabel ? "\nالموظف: " + empLabel : ""),
                "order",
                4500,
                {
                  soundType: "order",
                  href: "/agents/pending-execution",
                  groupKey: "agent-reports-ready",
                }
              );
            } else {
              window.showToast(
                newlyReady.length + " كشوف مندوب جاهزة للتنفيذ\nاضغط لفتح صفحة التنفيذ",
                "order",
                5000,
                {
                  soundType: "order",
                  href: "/agents/pending-execution",
                  groupKey: "agent-reports-ready",
                }
              );
            }
          }
        knownReadyAgentReportIds = new Set(ids);
      })
      .catch(function (err) {
        console.error("Error checking agent reports:", err);
      });
  }

  FinoraNotificationCenter.startRealtime = function (intervalMs) {
    if (orderPollTimer) return;
    var ms = intervalMs || 3000;
    checkNewOrders();
    checkAgentReportsReady();
    orderPollTimer = window.setInterval(function () {
      checkNewOrders();
      checkAgentReportsReady();
    }, ms);
  };

  FinoraNotificationCenter.stopRealtime = function () {
    if (orderPollTimer) {
      window.clearInterval(orderPollTimer);
      orderPollTimer = null;
    }
  };

  window.FinoraNotificationCenter = FinoraNotificationCenter;

  // Content scripts often run before this file loads, so auto-bind here.
  // At this point previous HTML (btn/panel) is already in the DOM.
  autoBindKnownPanels();

  document.addEventListener("DOMContentLoaded", function () {
    migrateLegacy();
    autoBindKnownPanels();
    if (document.body && document.body.dataset && document.body.dataset.userLoggedIn === "1") {
      FinoraNotificationCenter.startRealtime(3000);
    }
  });

  window.addEventListener("beforeunload", function () {
    document.body.classList.remove("dash-notif-open", "cash-notif-open");
  });
})(window, document);
