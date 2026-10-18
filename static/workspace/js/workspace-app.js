/**
 * Finora AI Workspace — Phase 1–3.
 */
(function () {
  const API = "/workspace/api";
  const IS_DEV = new URLSearchParams(window.location.search).get("dev") === "1";

  const store = new WorkspaceSessionStore();
  let windowManager = null;
  let avatar = null;
  let eventStream = null;
  let canvas = null;
  let uploadManager = null;
  let workflowClient = null;
  let documentIntelligenceClient = null;
  let courierAnalysisClient = null;
  let purchaseAnalysisClient = null;
  let inventoryForensicsClient = null;
  let timelineStore = null;
  let progressPanel = null;
  let flowLinksSvg = null;
  let flowMotionFrame = null;
  let flowStaticGeometry = null;
  let orderLinkSvg = null;
  let orderLinkFrame = null;
  let activeOrderWindowId = null;
  let windowTrayEl = null;
  let lastWorkspaceWindows = [];
  const openAuxWindowIds = new Set();
  let lastWorkspaceNotice = { message: "", kind: "info", at: 0 };
  let lastPostingSuccessAt = 0;
  let assistantChatSessionId = null;
  let chatBusy = false;
  let commandBusy = false;
  let workflowBusy = false;
  let mobileFileInput = null;
  let mobileAssistantUploadIds = [];
  const MOBILE_CHAT_SESSION_KEY = "finora.leon.mobileChatSession";

  const rootEl = document.getElementById("workspace-root");
  const statusPill = document.getElementById("ws-status-pill");
  const btnUpload = document.getElementById("btn-upload");
  const btnIntelligence = document.getElementById("btn-intelligence");
  const btnCourierAnalysis = document.getElementById("btn-courier-analysis");
  const btnWorkflow = document.getElementById("btn-workflow");
  const btnSelectWorkflow = document.getElementById("btn-select-workflow");
  const btnNextStep = document.getElementById("btn-next-step");
  const btnNew = document.getElementById("btn-new-session");
  const btnRun = document.getElementById("btn-run-mock");
  const btnCancel = document.getElementById("btn-cancel");
  const commandSelect = document.getElementById("ws-command-select");
  const commandRun = document.getElementById("ws-command-run");
  const canvasEl = document.getElementById("ws-canvas");
  const windowsLayer = document.getElementById("ws-windows-layer");
  const avatarLayer = document.getElementById("ws-avatar-layer");
  const mobileMessagesEl = document.getElementById("ws-mobile-messages");
  const mobileTypingEl = document.getElementById("ws-mobile-typing");
  const mobileSheetBackdrop = document.getElementById("ws-mobile-sheet-backdrop");
  const mobileWorkflowSheet = document.getElementById("ws-mobile-workflow-sheet");
  const mobileMemorySheet = document.getElementById("ws-mobile-memory-sheet");
  const mobileMemoryList = document.getElementById("ws-mobile-memory-list");

  function mobileTimeLabel() {
    try {
      return new Intl.DateTimeFormat("ar-IQ", {
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date());
    } catch (_) {
      return "الآن";
    }
  }

  function scrollMobileChat() {
    if (!mobileMessagesEl) return;
    requestAnimationFrame(() => {
      mobileMessagesEl.scrollTop = mobileMessagesEl.scrollHeight;
    });
  }

  function appendMobileMessage(role, message, options = {}) {
    const cleanMessage = String(message || "").trim();
    if (!mobileMessagesEl || !cleanMessage) return null;

    const article = document.createElement("article");
    article.className = `ws-mobile-message ws-mobile-message-${role === "user" ? "user" : "assistant"}`;
    article.dataset.mobileDynamic = "true";

    if (role !== "user") {
      const avatarEl = document.createElement("span");
      avatarEl.className = "ws-mobile-message-avatar";
      avatarEl.setAttribute("aria-hidden", "true");
      avatarEl.textContent = "L";
      article.appendChild(avatarEl);
    }

    const body = document.createElement("div");
    body.className = "ws-mobile-message-body";
    const bubble = document.createElement("div");
    bubble.className = "ws-mobile-bubble";
    if (options.title) {
      const title = document.createElement("strong");
      title.textContent = options.title;
      bubble.appendChild(title);
    }
    const content = document.createElement("span");
    content.textContent = cleanMessage;
    bubble.appendChild(content);
    const time = document.createElement("time");
    time.textContent = options.time || mobileTimeLabel();
    body.append(bubble, time);
    article.appendChild(body);

    mobileMessagesEl.insertBefore(article, mobileTypingEl || null);
    scrollMobileChat();
    return article;
  }

  function setMobileTyping(visible) {
    if (!mobileTypingEl) return;
    mobileTypingEl.hidden = !visible;
    if (visible) scrollMobileChat();
  }

  function resetMobileConversation() {
    if (!mobileMessagesEl) return;
    mobileMessagesEl.querySelectorAll("[data-mobile-dynamic]").forEach((item) => item.remove());
    setMobileTyping(false);
    scrollMobileChat();
  }

  function mobileFormatValue(value, kind) {
    if (kind === "money") {
      return `${Number(value || 0).toLocaleString("ar-IQ")} د.ع`;
    }
    if (kind === "number") {
      return Number(value || 0).toLocaleString("ar-IQ");
    }
    return String(value ?? "—");
  }

  function sendMobilePrompt(text) {
    const input = document.getElementById("ws-chat-input");
    if (!input || !text) return;
    input.value = text;
    input.focus();
    document.getElementById("ws-chat-send")?.click();
  }

  function appendMobilePresentation(presentation) {
    const widgets = Array.isArray(presentation?.widgets) ? presentation.widgets : [];
    if (!mobileMessagesEl || !widgets.length) return;

    const article = document.createElement("article");
    article.className = "ws-mobile-result";
    article.dataset.mobileDynamic = "true";

    const head = document.createElement("header");
    const headText = document.createElement("div");
    const eyebrow = document.createElement("span");
    eyebrow.textContent = "LEON • LIVE DATA";
    const title = document.createElement("strong");
    title.textContent = presentation.title || "نتيجة LEON";
    headText.append(eyebrow, title);
    const verified = document.createElement("span");
    verified.className = "ws-mobile-result-verified";
    verified.textContent = "من النظام";
    head.append(headText, verified);
    article.appendChild(head);

    widgets.forEach((widget) => {
      const section = document.createElement("section");
      section.className = `ws-mobile-widget ws-mobile-widget-${widget.type || "notice"}`;
      const sectionTitle = document.createElement("h3");
      sectionTitle.textContent = widget.title || "ملخص";
      section.appendChild(sectionTitle);
      if (widget.subtitle) {
        const subtitle = document.createElement("p");
        subtitle.className = "ws-mobile-widget-subtitle";
        subtitle.textContent = widget.subtitle;
        section.appendChild(subtitle);
      }

      if (widget.type === "metric_grid") {
        const grid = document.createElement("div");
        grid.className = "ws-mobile-metric-grid";
        (widget.items || []).forEach((item) => {
          const metric = document.createElement("div");
          metric.className = `ws-mobile-metric is-${item.tone || "purple"}`;
          const label = document.createElement("span");
          label.textContent = item.label || "—";
          const value = document.createElement("strong");
          value.textContent = mobileFormatValue(item.value, item.kind);
          metric.append(label, value);
          grid.appendChild(metric);
        });
        section.appendChild(grid);
      } else if (widget.type === "bar_list") {
        const list = document.createElement("div");
        list.className = "ws-mobile-bar-list";
        const values = (widget.items || []).map((item) => Number(item.value || 0));
        const max = Math.max(...values, 1);
        (widget.items || []).forEach((item) => {
          const row = document.createElement("div");
          const rowHead = document.createElement("span");
          const label = document.createElement("b");
          label.textContent = item.label || "—";
          const value = document.createElement("em");
          value.textContent = mobileFormatValue(item.value, widget.kind);
          rowHead.append(label, value);
          const track = document.createElement("i");
          track.style.setProperty("--ws-mobile-bar", `${Math.max(5, Math.round((Number(item.value || 0) / max) * 100))}%`);
          row.append(rowHead, track);
          list.appendChild(row);
        });
        section.appendChild(list);
      } else if (widget.type === "table") {
        const wrap = document.createElement("div");
        wrap.className = "ws-mobile-table-wrap";
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
        (widget.columns || []).forEach((column) => {
          const th = document.createElement("th");
          th.textContent = column.label || column.key || "—";
          headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        const tbody = document.createElement("tbody");
        (widget.rows || []).forEach((row) => {
          const tr = document.createElement("tr");
          (widget.columns || []).forEach((column) => {
            const td = document.createElement("td");
            td.textContent = mobileFormatValue(row[column.key], column.kind);
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
        table.append(thead, tbody);
        wrap.appendChild(table);
        section.appendChild(wrap);
      } else {
        const message = document.createElement("p");
        message.className = "ws-mobile-widget-message";
        message.textContent = widget.message || "";
        section.appendChild(message);
        if (widget.type === "action_plan") {
          section.classList.add(`is-risk-${widget.risk || "medium"}`);
          const badge = document.createElement("span");
          badge.className = "ws-mobile-plan-badge";
          badge.textContent = "تحتاج مراجعة وموافقة";
          section.appendChild(badge);
        }
      }
      article.appendChild(section);
    });

    const files = Array.isArray(presentation.files) ? presentation.files : [];
    if (files.length) {
      const fileBox = document.createElement("div");
      fileBox.className = "ws-mobile-result-files";
      const label = document.createElement("strong");
      label.textContent = "إنشاء ملف من النتيجة";
      const links = document.createElement("div");
      files.forEach((file) => {
        const link = document.createElement("a");
        link.href = file.url;
        link.download = "";
        link.textContent = file.label || String(file.format || "ملف").toUpperCase();
        links.appendChild(link);
      });
      fileBox.append(label, links);
      article.appendChild(fileBox);
    }

    const suggestions = Array.isArray(presentation.suggestions) ? presentation.suggestions : [];
    if (suggestions.length) {
      const followups = document.createElement("div");
      followups.className = "ws-mobile-result-followups";
      suggestions.slice(0, 3).forEach((suggestion) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = suggestion;
        button.addEventListener("click", () => sendMobilePrompt(suggestion));
        followups.appendChild(button);
      });
      article.appendChild(followups);
    }

    mobileMessagesEl.insertBefore(article, mobileTypingEl || null);
    scrollMobileChat();
    return article;
  }

  function mobileLabeledControl(labelText, control) {
    const label = document.createElement("label");
    const caption = document.createElement("span");
    caption.textContent = labelText;
    label.append(caption, control);
    return label;
  }

  function mobilePurchaseSelect(options, selectedId, placeholder) {
    const select = document.createElement("select");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    select.appendChild(empty);
    (options || []).forEach((item) => {
      const option = document.createElement("option");
      option.value = String(item.id);
      option.textContent = `${item.name}${item.sku ? ` — ${item.sku}` : ""}`;
      option.selected = Number(item.id) === Number(selectedId || 0);
      select.appendChild(option);
    });
    return select;
  }

  async function appendMobilePurchaseEditor(analysis) {
    if (!mobileMessagesEl || !purchaseAnalysisClient || !analysis?.id) return null;
    const posted = analysis.posting?.status === "posted";
    if (posted) return null;

    let catalog = { products: [], suppliers: [] };
    try {
      catalog = await purchaseAnalysisClient.catalog("", 160);
    } catch (error) {
      appendMobileMessage("assistant", error.message || "تعذّر تحميل الموردين والأصناف.", { title: "أدوات التصحيح" });
      return null;
    }

    const editor = document.createElement("article");
    editor.className = "ws-mobile-purchase-editor";
    editor.dataset.mobileDynamic = "true";
    editor.dataset.mobilePurchaseCard = String(analysis.id);

    const heading = document.createElement("header");
    const headingText = document.createElement("div");
    const eyebrow = document.createElement("span");
    eyebrow.textContent = "مراجعة قبل الاعتماد";
    const title = document.createElement("strong");
    title.textContent = "صحّح المورد والأصناف";
    const hint = document.createElement("p");
    hint.textContent = "لن يتغيّر المخزون إلا بعد الموافقة النهائية.";
    headingText.append(eyebrow, title, hint);
    heading.appendChild(headingText);
    editor.appendChild(heading);

    const supplier = analysis.supplier || {};
    const supplierBox = document.createElement("section");
    supplierBox.className = "ws-mobile-purchase-supplier";
    const supplierTitle = document.createElement("h3");
    supplierTitle.textContent = "1. المورد";
    const supplierCurrent = document.createElement("p");
    supplierCurrent.textContent = `الحالي: ${supplier.matched?.name || supplier.source_name || "غير محدد"}`;
    const supplierSelect = mobilePurchaseSelect(
      catalog.suppliers || [],
      supplier.matched?.id,
      "اختر مورداً موجوداً"
    );
    supplierSelect.className = "ws-mobile-purchase-select";
    const useSupplier = document.createElement("button");
    useSupplier.type = "button";
    useSupplier.textContent = "استخدام المورد المختار";
    const newSupplier = document.createElement("input");
    newSupplier.type = "text";
    newSupplier.value = supplier.source_name || "";
    newSupplier.placeholder = "اسم المورد الجديد";
    const createSupplier = document.createElement("button");
    createSupplier.type = "button";
    createSupplier.className = "is-secondary";
    createSupplier.textContent = "حفظه كمورد جديد";
    const supplierActions = document.createElement("div");
    supplierActions.className = "ws-mobile-purchase-actions";
    supplierActions.append(useSupplier, createSupplier);
    supplierBox.append(
      supplierTitle,
      supplierCurrent,
      mobileLabeledControl("مورد مسجل بالنظام", supplierSelect),
      mobileLabeledControl("أو مورد جديد", newSupplier),
      supplierActions
    );
    editor.appendChild(supplierBox);

    const setBusy = (button, busy, label) => {
      button.disabled = busy;
      if (label) button.textContent = busy ? "جاري الحفظ…" : label;
    };
    const refreshEditor = async (message, updatedAnalysis) => {
      if (message) appendMobileMessage("assistant", message, { title: "تم الحفظ" });
      await appendMobilePurchaseResult(updatedAnalysis || analysis);
    };
    useSupplier.addEventListener("click", async () => {
      const supplierId = Number(supplierSelect.value || 0);
      if (!supplierId) {
        appendMobileMessage("assistant", "اختر مورداً من القائمة أولاً.", { title: "المورد" });
        return;
      }
      setBusy(useSupplier, true, "استخدام المورد المختار");
      try {
        const result = await purchaseAnalysisClient.setSupplier(analysis.id, { supplierId });
        await refreshEditor("تم تصحيح المورد وربطه بالمورد المسجل.", result.analysis);
      } catch (error) {
        appendMobileMessage("assistant", error.message || "تعذّر حفظ المورد.", { title: "لم يكتمل الحفظ" });
        setBusy(useSupplier, false, "استخدام المورد المختار");
      }
    });
    createSupplier.addEventListener("click", async () => {
      const supplierName = newSupplier.value.trim();
      if (!supplierName) {
        appendMobileMessage("assistant", "اكتب اسم المورد الجديد أولاً.", { title: "المورد" });
        return;
      }
      setBusy(createSupplier, true, "حفظه كمورد جديد");
      try {
        const result = await purchaseAnalysisClient.setSupplier(analysis.id, { supplierName });
        await refreshEditor("تم حفظ اسم المورد الجديد للمراجعة.", result.analysis);
      } catch (error) {
        appendMobileMessage("assistant", error.message || "تعذّر حفظ المورد.", { title: "لم يكتمل الحفظ" });
        setBusy(createSupplier, false, "حفظه كمورد جديد");
      }
    });

    const rowsSection = document.createElement("section");
    rowsSection.className = "ws-mobile-purchase-rows";
    const rowsTitle = document.createElement("h3");
    rowsTitle.textContent = "2. الأصناف";
    rowsSection.appendChild(rowsTitle);

    (analysis.rows || []).forEach((row, position) => {
      const card = document.createElement("div");
      card.className = `ws-mobile-purchase-row is-${row.status || "review"}`;
      const cardHead = document.createElement("div");
      const rowTitle = document.createElement("strong");
      rowTitle.textContent = `الصنف ${position + 1}`;
      const status = document.createElement("span");
      status.textContent = ({ matched: "صنف موجود", new_product: "صنف جديد", review: "يحتاج قرار", invalid: "يحتاج تصحيح", excluded: "مستبعد" })[row.status] || "مراجعة";
      cardHead.append(rowTitle, status);

      const name = document.createElement("input");
      name.type = "text";
      name.value = row.product_name || "";
      name.placeholder = "اسم المنتج";
      const quantity = document.createElement("input");
      quantity.type = "number";
      quantity.min = "1";
      quantity.step = "1";
      quantity.value = String(row.quantity || 1);
      const price = document.createElement("input");
      price.type = "number";
      price.min = "1";
      price.step = "1";
      price.value = String(row.unit_price || 1);
      const numbers = document.createElement("div");
      numbers.className = "ws-mobile-purchase-numbers";
      numbers.append(
        mobileLabeledControl("الكمية", quantity),
        mobileLabeledControl("سعر الشراء", price)
      );

      const mode = document.createElement("select");
      [
        ["create_new", "إنشاء صنف جديد"],
        ["use_existing", "اختيار صنف موجود"],
        ["exclude", "استبعاد هذا السطر"],
      ].forEach(([value, label]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        option.selected = value === (row.decision === "exclude" ? "exclude" : row.decision === "use_existing" ? "use_existing" : "create_new");
        mode.appendChild(option);
      });
      const productSearch = document.createElement("input");
      productSearch.type = "search";
      productSearch.placeholder = "ابحث باسم الصنف أو الرمز";
      const products = mobilePurchaseSelect(catalog.products || [], row.matched_product?.id, "اختر الصنف الموجود");
      products.className = "ws-mobile-purchase-select";
      const existingWrap = document.createElement("div");
      existingWrap.className = "ws-mobile-purchase-existing";
      existingWrap.append(
        mobileLabeledControl("البحث في الأصناف", productSearch),
        mobileLabeledControl("الصنف المختار", products)
      );
      const toggleExisting = () => {
        existingWrap.hidden = mode.value !== "use_existing";
        name.disabled = mode.value === "exclude";
        quantity.disabled = mode.value === "exclude";
        price.disabled = mode.value === "exclude";
      };
      mode.addEventListener("change", toggleExisting);
      toggleExisting();

      let searchTimer = null;
      productSearch.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(async () => {
          try {
            const result = await purchaseAnalysisClient.catalog(productSearch.value, 80);
            const replacement = mobilePurchaseSelect(result.products || [], products.value, "اختر الصنف الموجود");
            products.replaceChildren(...replacement.childNodes);
          } catch (_) {
            /* Keep the existing list when a search request fails. */
          }
        }, 280);
      });

      const save = document.createElement("button");
      save.type = "button";
      save.className = "ws-mobile-purchase-save";
      save.textContent = "حفظ تعديل الصنف";
      save.addEventListener("click", async () => {
        const decision = mode.value;
        const productId = decision === "use_existing" ? Number(products.value || 0) : null;
        if (decision === "use_existing" && !productId) {
          appendMobileMessage("assistant", "ابحث ثم اختر الصنف الموجود أولاً.", { title: `الصنف ${position + 1}` });
          return;
        }
        if (decision !== "exclude" && (!name.value.trim() || Number(quantity.value) <= 0 || Number(price.value) <= 0)) {
          appendMobileMessage("assistant", "أكمل اسم المنتج والكمية وسعر الشراء بقيم صحيحة.", { title: `الصنف ${position + 1}` });
          return;
        }
        setBusy(save, true, "حفظ تعديل الصنف");
        try {
          let result = await purchaseAnalysisClient.decide(analysis.id, row.row_index, decision, productId);
          if (decision !== "exclude") {
            result = await purchaseAnalysisClient.updateValues(
              analysis.id,
              row.row_index,
              Number(quantity.value),
              Number(price.value),
              name.value.trim()
            );
          }
          await refreshEditor(`تم حفظ الصنف ${position + 1} وإعادة حساب الفاتورة.`, result.analysis);
        } catch (error) {
          appendMobileMessage("assistant", error.message || "تعذّر حفظ الصنف.", { title: "لم يكتمل الحفظ" });
          setBusy(save, false, "حفظ تعديل الصنف");
        }
      });

      card.append(
        cardHead,
        mobileLabeledControl("اسم المنتج", name),
        numbers,
        mobileLabeledControl("طريقة التعامل", mode),
        existingWrap,
        save
      );
      rowsSection.appendChild(card);
    });
    editor.appendChild(rowsSection);

    const executionBox = document.createElement("section");
    executionBox.className = "ws-mobile-purchase-execution";
    const renderExecutionStart = () => {
      const summary = analysis.summary || {};
      const executionTitle = document.createElement("h3");
      executionTitle.textContent = "3. اعتماد الفاتورة";
      const executionHint = document.createElement("p");
      const blocking = Array.isArray(summary.blocking) ? summary.blocking : [];
      executionHint.textContent = summary.ready
        ? `جاهزة: ${Number(summary.total_units || 0).toLocaleString("ar-IQ")} قطعة بإجمالي ${Number(summary.grand_total || 0).toLocaleString("ar-IQ")} د.ع.`
        : (blocking[0] || "أكمل تصحيح المورد والأصناف أولاً.");
      const prepareButton = document.createElement("button");
      prepareButton.type = "button";
      prepareButton.className = "ws-mobile-purchase-execute";
      prepareButton.disabled = !summary.ready;
      prepareButton.textContent = summary.ready ? "مراجعة نهائية وتنفيذ الفاتورة" : "التنفيذ غير متاح حتى تكتمل المراجعة";
      prepareButton.addEventListener("click", async () => {
        setBusy(prepareButton, true, "مراجعة نهائية وتنفيذ الفاتورة");
        try {
          const prepared = await purchaseAnalysisClient.prepare(analysis.id);
          const preview = prepared.preview || {};
          const confirmTitle = document.createElement("h3");
          confirmTitle.textContent = "تأكيد التنفيذ";
          const confirmMessage = document.createElement("p");
          confirmMessage.textContent = `سيتم تسجيل شراء وإضافة ${Number(preview.total_units || summary.total_units || 0).toLocaleString("ar-IQ")} قطعة للمخزون بقيمة ${Number(preview.grand_total || summary.grand_total || 0).toLocaleString("ar-IQ")} د.ع. هل أنت متأكد؟`;
          const confirmActions = document.createElement("div");
          confirmActions.className = "ws-mobile-purchase-confirm-actions";
          const approveButton = document.createElement("button");
          approveButton.type = "button";
          approveButton.className = "ws-mobile-purchase-execute";
          approveButton.textContent = "نعم، نفّذ وأضف للمخزون";
          const cancelButton = document.createElement("button");
          cancelButton.type = "button";
          cancelButton.className = "is-secondary";
          cancelButton.textContent = "رجوع للتعديل";
          approveButton.addEventListener("click", async () => {
            setBusy(approveButton, true, "نعم، نفّذ وأضف للمخزون");
            cancelButton.disabled = true;
            try {
              const result = await purchaseAnalysisClient.approve(analysis.id);
              appendMobileMessage(
                "assistant",
                `تم تسجيل فاتورة الشراء #${result.posting?.purchase_id || ""} وإضافة الكميات إلى المخزون بنجاح.`,
                { title: "اكتمل التنفيذ" }
              );
              await appendMobilePurchaseResult(result.analysis || analysis);
            } catch (error) {
              appendMobileMessage("assistant", error.message || "تعذّر تنفيذ الفاتورة ولم يتم اعتماد تغيير ناقص.", { title: "لم يكتمل التنفيذ" });
              setBusy(approveButton, false, "نعم، نفّذ وأضف للمخزون");
              cancelButton.disabled = false;
            }
          });
          cancelButton.addEventListener("click", async () => {
            cancelButton.disabled = true;
            try {
              await purchaseAnalysisClient.cancel(analysis.id);
            } catch (_) {
              /* The editor can still return safely even if no approval remained open. */
            }
            renderExecutionStart();
          });
          confirmActions.append(approveButton, cancelButton);
          executionBox.replaceChildren(confirmTitle, confirmMessage, confirmActions);
          scrollMobileChat();
        } catch (error) {
          appendMobileMessage("assistant", error.message || "تعذّر تجهيز المراجعة النهائية.", { title: "لم يكتمل التجهيز" });
          setBusy(prepareButton, false, "مراجعة نهائية وتنفيذ الفاتورة");
        }
      });
      executionBox.replaceChildren(executionTitle, executionHint, prepareButton);
    };
    renderExecutionStart();
    editor.appendChild(executionBox);
    mobileMessagesEl.insertBefore(editor, mobileTypingEl || null);
    scrollMobileChat();
    return editor;
  }

  async function appendMobilePurchaseResult(analysis) {
    const summary = analysis?.summary || {};
    const rows = Array.isArray(analysis?.rows) ? analysis.rows : [];
    if (!analysis?.id && !rows.length && !Object.keys(summary).length) return false;
    const supplier = analysis.supplier || {};
    const supplierName = supplier.matched?.name || supplier.source_name || "المورد غير مقروء";
    const invoice = analysis.invoice || {};
    const posted = analysis.posting?.status === "posted";
    const widgets = [
      {
        type: "metric_grid",
        title: "ملخص فاتورة الشراء",
        subtitle: `المورد: ${supplierName}${invoice.supplier_invoice_no ? ` • فاتورة ${invoice.supplier_invoice_no}` : ""}`,
        items: [
          { label: "الأسطر المطابقة", value: summary.matched_rows || 0, kind: "number", tone: "green" },
          { label: "منتجات جديدة", value: summary.new_product_rows || 0, kind: "number", tone: "purple" },
          { label: "تحتاج مراجعة", value: summary.review_rows || 0, kind: "number", tone: "amber" },
          { label: "إجمالي القطع", value: summary.total_units || 0, kind: "number", tone: "blue" },
          { label: "إجمالي الفاتورة", value: summary.grand_total || 0, kind: "money", tone: "purple" },
        ],
      },
    ];
    if (rows.length) {
      widgets.push({
        type: "table",
        title: "أصناف فاتورة الشراء",
        columns: [
          { key: "product_name", label: "الصنف", kind: "text" },
          { key: "status_label", label: "المطابقة", kind: "text" },
          { key: "quantity", label: "الكمية", kind: "number" },
          { key: "unit_price", label: "سعر الشراء", kind: "money" },
          { key: "line_total", label: "الإجمالي", kind: "money" },
        ],
        rows: rows.slice(0, 30).map((row) => ({
          ...row,
          status_label: ({ matched: "مطابق", new_product: "منتج جديد", review: "مراجعة", invalid: "غير صالح", excluded: "مستبعد" })[row.status] || row.status || "—",
        })),
      });
    }
    const blocking = Array.isArray(summary.blocking) ? summary.blocking : [];
    widgets.push({
      type: "notice",
      title: posted ? "تم تنفيذ الفاتورة" : (summary.ready ? "جاهز للمراجعة النهائية" : "يحتاج إكمال المراجعة"),
      message: posted
        ? `تم تسجيل الشراء #${analysis.posting?.purchase_id || ""} وإضافة الكميات إلى المخزون.`
        : (blocking.length ? blocking.slice(0, 4).join(" • ") : "لم يتم إدخال أي كمية إلى المخزون قبل الموافقة الصريحة."),
    });

    const cardId = String(analysis.id || "purchase");
    mobileMessagesEl?.querySelectorAll("[data-mobile-purchase-card]").forEach((item) => {
      if (item.dataset.mobilePurchaseCard === cardId) item.remove();
    });
    const resultCard = appendMobilePresentation({
      title: posted ? "فاتورة الشراء المنفّذة" : "نتيجة تحليل مستند الشراء",
      widgets,
      suggestions: posted ? ["اعرض ملخص الفاتورة"] : ["اعرض ملخص الفاتورة", "ما الأصناف التي تحتاج مراجعة؟"],
    });
    if (resultCard) resultCard.dataset.mobilePurchaseCard = cardId;
    if (!posted) await appendMobilePurchaseEditor(analysis);
    return true;
  }

  function storedMobileChatSession() {
    try {
      const value = Number(localStorage.getItem(MOBILE_CHAT_SESSION_KEY) || 0);
      return Number.isInteger(value) && value > 0 ? value : null;
    } catch (_) {
      return null;
    }
  }

  function saveMobileChatSession(sessionId) {
    try {
      if (sessionId) localStorage.setItem(MOBILE_CHAT_SESSION_KEY, String(sessionId));
      else localStorage.removeItem(MOBILE_CHAT_SESSION_KEY);
    } catch (_) {
      /* Storage can be unavailable in privacy mode; chat still works. */
    }
  }

  function restoredTimeLabel(raw) {
    if (!raw) return "";
    try {
      return new Intl.DateTimeFormat("ar-IQ", { hour: "numeric", minute: "2-digit" }).format(new Date(raw));
    } catch (_) {
      return "";
    }
  }

  function isMobileChatMode() {
    return window.matchMedia("(max-width: 767px), (max-width: 930px) and (max-height: 500px) and (pointer: coarse)").matches;
  }

  function closeMobileSheets() {
    if (mobileWorkflowSheet) mobileWorkflowSheet.hidden = true;
    if (mobileMemorySheet) mobileMemorySheet.hidden = true;
    if (mobileSheetBackdrop) mobileSheetBackdrop.hidden = true;
    rootEl?.classList.remove("ws-mobile-sheet-open");
  }

  function openMobileSheet(sheet) {
    if (!sheet || !isMobileChatMode()) return;
    closeMobileSheets();
    sheet.hidden = false;
    if (mobileSheetBackdrop) mobileSheetBackdrop.hidden = false;
    rootEl?.classList.add("ws-mobile-sheet-open");
  }

  async function loadMobileConversation(sessionId) {
    if (!sessionId || !mobileMessagesEl) return false;
    try {
      const response = await fetch(`/assistant/api/chat/sessions/${sessionId}/messages`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) {
        saveMobileChatSession(null);
        return false;
      }
      assistantChatSessionId = data.session_id || sessionId;
      saveMobileChatSession(assistantChatSessionId);
      mobileMessagesEl.querySelectorAll("[data-mobile-dynamic]").forEach((item) => item.remove());
      (data.messages || []).forEach((message) => {
        appendMobileMessage(message.role, message.content, { time: restoredTimeLabel(message.created_at) });
        if (message.role === "assistant" && message.presentation) {
          appendMobilePresentation(message.presentation);
        }
      });
      scrollMobileChat();
      return true;
    } catch (_) {
      /* The welcome state is a safe fallback when history is unavailable. */
      return false;
    }
  }

  async function restoreMobileConversation() {
    const sessionId = storedMobileChatSession();
    if (!isMobileChatMode() || !sessionId || !mobileMessagesEl) return;
    await loadMobileConversation(sessionId);
  }

  function mobileMemoryDate(raw) {
    if (!raw) return "";
    try {
      return new Intl.DateTimeFormat("ar-IQ", { month: "short", day: "numeric" }).format(new Date(raw));
    } catch (_) {
      return "";
    }
  }

  async function loadMobileMemory() {
    if (!mobileMemoryList) return;
    mobileMemoryList.innerHTML = '<span class="ws-mobile-memory-loading">جاري تحميل الذاكرة…</span>';
    try {
      const response = await fetch("/assistant/api/chat/sessions", {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) throw new Error(data.error || "تعذّر تحميل الذاكرة");
      mobileMemoryList.replaceChildren();
      const sessions = Array.isArray(data.sessions) ? data.sessions : [];
      if (!sessions.length) {
        const empty = document.createElement("span");
        empty.className = "ws-mobile-memory-empty";
        empty.textContent = "لا توجد محادثات محفوظة بعد.";
        mobileMemoryList.appendChild(empty);
        return;
      }
      sessions.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ws-mobile-memory-item";
        if (Number(item.id) === Number(assistantChatSessionId)) button.classList.add("is-active");
        const textWrap = document.createElement("span");
        const title = document.createElement("strong");
        title.textContent = item.title || "محادثة LEON";
        const preview = document.createElement("small");
        preview.textContent = item.preview || `${item.message_count || 0} رسالة`;
        textWrap.append(title, preview);
        const time = document.createElement("time");
        time.textContent = mobileMemoryDate(item.updated_at);
        button.append(textWrap, time);
        button.addEventListener("click", async () => {
          button.disabled = true;
          const restored = await loadMobileConversation(Number(item.id));
          button.disabled = false;
          if (restored) closeMobileSheets();
        });
        mobileMemoryList.appendChild(button);
      });
    } catch (error) {
      mobileMemoryList.replaceChildren();
      const failed = document.createElement("span");
      failed.className = "ws-mobile-memory-empty";
      failed.textContent = error.message || "تعذّر تحميل الذاكرة.";
      mobileMemoryList.appendChild(failed);
    }
  }

  function setStatus(status) {
    const labels = {
      created: "جاهز",
      ready: "جاهز",
      running: "قيد التشغيل",
      waiting_user: "بانتظار المستخدم",
      waiting_approval: "بانتظار الموافقة",
      completed: "مكتمل",
      cancelled: "ملغي",
      failed: "فشل",
    };
    statusPill.textContent = labels[status] || status || "جاهز";
    statusPill.className = "ws-status-pill";
    if (status === "running") statusPill.classList.add("ws-status-running");
    if (status === "completed") statusPill.classList.add("ws-status-completed");
    if (status === "cancelled") statusPill.classList.add("ws-status-cancelled");
    if (status === "waiting_approval" || status === "waiting_user") {
      statusPill.classList.add("ws-status-running");
    }
  }

  function setIntelligenceBusy(busy) {
    if (!btnIntelligence) return;
    btnIntelligence.disabled = busy || !hasActiveDocument();
    btnIntelligence.textContent = busy ? "جاري الفهم..." : "فهم المستند";
    btnIntelligence.classList.toggle("ws-btn-loading", busy);
    syncCommandControls();
  }

  function hasActiveDocument() {
    const session = store.getSession();
    if (!session) return false;
    if (session.active_document) return true;
    const meta = session.metadata || {};
    return Boolean(meta.active_document_id) || (session.documents && session.documents.length > 0);
  }

  function updateIntelligenceButton() {
    if (!btnIntelligence) return;
    const busy = documentIntelligenceClient && documentIntelligenceClient.isBusy();
    btnIntelligence.disabled = busy || !hasActiveDocument();
    syncCommandControls();
  }

  function updateCourierButton() {
    if (!btnCourierAnalysis) return;
    const busy = courierAnalysisClient && courierAnalysisClient.isBusy();
    btnCourierAnalysis.disabled = busy || !hasActiveDocument();
    syncCommandControls();
  }

  function setCourierBusy(busy) {
    if (!btnCourierAnalysis) return;
    btnCourierAnalysis.disabled = busy || !hasActiveDocument();
    btnCourierAnalysis.textContent = busy ? "جاري التحليل..." : "تحليل كشف التسديد قراءة فقط";
    btnCourierAnalysis.classList.toggle("ws-btn-loading", busy);
    syncCommandControls();
  }

  function completeDocumentScan(stage) {
    if (!windowManager) return;
    windowManager.applyEvent({
      type: "document.scan.updated",
      payload: {
        active: false,
        progress: 100,
        stage: stage || "اكتمل فحص المستند",
        error: false,
      },
    });
  }

  function setUploadBusy(busy) {
    if (btnUpload) {
      btnUpload.disabled = busy;
      btnUpload.textContent = busy ? "جاري الرفع..." : "رفع مستند";
      btnUpload.classList.toggle("ws-btn-loading", busy);
    }
    syncCommandControls();
  }

  function commandTarget(value) {
    return {
      upload: btnUpload,
      intelligence: btnIntelligence,
      courier: btnCourierAnalysis,
      workflow: btnWorkflow,
      select_workflow: btnSelectWorkflow,
      mock: btnRun,
      cancel: btnCancel,
    }[value];
  }

  function syncCommandControls() {
    if (!commandSelect || !commandRun) return;
    [...commandSelect.options].forEach((opt) => {
      const target = commandTarget(opt.value);
      opt.disabled = Boolean(target && target.disabled);
    });
    const selectedTarget = commandTarget(commandSelect.value);
    const labels = {
      courier: "تحليل",
      intelligence: "فهم",
      select_workflow: "اختيار",
      workflow: "تشغيل",
      cancel: "إلغاء",
    };
    commandSelect.disabled = commandBusy;
    commandRun.disabled = commandBusy || Boolean(selectedTarget && selectedTarget.disabled);
    commandRun.textContent = commandBusy
      ? "جاري التنفيذ..."
      : (labels[commandSelect.value] || "تشغيل");
  }

  async function runSelectedCommand() {
    if (!commandSelect || commandBusy) return;
    const value = commandSelect.value;
    const target = commandTarget(value);
    if (!target || target.disabled) return;

    commandBusy = true;
    syncCommandControls();
    try {
      if (value === "intelligence") {
        avatar.setMode("reading_document");
        avatar.speak("بدأت فهم المستند. سأعرض النتيجة عند اكتمال القراءة.");
        showWorkspaceNotice("بدأ فهم المستند فعلياً. انتظر اكتمال القراءة...", "info");
        await documentIntelligenceClient.runForActiveSessionDocument();
        showWorkspaceNotice("اكتمل فهم المستند وظهرت النتيجة في النوافذ.", "success");
        return;
      }
      if (value === "courier") {
        avatar.setMode("scanning");
        avatar.speak("بدأ تحليل كشف التسديد ومطابقة الصفوف.");
        showWorkspaceNotice("بدأ تحليل كشف التسديد فعلياً...", "info");
        await courierAnalysisClient.runForSession();
        showWorkspaceNotice("اكتمل تحليل كشف التسديد.", "success");
        return;
      }
      if (value === "select_workflow") {
        ensureWorkflowSelectorWindow();
        avatar.setMode("waiting_user");
        avatar.speak("اختر نوع العمل من النافذة الظاهرة.");
        showWorkspaceNotice("اختر نوع العمل من النافذة التي ظهرت أمامك.", "info");
        return;
      }
      if (value === "workflow") {
        await runRecommendedWorkflow();
        return;
      }
      if (value === "cancel") {
        const session = store.getSession();
        if (!session) return;
        await api(`/sessions/${session.id}/cancel`, { method: "POST", body: "{}" });
        await refreshSession();
        avatar.setMode("warning");
        avatar.speak("تم إلغاء المهمة الحالية.");
        showWorkspaceNotice("تم إلغاء المهمة الحالية.", "success");
      }
    } catch (error) {
      if (error.message === "SESSION_NOT_FOUND" || error.code === "SESSION_NOT_FOUND") {
        await recoverMissingSession();
        ensureWorkflowSelectorWindow();
        avatar.setMode("waiting_user");
        avatar.speak("انتهت الجلسة السابقة. أنشأت جلسة جديدة، اختر نوع العمل للمتابعة.");
        showWorkspaceNotice("انتهت الجلسة السابقة وتم إنشاء جلسة جديدة. اختر نوع العمل للمتابعة.", "info", 7000);
        return;
      }
      avatar.setMode("error");
      avatar.speak(error.message || "تعذّر تنفيذ الأمر.");
      avatar.playTone("error");
      showWorkspaceNotice(error.message || "تعذّر تنفيذ الأمر المحدد.", "error", 7000);
    } finally {
      commandBusy = false;
      syncCommandControls();
    }
  }

  function selectMainReportWindow(windows) {
    const list = windows || [];
    return (
      list.find((w) => w.type === "inventory_forensics") ||
      list.find((w) => w.type === "courier_settlement_analysis") ||
      list.find((w) => w.type === "purchase_invoice_analysis") ||
      list.find((w) => w.type === "live_report") ||
      null
    );
  }

  function isMainWorkspaceWindow(windowSpec, reportWindow, docWindow) {
    if (!windowSpec) return false;
    return Boolean(
      (reportWindow && windowSpec.id === reportWindow.id) ||
      (docWindow && windowSpec.id === docWindow.id)
    );
  }

  function windowLabel(windowSpec) {
    const labels = {
      assistant_notes: "ملاحظات LEON",
      courier_rows: "الصفوف",
      courier_issues: "المشاكل",
      financial_preview: "مالية",
      document_intelligence: "فهم المستند",
      raw_table_preview: "الجداول",
      workflow_selector: "نوع العمل",
      approval_panel: "الموافقة",
      session_timeline: "الأحداث",
      order_details: "تفاصيل الطلب",
      employee_performance: "أداء الموظفين",
      purchase_invoice_analysis: "مطابقة فاتورة الشراء",
      inventory_forensics: "المحقق الذكي للمخزون",
    };
    return labels[windowSpec.type] || windowSpec.title || windowSpec.type || "نافذة";
  }

  function escHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  function showWorkspaceNotice(message, kind = "info", duration = 4200) {
    const cleanMessage = String(message || "").trim();
    if (!cleanMessage) return;
    const now = Date.now();
    if (
      lastWorkspaceNotice.message === cleanMessage
      && now - lastWorkspaceNotice.at < 2000
    ) return;
    lastWorkspaceNotice = { message: cleanMessage, kind, at: now };

    let stack = document.getElementById("ws-notice-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "ws-notice-stack";
      stack.className = "ws-notice-stack";
      stack.setAttribute("aria-live", "polite");
      document.body.appendChild(stack);
    }
    const notice = document.createElement("div");
    notice.className = `ws-notice ws-notice-${kind}`;
    notice.textContent = cleanMessage;
    stack.appendChild(notice);
    requestAnimationFrame(() => notice.classList.add("visible"));
    window.setTimeout(() => {
      notice.classList.remove("visible");
      window.setTimeout(() => notice.remove(), 220);
    }, duration);
  }

  function signalPostingSuccess(safeRows = 0) {
    const now = Date.now();
    if (now - lastPostingSuccessAt < 2000) return;
    lastPostingSuccessAt = now;
    avatar.setMode("success");
    avatar.speak("تم تنفيذ الطلبات المطابقة السليمة فقط.");
    avatar.playTone("success");
    showWorkspaceNotice(
      Number(safeRows) > 0
        ? `تم التنفيذ بنجاح لـ ${Number(safeRows)} طلب.`
        : "تم التنفيذ بنجاح.",
      "success",
      6000
    );
  }

  function mergeWindowList(existing, nextWindow) {
    const list = [...(existing || [])];
    const idx = list.findIndex((w) => w.id === nextWindow.id);
    if (idx >= 0) list[idx] = nextWindow;
    else list.push(nextWindow);
    return list;
  }

  function parseOrderDetailsCommand(rawText) {
    const digitMap = { "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9", "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9" };
    const text = String(rawText || "")
      .replace(/[٠-٩۰-۹]/g, (digit) => digitMap[digit] || digit)
      .replace(/ـ/g, " ")
      .trim();
    const mentionsOrder = /(?:ال)?طلب|order/i.test(text);
    const wantsDetails = /تفاصيل|تفاصيله|حركات|حركته|المالية|دفعات|تسديد|طلع|اعرض|اظهر|أظهر|افتح|راجع|show|details|history|financial|open/i.test(text);
    if (!mentionsOrder || !wantsDetails) return { matched: false, orderId: null };

    const patterns = [
      /(?:ال)?طلب\s*(?:رقم|#|number|no\.?)?\s*#?\s*(\d{1,10})/i,
      /(?:تفاصيل|حركات|دفعات|تسديد)\s*(?:ال)?طلب\s*#?\s*(\d{1,10})/i,
      /#(\d{1,10})/,
      /(\d{1,10})/,
    ];
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) return { matched: true, orderId: Number(match[1]) };
    }
    return { matched: true, orderId: null };
  }

  window.finoraParseOrderDetailsCommand = parseOrderDetailsCommand;

  function normalizeWorkspaceWindows(windows) {
    const list = windows || [];
    const doc = list.find((w) => w.type === "document_viewer");
    const report = selectMainReportWindow(list);
    const auxiliary = list
      .filter((w) => !isMainWorkspaceWindow(w, report, doc))
      .filter((w) => openAuxWindowIds.has(w.id))
      .map((w) => ({ ...w, ui_auxiliary: true }));
    return [report, doc, ...auxiliary].filter(Boolean);
  }

  function ensureWindowTray() {
    if (windowTrayEl || !canvasEl) return windowTrayEl;
    windowTrayEl = document.createElement("div");
    windowTrayEl.id = "ws-window-tray";
    windowTrayEl.className = "ws-window-tray";
    canvasEl.appendChild(windowTrayEl);
    windowTrayEl.addEventListener("click", (event) => {
      const button = event.target.closest("[data-window-id]");
      if (!button) return;
      const id = button.dataset.windowId;
      if (!id) return;
      if (openAuxWindowIds.has(id)) {
        openAuxWindowIds.delete(id);
      } else {
        openAuxWindowIds.add(id);
      }
      renderWorkspaceWindows(lastWorkspaceWindows);
    });
    return windowTrayEl;
  }

  function renderWindowTray(windows) {
    const tray = ensureWindowTray();
    if (!tray) return;
    const list = windows || [];
    const doc = list.find((w) => w.type === "document_viewer");
    const report = selectMainReportWindow(list);
    const auxiliary = list.filter((w) => !isMainWorkspaceWindow(w, report, doc));
    if (!auxiliary.length) {
      tray.hidden = true;
      tray.innerHTML = "";
      return;
    }

    tray.hidden = false;
    tray.innerHTML = `
      <span class="ws-window-tray-title">النوافذ</span>
      <div class="ws-window-tray-list">
        ${auxiliary
          .map((w) => {
            const active = openAuxWindowIds.has(w.id);
            return `<button type="button" class="ws-window-tray-btn ${active ? "active" : ""}" data-window-id="${escHtml(w.id)}">${escHtml(windowLabel(w))}</button>`;
          })
          .join("")}
      </div>
    `;
  }

  function ensureFlowLinksSvg() {
    if (flowLinksSvg || !canvasEl) return flowLinksSvg;
    flowLinksSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    flowLinksSvg.setAttribute("id", "ws-flow-links");
    flowLinksSvg.setAttribute("class", "ws-flow-links");
    flowLinksSvg.setAttribute("aria-label", "مسار معالجة المستند من المعاينة عبر LEON إلى التقرير");
    flowLinksSvg.innerHTML = `
      <defs>
        <linearGradient id="ws-flow-preview-gradient" x1="0" x2="1">
          <stop offset="0%" stop-color="#4fd1c5"></stop>
          <stop offset="55%" stop-color="#31c48d"></stop>
          <stop offset="100%" stop-color="#8b7cff"></stop>
        </linearGradient>
        <linearGradient id="ws-flow-report-gradient" x1="0" x2="1">
          <stop offset="0%" stop-color="#8b7cff"></stop>
          <stop offset="52%" stop-color="#6d5efc"></stop>
          <stop offset="100%" stop-color="#4f8cff"></stop>
        </linearGradient>
        <filter id="ws-flow-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="4" result="blur"></feGaussianBlur>
          <feMerge>
            <feMergeNode in="blur"></feMergeNode>
            <feMergeNode in="SourceGraphic"></feMergeNode>
          </feMerge>
        </filter>
        <marker id="ws-flow-arrow-preview" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#31c48d"></path>
        </marker>
        <marker id="ws-flow-arrow-report" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z"></path>
        </marker>
      </defs>
      <path class="ws-flow-track ws-flow-track-preview" data-flow-path="preview"></path>
      <path class="ws-flow-draw ws-flow-draw-preview" data-flow-draw="preview"></path>
      <path id="ws-flow-preview-route" class="ws-flow-path ws-flow-path-preview" data-flow-path="preview"></path>
      <path class="ws-flow-hitarea" data-flow-path="preview" data-flow-hit="preview"></path>
      <path class="ws-flow-track ws-flow-track-report" data-flow-path="report"></path>
      <path class="ws-flow-draw ws-flow-draw-report" data-flow-draw="report"></path>
      <path id="ws-flow-report-route" class="ws-flow-path ws-flow-path-report" data-flow-path="report"></path>
      <path class="ws-flow-hitarea" data-flow-path="report" data-flow-hit="report"></path>

      <g class="ws-flow-packets ws-flow-packets-preview" aria-hidden="true">
        <circle class="ws-flow-packet ws-flow-packet-preview" r="4.5">
          <animateMotion dur="2.8s" begin="0s" repeatCount="indefinite"><mpath href="#ws-flow-preview-route"></mpath></animateMotion>
        </circle>
        <circle class="ws-flow-packet ws-flow-packet-preview ws-flow-packet-small" r="3">
          <animateMotion dur="2.8s" begin="-0.95s" repeatCount="indefinite"><mpath href="#ws-flow-preview-route"></mpath></animateMotion>
        </circle>
        <circle class="ws-flow-packet ws-flow-packet-preview ws-flow-packet-small" r="3">
          <animateMotion dur="2.8s" begin="-1.9s" repeatCount="indefinite"><mpath href="#ws-flow-preview-route"></mpath></animateMotion>
        </circle>
      </g>
      <g class="ws-flow-packets ws-flow-packets-report" aria-hidden="true">
        <circle class="ws-flow-packet ws-flow-packet-report" r="4.5">
          <animateMotion dur="2.55s" begin="0s" repeatCount="indefinite"><mpath href="#ws-flow-report-route"></mpath></animateMotion>
        </circle>
        <circle class="ws-flow-packet ws-flow-packet-report ws-flow-packet-small" r="3">
          <animateMotion dur="2.55s" begin="-0.85s" repeatCount="indefinite"><mpath href="#ws-flow-report-route"></mpath></animateMotion>
        </circle>
        <circle class="ws-flow-packet ws-flow-packet-report ws-flow-packet-small" r="3">
          <animateMotion dur="2.55s" begin="-1.7s" repeatCount="indefinite"><mpath href="#ws-flow-report-route"></mpath></animateMotion>
        </circle>
      </g>

      <g class="ws-flow-node ws-flow-node-source" data-flow-node="source" aria-hidden="true">
        <circle class="ws-flow-node-pulse" r="12"></circle>
        <circle class="ws-flow-node-core" r="5"></circle>
      </g>
      <g class="ws-flow-node ws-flow-node-leon-input" data-flow-node="leon-input" aria-hidden="true">
        <circle class="ws-flow-node-pulse" r="13"></circle>
        <circle class="ws-flow-node-core" r="5"></circle>
      </g>
      <g class="ws-flow-node ws-flow-node-leon-output" data-flow-node="leon-output" aria-hidden="true">
        <circle class="ws-flow-node-pulse" r="13"></circle>
        <circle class="ws-flow-node-core" r="5"></circle>
      </g>
      <g class="ws-flow-node ws-flow-node-target" data-flow-node="target" aria-hidden="true">
        <circle class="ws-flow-node-pulse" r="12"></circle>
        <circle class="ws-flow-node-core" r="5"></circle>
      </g>

      <g class="ws-flow-stage ws-flow-stage-preview" data-flow-stage="preview" data-flow-target="preview"
         role="button" tabindex="0" aria-label="فتح معاينة المستند">
        <path class="ws-flow-stage-stem" d="M 0 21 L 0 38"></path>
        <rect x="-86" y="-23" width="172" height="46" rx="16"></rect>
        <circle class="ws-flow-stage-ring" cx="-64" cy="0" r="10"></circle>
        <circle class="ws-flow-stage-dot" cx="-64" cy="0" r="4"></circle>
        <text class="ws-flow-stage-label" x="12" y="-2" text-anchor="middle" data-flow-label="preview">قراءة المستند</text>
        <text class="ws-flow-stage-detail" x="12" y="13" text-anchor="middle" data-flow-detail="preview">اضغط لفتح المصدر</text>
        <title>انقر للانتقال إلى معاينة المستند</title>
      </g>
      <g class="ws-flow-stage ws-flow-stage-report" data-flow-stage="report" data-flow-target="report"
         role="button" tabindex="0" aria-label="فتح تقرير التحليل">
        <path class="ws-flow-stage-stem" d="M 0 21 L 0 38"></path>
        <rect x="-86" y="-23" width="172" height="46" rx="16"></rect>
        <circle class="ws-flow-stage-ring" cx="-64" cy="0" r="10"></circle>
        <circle class="ws-flow-stage-dot" cx="-64" cy="0" r="4"></circle>
        <text class="ws-flow-stage-label" x="12" y="-2" text-anchor="middle" data-flow-label="report">بناء التقرير</text>
        <text class="ws-flow-stage-detail" x="12" y="13" text-anchor="middle" data-flow-detail="report">اضغط لفتح النتيجة</text>
        <title>انقر للانتقال إلى تقرير التحليل</title>
      </g>
    `;
    flowLinksSvg.querySelectorAll(".ws-flow-stage").forEach((stage) => {
      const activate = () => focusFlowTarget(stage.dataset.flowTarget);
      stage.addEventListener("click", activate);
      stage.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      });
      stage.addEventListener("mouseenter", () => {
        flowLinksSvg.dataset.hoverLeg = stage.dataset.flowTarget;
      });
      stage.addEventListener("mouseleave", () => {
        delete flowLinksSvg.dataset.hoverLeg;
      });
    });
    canvasEl.insertBefore(flowLinksSvg, canvasEl.firstChild);
    return flowLinksSvg;
  }

  function flowTargetTypes(target) {
    const mode = String(avatar?.mode || "idle");
    if (target === "preview") {
      return ["document_viewer", "document_intelligence", "raw_table_preview"];
    }
    if (mode === "waiting_approval") {
      return ["approval_panel"];
    }
    if (mode === "waiting_user") {
      return ["workflow_selector", "approval_panel"];
    }
    if (["warning", "error", "failed"].includes(mode)) {
      return ["courier_issues", "assistant_notes", "order_details", "courier_settlement_analysis", "live_report", "document_intelligence"];
    }
    return ["inventory_forensics", "employee_performance", "order_details", "purchase_invoice_analysis", "courier_settlement_analysis", "live_report", "assistant_notes"];
  }

  function flowWindowSpec(target) {
    const types = flowTargetTypes(target);
    for (const type of types) {
      const spec = (lastWorkspaceWindows || []).find(
        (item) => item.type === type && (item.state || "open") !== "closed" && !item.hidden
      );
      if (spec) return spec;
    }
    return null;
  }

  function revealFlowWindow(spec) {
    if (!spec) return false;
    const report = selectMainReportWindow(lastWorkspaceWindows);
    const doc = (lastWorkspaceWindows || []).find((item) => item.type === "document_viewer");
    if (!isMainWorkspaceWindow(spec, report, doc)) openAuxWindowIds.add(spec.id);
    renderWorkspaceWindows(lastWorkspaceWindows);
    requestAnimationFrame(() => windowManager?.focusWindow(spec.id));
    return true;
  }

  function openFlowAttentionWindow(kind, message) {
    const isError = kind === "error";
    const windowId = "win_leon_flow_attention";
    const cleanMessage = String(message || "").trim() || (
      isError
        ? "تعذّر إكمال العملية، لكن لم تصل تفاصيل إضافية من الخادم. أعد المحاولة، وإذا تكرر الخطأ راجع سجل الأحداث."
        : "لا توجد نافذة موافقة فعّالة حالياً. حدّث الجلسة أو أعد تشغيل الخطوة المطلوبة."
    );
    const spec = {
      id: windowId,
      type: "assistant_notes",
      title: isError ? "تفاصيل المشكلة" : "الإجراء المطلوب",
      status: isError ? "يحتاج مراجعة" : "بانتظارك",
      state: "open",
      hidden: false,
      ui_auxiliary: true,
      interactive: true,
      z_index: 1050,
      props: {
        analysisId: "leon_flow_attention",
        notes: [cleanMessage],
        showDetails: false,
      },
    };
    openAuxWindowIds.add(windowId);
    renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, spec));
    requestAnimationFrame(() => windowManager?.focusWindow(windowId));
  }

  function focusFlowTarget(target) {
    const mode = String(avatar?.mode || "idle");
    const spec = flowWindowSpec(target);
    if (revealFlowWindow(spec)) {
      const label = windowLabel(spec);
      showWorkspaceNotice(`تم فتح نافذة ${label}.`, "info");
      return;
    }

    if (target === "report" && mode === "waiting_approval") {
      const message = avatar?.bubbleTextEl?.textContent || "لا توجد موافقة فعّالة مرتبطة بهذه الجلسة حالياً.";
      openFlowAttentionWindow("action", message);
      showWorkspaceNotice("لا توجد نافذة موافقة فعّالة؛ عرضت تفاصيل الحالة الحالية.", "info", 5600);
      return;
    }
    if (["warning", "error", "failed"].includes(mode)) {
      const message = lastWorkspaceNotice.kind === "error"
        ? lastWorkspaceNotice.message
        : (avatar?.bubbleTextEl?.textContent || avatar?.taskEl?.textContent);
      openFlowAttentionWindow("error", message);
      showWorkspaceNotice("تم فتح تفاصيل المشكلة المتاحة.", "error", 5600);
      return;
    }

    showWorkspaceNotice(
      target === "preview"
        ? "لا يوجد مستند أو مصدر مفتوح في هذه الجلسة."
        : "لا توجد نتيجة أو نافذة إجراء متاحة في هذه الجلسة.",
      "warning",
      5200
    );
  }

  function updateFlowState(mode) {
    const svg = ensureFlowLinksSvg();
    if (!svg) return;
    const normalized = String(mode || avatar?.mode || "idle");
    let state = "idle";
    let activeLeg = "none";
    let previewLabel = "استلام المستند";
    let reportLabel = "بانتظار التحليل";
    let previewDetail = "اضغط لفتح المصدر";
    let reportDetail = "اضغط لفتح النتيجة";
    let previewStatus = "hidden";
    let reportStatus = "hidden";

    if (["reading_document", "scanning"].includes(normalized)) {
      state = "reading";
      activeLeg = "preview";
      previewLabel = "قراءة المستند";
      previewDetail = "بيانات حية داخلة إلى LEON";
      previewStatus = "active";
      reportLabel = "بانتظار القراءة";
    } else if (["thinking", "matching", "running", "executing"].includes(normalized)) {
      state = "processing";
      activeLeg = "both";
      previewLabel = "تم استلام البيانات";
      previewDetail = "اضغط لمراجعة المصدر";
      previewStatus = "done";
      reportLabel = "مطابقة وبناء التقرير";
      reportDetail = "تحليل مباشر من LEON";
      reportStatus = "active";
    } else if (["waiting_approval", "waiting_user"].includes(normalized)) {
      state = "review";
      activeLeg = "report";
      previewLabel = "اكتمل الفحص";
      previewDetail = "اضغط لمراجعة المصدر";
      previewStatus = "done";
      reportLabel = normalized === "waiting_approval" ? "بانتظار الموافقة" : "بانتظار اختيارك";
      reportDetail = "اضغط لفتح الإجراء المطلوب";
      reportStatus = "active";
    } else if (["success", "completed"].includes(normalized)) {
      state = "complete";
      activeLeg = "both";
      previewLabel = "تمت قراءة المستند";
      reportLabel = "التقرير جاهز";
    } else if (["warning", "error", "failed"].includes(normalized)) {
      state = "error";
      activeLeg = "both";
      previewLabel = "راجع بيانات المصدر";
      previewDetail = "اضغط لفحص المستند";
      previewStatus = "error";
      reportLabel = "يحتاج إلى مراجعة";
      reportDetail = "اضغط لفتح تفاصيل المشكلة";
      reportStatus = "error";
    }

    svg.dataset.flowState = state;
    svg.dataset.activeLeg = activeLeg;
    const previewText = svg.querySelector('[data-flow-label="preview"]');
    const reportText = svg.querySelector('[data-flow-label="report"]');
    const previewDetailText = svg.querySelector('[data-flow-detail="preview"]');
    const reportDetailText = svg.querySelector('[data-flow-detail="report"]');
    const previewStage = svg.querySelector('[data-flow-stage="preview"]');
    const reportStage = svg.querySelector('[data-flow-stage="report"]');
    if (previewText) previewText.textContent = previewLabel;
    if (reportText) reportText.textContent = reportLabel;
    if (previewDetailText) previewDetailText.textContent = previewDetail;
    if (reportDetailText) reportDetailText.textContent = reportDetail;
    if (previewStage) previewStage.dataset.stageStatus = previewStatus;
    if (reportStage) reportStage.dataset.stageStatus = reportStatus;
  }

  function setFlowPath(name, start, end) {
    const svg = ensureFlowLinksSvg();
    const paths = svg && svg.querySelectorAll(`[data-flow-path="${name}"]`);
    if (!paths?.length || !start || !end) return;
    const midX = (start.x + end.x) / 2;
    const d = `M ${start.x} ${start.y} C ${midX} ${start.y}, ${midX} ${end.y}, ${end.x} ${end.y}`;
    paths.forEach((path) => path.setAttribute("d", d));
    const drawPath = svg.querySelector(`[data-flow-draw="${name}"]`);
    if (drawPath) {
      drawPath.setAttribute("d", d);
      const length = Math.max(1, drawPath.getTotalLength());
      drawPath.style.setProperty("--flow-length", `${length}px`);
    }
    const route = svg.querySelector(`#ws-flow-${name}-route`);
    const stage = svg.querySelector(`[data-flow-stage="${name}"]`);
    if (route && stage) {
      const point = route.getPointAtLength(route.getTotalLength() * 0.5);
      stage.setAttribute("transform", `translate(${point.x} ${point.y - 38})`);
    }
  }

  function setFlowNode(name, point) {
    const node = flowLinksSvg?.querySelector(`[data-flow-node="${name}"]`);
    if (node && point) node.setAttribute("transform", `translate(${point.x} ${point.y})`);
  }

  function syncLeonFlowMotion() {
    if (!flowStaticGeometry || !flowLinksSvg || !avatar || document.hidden) return;
    const avatarCore = avatar.el && avatar.el.querySelector(".ws-leon-core");
    if (!avatarCore) return;

    const canvasRect = canvasEl.getBoundingClientRect();
    const avatarRect = avatarCore.getBoundingClientRect();
    const leonInput = {
      x: avatarRect.right - canvasRect.left,
      y: avatarRect.top + avatarRect.height / 2 - canvasRect.top,
    };
    const leonOutput = {
      x: avatarRect.left - canvasRect.left,
      y: avatarRect.top + avatarRect.height / 2 - canvasRect.top,
    };

    setFlowPath("preview", flowStaticGeometry.source, leonInput);
    setFlowPath("report", leonOutput, flowStaticGeometry.target);
    setFlowNode("leon-input", leonInput);
    setFlowNode("leon-output", leonOutput);
  }

  function startFlowMotionLoop() {
    if (flowMotionFrame !== null) return;
    const followLeon = () => {
      syncLeonFlowMotion();
      flowMotionFrame = requestAnimationFrame(followLeon);
    };
    flowMotionFrame = requestAnimationFrame(followLeon);
  }

  function ensureOrderLinkSvg() {
    if (orderLinkSvg || !canvasEl) return orderLinkSvg;
    orderLinkSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    orderLinkSvg.setAttribute("class", "ws-order-link is-hidden");
    orderLinkSvg.setAttribute("aria-hidden", "true");
    orderLinkSvg.innerHTML = `
      <defs>
        <linearGradient id="ws-order-link-gradient" x1="0" x2="1">
          <stop offset="0%" stop-color="#4fd1c5"></stop>
          <stop offset="52%" stop-color="#6d5efc"></stop>
          <stop offset="100%" stop-color="#4f8cff"></stop>
        </linearGradient>
        <filter id="ws-order-link-glow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="3.2" result="blur"></feGaussianBlur>
          <feMerge><feMergeNode in="blur"></feMergeNode><feMergeNode in="SourceGraphic"></feMergeNode></feMerge>
        </filter>
        <marker id="ws-order-link-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#6d5efc"></path>
        </marker>
      </defs>
      <path class="ws-order-link-track" data-order-link-track></path>
      <path class="ws-order-link-draw" data-order-link-draw></path>
      <path id="ws-order-link-route" class="ws-order-link-path" data-order-link-path marker-end="url(#ws-order-link-arrow)"></path>
      <g aria-hidden="true">
        <circle class="ws-order-link-packet" r="4"><animateMotion dur="1.85s" repeatCount="indefinite"><mpath href="#ws-order-link-route"></mpath></animateMotion></circle>
        <circle class="ws-order-link-packet" r="2.7"><animateMotion dur="1.85s" begin="-.92s" repeatCount="indefinite"><mpath href="#ws-order-link-route"></mpath></animateMotion></circle>
      </g>
      <g data-order-link-node="source"><circle class="ws-order-link-node-pulse" r="7"></circle><circle class="ws-order-link-node-core" r="4"></circle></g>
      <g data-order-link-node="target"><circle class="ws-order-link-node-pulse" r="7"></circle><circle class="ws-order-link-node-core" r="4"></circle></g>`;
    canvasEl.appendChild(orderLinkSvg);
    return orderLinkSvg;
  }

  function setOrderLinkState(state) {
    const svg = ensureOrderLinkSvg();
    if (svg) svg.dataset.state = state || "loading";
  }

  function syncOrderLink() {
    const svg = ensureOrderLinkSvg();
    const avatarCore = avatar?.el?.querySelector(".ws-leon-core");
    const target = activeOrderWindowId && windowManager?.windows.get(activeOrderWindowId);
    if (!svg || !canvasEl || !avatarCore || !target || !openAuxWindowIds.has(activeOrderWindowId)) {
      svg?.classList.add("is-hidden");
      return;
    }

    const canvasRect = canvasEl.getBoundingClientRect();
    const avatarRect = avatarCore.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    if (!canvasRect.width || !canvasRect.height || !targetRect.width) {
      svg.classList.add("is-hidden");
      return;
    }
    svg.classList.remove("is-hidden");
    svg.setAttribute("viewBox", `0 0 ${canvasRect.width} ${canvasRect.height}`);

    const avatarCenterX = avatarRect.left + avatarRect.width / 2;
    const targetCenterX = targetRect.left + targetRect.width / 2;
    const targetIsLeft = targetCenterX < avatarCenterX;
    const start = {
      x: (targetIsLeft ? avatarRect.left : avatarRect.right) - canvasRect.left,
      y: avatarRect.top + avatarRect.height / 2 - canvasRect.top,
    };
    const end = {
      x: (targetIsLeft ? targetRect.right : targetRect.left) - canvasRect.left,
      y: Math.min(
        targetRect.bottom - 38,
        Math.max(targetRect.top + 54, avatarRect.top + avatarRect.height / 2)
      ) - canvasRect.top,
    };
    const distance = Math.max(90, Math.abs(end.x - start.x));
    const direction = targetIsLeft ? -1 : 1;
    const bend = Math.min(190, distance * .48);
    const d = `M ${start.x} ${start.y} C ${start.x + bend * direction} ${start.y}, ${end.x - bend * direction} ${end.y}, ${end.x} ${end.y}`;
    svg.querySelectorAll("[data-order-link-track], [data-order-link-draw], [data-order-link-path]").forEach((path) => path.setAttribute("d", d));
    const draw = svg.querySelector("[data-order-link-draw]");
    if (draw) {
      try { draw.style.setProperty("--order-link-length", `${Math.max(1, draw.getTotalLength())}px`); } catch (_) { /* SVG not painted yet */ }
    }
    svg.querySelector('[data-order-link-node="source"]')?.setAttribute("transform", `translate(${start.x} ${start.y})`);
    svg.querySelector('[data-order-link-node="target"]')?.setAttribute("transform", `translate(${end.x} ${end.y})`);
  }

  function startOrderLinkLoop() {
    if (orderLinkFrame !== null) return;
    const follow = () => {
      syncOrderLink();
      orderLinkFrame = requestAnimationFrame(follow);
    };
    orderLinkFrame = requestAnimationFrame(follow);
  }

  function syncFlowScene() {
    if (!canvasEl || !windowManager || !avatar) return;
    rootEl?.classList.add("ws-flow-mode");
    avatar.moveTo(0.5, 0.52);

    const svg = ensureFlowLinksSvg();
    const canvasRect = canvasEl.getBoundingClientRect();
    svg.setAttribute("viewBox", `0 0 ${canvasRect.width} ${canvasRect.height}`);

    const docEntry = [...windowManager.windows.entries()].find(([, el]) => {
      const spec = JSON.parse(el.dataset.spec || "{}");
      return spec.type === "document_viewer";
    });
    const reportEntry = [...windowManager.windows.entries()].find(([, el]) => {
      const spec = JSON.parse(el.dataset.spec || "{}");
      return spec.type === "inventory_forensics" || spec.type === "courier_settlement_analysis" || spec.type === "purchase_invoice_analysis" || spec.type === "live_report";
    });
    const avatarCore = avatar.el && avatar.el.querySelector(".ws-leon-core");
    if (!docEntry || !reportEntry || !avatarCore) {
      flowStaticGeometry = null;
      svg.classList.add("ws-flow-links-hidden");
      return;
    }

    svg.classList.remove("ws-flow-links-hidden");
    const docRect = docEntry[1].getBoundingClientRect();
    const reportRect = reportEntry[1].getBoundingClientRect();
    const avatarRect = avatarCore.getBoundingClientRect();
    const leonInput = {
      x: avatarRect.right - canvasRect.left,
      y: avatarRect.top + avatarRect.height / 2 - canvasRect.top,
    };
    const leonOutput = {
      x: avatarRect.left - canvasRect.left,
      y: avatarRect.top + avatarRect.height / 2 - canvasRect.top,
    };
    const source = {
      x: docRect.left - canvasRect.left,
      y: docRect.top + docRect.height / 2 - canvasRect.top,
    };
    const target = {
      x: reportRect.right - canvasRect.left,
      y: reportRect.top + reportRect.height / 2 - canvasRect.top,
    };
    flowStaticGeometry = { source, target };
    setFlowPath(
      "preview",
      source,
      leonInput
    );
    setFlowPath(
      "report",
      leonOutput,
      target
    );
    setFlowNode("source", source);
    setFlowNode("leon-input", leonInput);
    setFlowNode("leon-output", leonOutput);
    setFlowNode("target", target);
    updateFlowState(avatar.mode);
  }

  function renderWorkspaceWindows(windows) {
    const incoming = windows || [];
    const localInteractiveWindows = (lastWorkspaceWindows || []).filter(
      (item) => (
        ["order_details", "employee_performance"].includes(item.type)
        || item.id === "win_leon_flow_attention"
      )
        && !incoming.some((candidate) => candidate.id === item.id)
    );
    lastWorkspaceWindows = [...incoming, ...localInteractiveWindows];
    lastWorkspaceWindows
      .filter(
        (item) => item.type === "workflow_selector"
          || (
            item.type === "approval_panel"
            && (
              (item.props || {}).action === "courier_posting"
              || (item.props || {}).action === "return_posting"
              || (item.props || {}).action === "purchase_posting"
              || (store.getSession() || {}).status === "waiting_approval"
              || avatar?.mode === "waiting_approval"
            )
          )
      )
      .forEach((item) => openAuxWindowIds.add(item.id));
    const visible = normalizeWorkspaceWindows(lastWorkspaceWindows);
    renderWindowTray(lastWorkspaceWindows);
    windowManager.renderWindows(visible);
    requestAnimationFrame(syncFlowScene);
    requestAnimationFrame(syncOrderLink);
  }

  function showWorkspaceWindowType(type) {
    const target = (lastWorkspaceWindows || []).find((item) => item.type === type);
    if (!target) return false;
    openAuxWindowIds.add(target.id);
    renderWorkspaceWindows(lastWorkspaceWindows);
    requestAnimationFrame(() => windowManager.focusWindow(target.id));
    return true;
  }

  function ensureWorkflowSelectorWindow() {
    const session = store.getSession() || {};
    const metadata = session.metadata || {};
    const lastIntelligence = metadata.last_intelligence || {};
    const recommended = lastIntelligence.document_kind;
    const selectorId = "win_workflow_selector_manual";
    const current = (lastWorkspaceWindows || []).find(
      (item) => item.type === "workflow_selector"
    );
    const selectorSpec = {
      ...(current || {}),
      id: current?.id || selectorId,
      type: "workflow_selector",
      title: "اختيار نوع العمل",
      status: "waiting",
      state: "open",
      hidden: false,
      placement: "center",
      position: current?.position || { x: 540, y: 250, width: 440, height: 310 },
      z_index: 1000,
      interactive: true,
      props: {
        ...(current?.props || {}),
        recommendedWorkflow: recommended || null,
        recommendedConfidence: lastIntelligence.confidence ?? null,
      },
    };
    openAuxWindowIds.add(selectorSpec.id);
    renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, selectorSpec));
    requestAnimationFrame(() => {
      windowManager.openWindow(selectorSpec);
      windowManager.focusWindow(selectorSpec.id);
    });
    return selectorSpec;
  }

  async function startWorkflowType(type) {
    const selectedType = String(type || "").trim();
    if (!selectedType || selectedType === "unknown_document") {
      ensureWorkflowSelectorWindow();
      return { waiting: "user_input" };
    }
    if (workflowBusy) {
      showWorkspaceNotice("انتظر حتى تكتمل الخطوة الحالية ثم اختر نوع العمل.", "info", 4800);
      return { waiting: "running" };
    }

    workflowBusy = true;
    try {
      const current = store.getSession() || {};
      const currentType = String(current.workflow_type || "");
      const isActive = ["running", "waiting_approval"].includes(current.status);

      if (isActive && currentType === selectedType) {
        if (current.status === "waiting_approval") {
          showWorkspaceWindowType("approval_panel");
          avatar.setMode("waiting_approval");
          avatar.speak("هذا المسار ينتظر موافقتك من النافذة الظاهرة.");
          return { waiting: "approval", session: current };
        }
        avatar.setMode("running");
        avatar.speak("أكمل تشغيل مسار العمل الحالي.");
      } else {
        if (isActive) {
          avatar.setMode("running");
          avatar.setTask("أبدّل إلى نوع العمل الجديد");
          avatar.speak("سأوقف المسار السابق وأبدأ النوع الذي اخترته.");
          showWorkspaceNotice("جاري تبديل نوع العمل...", "info");
          await workflowClient.cancelWorkflow();
        }
        avatar.setMode("running");
        avatar.speak("بدأ تشغيل سير العمل المختار.");
        showWorkspaceNotice("بدأ تشغيل سير العمل المختار...", "info");
        await workflowClient.startWorkflow(selectedType);
      }

      const result = await workflowClient.runUntilBlocked();
      if (result?.waiting === "approval") {
        avatar.setMode("waiting_approval");
        showWorkspaceWindowType("approval_panel");
        showWorkspaceNotice("سير العمل ينتظر موافقتك.", "info");
      } else if (result?.waiting === "user_input") {
        avatar.setMode("waiting_user");
        showWorkspaceNotice("سير العمل يحتاج اختياراً منك.", "info");
        showWorkspaceWindowType("workflow_selector");
      } else {
        const readOnlyLabels = {
          return_statement: "اكتملت قراءة كشف الراجع",
          purchase_invoice: "اكتملت قراءة مستند الشراء",
          inventory_forensics: "المحقق الذكي للمخزون جاهز",
        };
        const completionLabel = readOnlyLabels[selectedType] || "اكتمل سير العمل بنجاح";
        avatar.setMode("success");
        avatar.setTask(completionLabel);
        avatar.speak(`${completionLabel}. عرضت لك البيانات والجداول المستخرجة للمراجعة.`);
        avatar.playTone("success");
        if (["return_statement", "purchase_invoice", "inventory_forensics"].includes(selectedType)) {
          const resultWindow = ["inventory_forensics", "purchase_invoice_analysis", "courier_settlement_analysis", "raw_table_preview", "document_intelligence", "assistant_notes"]
            .find((windowType) => showWorkspaceWindowType(windowType));
          if (!resultWindow) {
            showWorkspaceNotice("اكتملت القراءة، لكن المستند لم يحتوِ على جدول قابل للاستخراج.", "warning", 6500);
          } else {
            showWorkspaceNotice(`${completionLabel} وتم فتح النتيجة.`, "success", 5200);
          }
        } else {
          showWorkspaceNotice("اكتمل سير العمل بنجاح.", "success");
        }
      }
      return result;
    } finally {
      workflowBusy = false;
    }
  }

  async function runRecommendedWorkflow() {
    const session = store.getSession() || {};
    const metadata = session.metadata || {};
    const recommended = (metadata.last_intelligence || {}).document_kind;
    const supported = new Set([
      "courier_settlement",
      "return_statement",
      "purchase_invoice",
      "inventory_forensics",
      "mock_workspace",
    ]);
    const candidate = supported.has(recommended)
      ? recommended
      : (supported.has(session.workflow_type) ? session.workflow_type : null);
    if (!candidate) {
      ensureWorkflowSelectorWindow();
      avatar.setMode("waiting_user");
      avatar.speak("حدد نوع العمل أولاً، وبعدها أشغل سير العمل.");
      showWorkspaceNotice("حدد نوع العمل أولاً من النافذة الظاهرة.", "info");
      return { waiting: "user_input" };
    }
    return startWorkflowType(candidate);
  }

  function ensureCourierApprovalWindow(analysisId, preview = {}) {
    if (!analysisId) return false;
    const current = (lastWorkspaceWindows || []).find(
      (item) => item.type === "approval_panel"
        && (item.props || {}).action === "courier_posting"
    );
    const windowId = current?.id || `win_approval_courier_${String(analysisId).slice(0, 8)}`;
    const safeRows = Number(preview?.safe_rows || 0);
    const approvalSpec = {
      ...(current || {}),
      id: windowId,
      type: "approval_panel",
      title: "موافقة تنفيذ كشف التسديد",
      status: "waiting",
      state: "open",
      hidden: false,
      placement: "center",
      position: current?.position || { x: 520, y: 220, width: 460, height: 300 },
      z_index: 1000,
      interactive: true,
      props: {
        ...(current?.props || {}),
        action: "courier_posting",
        analysisId,
        step_id: "courier_posting_approval",
        message: safeRows
          ? `تنفيذ ${safeRows} طلب مطابق وسليم عبر كشف الشحن الحالي؟`
          : "هل تريد تنفيذ الطلبات المطابقة السليمة في هذا الكشف؟",
        hint: "سيتم تنفيذ الصفوف الآمنة فقط بعد موافقتك الصريحة.",
        acceptText: "تنفيذ آمن",
        rejectText: "إلغاء",
        preview: preview || {},
      },
    };
    openAuxWindowIds.add(windowId);
    renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, approvalSpec));
    requestAnimationFrame(() => {
      windowManager.openWindow(approvalSpec);
      windowManager.focusWindow(windowId);
    });
    return true;
  }

  function invalidateCourierApprovalWindow(analysisId) {
    const staleIds = new Set(
      (lastWorkspaceWindows || [])
        .filter((item) => (
          item.type === "approval_panel"
          && (item.props || {}).action === "courier_posting"
          && (!analysisId || String((item.props || {}).analysisId) === String(analysisId))
        ))
        .map((item) => item.id)
    );
    if (!staleIds.size) return;
    staleIds.forEach((id) => openAuxWindowIds.delete(id));
    renderWorkspaceWindows(
      (lastWorkspaceWindows || []).filter((item) => !staleIds.has(item.id))
    );
    showWorkspaceNotice(
      "تم تحديث حسابات الكشف. افتح التنفيذ مرة أخرى لمراجعة الأرقام الجديدة.",
      "info",
      4500
    );
  }

  function ensureReturnApprovalWindow(analysisId, preview = {}) {
    if (!analysisId) return false;
    const current = (lastWorkspaceWindows || []).find(
      (item) => item.type === "approval_panel"
        && (item.props || {}).action === "return_posting"
    );
    const windowId = current?.id || `win_approval_return_${String(analysisId).slice(0, 8)}`;
    const safeRows = Number(preview?.safe_rows || 0);
    const totalUnits = Number(preview?.total_units || 0);
    const approvalSpec = {
      ...(current || {}),
      id: windowId,
      type: "approval_panel",
      title: "موافقة تنفيذ كشف الراجع",
      status: "waiting",
      state: "open",
      hidden: false,
      placement: "center",
      position: current?.position || { x: 520, y: 205, width: 480, height: 340 },
      z_index: 1200,
      interactive: true,
      props: {
        ...(current?.props || {}),
        action: "return_posting",
        analysisId,
        step_id: "return_posting_approval",
        message: safeRows
          ? `ترجيع ${safeRows} طلب مطابق وإعادة ${totalUnits} قطعة إلى المخزون؟`
          : "هل تريد تنفيذ الطلبات المطابقة في كشف الراجع وإعادة مخزونها؟",
        hint: "سيتم تنفيذ الصفوف المؤكدة فقط. الصفوف المستبعدة أو غير المطابقة لن تتغير.",
        acceptText: "تنفيذ الراجع",
        rejectText: "إلغاء",
        preview: { kind: "return", ...(preview || {}) },
      },
    };
    openAuxWindowIds.add(windowId);
    renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, approvalSpec));
    requestAnimationFrame(() => {
      windowManager.openWindow(approvalSpec);
      windowManager.focusWindow(windowId);
    });
    return true;
  }

  function ensurePurchaseApprovalWindow(analysisId, preview = {}) {
    if (!analysisId) return false;
    const current = (lastWorkspaceWindows || []).find(
      (item) => item.type === "approval_panel"
        && (item.props || {}).action === "purchase_posting"
    );
    const windowId = current?.id || `win_approval_purchase_${String(analysisId).slice(0, 8)}`;
    const supplier = preview.supplier || {};
    const supplierName = (supplier.matched || {}).name || supplier.source_name || "المورد الجديد";
    const approvalSpec = {
      ...(current || {}),
      id: windowId,
      type: "approval_panel",
      title: "موافقة إدخال فاتورة الشراء",
      status: "waiting",
      state: "open",
      hidden: false,
      placement: "center",
      position: current?.position || { x: 520, y: 200, width: 500, height: 360 },
      z_index: 1250,
      interactive: true,
      props: {
        ...(current?.props || {}),
        action: "purchase_posting",
        analysisId,
        step_id: "purchase_posting_approval",
        message: `اعتماد فاتورة ${supplierName} وإضافة ${Number(preview.total_units || 0)} قطعة للمخزون؟`,
        hint: "سيتم إنشاء المنتجات الجديدة مخفية عن المتجر وبسعر بيع مؤقت يساوي التكلفة، وتسجيل الشراء آجل، ولن تتكرر العملية عند الضغط مرة ثانية.",
        acceptText: "اعتماد وإضافة للمخزون",
        rejectText: "إلغاء",
        preview: { kind: "purchase", ...(preview || {}) },
      },
    };
    openAuxWindowIds.add(windowId);
    renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, approvalSpec));
    requestAnimationFrame(() => {
      windowManager.openWindow(approvalSpec);
      windowManager.focusWindow(windowId);
    });
    return true;
  }

  function printCourierReport() {
    const entry = [...windowManager.windows.values()].find((el) => {
      const spec = JSON.parse(el.dataset.spec || "{}");
      return spec.type === "courier_settlement_analysis";
    });
    if (!entry) return;
    const cleanup = () => {
      document.body.classList.remove("ws-print-report-mode");
      entry.classList.remove("ws-print-report-target");
      window.removeEventListener("afterprint", cleanup);
    };
    document.body.classList.add("ws-print-report-mode");
    entry.classList.add("ws-print-report-target");
    window.addEventListener("afterprint", cleanup, { once: true });
    window.print();
    window.setTimeout(cleanup, 1500);
  }

  function applyWorkspaceEvent(data) {
    if (!data || !windowManager) return;
    if (data.type === "window.opened" && data.payload && data.payload.window) {
      renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, data.payload.window));
      return;
    }
    if (data.type === "window.updated" && data.payload && data.payload.windows) {
      renderWorkspaceWindows(data.payload.windows);
      return;
    }
    windowManager.applyEvent(data);
    requestAnimationFrame(syncFlowScene);
  }

  function updateUrl(sessionId) {
    const url = new URL(window.location.href);
    url.searchParams.set("session", sessionId);
    window.history.replaceState({}, "", url);
  }

  async function api(path, options = {}) {
    const res = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const code = data.error || `HTTP ${res.status}`;
      if (code === "not_found") {
        throw new Error("SESSION_NOT_FOUND");
      }
      throw new Error(data.message || code);
    }
    return data;
  }

  function ensureTimelineWindow(session) {
    const windows = session.windows || [];
    if (!IS_DEV) {
      return windows.filter((w) => w.type !== "session_timeline");
    }
    if (windows.some((w) => w.type === "session_timeline")) return windows;
    return [
      ...windows,
      {
        id: "win_timeline_1",
        type: "session_timeline",
        title: "سجل الأحداث",
        status: "ready",
        position: { x: 40, y: 420, width: 360, height: 200 },
        placement: "bottom",
        z_index: 8,
        props: { items: timelineStore.items },
        interactive: false,
      },
    ];
  }

  function patchDocumentViewerLoading(loading) {
    const session = store.getSession();
    if (!session || !session.windows) return;
    const windows = session.windows.map((w) => {
      if (w.type !== "document_viewer") return w;
      return {
        ...w,
        status: loading ? "loading" : w.status,
        props: { ...(w.props || {}), loading },
      };
    });
    renderWorkspaceWindows(windows);
  }

  function showDocumentViewerError(message) {
    const session = store.getSession();
    if (!session || !session.windows) return;
    const windows = session.windows.map((w) => {
      if (w.type !== "document_viewer") return w;
      return {
        ...w,
        status: "error",
        props: { ...(w.props || {}), loading: false, error: message },
      };
    });
    renderWorkspaceWindows(windows);
  }

  function renderFromSession(session) {
    if (!session) return;
    setStatus(session.status);
    const windows = ensureTimelineWindow(session);
    renderWorkspaceWindows(windows);
    avatar.applyState(session.avatar_state || {});
    avatar.moveTo(0.5, 0.52);
    updateIntelligenceButton();
    updateCourierButton();
    if (btnRun) {
      btnRun.disabled = session.status === "running" || session.status === "completed";
    }
    syncCommandControls();
  }

  function onSessionUpdate(session) {
    store.setSession(session);
    renderFromSession(session);
    const courier = session && session.courier_analysis;
    if (courier && ["completed", "posted"].includes(courier.status)) {
      completeDocumentScan("اكتمل فحص ومطابقة الكشف");
    }
  }

  function connectStream(sessionId, replayFromStart = false) {
    if (eventStream) eventStream.disconnect();
    LiveReportWindow.resetDedup();
    eventStream = new WorkspaceEventStream(sessionId);
    if (replayFromStart) {
      // Recovery: report is empty but the cursor is ahead — replay everything
      // so the live report re-fills. Non-report replayed events are ignored.
      eventStream.lastEventId = 0;
    }

    eventStream.onAny((data) => {
      if (timelineStore.addFromEvent(data)) {
        windowManager.updateTimelineItems(timelineStore.items);
      }
      if (!data._fromReplay) {
        applyWorkspaceEvent(data);
      } else if (data.type === "report.appended") {
        // On replay we only re-hydrate the streaming report; window state is
        // already authoritative from the session GET, so we do not re-apply
        // replayed window/workflow events (which could resurrect stale cards).
        applyWorkspaceEvent(data);
      }
    });

    eventStream.on("workflow.started", (data) => {
      if (data._fromReplay) return;
      const title = (data.payload && data.payload.title) || "";
      windowManager.applyEvent({
        type: "report.appended",
        payload: { line: `— بدأ سير عمل جديد${title ? ": " + title : ""} —` },
      });
    });

    eventStream.on("avatar.updated", (data) => {
      if (data.payload && data.payload.avatar_state) {
        avatar.applyState(data.payload.avatar_state);
        store.patchSession({ avatar_state: data.payload.avatar_state });
      }
    });

    eventStream.on("window.updated", (data) => {
      if (data.payload && data.payload.windows) {
        const withTimeline = ensureTimelineWindow({ windows: data.payload.windows });
        renderWorkspaceWindows(withTimeline);
        store.patchSession({ windows: data.payload.windows });
      }
    });

    eventStream.on("document.preview.ready", () => {
      setUploadBusy(false);
      updateIntelligenceButton();
    });

    eventStream.on("document.intelligence.started", () => {
      avatar.setMode("reading_document");
      avatar.setProgress(10);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 6, stage: "تهيئة المستند للفحص" },
      });
      avatar.speak("أبدأ قراءة المستند مبدئياً.");
    });

    eventStream.on("document.preprocessing.started", () => {
      avatar.setProgress(20);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 20, stage: "تدوير الصورة وتحسين الدقة" },
      });
    });

    eventStream.on("document.preprocessing.completed", () => {
      avatar.setProgress(30);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 38, stage: "اكتمل تحسين الصورة" },
      });
    });

    eventStream.on("document.text.extracted", () => {
      avatar.setProgress(40);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 52, stage: "استخراج النص والأرقام" },
      });
    });

    eventStream.on("document.vision.started", () => {
      avatar.setProgress(47);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 64, stage: "قراءة بصرية دقيقة للصفوف" },
      });
    });

    eventStream.on("document.vision.completed", () => {
      avatar.setProgress(54);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 82, stage: "تدقيق الأرقام والحقول" },
      });
    });

    eventStream.on("document.tables.extracted", () => {
      avatar.setProgress(58);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 92, stage: "تنظيم صفوف الكشف" },
      });
    });

    eventStream.on("document.intelligence.completed", () => {
      const workflowType = String((store.getSession() || {}).workflow_type || "");
      const continuesWithMatching = ["return_statement", "purchase_invoice"].includes(workflowType);
      avatar.setMode(continuesWithMatching ? "matching" : "success");
      avatar.setProgress(continuesWithMatching ? 58 : 100);
      completeDocumentScan("اكتمل فحص المستند");
    });

    eventStream.on("document.intelligence.failed", (data) => {
      avatar.setMode("warning");
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: false, progress: 100, stage: "تعذّر فحص المستند", error: true },
      });
      const err = (data.payload && data.payload.error) || "فشل تحليل المستند";
      avatar.speak(err);
    });

    eventStream.on("courier.analysis.started", () => {
      avatar.setMode("reading_document");
      avatar.setProgress(62);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 62, stage: "قراءة صفوف كشف التوصيل" },
      });
      avatar.speak("أهلاً، جاري تحليل كشف شركة التوصيل ومطابقة الطلبات...");
      if (progressPanel) {
        progressPanel.reset();
        progressPanel.show();
        progressPanel.markActive("read");
      }
    });

    eventStream.on("courier.rows.parsed", () => {
      avatar.setMode("matching");
      avatar.setProgress(78);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 78, stage: "اكتمل استخراج صفوف الكشف" },
      });
      if (progressPanel) progressPanel.markActive("match");
    });

    eventStream.on("courier.matching.started", () => {
      avatar.setMode("matching");
      avatar.setProgress(85);
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: true, progress: 90, stage: "مطابقة الأرقام مع الطلبات" },
      });
      if (progressPanel) progressPanel.markActive("match");
    });

    eventStream.on("courier.row.matched", (data) => {
      const payload = (data && data.payload) || {};
      const processed = Number(payload.processed || 0);
      const total = Math.max(1, Number(payload.total || 1));
      const progress = Math.min(97, 90 + Math.round((processed / total) * 7));
      avatar.setProgress(Math.min(97, 85 + Math.round((processed / total) * 12)));
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: {
          active: true,
          progress,
          stage: `تم تحليل ${processed} من ${total} صف`,
        },
      });
    });

    eventStream.on("courier.row.corrected", () => {
      avatar.setMode("success");
      avatar.speak("تم تغيير الطلب وإعادة فحص الصف.");
    });

    eventStream.on("courier.issues.detected", () => {
      avatar.setProgress(98);
      if (progressPanel) progressPanel.markActive("fees");
    });

    eventStream.on("courier.financial_preview.ready", () => {
      avatar.setProgress(99);
      if (progressPanel) progressPanel.markActive("profit");
    });

    eventStream.on("courier.analysis.completed", () => {
      avatar.setMode("success");
      avatar.setProgress(100);
      completeDocumentScan("اكتمل فحص ومطابقة الكشف");
      avatar.speak("اكتمل تحليل كشف التسديد — نتائج قراءة فقط.");
      updateCourierButton();
      if (progressPanel) {
        progressPanel.completeAll();
        setTimeout(() => progressPanel.hide(), 2500);
      }
    });

    eventStream.on("courier.analysis.failed", (data) => {
      avatar.setMode("warning");
      windowManager.applyEvent({
        type: "document.scan.updated",
        payload: { active: false, progress: 100, stage: "تعذّر فحص كشف التوصيل", error: true },
      });
      avatar.speak((data.payload && data.payload.error) || "فشل تحليل الكشف");
      if (progressPanel) progressPanel.hide();
    });

    eventStream.on("courier.posting.approval_required", (data) => {
      const payload = data?.payload || {};
      ensureCourierApprovalWindow(payload.analysisId, payload.preview || {});
      avatar.setMode("waiting_approval");
      avatar.speak("التنفيذ يحتاج موافقة صريحة.");
      avatar.playTone("info");
      showWorkspaceNotice("تم تجهيز التنفيذ. راجع المعاينة واضغط «تنفيذ آمن».", "info");
    });

    eventStream.on("return.posting.approval_required", (data) => {
      const payload = data?.payload || {};
      ensureReturnApprovalWindow(payload.analysisId, payload.preview || {});
      avatar.setMode("waiting_approval");
      avatar.speak("راجع عدد الطلبات والقطع، ثم وافق على تنفيذ الراجع.");
      avatar.playTone("info");
      showWorkspaceNotice("تم تجهيز موافقة الراجع. اضغط «تنفيذ الراجع» أو «إلغاء».", "info");
    });

    eventStream.on("purchase.analysis.completed", () => {
      avatar.setMode("success");
      avatar.setProgress(100);
      avatar.speak("اكتملت مطابقة المورد والمنتجات. راجع النافذة قبل الاعتماد.");
      showWorkspaceWindowType("purchase_invoice_analysis");
      showWorkspaceNotice("اكتملت مطابقة فاتورة الشراء وأصبحت جاهزة للمراجعة.", "success", 6000);
    });

    eventStream.on("inventory.forensics.completed", () => {
      avatar.setMode("success");
      avatar.setProgress(100);
      avatar.setTask("اكتمل التحقيق بحركات المخزون");
      avatar.speak("اكتمل تتبع المنتج قطعةً قطعة وربط الحركات بالطلبات والفروع والموظفين.");
      avatar.playTone("success");
      showWorkspaceWindowType("inventory_forensics");
      showWorkspaceNotice("اكتمل التحقيق. راجع الفروقات والحركات ومعرفات القطع في النافذة.", "success", 6500);
    });

    eventStream.on("purchase.posting.approval_required", (data) => {
      const payload = data?.payload || {};
      ensurePurchaseApprovalWindow(payload.analysisId, payload.preview || {});
      avatar.setMode("waiting_approval");
      avatar.speak("راجع المورد والأصناف والكميات، ثم وافق على إضافة الفاتورة للمخزون.");
      avatar.playTone("info");
      showWorkspaceNotice("تم تجهيز الموافقة النهائية لفاتورة الشراء.", "info");
    });

    eventStream.on("purchase.posting.completed", (data) => {
      const posting = data?.payload?.posting || {};
      avatar.setMode("success");
      avatar.speak("تم تسجيل فاتورة الشراء وإضافة الكميات إلى المخزون بنجاح.");
      avatar.playTone("success");
      showWorkspaceNotice(`تم تسجيل عملية الشراء #${posting.purchase_id || ""} وإضافة المخزون.`, "success", 7000);
      refreshSession();
    });

    eventStream.on("courier.posting.started", () => {
      avatar.setMode("matching");
      avatar.speak("بدأ تنفيذ الصفوف المطابقة السليمة.");
      showWorkspaceNotice("بدأ تنفيذ الطلبات السليمة...", "info");
    });

    eventStream.on("courier.posting.completed", (data) => {
      signalPostingSuccess(data?.payload?.posting?.safe_rows || 0);
      const adjustments = data?.payload?.posting?.price_adjustments || [];
      if (adjustments.length) {
        const details = adjustments.map((item) => {
          const type = item.kind === "replacement" ? "استبدال" : "تصحيح سعر";
          return `الطلب ${item.order_number || item.invoice_id}: ${type} من ${Number(item.original_total || 0).toLocaleString("en-US")} إلى ${Number(item.target_total || 0).toLocaleString("en-US")} د.ع`;
        });
        avatar.speak(`اكتمل التنفيذ وتم تعديل سعر ${adjustments.length} طلب.`);
        window.alert(`تم تنفيذ الكشف وتسجيل تغييرات الأسعار:\n${details.join("\n")}`);
      } else {
        avatar.speak("اكتمل التنفيذ الآمن.");
      }
      refreshSession();
    });

    eventStream.on("session.completed", () => {
      setStatus("completed");
      if (btnRun) btnRun.disabled = true;
      refreshSession();
    });

    eventStream.on("session.cancelled", () => {
      setStatus("cancelled");
      if (btnRun) btnRun.disabled = true;
    });

    eventStream.connect();
  }

  async function refreshSession() {
    const session = store.getSession();
    if (!session) return;
    const data = await api(`/sessions/${session.id}`);
    store.setSession(data.session);
    renderFromSession(data.session);
  }

  async function createSession() {
    const data = await api("/sessions", { method: "POST", body: JSON.stringify({}) });
    store.setSession(data.session);
    updateUrl(data.session.id);
    renderFromSession(data.session);
    connectStream(data.session.id);
    return data.session;
  }

  async function recoverMissingSession() {
    console.warn("Workspace session missing — creating a new session");
    try {
      const session = await createSession();
      showWorkspaceNotice("انتهت صلاحية الجلسة السابقة. تم إنشاء جلسة جديدة.", "info", 7000);
      return session;
    } catch (err) {
      avatar.setMode("error");
      avatar.speak(err.message || "تعذّر إنشاء جلسة جديدة.");
      showWorkspaceNotice(err.message || "تعذّر إنشاء جلسة جديدة.", "error", 7000);
      throw err;
    }
  }

  function updateOrderWindow(windowId, patch) {
    const index = (lastWorkspaceWindows || []).findIndex((item) => item.id === windowId);
    if (index >= 0) {
      const current = lastWorkspaceWindows[index];
      lastWorkspaceWindows[index] = {
        ...current,
        ...patch,
        props: { ...(current.props || {}), ...(patch.props || {}) },
      };
    }
    windowManager?.updateWindow(windowId, patch);
    requestAnimationFrame(syncOrderLink);
  }

  function openEmployeePerformanceWindow(data) {
    if (!data || data.restricted || data.error || !Array.isArray(data.performance)) return false;
    const windowId = "win_leon_employee_performance";
    lastWorkspaceWindows = (lastWorkspaceWindows || []).filter(
      (item) => item.type !== "employee_performance" || item.id === windowId
    );
    const spec = {
      id: windowId,
      type: "employee_performance",
      title: "تحليل أداء الموظفين",
      status: "بيانات مباشرة",
      state: "open",
      hidden: false,
      ui_auxiliary: true,
      interactive: true,
      z_index: 1200,
      props: { data },
    };
    openAuxWindowIds.add(windowId);
    renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, spec));
    requestAnimationFrame(() => windowManager?.focusWindow(windowId));
    return true;
  }

  async function fetchOrderJson(url) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 404) throw new Error("رقم الطلب غير موجود في النظام.");
      if (response.status === 403) throw new Error("ليس لديك صلاحية لعرض هذا الطلب.");
      throw new Error(data.message || data.error || "تعذّر جلب بيانات الطلب.");
    }
    return data;
  }

  function waitForOrderStage(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function openLeonOrderDetails(orderId) {
    const numericId = Number(orderId);
    if (!Number.isInteger(numericId) || numericId <= 0) {
      throw new Error("اكتب رقم طلب صحيح حتى أفتحه.");
    }

    const windowId = `win_leon_order_${numericId}`;
    (lastWorkspaceWindows || [])
      .filter((item) => item.type === "order_details" && item.id !== windowId)
      .forEach((item) => openAuxWindowIds.delete(item.id));
    lastWorkspaceWindows = (lastWorkspaceWindows || []).filter(
      (item) => item.type !== "order_details" || item.id === windowId
    );

    const spec = {
      id: windowId,
      type: "order_details",
      title: `تفاصيل الطلب #${numericId}`,
      status: "جاري البحث",
      state: "open",
      ui_auxiliary: true,
      z_index: 260,
      props: {
        orderId: numericId,
        phase: "locating",
        message: "أحدد الطلب وأراجع صلاحية الوصول...",
      },
    };
    activeOrderWindowId = windowId;
    openAuxWindowIds.add(windowId);
    renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, spec));
    requestAnimationFrame(() => windowManager?.focusWindow(windowId));
    setOrderLinkState("loading");
    avatar.setMode("thinking");
    avatar.setTask(`أبحث عن الطلب ${numericId}`);
    avatar.speak(`أبحث الآن عن الطلب رقم ${numericId} وأجمع تفاصيله وحركاته المالية.`);

    try {
      const details = await fetchOrderJson(`/orders/details/${numericId}`);
      updateOrderWindow(windowId, {
        status: "بيانات الطلب",
        props: { phase: "details", details, message: "تم تحميل بيانات الطلب." },
      });
      avatar.setMode("reading_document");
      avatar.setTask("أقرأ تفاصيل الطلب والأصناف");

      const historyRequest = fetchOrderJson(`/orders/history/${numericId}`);
      await waitForOrderStage(420);
      updateOrderWindow(windowId, {
        status: "الحركات المالية",
        props: { phase: "finance", message: "تم تحميل الدفعات والحسابات." },
      });
      avatar.setMode("matching");
      avatar.setTask("أطابق الدفعات والحركات المالية");

      await waitForOrderStage(460);
      updateOrderWindow(windowId, {
        status: "سجل الطلب",
        props: { phase: "history", message: "أجمع سجل التغييرات والموظفين..." },
      });
      const historyData = await historyRequest;
      await waitForOrderStage(260);
      updateOrderWindow(windowId, {
        status: "مكتمل",
        props: {
          phase: "complete",
          history: historyData.events || [],
          historyStats: historyData.stats || {},
          message: "اكتملت جميع تفاصيل الطلب.",
        },
      });
      setOrderLinkState("complete");
      avatar.setMode("success");
      avatar.setTask(`اكتملت تفاصيل الطلب ${numericId}`);
      avatar.speak(`اكتملت تفاصيل الطلب رقم ${numericId}. عرضت بيانات الزبون والأصناف والدفعات وسجل الحركات في النافذة المرتبطة.`);
      avatar.playTone("success");
      showWorkspaceNotice(`تم فتح جميع تفاصيل الطلب #${numericId}.`, "success", 4800);
      return true;
    } catch (error) {
      updateOrderWindow(windowId, {
        status: "تعذّر التحميل",
        props: { phase: "error", error: error.message || "تعذّر تحميل الطلب." },
      });
      setOrderLinkState("error");
      avatar.setMode("error");
      avatar.setTask("تعذّر فتح الطلب");
      avatar.speak(error.message || "تعذّر فتح تفاصيل الطلب.");
      avatar.playTone("error");
      showWorkspaceNotice(error.message || "تعذّر فتح تفاصيل الطلب.", "error", 6500);
      return false;
    }
  }

  async function init() {
    canvas = new WorkspaceCanvas(canvasEl);
    timelineStore = new SessionTimelineStore();
    windowManager = new WorkspaceWindowManager(windowsLayer);
    if (window.WorkspaceLayoutDirector) {
      windowManager.setLayoutDirector(
        new WorkspaceLayoutDirector(() => canvas.getSize())
      );
    }
    avatar = new LeonAvatarAdapter(avatarLayer, canvas);
    startFlowMotionLoop();
    startOrderLinkLoop();
    if (window.WorkspaceProgressPanel) {
      progressPanel = new WorkspaceProgressPanel(canvasEl);
    }

    workflowClient = new WorkspaceWorkflowClient({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onSessionUpdate,
      onWaiting: (kind) => setStatus(kind === "approval" ? "waiting_approval" : "waiting_user"),
      onError: (err) => {
        if (String(err.message || "").includes("الجلسة غير موجودة")) {
          recoverMissingSession();
          return;
        }
        alert(err.message);
      },
    });

    purchaseAnalysisClient = new PurchaseAnalysisClient({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onSessionUpdate,
    });

    inventoryForensicsClient = new InventoryForensicsClient({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onSessionUpdate,
    });

    windowManager.setWorkflowHandlers({
      onApprove: async () => {
        await workflowClient.submitApproval(true);
        const s = store.getSession();
        if (s && s.status !== "completed") {
          await workflowClient.runNextStep();
        }
      },
      onReject: async () => {
        await workflowClient.submitApproval(false);
      },
      onCourierPostingApprove: async (spec) => {
        const analysisId = spec && spec.props && spec.props.analysisId;
        if (!analysisId || !courierAnalysisClient) return;
        try {
          avatar.setMode("matching");
          avatar.speak("جاري تنفيذ الطلبات السليمة...");
          showWorkspaceNotice("جاري تنفيذ الطلبات السليمة، انتظر قليلاً...", "info");
          const result = await courierAnalysisClient.approvePosting(analysisId);
          signalPostingSuccess(result?.posting?.safe_rows || 0);
          await refreshSession();
        } catch (e) {
          avatar.setMode("warning");
          avatar.speak("تعذّر التنفيذ. راجع الرسالة الظاهرة.");
          avatar.playTone("error");
          showWorkspaceNotice(e.message || "فشل تنفيذ كشف التسديد", "error", 7000);
          await refreshSession();
          alert(e.message || "فشل تنفيذ كشف التسديد");
          throw e;
        }
      },
      onCourierPostingReject: async (spec) => {
        const analysisId = spec && spec.props && spec.props.analysisId;
        if (!analysisId || !courierAnalysisClient) return;
        try {
          await courierAnalysisClient.cancelPosting(analysisId);
        } catch (e) {
          alert(e.message || "تعذر إلغاء الموافقة");
        }
      },
      onReturnPostingApprove: async (spec) => {
        const analysisId = spec && spec.props && spec.props.analysisId;
        if (!analysisId || !courierAnalysisClient) return;
        try {
          avatar.setMode("executing");
          avatar.setTask("أرجع الطلبات وأعيد المخزون");
          avatar.speak("جاري تنفيذ الراجع وإعادة الأصناف للمخزون...");
          showWorkspaceNotice("جاري تنفيذ كشف الراجع، انتظر قليلاً...", "info");
          const result = await courierAnalysisClient.approveReturn(analysisId);
          const count = Number(result?.posting?.safe_rows || 0);
          avatar.setMode("success");
          avatar.setTask("اكتمل تنفيذ كشف الراجع");
          avatar.speak(`تم ترجيع ${count} طلب وإعادة أصنافها للمخزون بنجاح.`);
          avatar.playTone("success");
          showWorkspaceNotice(`تم ترجيع ${count} طلب وإعادة المخزون بنجاح.`, "success", 6500);
          await refreshSession();
        } catch (e) {
          avatar.setMode("error");
          avatar.speak("تعذّر تنفيذ كشف الراجع. لم يُعتمد تغيير غير مكتمل.");
          avatar.playTone("error");
          showWorkspaceNotice(e.message || "فشل تنفيذ كشف الراجع", "error", 7500);
          alert(e.message || "فشل تنفيذ كشف الراجع");
          throw e;
        }
      },
      onReturnPostingReject: async (spec) => {
        const analysisId = spec && spec.props && spec.props.analysisId;
        if (!analysisId || !courierAnalysisClient) return;
        try {
          await courierAnalysisClient.cancelReturn(analysisId);
          avatar.setMode("success");
          avatar.speak("تم إلغاء تنفيذ كشف الراجع دون تغيير الطلبات أو المخزون.");
        } catch (e) {
          alert(e.message || "تعذّر إلغاء موافقة الراجع");
        }
      },
      onPurchaseDecision: async (spec, rowIndex, decision, productId) => {
        const analysisId = spec?.props?.analysisId;
        if (!analysisId || !purchaseAnalysisClient) return;
        try {
          avatar.setMode("matching");
          const result = await purchaseAnalysisClient.decide(analysisId, rowIndex, decision, productId);
          avatar.setMode("success");
          const decisionMessage = decision === "create_new"
            ? "تم اعتماد الصنف كمنتج جديد. سيُنشأ عند الاعتماد النهائي."
            : decision === "use_existing"
              ? "تم ربط الصنف بالمنتج الموجود."
              : "تم استبعاد الصنف من الفاتورة.";
          avatar.speak(decisionMessage);
          showWorkspaceNotice(decisionMessage, "success", 5200);
          return result;
        } catch (e) {
          avatar.setMode("warning");
          showWorkspaceNotice(e.message || "تعذّر تحديث قرار الصنف", "error", 6500);
          throw e;
        }
      },
      onPurchaseValues: async (spec, rowIndex, quantity, unitPrice, productName, unitPriceUsd) => {
        const analysisId = spec?.props?.analysisId;
        if (!analysisId || !purchaseAnalysisClient) return;
        try {
          const result = await purchaseAnalysisClient.updateValues(
            analysisId,
            rowIndex,
            quantity,
            unitPrice,
            productName,
            unitPriceUsd
          );
          avatar.setMode("success");
          const priceMessage = unitPriceUsd
            ? `تم تحويل ${unitPriceUsd} دولار على سعر 1350 وحفظه بالدينار.`
            : "تم حفظ الكمية والسعر وإعادة حساب المجاميع.";
          avatar.speak(priceMessage);
          showWorkspaceNotice(priceMessage, "success", 5200);
          return result;
        } catch (e) {
          avatar.setMode("warning");
          showWorkspaceNotice(e.message || "تعذّر حفظ الكمية والسعر", "error", 6500);
          throw e;
        }
      },
      onPurchaseSupplier: async (spec, values) => {
        const analysisId = spec?.props?.analysisId;
        if (!analysisId || !purchaseAnalysisClient) return;
        try {
          const result = await purchaseAnalysisClient.setSupplier(analysisId, values || {});
          avatar.setMode("success");
          avatar.speak("تم تصحيح المورد وإعادة تجهيز ملخص الفاتورة.");
          showWorkspaceNotice("تم حفظ المورد الصحيح.", "success", 4800);
          return result;
        } catch (e) {
          avatar.setMode("warning");
          showWorkspaceNotice(e.message || "تعذّر حفظ المورد", "error", 6500);
          throw e;
        }
      },
      onPurchaseCatalogSearch: async (query) => {
        if (!purchaseAnalysisClient) return { products: [], suppliers: [] };
        return purchaseAnalysisClient.catalog(query || "", 160);
      },
      onPurchasePrepare: async (spec) => {
        const analysisId = spec?.props?.analysisId;
        if (!analysisId || !purchaseAnalysisClient) return;
        try {
          avatar.setMode("matching");
          avatar.speak("أجهز المراجعة النهائية قبل إدخال المخزون.");
          const result = await purchaseAnalysisClient.prepare(analysisId);
          ensurePurchaseApprovalWindow(analysisId, result?.preview || {});
          avatar.setMode("waiting_approval");
          avatar.speak("راجع الملخص ثم وافق على تسجيل الشراء وإضافة المخزون.");
          return result;
        } catch (e) {
          avatar.setMode("warning");
          showWorkspaceNotice(e.message || "تعذّر تجهيز موافقة فاتورة الشراء", "error", 7000);
          throw e;
        }
      },
      onPurchasePostingApprove: async (spec) => {
        const analysisId = spec?.props?.analysisId;
        if (!analysisId || !purchaseAnalysisClient) return;
        try {
          avatar.setMode("executing");
          avatar.setTask("أسجل الشراء وأضيف المخزون");
          avatar.speak("جاري إنشاء المنتجات الجديدة وتسجيل الشراء وإضافة الكميات...");
          const result = await purchaseAnalysisClient.approve(analysisId);
          avatar.setMode("success");
          avatar.setTask("اكتملت فاتورة الشراء");
          avatar.speak("تم تسجيل فاتورة الشراء وإضافة الكميات للمخزون بنجاح.");
          avatar.playTone("success");
          showWorkspaceNotice(`تم تسجيل عملية الشراء #${result?.posting?.purchase_id || ""} بنجاح.`, "success", 7000);
          await refreshSession();
          return result;
        } catch (e) {
          avatar.setMode("error");
          avatar.speak("تعذّر تنفيذ الفاتورة. لم تُعتمد تغييرات ناقصة.");
          avatar.playTone("error");
          showWorkspaceNotice(e.message || "فشل تنفيذ فاتورة الشراء", "error", 7500);
          throw e;
        }
      },
      onPurchasePostingReject: async (spec) => {
        const analysisId = spec?.props?.analysisId;
        if (!analysisId || !purchaseAnalysisClient) return;
        await purchaseAnalysisClient.cancel(analysisId);
        avatar.setMode("success");
        avatar.speak("تم إلغاء التنفيذ دون تغيير المنتجات أو المخزون.");
      },
      onInventoryAnalyze: async (spec, filters) => {
        if (!inventoryForensicsClient) return null;
        try {
          avatar.setMode("matching");
          avatar.setProgress(35);
          avatar.setTask("أعيد بناء حركات المنتج قطعةً قطعة");
          avatar.speak("أراجع البيع والشراء والراجع والتحويلات والتعديلات وأربطها بالموظف والطلب.");
          showWorkspaceNotice("جاري التحقيق في حركات المنتج ومطابقة أرصدة الفروع...", "info");
          const result = await inventoryForensicsClient.analyze(filters);
          avatar.setMode((result?.analysis?.summary?.health === "critical") ? "warning" : "success");
          avatar.setProgress(100);
          return result;
        } catch (e) {
          avatar.setMode("error");
          avatar.setTask("تعذر إكمال التحقيق");
          avatar.speak("تعذر إكمال تدقيق المخزون ولم يتم تغيير أي كمية.");
          showWorkspaceNotice(e.message || "تعذر إكمال تدقيق المخزون", "error", 7500);
          throw e;
        }
      },
      onSelectWorkflow: async (type) => {
        try {
          await startWorkflowType(type);
        } catch (e) {
          if (e.message === "SESSION_NOT_FOUND") {
            await recoverMissingSession();
          } else {
            avatar.setMode("error");
            avatar.speak(e.message || "تعذّر تشغيل نوع العمل المختار.");
            showWorkspaceNotice(e.message || "تعذّر تشغيل نوع العمل المختار.", "error", 7000);
          }
        }
      },
    });

    uploadManager = new WorkspaceUploadManager({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onStart: () => {
        setUploadBusy(true);
        setMobileTyping(true);
        patchDocumentViewerLoading(true);
        avatar.setMode("reading_document");
        avatar.setTask("أرفع الملفات وأجهزها للقراءة");
        avatar.speak("جاري رفع الملفات أو الصور وتجهيزها للتحليل…");
      },
      onSuccess: (data) => {
        setUploadBusy(false);
        setMobileTyping(false);
        if (data.session) onSessionUpdate(data.session);
        updateIntelligenceButton();
        appendMobileMessage("assistant", "تم رفع الملف بنجاح. اختر طريقة العمل، أو دع LEON يتعرّف على نوع المستند تلقائياً.", {
          title: "اكتمل رفع المستند",
        });
        avatar.setMode("success");
        avatar.setTask("تم رفع الملفات");
        avatar.speak("تم رفع الملفات بنجاح. أقدر الآن أقرأها أو أحلل الكشف.");
        avatar.playTone("success");
        if (isMobileChatMode()) openMobileSheet(mobileWorkflowSheet);
      },
      onError: (err) => {
        setUploadBusy(false);
        setMobileTyping(false);
        appendMobileMessage("assistant", err.message || "تعذّر رفع الملف. حاول مرة ثانية.", {
          title: "لم يكتمل الرفع",
        });
        showDocumentViewerError(err.message || "فشل رفع المستند");
        avatar.setMode("error");
        avatar.setTask("فشل رفع الملفات");
        avatar.speak(err.message || "تعذّر رفع الملفات. حاول مرة ثانية.");
        avatar.playTone("error");
      },
    });

    async function uploadAssistantWorkbook(file) {
      const form = new FormData();
      form.append("file", file);
      if (assistantChatSessionId) form.append("session_id", String(assistantChatSessionId));
      const response = await fetch("/assistant/api/files/upload", {
        method: "POST",
        body: form,
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.success) {
        throw new Error(data.error || "تعذّر رفع ملف Excel إلى LEON");
      }
      if (data.file?.id) mobileAssistantUploadIds.push(data.file.id);
      return data.file;
    }

    async function handleMobileFiles(files) {
      const selected = [...(files || [])].filter(Boolean);
      if (!selected.length) return;
      const workbooks = selected.filter((file) => /\.(xlsx|xlsm)$/i.test(file.name || ""));
      const documents = selected.filter((file) => !/\.(xlsx|xlsm)$/i.test(file.name || ""));
      if (workbooks.length) {
        setMobileTyping(true);
        try {
          const uploaded = [];
          for (const file of workbooks) uploaded.push(await uploadAssistantWorkbook(file));
          appendMobileMessage(
            "assistant",
            `تمت قراءة ${uploaded.length} ملف Excel. اكتب ما تريد تحليله أو قل: حلّل فروقات الجرد.`,
            { title: "ملفات Excel جاهزة" }
          );
        } catch (error) {
          appendMobileMessage("assistant", error.message || "تعذّر رفع ملف Excel.", { title: "لم يكتمل الرفع" });
        } finally {
          setMobileTyping(false);
        }
      }
      if (documents.length) {
        await uploadManager.uploadCurrentSessionFiles(documents);
      }
    }

    function openMobileFilePicker() {
      if (!mobileFileInput) {
        mobileFileInput = document.createElement("input");
        mobileFileInput.type = "file";
        mobileFileInput.hidden = true;
        mobileFileInput.multiple = true;
        mobileFileInput.accept = ".pdf,.png,.jpg,.jpeg,.webp,.xlsx,.xlsm,application/pdf,image/*,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        mobileFileInput.addEventListener("change", () => {
          const files = mobileFileInput.files ? [...mobileFileInput.files] : [];
          handleMobileFiles(files).catch((error) => {
            setMobileTyping(false);
            appendMobileMessage("assistant", error.message || "تعذّر رفع الملفات.", { title: "لم يكتمل الرفع" });
          });
        });
        document.body.appendChild(mobileFileInput);
      }
      mobileFileInput.value = "";
      mobileFileInput.click();
    }

    function currentWorkspaceAnalysisWindow(workflowType) {
      const expectedType = workflowType === "purchase_invoice"
        ? "purchase_invoice_analysis"
        : "courier_settlement_analysis";
      const sessionWindows = Array.isArray(store.getSession()?.windows) ? store.getSession().windows : [];
      return [...sessionWindows, ...(lastWorkspaceWindows || [])]
        .reverse()
        .find((item) => item.type === expectedType) || null;
    }

    async function appendMobileWorkspaceResult(workflowType) {
      const activeType = workflowType || store.getSession()?.workflow_type;
      const spec = currentWorkspaceAnalysisWindow(activeType);
      const metadata = store.getSession()?.metadata || {};

      if (activeType === "purchase_invoice") {
        const analysis = spec?.props?.analysis || metadata.purchase_invoice_analysis || {};
        return appendMobilePurchaseResult(analysis);
      }

      if (!["courier_settlement", "return_statement"].includes(activeType) || !spec) return false;
      const props = spec.props || {};
      const isReturn = activeType === "return_statement" || props.analysisMode === "return";
      const analysisId = props.analysisId;
      const totalRows = Number(props.totalRows || 0);
      const matchedRows = Number(props.matchedRows || 0);
      const reviewRows = Number(props.reviewRows || 0);
      const unmatchedRows = Number(props.unmatchedRows || 0);
      const widgets = [];
      if (isReturn) {
        const preview = props.returnPreview || {};
        widgets.push({
          type: "metric_grid",
          title: "ملخص كشف الراجع",
          items: [
            { label: "إجمالي الصفوف", value: totalRows, kind: "number", tone: "purple" },
            { label: "جاهزة للترجيع", value: preview.safe_rows ?? matchedRows, kind: "number", tone: "green" },
            { label: "قطع ستعود للمخزون", value: preview.total_units || 0, kind: "number", tone: "blue" },
            { label: "تحتاج مراجعة", value: reviewRows, kind: "number", tone: "amber" },
            { label: "غير موجودة", value: unmatchedRows, kind: "number", tone: "red" },
          ],
        });
      } else {
        widgets.push({
          type: "metric_grid",
          title: "ملخص كشف التسديد",
          items: [
            { label: "إجمالي الطلبات", value: totalRows, kind: "number", tone: "purple" },
            { label: "طلبات مطابقة", value: matchedRows, kind: "number", tone: "green" },
            { label: "تحتاج مراجعة", value: reviewRows, kind: "number", tone: "amber" },
            { label: "غير موجودة", value: unmatchedRows, kind: "number", tone: "red" },
            { label: "المبلغ المحصّل", value: props.totalCollected || 0, kind: "money", tone: "green" },
            { label: "أجور التوصيل", value: props.totalFees || 0, kind: "money", tone: "blue" },
          ],
        });
      }
      if (analysisId && courierAnalysisClient) {
        try {
          const rowData = await courierAnalysisClient.getRows(analysisId, { page_size: 100 });
          const rows = Array.isArray(rowData.rows) ? rowData.rows : [];
          if (rows.length) {
            widgets.push({
              type: "table",
              title: isReturn ? "طلبات كشف الراجع" : "طلبات كشف التسديد",
              columns: [
                { key: "normalized_order_number", label: "الطلب", kind: "text" },
                { key: "customer_name", label: "الزبون", kind: "text" },
                { key: "match_label", label: "الحالة", kind: "text" },
                { key: "collected_amount", label: "المبلغ", kind: "money" },
                { key: "delivery_fee", label: "التوصيل", kind: "money" },
              ],
              rows: rows.slice(0, 40).map((row) => ({
                ...row,
                match_label: ({ matched: "مطابق", review: "مراجعة", unmatched: "غير مطابق", duplicate: "مكرر" })[row.match_status] || row.match_status || "—",
              })),
            });
          }
        } catch (_) {
          widgets.push({ type: "notice", title: "تفاصيل الصفوف", message: "ظهر الملخص، لكن تعذّر تحميل تفاصيل الصفوف حالياً." });
        }
      }
      widgets.push({
        type: "notice",
        title: "التحليل آمن",
        message: isReturn
          ? "لم يتم تغيير حالة الطلبات أو إعادة المخزون قبل موافقتك."
          : "النتيجة قراءة ومطابقة فقط، ولم يتم تسديد أو ترحيل أي طلب قبل موافقتك.",
      });
      appendMobilePresentation({
        title: isReturn ? "نتيجة تحليل كشف الراجع" : "نتيجة تحليل كشف التسديد",
        widgets,
        suggestions: ["اعرض الطلبات غير المطابقة", "ما المشاكل التي تحتاج مراجعة؟"],
      });
      return true;
    }

    async function runMobileWorkflow(type) {
      const selected = String(type || "");
      closeMobileSheets();
      setMobileTyping(true);
      const labels = {
        auto: "التعرّف التلقائي",
        purchase_invoice: "مستند شراء",
        courier_settlement: "كشف تسديد نقل",
        return_statement: "كشف راجع",
      };
      appendMobileMessage("user", `طريقة العمل: ${labels[selected] || selected}`);
      try {
        let result;
        let resolvedType = selected;
        if (selected === "auto") {
          avatar.setMode("reading_document");
          avatar.setTask("أتعرف على نوع المستند");
          const intelligence = await documentIntelligenceClient.runForActiveSessionDocument();
          const kind = intelligence?.result?.document_kind
            || intelligence?.document_kind
            || (store.getSession()?.metadata?.last_intelligence || {}).document_kind;
          const confidence = intelligence?.result?.confidence
            ?? intelligence?.confidence
            ?? (store.getSession()?.metadata?.last_intelligence || {}).confidence;
          const kindLabels = {
            purchase_invoice: "مستند شراء",
            courier_settlement: "كشف تسديد نقل",
            return_statement: "كشف راجع",
          };
          if (!kind || kind === "unknown_document") {
            appendMobileMessage("assistant", "لم أحصل على ثقة كافية لتحديد النوع. اختر شراء أو تسديد أو راجع يدوياً.", {
              title: "أحتاج اختيارك",
            });
            openMobileSheet(mobileWorkflowSheet);
            return;
          }
          resolvedType = kind;
          appendMobileMessage(
            "assistant",
            `تعرّفت على المستند: ${kindLabels[kind] || kind}${confidence != null ? ` — الثقة ${Math.round(Number(confidence) * 100)}%` : ""}. سأبدأ المسار المناسب.`,
            { title: "تم تحديد نوع المستند" }
          );
          result = await startWorkflowType(kind);
        } else {
          result = await startWorkflowType(selected);
        }
        const resultShown = await appendMobileWorkspaceResult(resolvedType);
        if (result?.waiting === "approval") {
          appendMobileMessage("assistant", "اكتمل التحليل ووصل إلى خطوة تحتاج موافقتك قبل أي تغيير داخل النظام.", {
            title: "بانتظار الموافقة",
          });
        } else if (result?.waiting === "user_input") {
          appendMobileMessage("assistant", "أحتاج منك معلومة إضافية لإكمال هذا المسار.", { title: "بانتظارك" });
        } else {
          appendMobileMessage("assistant", resultShown
            ? "عرضت لك الملخص والجدول داخل المحادثة."
            : `اكتمل مسار ${labels[resolvedType] || "المستند"}، لكن لم تصل بيانات قابلة للعرض. أعد المحاولة أو ارفع صورة أوضح.`, {
            title: "اكتمل التحليل",
          });
        }
      } catch (error) {
        appendMobileMessage("assistant", error.message || "تعذّر تشغيل طريقة العمل.", { title: "لم يكتمل التحليل" });
      } finally {
        setMobileTyping(false);
      }
    }

    documentIntelligenceClient = new DocumentIntelligenceClient({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onSessionUpdate,
      onStart: () => {
        setIntelligenceBusy(true);
        avatar.setMode("reading_document");
        avatar.setTask("أحسن الصورة وأقرأ المستند");
        avatar.speak("بدأت تحسين الصورة وقراءة محتوى المستند.");
        windowManager.applyEvent({
          type: "document.scan.updated",
          payload: { active: true, progress: 3, stage: "بدء الماسح الضوئي" },
        });
      },
      onComplete: () => {
        setIntelligenceBusy(false);
        updateIntelligenceButton();
        completeDocumentScan("اكتمل فحص المستند");
        avatar.setMode("success");
        avatar.setTask("اكتملت قراءة المستند");
      },
      onError: (err) => {
        setIntelligenceBusy(false);
        updateIntelligenceButton();
        windowManager.applyEvent({
          type: "document.scan.updated",
          payload: { active: false, progress: 100, stage: "تعذّر فحص المستند", error: true },
        });
        avatar.setMode("error");
        avatar.setTask("تعذرت قراءة المستند");
        avatar.speak(err.message || "فشل فهم المستند");
        alert(err.message || "فشل فهم المستند");
      },
    });

    courierAnalysisClient = new CourierAnalysisClient({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onSessionUpdate,
      onStart: () => {
        setCourierBusy(true);
        avatar.setMode("reading_document");
        avatar.setTask("أقرأ الكشف وأطابق الطلبات");
        avatar.speak("أقرأ صفوف الكشف وأطابقها مع الطلبات والحسابات.");
        windowManager.applyEvent({
          type: "document.scan.updated",
          payload: { active: true, progress: 3, stage: "بدء فحص كشف التوصيل" },
        });
      },
      onComplete: () => {
        setCourierBusy(false);
        updateCourierButton();
        completeDocumentScan("اكتمل فحص ومطابقة الكشف");
        avatar.setMode("success");
        avatar.setTask("اكتملت مطابقة الكشف");
      },
      onError: (err) => {
        setCourierBusy(false);
        updateCourierButton();
        windowManager.applyEvent({
          type: "document.scan.updated",
          payload: { active: false, progress: 100, stage: "تعذّر فحص كشف التوصيل", error: true },
        });
        avatar.setMode("error");
        avatar.setTask("تعذر تحليل الكشف");
        avatar.speak(err.message || "فشل تحليل كشف التسديد");
        alert(err.message || "فشل تحليل كشف التسديد");
      },
    });

    windowManager.setCourierHandlers({
      loadRows: async (analysisId, filter, bodyEl) => {
        const status = filter === "all" ? undefined : filter;
        const data = await courierAnalysisClient.getRows(analysisId, { status, page_size: 100 });
        CourierRowsWindow.showRows(
          bodyEl.closest(".ws-courier-rows") ? bodyEl.parentElement : bodyEl,
          data.rows,
          {
            filter,
            total: data.total,
            counts: data.counts,
            paymentMethods: data.payment_methods || [],
          }
        );
      },
      onChangeOrder: async (spec, row, orderNumber) => {
        const aid = spec && spec.props && spec.props.analysisId;
        if (!aid || !row || !row.id) throw new Error("تعذر تحديد صف الكشف");
        return courierAnalysisClient.correctRowOrder(aid, row.id, orderNumber);
      },
      onApproveCandidate: async (spec, row) => {
        const aid = spec && spec.props && spec.props.analysisId;
        if (!aid || !row || !row.id) throw new Error("تعذّر تحديد صف الكشف");
        return courierAnalysisClient.approveRowCandidate(aid, row.id);
      },
      onPaymentMethodChange: async (spec, row, treasuryAccountId) => {
        const aid = spec && spec.props && spec.props.analysisId;
        if (!aid || !row || !row.id) throw new Error("تعذّر تحديد صف الكشف");
        const result = await courierAnalysisClient.setRowPaymentMethod(
          aid,
          row.id,
          treasuryAccountId
        );
        invalidateCourierApprovalWindow(aid);
        return result;
      },
      onConfirmReplacement: async (spec, row) => {
        const aid = spec && spec.props && spec.props.analysisId;
        if (!aid || !row || !row.id) throw new Error("تعذّر تحديد صف الكشف");
        const result = await courierAnalysisClient.confirmRowReplacement(aid, row.id);
        invalidateCourierApprovalWindow(aid);
        return result;
      },
      onDeleteRow: async (spec, row) => {
        const aid = spec && spec.props && spec.props.analysisId;
        if (!aid || !row || !row.id) throw new Error("تعذّر تحديد صف الكشف");
        return courierAnalysisClient.deleteRow(aid, row.id);
      },
      loadIssues: async (analysisId, bodyEl) => {
        const data = await courierAnalysisClient.getIssues(analysisId);
        CourierIssuesWindow.showIssues(bodyEl, data.issues);
      },
      loadReportIssues: async (analysisId, bodyEl) => {
        try {
          const data = await courierAnalysisClient.getIssues(analysisId);
          CourierSettlementAnalysisWindow.patchFromEvent(bodyEl, { issues: data.issues || [] });
        } catch (e) {
          /* keep placeholder */
        }
      },
      onExport: () => printCourierReport(),
      onPrintCourier: (spec) => {
        const analysisId = spec && spec.props && spec.props.analysisId;
        if (!analysisId) {
          alert("تعذّر تحديد كشف التحليل للطباعة.");
          return;
        }
        window.open(
          `/workspace/courier-analysis/${encodeURIComponent(analysisId)}/print`,
          "_blank",
          "noopener"
        );
      },
      onShowWindow: (type) => showWorkspaceWindowType(type),
      onReanalyze: async () => {
        if (!courierAnalysisClient || courierAnalysisClient.isBusy()) return;
        try {
          await courierAnalysisClient.runForSession(
            null,
            null,
            { forceDocumentAnalysis: true }
          );
        } catch (e) {
          /* onError already presents the server message */
        }
      },
      onSettle: async (spec) => {
        const aid = spec && spec.props && spec.props.analysisId;
        if (!aid) return;
        const isReturn = (spec.props || {}).analysisMode === "return";
        try {
          avatar.setMode("matching");
          avatar.speak(isReturn ? "جاري تجهيز معاينة تنفيذ الراجع..." : "جاري تجهيز معاينة التنفيذ...");
          avatar.playTone("info");
          showWorkspaceNotice("جاري تجهيز موافقة التنفيذ...", "info");
          const prepared = isReturn
            ? await courierAnalysisClient.prepareReturn(aid)
            : await courierAnalysisClient.preparePosting(aid);
          if (isReturn) {
            ensureReturnApprovalWindow(aid, prepared?.preview || {});
          } else {
            ensureCourierApprovalWindow(aid, prepared?.preview || {});
          }
          avatar.setMode("waiting_approval");
          avatar.speak(
            isReturn
              ? "راجِع عدد الطلبات والقطع ثم وافق على تنفيذ الراجع."
              : "راجِع المعاينة ثم وافق على التنفيذ الآمن."
          );
          showWorkspaceNotice(
            isReturn
              ? "تم تجهيز الموافقة. اضغط «تنفيذ الراجع» لإعادة المخزون."
              : "تم تجهيز الموافقة. اضغط «تنفيذ آمن» لإكمال العملية.",
            "info"
          );
        } catch (e) {
          avatar.setMode("warning");
          avatar.speak("تعذّر تجهيز التنفيذ. راجع الرسالة الظاهرة.");
          avatar.playTone("error");
          showWorkspaceNotice(e.message || "تعذر تجهيز موافقة التنفيذ", "error", 7000);
          alert(e.message || "تعذر تجهيز موافقة التنفيذ");
          throw e;
        }
      },
      onFilter: async (spec, filter) => {
        const aid = (spec.props || {}).analysisId;
        if (!aid) return;
        const data = await courierAnalysisClient.getRows(aid, {
          status: filter === "all" ? undefined : filter,
          page_size: 100,
        });
        const winEl = [...windowManager.windows.values()].find((el) => {
          const s = JSON.parse(el.dataset.spec || "{}");
          return s.type === "courier_rows" && (s.props || {}).analysisId === aid;
        });
        if (winEl) {
          CourierRowsWindow.showRows(winEl.querySelector(".ws-window-body"), data.rows, {
            filter,
            total: data.total,
            counts: data.counts,
          });
        }
      },
    });

    store.subscribe(renderFromSession);

    if (btnUpload) btnUpload.addEventListener("click", () => uploadManager.openPicker());
    const chatAttach = document.getElementById("ws-chat-attach");
    if (chatAttach) {
      chatAttach.addEventListener("click", () => {
        if (isMobileChatMode()) openMobileFilePicker();
        else uploadManager.openPicker();
      });
    }
    document.querySelectorAll("[data-mobile-prompt]").forEach((button) => {
      button.addEventListener("click", () => {
        sendMobilePrompt(button.dataset.mobilePrompt || "");
      });
    });
    document.querySelectorAll("[data-mobile-upload]").forEach((button) => {
      button.addEventListener("click", openMobileFilePicker);
    });
    const mobileWorkflowButton = document.getElementById("ws-mobile-workflow-button");
    if (mobileWorkflowButton) {
      mobileWorkflowButton.addEventListener("click", () => openMobileSheet(mobileWorkflowSheet));
    }
    const mobileMemoryButton = document.getElementById("ws-mobile-memory-button");
    if (mobileMemoryButton) {
      mobileMemoryButton.addEventListener("click", () => {
        openMobileSheet(mobileMemorySheet);
        loadMobileMemory();
      });
    }
    mobileSheetBackdrop?.addEventListener("click", closeMobileSheets);
    document.querySelectorAll("[data-mobile-sheet-close]").forEach((button) => {
      button.addEventListener("click", closeMobileSheets);
    });
    document.querySelectorAll("[data-mobile-workflow]").forEach((button) => {
      button.addEventListener("click", () => runMobileWorkflow(button.dataset.mobileWorkflow));
    });
    const mobileNewSession = document.getElementById("ws-mobile-new-session");
    if (mobileNewSession) {
      mobileNewSession.addEventListener("click", async () => {
        closeMobileSheets();
        assistantChatSessionId = null;
        mobileAssistantUploadIds = [];
        saveMobileChatSession(null);
        resetMobileConversation();
        appendMobileMessage("assistant", "بدأت لك محادثة جديدة. ما الذي تريد مراجعته؟");
        btnNew?.click();
      });
    }
    if (commandSelect) commandSelect.addEventListener("change", syncCommandControls);
    if (commandRun) commandRun.addEventListener("click", runSelectedCommand);
    window.addEventListener("ws:leon-mode-changed", (event) => {
      updateFlowState(event.detail?.mode);
    });
    window.addEventListener("ws:upload-request", () => uploadManager.openPicker());
    window.addEventListener("ws:upload-files", (event) => {
      const files = event.detail && event.detail.files ? event.detail.files : [];
      uploadManager.uploadCurrentSessionFiles(files);
    });
    window.addEventListener("ws:hide-window", (event) => {
      const id = event.detail && event.detail.windowId;
      if (!id) return;
      openAuxWindowIds.delete(id);
      renderWorkspaceWindows(lastWorkspaceWindows);
    });
    window.addEventListener("ws:show-issues-details", () => {
      const win = [...windowManager.windows.entries()].find(([, el]) => {
        const s = JSON.parse(el.dataset.spec || "{}");
        return s.type === "courier_issues" || s.type === "courier_settlement_analysis";
      });
      if (win) windowManager.focusWindow(win[0]);
    });

    if (btnIntelligence) {
      btnIntelligence.addEventListener("click", async () => {
        try {
          showWorkspaceNotice("بدأ فهم المستند فعلياً...", "info");
          await documentIntelligenceClient.runForActiveSessionDocument();
          showWorkspaceNotice("اكتمل فهم المستند.", "success");
        } catch (e) {
          /* onError */
        }
      });
    }

    if (btnCourierAnalysis) {
      btnCourierAnalysis.addEventListener("click", async () => {
        try {
          await courierAnalysisClient.runForSession();
        } catch (e) {
          /* onError */
        }
      });
    }

    if (btnWorkflow) {
      btnWorkflow.addEventListener("click", async () => {
        try {
          btnWorkflow.disabled = true;
          await runRecommendedWorkflow();
        } catch (e) {
          if (e.message === "SESSION_NOT_FOUND") {
            await recoverMissingSession();
          } else {
            avatar.setMode("error");
            avatar.speak(e.message || "تعذّر تشغيل سير العمل.");
            showWorkspaceNotice(e.message || "تعذّر تشغيل سير العمل.", "error", 7000);
          }
        } finally {
          btnWorkflow.disabled = false;
        }
      });
    }

    if (btnSelectWorkflow) {
      btnSelectWorkflow.addEventListener("click", () => {
        ensureWorkflowSelectorWindow();
        avatar.setMode("waiting_user");
        avatar.speak("اختر نوع العمل من النافذة الظاهرة.");
        showWorkspaceNotice("اختر نوع العمل من النافذة الظاهرة.", "info");
      });
    }

    if (btnNextStep && IS_DEV) {
      btnNextStep.hidden = false;
      btnNextStep.addEventListener("click", async () => {
        try {
          await workflowClient.runNextStep();
        } catch (e) {
          alert(e.message);
        }
      });
    }

    if (btnNew) {
      btnNew.addEventListener("click", async () => {
        try {
          btnNew.disabled = true;
          await createSession();
        } catch (e) {
          alert(e.message);
        } finally {
          btnNew.disabled = false;
        }
      });
    }

    const btnFocus = document.getElementById("btn-focus");
    if (btnFocus) {
      btnFocus.addEventListener("click", () => {
        document.getElementById("workspace-root").classList.toggle("ws-focus");
      });
    }

    const btnFullscreen = document.getElementById("btn-fullscreen");
    if (btnFullscreen) {
      btnFullscreen.addEventListener("click", () => {
        if (document.fullscreenElement) {
          document.exitFullscreen();
        } else {
          document.documentElement.requestFullscreen?.();
        }
      });
    }

    const chatInput = document.getElementById("ws-chat-input");
    const chatSend = document.getElementById("ws-chat-send");
    const chatbar = document.querySelector(".ws-chatbar");

    function isMobileResultRequest(text) {
      const normalized = String(text || "").trim().toLowerCase();
      return isMobileChatMode() && (
        /وين\s*(ال)?نتيج/.test(normalized)
        || /(اعرض|اظهر|أظهر|طلع)\s*(لي\s*)?(ال)?(نتيج|تحليل)/.test(normalized)
        || /(النتيج|التحليل)\s*(وين|ماكو|موجود)/.test(normalized)
      );
    }

    async function sendChat() {
      const text = (chatInput.value || "").trim();
      if (!text || chatBusy) return;
      const pendingUploadIds = [...mobileAssistantUploadIds];
      const orderCommand = parseOrderDetailsCommand(text);
      appendMobileMessage("user", text);

      chatBusy = true;
      chatInput.value = "";
      chatInput.disabled = true;
      chatSend.disabled = true;
      chatbar?.classList.add("is-busy");
      setMobileTyping(true);

      try {
        if (isMobileResultRequest(text)) {
          const shown = await appendMobileWorkspaceResult(store.getSession()?.workflow_type);
          if (shown) {
            appendMobileMessage("assistant", "هذه آخر نتيجة تحليل، عرضتها لك داخل المحادثة.", { title: "النتيجة جاهزة" });
          } else {
            appendMobileMessage("assistant", "لا توجد نتيجة تحليل محفوظة في جلسة المستند الحالية. ارفع المستند ثم اختر طريقة العمل من الزر أعلى الشاشة.", { title: "لا توجد نتيجة بعد" });
          }
          return;
        }
        if (orderCommand.matched) {
          if (!orderCommand.orderId) {
            appendMobileMessage("assistant", "اكتب رقم الطلب المطلوب، مثلاً: اعرض تفاصيل الطلب 508.");
            avatar.setMode("waiting_user");
            avatar.setTask("بانتظار رقم الطلب");
            avatar.speak("اكتب رقم الطلب، مثلاً: طلع تفاصيل الطلب 508، وأنا أعرض كل تفاصيله وحركاته المالية.");
            avatar.playTone("info");
            showWorkspaceNotice("اكتب رقم الطلب المطلوب.", "info", 4200);
            return;
          }
          const opened = await openLeonOrderDetails(orderCommand.orderId);
          appendMobileMessage(
            "assistant",
            opened
              ? `راجعت الطلب رقم ${orderCommand.orderId} وجهّزت تفاصيله وحركاته المالية.`
              : `تعذّر فتح تفاصيل الطلب رقم ${orderCommand.orderId}. حاول مرة ثانية.`,
            { title: opened ? "تفاصيل الطلب جاهزة" : "تعذّر تحميل الطلب" }
          );
          return;
        }

        avatar.setMode("thinking");
        avatar.setTask("أفهم سؤالك وأراجع بيانات النظام");
        avatar.speak("لحظة، أفهم طلبك وأراجع بيانات النظام الفعلية…");
        const response = await fetch("/assistant/api/chat/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: "report",
            period: "last_30_days",
            message: text,
            session_id: assistantChatSessionId,
            upload_ids: pendingUploadIds,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.success === false) {
          throw new Error(data.message || data.error || "تعذّر الحصول على جواب من LEON");
        }

        assistantChatSessionId = data.session_id || assistantChatSessionId;
        saveMobileChatSession(assistantChatSessionId);
        if (pendingUploadIds.length) {
          const consumedIds = new Set(pendingUploadIds);
          mobileAssistantUploadIds = mobileAssistantUploadIds.filter((id) => !consumedIds.has(id));
        }
        const reply = String(data.reply || "اكتملت المراجعة، لكن لم يصل نص للجواب.");
        appendMobileMessage("assistant", reply, {
          title: data.action_plan ? "تحتاج موافقتك قبل التنفيذ" : "إجابة LEON",
        });
        appendMobilePresentation(data.presentation);
        const needsApproval = Boolean(data.action_plan);
        const employeePerformance = data.local_findings?.employee_performance;
        const openedEmployeeDashboard = openEmployeePerformanceWindow(employeePerformance);
        const employeeRows = Array.isArray(employeePerformance?.performance)
          ? employeePerformance.performance.length
          : 0;
        const spokenReply = openedEmployeeDashboard
          ? `جهزت لك نافذة أداء احترافية تضم ${employeeRows} موظف، مع الطلبات والمبيعات والتحصيل والمرتجعات ومؤشرات الأداء.`
          : reply;
        avatar.setMode(needsApproval ? "waiting_approval" : "success");
        avatar.setTask(
          needsApproval
            ? "جهزت خطة وتحتاج موافقتك"
            : (openedEmployeeDashboard ? "عرضت لوحة أداء الموظفين" : "اكتمل الجواب")
        );
        avatar.speak(spokenReply);
        avatar.playTone(needsApproval ? "info" : "success");
        showWorkspaceNotice(
          needsApproval
            ? "LEON جهز خطة آمنة وتحتاج موافقتك قبل التنفيذ."
            : (openedEmployeeDashboard ? "تم فتح لوحة أداء الموظفين." : "وصل جواب LEON."),
          needsApproval ? "info" : "success",
          openedEmployeeDashboard ? 4800 : 3600
        );
      } catch (error) {
        appendMobileMessage("assistant", error.message || "حدث خطأ أثناء الاتصال بـ LEON. حاول مرة ثانية.", {
          title: "تعذّر إكمال الطلب",
        });
        avatar.setMode("error");
        avatar.setTask("تعذر إكمال الجواب");
        avatar.speak(error.message || "حدث خطأ أثناء الاتصال بالمساعد.");
        avatar.playTone("error");
        showWorkspaceNotice(error.message || "تعذر الاتصال بـ LEON", "error", 6500);
      } finally {
        setMobileTyping(false);
        chatBusy = false;
        chatInput.disabled = false;
        chatSend.disabled = false;
        chatbar?.classList.remove("is-busy");
        chatInput.focus();
      }
    }
    if (chatSend) chatSend.addEventListener("click", sendChat);
    if (chatInput) {
      chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendChat();
      });
    }

    btnRun.addEventListener("click", async () => {
      const session = store.getSession();
      if (!session) return;
      try {
        btnRun.disabled = true;
        setStatus("running");
        await api(`/sessions/${session.id}/run-mock`, { method: "POST", body: "{}" });
      } catch (e) {
        alert(e.message);
        btnRun.disabled = false;
      }
    });

    btnCancel.addEventListener("click", async () => {
      const session = store.getSession();
      if (!session) return;
      try {
        await api(`/sessions/${session.id}/cancel`, { method: "POST", body: "{}" });
        await refreshSession();
      } catch (e) {
        alert(e.message);
      }
    });

    let _resizeTimer = null;
    window.addEventListener("resize", () => {
      if (windowManager) windowManager.relayout();
      clearTimeout(_resizeTimer);
      _resizeTimer = setTimeout(() => {
        if (avatar) avatar.moveTo(0.5, 0.52);
        syncFlowScene();
      }, 120);
    });

    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session");

    try {
      if (sessionId) {
        const data = await api(`/sessions/${sessionId}`);
        store.setSession(data.session);
        renderFromSession(data.session);
        const reportWin = (data.session.windows || []).find((w) => w.type === "live_report");
        const reportEmpty = !reportWin || !((reportWin.props || {}).lines || []).length;
        connectStream(sessionId, reportEmpty);
      } else {
        await createSession();
      }
    } catch (e) {
      console.warn("Session load failed, creating new", e);
      await createSession();
    }
    await restoreMobileConversation();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
