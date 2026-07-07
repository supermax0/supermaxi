/**
 * تنسيق آمن لردود المساعد المالي (بدون تنفيذ HTML من المصدر).
 * يُستخدم في صفحة المحادثة وكتلة التحليل في لوحة التحكم.
 */
(function (global) {
  "use strict";

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function linkInvoices(text) {
    return String(text || "").replace(/#(\d+)/g, function (match, id) {
      return '<a class="ai-fmt-link" href="/orders?open_details=' + encodeURIComponent(id) + '" target="_blank" rel="noopener">#' + id + "</a>";
    });
  }

  function parseMetricParts(line) {
    return String(line || "")
      .split("|")
      .map(function (part) { return part.trim().replace(/\.$/, ""); })
      .filter(Boolean);
  }

  function renderProductEvidence(lines, startIndex) {
    const first = lines[startIndex] || "";
    const match = first.match(/^-\s*المنتج\s*#?(\d+)\s*:\s*(.*)$/);
    if (!match) return null;

    const productId = match[1];
    const detailParts = parseMetricParts(match[2]);
    const productName = detailParts.shift() || ("منتج #" + productId);
    const stats = detailParts;
    const stockRows = [];
    const orders = [];
    const movements = [];
    let i = startIndex + 1;

    while (i < lines.length) {
      const line = lines[i] || "";
      if (/^-\s*المنتج\s*#?\d+/.test(line) || /^(الاستنتاج|الأدلة من النظام|النقاط المهمة|المخاطر|الخطوات المقترحة)\s*:/.test(line)) {
        break;
      }
      const trimmed = line.replace(/^-\s*/, "").trim();
      const branchMatch = trimmed.match(/^(.+?):\s*نظام\s*([-\d,]+)،\s*محجوز\/جاري الشحن\s*([-\d,]+)،\s*قابل للبيع\s*([-\d,]+)/);
      if (branchMatch) {
        stockRows.push({
          branch: branchMatch[1],
          system: branchMatch[2],
          reserved: branchMatch[3],
          salable: branchMatch[4]
        });
      } else if (/آخر الطلبات\s*:/.test(trimmed)) {
        trimmed.replace(/#(\d+)\s*([^|#]*)/g, function (_, id, text) {
          orders.push({ id: id, text: (text || "").trim() });
          return "";
        });
      } else if (/آخر الحركات\s*:/.test(trimmed)) {
        const movementText = trimmed.replace(/^آخر الحركات\s*:\s*/, "");
        movementText.split("|").map(function (x) { return x.trim(); }).filter(Boolean).slice(0, 5).forEach(function (x) {
          movements.push(x);
        });
      }
      i++;
    }

    const statHtml = stats.map(function (stat) {
      const parts = stat.split(/\s+/);
      const value = parts.pop() || "";
      const label = parts.join(" ") || stat;
      return '<span class="ai-fmt-stat"><small>' + escapeHtml(label) + '</small><strong>' + escapeHtml(value) + "</strong></span>";
    }).join("");

    const stockHtml = stockRows.length ? (
      '<div class="ai-fmt-table-wrap"><table class="ai-fmt-table"><thead><tr><th>الفرع</th><th>النظام</th><th>محجوز/شحن</th><th>قابل للبيع</th></tr></thead><tbody>' +
      stockRows.map(function (row) {
        return "<tr><td>" + escapeHtml(row.branch) + "</td><td>" + escapeHtml(row.system) + "</td><td>" + escapeHtml(row.reserved) + "</td><td><strong>" + escapeHtml(row.salable) + "</strong></td></tr>";
      }).join("") +
      "</tbody></table></div>"
    ) : "";

    const ordersHtml = orders.length ? (
      '<div class="ai-fmt-row-title">روابط الطلبات</div><div class="ai-fmt-order-links">' +
      orders.slice(0, 8).map(function (order) {
        return '<a href="/orders?open_details=' + encodeURIComponent(order.id) + '" target="_blank" rel="noopener">طلب #' + escapeHtml(order.id) + '<small>' + escapeHtml(order.text) + "</small></a>";
      }).join("") +
      "</div>"
    ) : "";

    const movementHtml = movements.length ? (
      '<div class="ai-fmt-row-title">آخر الحركات</div><ul class="ai-fmt-mini-list">' +
      movements.map(function (move) { return "<li>" + linkInvoices(escapeHtml(move)) + "</li>"; }).join("") +
      "</ul>"
    ) : "";

    return {
      nextIndex: i,
      html:
        '<section class="ai-fmt-product-card">' +
          '<div class="ai-fmt-product-head"><div><small>منتج #' + escapeHtml(productId) + '</small><strong>' + escapeHtml(productName) + '</strong></div><a href="/inventory/" target="_blank" rel="noopener">المخزون</a></div>' +
          (statHtml ? '<div class="ai-fmt-stats">' + statHtml + "</div>" : "") +
          stockHtml +
          ordersHtml +
          movementHtml +
        "</section>"
    };
  }

  function renderStructured(raw) {
    const lines = String(raw || "").split(/\r?\n/).map(function (line) { return line.trim(); }).filter(Boolean);
    if (!lines.length) return "";

    const parts = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^الأدلة المحلية المباشرة\s*:/.test(line)) {
        parts.push('<h3 class="ai-fmt-section-title">الأدلة المحلية المباشرة</h3>');
        i++;
        continue;
      }
      if (/^-\s*المنتج\s*#?\d+/.test(line)) {
        const card = renderProductEvidence(lines, i);
        if (card) {
          parts.push(card.html);
          i = card.nextIndex;
          continue;
        }
      }
      const heading = line.match(/^(الاستنتاج|الأدلة من النظام|النقاط المهمة|المخاطر|الخطوات المقترحة)\s*:\s*(.*)$/);
      if (heading) {
        const title = heading[1];
        const body = heading[2];
        const items = [];
        i++;
        while (i < lines.length && !/^(الاستنتاج|الأدلة من النظام|النقاط المهمة|المخاطر|الخطوات المقترحة|الأدلة المحلية المباشرة)\s*:/.test(lines[i]) && !/^-\s*المنتج\s*#?\d+/.test(lines[i])) {
          items.push(lines[i].replace(/^[-•]\s*/, ""));
          i++;
        }
        const tone = title === "المخاطر" ? " is-warn" : (title === "الأدلة من النظام" ? " is-evidence" : "");
        parts.push(
          '<section class="ai-fmt-section' + tone + '">' +
          '<h3>' + escapeHtml(title) + '</h3>' +
          (body ? '<p>' + linkInvoices(escapeHtml(body)) + '</p>' : '') +
          (items.length ? '<ul>' + items.map(function (item) { return '<li>' + linkInvoices(escapeHtml(item)) + '</li>'; }).join("") + '</ul>' : '') +
          '</section>'
        );
        continue;
      }
      parts.push('<p class="ai-fmt-p">' + linkInvoices(escapeHtml(line)) + '</p>');
      i++;
    }
    return '<div class="ai-fmt-root ai-fmt-structured" dir="rtl">' + parts.join("") + "</div>";
  }

  /**
   * يحوّل نصاً عادياً (قد يحتوي **غامق** و`كود` وفقرات وقوائم) إلى HTML آمن.
   */
  function formatAiMessageToHtml(raw) {
    if (/الأدلة المحلية المباشرة\s*:|الاستنتاج\s*:|الأدلة من النظام\s*:/.test(String(raw || ""))) {
      return renderStructured(raw);
    }

    let t = escapeHtml(String(raw || ""));

    // **غامق** (بدون تجاوز أسطر)
    t = t.replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>");

    // `كود داخلي`
    t = t.replace(/`([^`\n]+)`/g, '<code class="ai-fmt-code">$1</code>');

    // عناوين Markdown خفيفة في بداية السطر
    t = t.replace(/^### (.+)$/gm, '<h4 class="ai-fmt-h4">$1</h4>');
    t = t.replace(/^## (.+)$/gm, '<h3 class="ai-fmt-h3">$1</h3>');
    t = t.replace(/^# (.+)$/gm, '<h3 class="ai-fmt-h3 ai-fmt-h3-top">$1</h3>');

    const chunks = t.split(/\n{2,}/);
    const parts = [];

    for (let i = 0; i < chunks.length; i++) {
      let block = chunks[i].trim();
      if (!block) continue;

      // كتلة مسبقاً عنوان h3/h4
      if (/^<h[34] class="ai-fmt-h/.test(block)) {
        parts.push(block);
        continue;
      }

      const lines = block.split("\n").map(function (l) {
        return l.trimEnd();
      });
      const nonempty = lines.filter(function (l) {
        return l.trim().length > 0;
      });
      if (nonempty.length >= 2 && nonempty.every(function (l) {
        return /^(\d+\.|[-•])\s/.test(l.trim());
      })) {
        const isOl = /^\d+\./.test(nonempty[0].trim());
        const inner = nonempty
          .map(function (l) {
            const c = l.replace(/^(\d+\.|[-•])\s+/, "").trim();
            return "<li>" + c.split("\n").join("<br>") + "</li>";
          })
          .join("");
        parts.push(
          (isOl ? '<ol class="ai-fmt-list ai-fmt-ol">' : '<ul class="ai-fmt-list ai-fmt-ul">') +
            inner +
            (isOl ? "</ol>" : "</ul>")
        );
        continue;
      }

      parts.push('<p class="ai-fmt-p">' + block.split("\n").join("<br>") + "</p>");
    }

    return '<div class="ai-fmt-root" dir="rtl">' + parts.join("").replace(/#(\d+)/g, function (match, id) {
      return '<a class="ai-fmt-link" href="/orders?open_details=' + encodeURIComponent(id) + '" target="_blank" rel="noopener">#' + id + "</a>";
    }) + "</div>";
  }

  global.formatAiMessageToHtml = formatAiMessageToHtml;
})(typeof window !== "undefined" ? window : this);
