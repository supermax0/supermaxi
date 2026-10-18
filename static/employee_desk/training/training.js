(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const config = JSON.parse($("training-config").textContent);
  const storageKey = `finora:employee-academy:v1:${config.scope}`;
  const modules = [
    { id: "login", title: "تسجيل الدخول", subtitle: "اعرف بوابة مكتبك", kind: "جرّب على الصورة", quiz: { q: "إذا حسابك ما يفتح، شتسوي؟", answers: ["تطلب حساب زميلك حتى تكمل", "تراجع معرف الشركة وبياناتك وتتواصل ويّا الإدارة", "تكرر كلمات مرور عشوائية"], correct: 1, why: "استخدم حسابك وحدك. تأكد من الشركة وبيانات الدخول وصلاحية مكتب الموظف." } },
    { id: "messages", title: "افتح أول رسالة", subtitle: "القائمة والمحادثة", kind: "جرّب على الصورة", quiz: { q: "قبل ما تجاوب رسالة، شنو تراجع؟", answers: ["اسم الزبون وسياق المحادثة والسؤال المطلوب", "آخر كلمة بالرسالة فقط", "تبعث نفس الجواب لكل الزبائن"], correct: 0, why: "قراءة المحادثة تمنع الرد على زبون أو طلب مختلف." } },
    { id: "reply", title: "اكتب وارسل الرد", subtitle: "الكتابة والردود السريعة", kind: "جرّب على الصورة", quiz: { q: "شنو لازم تعرف عن الردود السريعة؟", answers: ["كلها مسودات تحتاج إرسال ثاني", "تغيّر سعر المنتج تلقائياً", "الضغط على الرد يرسله مباشرة، فتتأكد منه قبل الضغط"], correct: 2, why: "بالواجهة الحالية الرد السريع ينرسل مباشرة. راجع محتواه وملاءمته قبل الضغط." } },
    { id: "booking", title: "سجّل حجز مضبوط", subtitle: "الزبون، المنتج، والتأكيد", kind: "جرّب على الصورة", quiz: { q: "متى تضغط «احجز الطلب»؟", answers: ["بمجرد وصول أول استفسار", "بعد موافقة الزبون ومراجعة بياناته والمنتج والكمية واللون والسعر", "قبل اختيار الزبون"], correct: 1, why: "راجع التفاصيل والسعر النهائي ويّا الزبون، واحجز مرة وحدة ثم انتظر نتيجة النظام." } },
    { id: "products", title: "اعرف منتجاتك", subtitle: "سعر ومواصفات من النظام", kind: "اختبار معرفة" },
    { id: "style", title: "شلون ترد بثقة؟", subtitle: "مواقف وردود عملية", kind: "٣ مواقف تفاعلية" },
    { id: "practice", title: "جرّب أول حجز", subtitle: "تطبيق يجمع اللي تعلمته", kind: "تمرين آمن" },
  ];
  const scenarios = [
    { q: "الزبون: هذا المنتج بيه ضمان سنة؟", answers: ["إي أكيد، سنة كاملة.", "خل أتأكدلك من سياسة الضمان المعتمدة وأرجعلك بالمعلومة الصحيحة.", "كل المنتجات نفس الضمان."], correct: 1, why: "إذا الضمان مو مسجل أو مو مؤكد، راجعه ويّا المسؤول قبل الوعد." },
    { q: "الزبون: أريده يوصل اليوم، تكدرون؟", answers: ["أكيد خلال ساعة.", "احجز وبعدين نشوف.", "ممكن محافظتك ومنطقتك؟ أتأكدلك من موعد التوصيل قبل ما نثبت الطلب."], correct: 2, why: "اسأل عن الموقع وتأكد من الموعد وأجور التوصيل قبل تثبيت الاتفاق." },
    { q: "الزبون: السعر غالي، سويلي خصم!", answers: ["أتفهمك، أراجع إذا متوفر عرض أو خصم معتمد وأوضحلك الخيارات.", "أخصملك من عندي، بس احجز.", "إذا مو عاجبك لا تشتري."], correct: 0, why: "الأسلوب محترم، والخصم يحتاج صلاحية أو عرض معتمد." },
  ];
  let saved = {};
  let storageAvailable = true;
  try { saved = JSON.parse(localStorage.getItem(storageKey) || "{}") || {}; }
  catch { storageAvailable = false; }
  const done = new Set(Array.isArray(saved.done) ? saved.done.filter((id) => modules.some((m) => m.id === id)) : []);
  const positions = saved.positions && typeof saved.positions === "object" && !Array.isArray(saved.positions) ? saved.positions : {};
  let current = modules.find((m) => m.id === saved.current) || modules[0];
  let lessons = {};
  let stepIndex = 0;
  let selectedProduct = null;
  let catalogRequest = null;
  let scenarioIndex = 0;
  let challengeProduct = null;
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const money = (value) => `${Number(value || 0).toLocaleString("en-US")} د.ع`;
  const digits = (value) => String(value).replace(/[٠-٩۰-۹]/g, (c) => String("٠١٢٣٤٥٦٧٨٩".includes(c) ? "٠١٢٣٤٥٦٧٨٩".indexOf(c) : "۰۱۲۳۴۵۶۷۸۹".indexOf(c)));
  const colors = (product) => (product.colors || []).map((c) => typeof c === "string" ? c : c.name).filter(Boolean);
  function feedback(id, message, success = false) { $(id).textContent = message; $(id).className = success ? "success" : "error"; }
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify({ done: [...done], positions, current: current.id })); }
    catch { storageAvailable = false; }
    $("storage-note").textContent = storageAvailable ? "تقدّمك محفوظ بهذا المتصفح ولهذا الحساب فقط." : "الحفظ المحلي غير متاح بهذا المتصفح؛ تقدّمك مستمر إلى أن تغلق الصفحة.";
  }
  function renderNav() {
    $("module-nav").innerHTML = modules.map((m, i) => `<button type="button" class="module-link ${current.id === m.id ? "active" : ""} ${done.has(m.id) ? "done" : ""}" data-module="${m.id}" ${current.id === m.id ? 'aria-current="step"' : ""}><span class="module-index">${done.has(m.id) ? "✓" : String(i + 1).padStart(2, "0")}</span><span><strong>${m.title}</strong><small>${m.subtitle}</small></span></button>`).join("");
    $("course-progress").value = done.size;
    $("course-percent").textContent = `${Math.round(done.size / modules.length * 100)}%`;
    $("course-finished").hidden = done.size !== modules.length;
  }
  function complete() {
    done.add(current.id); persist(); renderNav();
    $("module-complete").hidden = false;
    const next = modules.findIndex((m) => m.id === current.id) + 1;
    $("next-module").textContent = next === modules.length ? "مراجعة المسار ↗" : "الدرس الجاي ←";
  }
  function openModule(id, focus = true) {
    current = modules.find((m) => m.id === id) || modules[0];
    for (const name of ["walkthrough", "knowledge", "conversation", "practice", "module-quiz", "module-complete"]) $(name).hidden = true;
    $("module-number").textContent = `الدرس ${modules.indexOf(current) + 1} من ${modules.length}`;
    $("module-title").textContent = current.title;
    $("module-kind").textContent = current.kind;
    $("module-complete").hidden = !done.has(current.id);
    if (current.quiz) {
      $("walkthrough").hidden = false;
      const list = lessons[current.id] || [];
      const position = Number(positions[current.id]);
      stepIndex = Number.isInteger(position) ? Math.min(Math.max(position, 0), Math.max(list.length - 1, 0)) : 0;
      renderStep();
    } else if (current.id === "products") {
      $("knowledge").hidden = false;
      loadProducts();
    } else if (current.id === "style") {
      $("conversation").hidden = false;
      scenarioIndex = 0; renderScenario();
    } else {
      $("practice").hidden = false;
      setupPractice();
    }
    renderNav(); persist();
    if (focus) $("module-title").scrollIntoView({ block: "start", behavior: "instant" });
  }
  function targetStyle(target) {
    return `left:${target.x}%;top:${target.y}%;width:${target.width}%;height:${target.height}%`;
  }
  function renderStep() {
    const steps = lessons[current.id] || [];
    const step = steps[stepIndex];
    if (!step) return;
    positions[current.id] = stepIndex;
    $("step-counter").textContent = `خطوة ${stepIndex + 1} / ${steps.length}`;
    $("step-title").textContent = step.title;
    $("step-description").textContent = step.description;
    $("step-task").textContent = step.task;
    $("step-image").src = config.assetRoot + step.image;
    $("step-image").alt = `واجهة مكتب الموظف: ${step.title}. ${step.task}`;
    $("hotspot").style.cssText = targetStyle(step.target);
    $("hotspot").setAttribute("aria-label", step.task);
    $("hotspot").className = "";
    $("hotspot").firstElementChild.textContent = "اضغط هنا";
    $("step-feedback").textContent = "";
    $("step-hint").textContent = step.hint;
    $("step-hint").hidden = true;
    $("step-next").disabled = true;
    $("step-next").textContent = stepIndex === steps.length - 1 ? "اختبر فهمك ←" : "الخطوة الجاية ←";
    $("step-prev").disabled = stepIndex === 0;
    $("module-quiz").hidden = true;
    persist();
  }
  function renderAnswers(container, answers, correct, onCorrect, feedbackId, explanation) {
    $(container).innerHTML = answers.map((a, i) => `<button class="answer" type="button" data-answer="${i}">${esc(a)}</button>`).join("");
    $(container).onclick = (event) => {
      const button = event.target.closest("[data-answer]");
      if (!button || button.disabled) return;
      const right = Number(button.dataset.answer) === correct;
      button.classList.add(right ? "correct" : "wrong");
      if (!right) { feedback(feedbackId, "مو هذا الخيار الأنسب. فكّر بالمعلومة المؤكدة وجرّب مرة ثانية."); return; }
      $(container).querySelectorAll("button").forEach((b) => { b.disabled = true; });
      feedback(feedbackId, `صح ✓ ${explanation}`, true); onCorrect();
    };
  }
  function renderQuiz() {
    $("module-quiz").hidden = false;
    $("quiz-question").textContent = current.quiz.q;
    $("quiz-feedback").textContent = "";
    renderAnswers("quiz-answers", current.quiz.answers, current.quiz.correct, complete, "quiz-feedback", current.quiz.why);
    $("module-quiz").scrollIntoView({ block: "center", behavior: "instant" });
  }
  async function loadProducts() {
    catalogRequest?.abort();
    const controller = new AbortController(); catalogRequest = controller;
    $("product-status").textContent = "جاري قراءة الكتالوج…";
    $("product-list").replaceChildren();
    $("product-detail").textContent = "اختَر منتج من القائمة حتى تتعلّم عليه.";
    $("product-challenge").hidden = true;
    try {
      const response = await fetch(`/api/employee-desk/training/products?q=${encodeURIComponent($("product-search").value.trim())}`, { signal: controller.signal, cache: "no-store" });
      if (response.status === 401 || response.status === 403) throw new Error("انتهت الجلسة أو ما عندك صلاحية. ارجع للمكتب وسجّل دخولك.");
      if (!response.ok) throw new Error("تعذر تحميل المنتجات. جرّب البحث مرة ثانية.");
      const data = await response.json();
      if (!data.ok || !Array.isArray(data.products)) throw new Error("تعذر قراءة الكتالوج. جرّب مرة ثانية.");
      if (controller.signal.aborted) return;
      $("product-status").textContent = data.products.length ? `ظهرت ${data.products.length} نتيجة (لحد 48 بالبحث). الأسعار مقروءة هسّه من النظام.` : "ماكو منتجات مطابقة. جرّب اسم ثاني أو راجع المسؤول حتى يكمل الكتالوج.";
      data.products.forEach((product) => {
        const button = document.createElement("button"); button.type = "button"; button.className = "product-choice";
        button.innerHTML = `<strong>${esc(product.name)}</strong><small>${esc(product.sku || "منتج من الكتالوج")}</small>`;
        button.onclick = () => {
          $("product-list").querySelectorAll("button").forEach((b) => b.classList.remove("active"));
          button.classList.add("active"); selectedProduct = product; showProduct(product);
        };
        $("product-list").append(button);
      });
    } catch (error) { if (error.name !== "AbortError") feedback("product-status", error.message); }
  }
  function showProduct(product) {
    $("product-challenge").hidden = true;
    const specs = (product.specs || []).map((row) => `${row.label}: ${row.value}`).join("\n");
    const description = [product.description, specs].filter(Boolean).join("\n");
    const region = product.dual_region_pricing && product.governorate_sale_price != null
      ? `<p class="product-spec">سعر ${esc(product.primary_province || "المحافظة الأساسية")}: ${money(product.price)}<br>باقي المحافظات: ${money(product.governorate_sale_price)}</p>` : "";
    const colorPrices = (product.colors || []).filter((c) => typeof c === "object" && c.name && c.sale_price != null && Number(c.sale_price) !== Number(product.price));
    const colorRegionPrices = product.dual_region_pricing ? (product.colors || []).filter((c) => typeof c === "object" && c.name && c.governorate_sale_price != null) : [];
    let photo = "";
    if (product.image_url) {
      try { const url = new URL(product.image_url, location.origin); if (["http:", "https:"].includes(url.protocol)) photo = `<img class="product-photo" src="${esc(url.href)}" alt="${esc(product.name)}" loading="lazy">`; } catch { /* An invalid optional image does not hide selling information. */ }
    }
    $("product-detail").innerHTML = `<span class="source-label">بيانات فعلية</span>${photo}<h3>${esc(product.name)}</h3><p class="price">${money(product.price)}</p><small>سعر البيع الأساسي المسجل</small>${region}<h4>المواصفات</h4><p class="product-spec">${esc(description || "المواصفات غير مسجلة لهذا المنتج. راجع المسؤول، ولا تعطي الزبون تفاصيل غير مؤكدة.")}</p><h4>الألوان المسجلة</h4><div class="color-tags">${colors(product).map((c) => `<span>${esc(c)}</span>`).join("") || "غير مسجلة"}</div>${colorPrices.length ? `<h4>أسعار البيع حسب اللون</h4>${colorPrices.map((c) => `<p class="product-spec">${esc(c.name)}: ${money(c.sale_price)}</p>`).join("")}` : ""}${colorRegionPrices.length ? `<h4>أسعار المحافظات حسب اللون</h4>${colorRegionPrices.map((c) => `<p class="product-spec">${esc(c.name)}: ${money(c.governorate_sale_price)}</p>`).join("")}` : ""}<h4>مثال رد مبني على البيانات</h4><p class="product-spec">${esc(`أهلاً وسهلاً، سعر ${product.name} الأساسي ${money(product.price)}.${description ? ` المواصفات المسجلة: ${description}` : " خل أتأكدلك من التفاصيل المطلوبة ويّا المسؤول."} ممكن محافظتك ومنطقتك حتى نتأكد من التوصيل والسعر النهائي؟`)}</p><button class="secondary" id="start-price-quiz" type="button">قرأت المعلومات، اختبرني بالسعر</button>`;
    $("product-detail").querySelector("img")?.addEventListener("error", (event) => { event.currentTarget.hidden = true; });
    $("start-price-quiz").onclick = () => {
      challengeProduct = product;
      $("product-detail").textContent = "خبّينا السعر مؤقتاً. جاوب من ذاكرتك، أو اختَر المنتج مرة ثانية حتى تراجعه.";
      $("price-question").textContent = `شنو سعر البيع الأساسي المسجل لـ ${product.name}؟`;
      $("price-answer").value = ""; $("price-feedback").textContent = "";
      $("product-challenge").hidden = false; $("price-answer").focus();
    };
  }
  function renderScenario() {
    const scenario = scenarios[scenarioIndex];
    $("scenario-question").textContent = `${scenarioIndex + 1} / ${scenarios.length} — ${scenario.q}`;
    $("scenario-feedback").textContent = "";
    $("scenario-next").disabled = true;
    $("scenario-next").textContent = scenarioIndex === scenarios.length - 1 ? "إكمال درس الردود ✓" : "الموقف الجاي ←";
    renderAnswers("scenario-answers", scenario.answers, scenario.correct, () => { $("scenario-next").disabled = false; }, "scenario-feedback", scenario.why);
  }
  function setupPractice() {
    $("practice-form").reset(); $("practice-feedback").replaceChildren();
    $("practice-message").textContent = selectedProduct ? `الزبون: مرحباً، شنو سعر ${selectedProduct.name} ومواصفاته؟ وأريد أحجز قطعة.` : "حتى تتمرّن على معلومة حقيقية: افتح درس «اعرف منتجاتك» واختَر منتج، بعدها ارجع هنا.";
    $("practice-submit").disabled = !selectedProduct;
    const list = selectedProduct ? colors(selectedProduct) : [];
    $("practice-color-label").hidden = list.length === 0;
    $("practice-color").required = list.length > 0;
    $("practice-color").innerHTML = `<option value="">اختَر اللون</option>${list.map((c) => `<option>${esc(c)}</option>`).join("")}`;
  }
  $("module-nav").onclick = (event) => { const button = event.target.closest("[data-module]"); if (button) openModule(button.dataset.module); };
  $("hotspot").onclick = () => { $("hotspot").classList.add("hit"); $("hotspot").firstElementChild.textContent = "صح ✓"; $("step-feedback").textContent = "بالضبط، هذا المكان الصحيح ✓ هسّه كمّل الخطوة الجاية."; $("step-next").disabled = false; };
  $("phone-screen").onclick = (event) => { if (!event.target.closest("button")) $("step-feedback").textContent = "دوّر على الإطار الملوّن واضغط عليه. تكدر تستخدم زر «أحتاج توضيح»."; };
  $("show-hint").onclick = () => { $("step-hint").hidden = !$("step-hint").hidden; };
  $("step-next").onclick = () => {
    if (stepIndex < lessons[current.id].length - 1) {
      stepIndex++; renderStep(); $("step-title").focus({ preventScroll: true });
      if (window.matchMedia("(max-width: 560px)").matches) $("step-title").scrollIntoView({ block: "start", behavior: "instant" });
    } else renderQuiz();
  };
  $("step-prev").onclick = () => { if (stepIndex > 0) { stepIndex--; renderStep(); } };
  $("next-module").onclick = () => { openModule(modules[(modules.indexOf(current) + 1) % modules.length].id); };
  $("product-search-form").onsubmit = (event) => { event.preventDefault(); loadProducts(); };
  $("price-form").onsubmit = (event) => {
    event.preventDefault(); if (!challengeProduct) return;
    const raw = digits($("price-answer").value).replace(/[,٬\s]/g, "");
    if (!/^\d+$/.test(raw) || Number(raw) !== Number(challengeProduct.price)) { feedback("price-feedback", "السعر مو مطابق. جرّب مرة ثانية أو اختَر المنتج حتى تراجع سعره."); return; }
    feedback("price-feedback", `صحيح ✓ السعر المسجل وقت البحث ${money(challengeProduct.price)}. راجعه دائماً قبل الاتفاق النهائي.`, true); complete();
  };
  $("scenario-next").onclick = () => { if (scenarioIndex < scenarios.length - 1) { scenarioIndex++; renderScenario(); } else complete(); };
  $("practice-form").onsubmit = (event) => {
    event.preventDefault(); if (!selectedProduct) return;
    const form = new FormData(event.currentTarget);
    const phone = digits(form.get("phone")).replace(/[\s()+-]/g, "");
    if (!/^(?:07\d{9}|9647\d{9})$/.test(phone)) { feedback("practice-feedback", "راجع رقم الهاتف العراقي: 11 رقم يبدأ بـ 07، أو الصيغة الدولية +9647…"); return; }
    if (["customer", "city", "address"].some((key) => String(form.get(key) || "").trim().length < 2)) { feedback("practice-feedback", "كمّل اسم الزبون والمحافظة والعنوان بشكل واضح."); return; }
    const quantity = Number(form.get("quantity"));
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 99) { feedback("practice-feedback", "راجع الكمية المطلوبة."); return; }
    const reply = digits($("practice-reply").value).replace(/[,٬]/g, "").trim();
    const price = String(Number(selectedProduct.price));
    const replyNumbers = reply.match(/\d+/g) || [];
    if (reply.length < 25 || !replyNumbers.includes(price)) { feedback("practice-feedback", "راجع ردك: رحّب بالزبون، اذكر السعر الصحيح بالأرقام، وجاوب من المواصفات المسجلة أو وضّح أنك راح تتأكد منها."); return; }
    if (colors(selectedProduct).length && !colors(selectedProduct).includes(form.get("color"))) { feedback("practice-feedback", "اختَر لون مسجل بالكتالوج."); return; }
    if (!$("practice-confirm").checked) return;
    $("practice-feedback").className = "success";
    $("practice-feedback").innerHTML = `<h4>بيانات التمرين مكتملة ✓</h4><p>${esc(form.get("customer"))} · ${esc(form.get("city"))} · ${esc(form.get("address"))}</p><p>${esc(selectedProduct.name)} × ${quantity}${form.get("color") ? ` · ${esc(form.get("color"))}` : ""} · مجموع المنتجات: ${money(Number(selectedProduct.price) * quantity)} (قبل التوصيل وأي تعديل معتمد).</p><p>راجع صياغة ردك ومواصفات المنتج ويّا المشرف. بالعمل الفعلي تنتظر تأكيد نجاح الحجز من النظام وتتجنب تكرار الضغط.</p><b>اكتمل التمرين فقط؛ ما تم تسجيل طلب أو إرسال رد.</b>`;
    complete();
  };
  $("reset-progress").onclick = () => {
    if (!window.confirm("تريد تمسح تقدّم التدريب لهذا الحساب بهذا المتصفح وتبدأ من جديد؟")) return;
    done.clear(); Object.keys(positions).forEach((key) => delete positions[key]); openModule("login");
  };
  $("zoom-image").onclick = () => {
    const step = lessons[current.id][stepIndex];
    $("zoom-caption").textContent = step.task;
    $("zoom-content").innerHTML = `<img src="${esc(config.assetRoot + step.image)}" alt="${esc(step.title)}"><div class="zoom-marker" style="${targetStyle(step.target)}"><span>هنا مكان الضغط</span></div>`;
    $("image-dialog").showModal();
  };
  $("close-image").onclick = () => $("image-dialog").close();
  $("step-image").onerror = () => { $("step-feedback").textContent = "تعذر تحميل الصورة. حدّث الصفحة أو راجع المسؤول."; $("step-next").disabled = true; };
  async function start() {
    try {
      const response = await fetch(config.lessonsUrl, { cache: "no-cache" });
      if (!response.ok) throw new Error("تعذر تحميل الدروس. حدّث الصفحة وحاول مرة ثانية.");
      lessons = await response.json();
      if (modules.some((m) => m.quiz && (!Array.isArray(lessons[m.id]) || !lessons[m.id].length))) throw new Error("ملفات الدروس غير مكتملة. راجع المسؤول.");
      $("load-status").hidden = true; openModule(current.id, false);
    } catch (error) { $("load-status").textContent = error.message; }
  }
  start();
})();
