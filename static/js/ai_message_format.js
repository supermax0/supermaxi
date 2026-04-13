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

  /**
   * يحوّل نصاً عادياً (قد يحتوي **غامق** و`كود` وفقرات وقوائم) إلى HTML آمن.
   */
  function formatAiMessageToHtml(raw) {
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

    return '<div class="ai-fmt-root" dir="rtl">' + parts.join("") + "</div>";
  }

  global.formatAiMessageToHtml = formatAiMessageToHtml;
})(typeof window !== "undefined" ? window : this);
