/* FINORA Smart Commerce V2 shell: search suggestions, recent searches, delivery area, drawer, favourites,
   and a lazily loaded assistant. Small on purpose: nothing here runs before the page is usable. */
(function () {
  "use strict";
  var cfg = window.STOREFRONT_CONFIG || {};
  var slug = cfg.tenantSlug || "";
  var RECENT_KEY = "sm_recent_searches:" + slug;
  var AREA_KEY = "sm_delivery_area:" + slug;

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      if (value === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, value);
    } catch (_) { /* private mode / blocked storage: features degrade, the shop still works */ }
    return null;
  }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text) node.textContent = text;
    return node;
  }

  function formatPrice(p) {
    if (!p || !p.price) return "";
    var n = new Intl.NumberFormat("en-US").format(Number(p.price) || 0);
    return p.price_currency === "USD" ? "$" + n : n + " د.ع";
  }

  /* ---------- recent searches ---------- */
  function recent() {
    try { return JSON.parse(store(RECENT_KEY) || "[]").filter(Boolean).slice(0, 6); } catch (_) { return []; }
  }
  var personalize = cfg.personalize !== false;
  if (!personalize) {  /* switched off: forget what this browser kept, keep nothing new */
    store(RECENT_KEY, null);
    store("sm_viewed:" + slug, null);
  }
  function remember(q) {
    if (!personalize) return;
    q = String(q || "").trim();
    if (q.length < 2) return;
    var list = recent().filter(function (x) { return x !== q; });
    list.unshift(q);
    store(RECENT_KEY, JSON.stringify(list.slice(0, 6)));
  }

  /* ---------- search suggestions (debounced, cancellable) ---------- */
  var form = document.querySelector("[data-sm-search]");
  if (form) {
    var input = form.querySelector("input[name=q]");
    var box = document.getElementById("smSuggest");
    var timer = null;
    var controller = null;
    var active = -1;

    var close = function () { box.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
    var open = function () { box.hidden = false; input.setAttribute("aria-expanded", "true"); };
    var go = function (q) { input.value = q; remember(q); form.submit(); };

    var showRecent = function () {
      var list = recent();
      box.innerHTML = "";
      if (!list.length) { close(); return; }
      box.appendChild(el("div", { class: "sm-suggest__label" }, "آخر عمليات البحث"));
      list.forEach(function (q) {
        var b = el("button", { type: "button", role: "option" }, q);
        b.addEventListener("click", function () { go(q); });
        box.appendChild(b);
      });
      open();
    };

    var render = function (q, data) {
      box.innerHTML = "";
      var products = (data && data.products) || [];
      if (!products.length) {
        box.appendChild(el("div", { class: "sm-suggest__label" }, "لا نتائج مطابقة — اضغط بحث لعرض البدائل"));
        open();
        return;
      }
      box.appendChild(el("div", { class: "sm-suggest__label" }, (data.total || products.length) + " نتيجة"));
      products.forEach(function (p) {
        var a = el("a", { href: p.url, role: "option", "aria-selected": "false" });
        if (p.image_url) a.appendChild(el("img", { src: p.image_url, alt: "", width: "40", height: "40", loading: "lazy" }));
        var text = el("span");
        text.appendChild(el("span", {}, p.name));
        text.appendChild(document.createElement("br"));
        text.appendChild(el("small", {}, [p.model, formatPrice(p)].filter(Boolean).join(" · ")));
        a.appendChild(text);
        a.addEventListener("click", function () { remember(q); });
        box.appendChild(a);
      });
      var all = el("button", { type: "button" }, "عرض كل النتائج لـ «" + q + "»");
      all.addEventListener("click", function () { go(q); });
      box.appendChild(all);
      open();
    };

    var fetchSuggest = function () {
      var q = input.value.trim();
      if (q.length < 2) { showRecent(); return; }
      if (controller) controller.abort();
      controller = new AbortController();
      var url = "/shop/" + encodeURIComponent(slug) + "/api/products?per_page=6&q=" + encodeURIComponent(q);
      fetch(url, { signal: controller.signal, headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { if (data && input.value.trim() === q) render(q, data); })
        .catch(function (err) { if (err && err.name !== "AbortError") close(); });
    };

    input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(fetchSuggest, 220); });
    input.addEventListener("focus", function () { if (!input.value.trim()) showRecent(); });
    input.addEventListener("keydown", function (e) {
      var items = box.querySelectorAll("a[role=option]");
      if (e.key === "Escape") { close(); return; }
      if (!items.length || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items.forEach(function (n, i) { n.setAttribute("aria-selected", i === active ? "true" : "false"); });
      items[active].focus();
    });
    form.addEventListener("submit", function () { remember(input.value); });
    document.addEventListener("click", function (e) { if (!form.contains(e.target)) close(); });
  }

  /* recent searches on the home page */
  var recentSection = document.querySelector("[data-sm-recent]");
  if (recentSection && recent().length) {
    var list = recentSection.querySelector("[data-sm-recent-list]");
    recent().forEach(function (q) {
      list.appendChild(el("a", { class: "sm-chip", href: "/shop/" + encodeURIComponent(slug) + "/?q=" + encodeURIComponent(q) }, q));
    });
    recentSection.hidden = false;
  }

  /* ---------- delivery area ---------- */
  var areaBtn = document.querySelector("[data-sm-area]");
  var dialog = document.getElementById("smAreaDialog");
  var label = document.querySelector("[data-sm-area-label]");
  var select = document.querySelector("[data-sm-area-select]");
  var savedArea = store(AREA_KEY);
  if (savedArea && label) label.textContent = "التوصيل إلى " + savedArea;
  // the server needs the province for availability, fees and ranking (kept in the session; no exact location)
  function syncArea(province, reload) {
    fetch("/shop/" + encodeURIComponent(slug) + "/api/delivery-area", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ province: province || "" }),
    })
      .then(function (r) { if (r.ok && reload && document.querySelector("[data-sm-delivery]")) window.location.reload(); })
      .catch(function () { /* the page still works without it */ });
  }
  if (savedArea && cfg.deliveryArea !== savedArea) syncArea(savedArea, !!document.querySelector("[data-sm-delivery]"));
  if (areaBtn && dialog && typeof dialog.showModal === "function") {
    document.addEventListener("click", function (e) {
      if (!e.target.closest || !e.target.closest("[data-sm-area]")) return;
      if (select && savedArea) select.value = savedArea;
      dialog.showModal();
    });
    dialog.addEventListener("close", function () {
      if (dialog.returnValue !== "save" || !select) return;
      savedArea = select.value || null;
      store(AREA_KEY, savedArea);
      if (label) label.textContent = savedArea ? "التوصيل إلى " + savedArea : "منطقة التوصيل";
      syncArea(savedArea, true);
    });
  } else if (areaBtn) {
    areaBtn.hidden = true;
  }

  /* ---------- drawer ---------- */
  var drawer = document.getElementById("smDrawer");
  var menuBtn = document.querySelector("[data-sm-menu]");
  if (drawer && menuBtn) {
    var setDrawer = function (on) {
      drawer.hidden = !on;
      menuBtn.setAttribute("aria-expanded", on ? "true" : "false");
      document.body.style.overflow = on ? "hidden" : "";
    };
    menuBtn.addEventListener("click", function () { setDrawer(drawer.hidden); });
    drawer.querySelectorAll("[data-sm-menu-close], a").forEach(function (n) { n.addEventListener("click", function () { setDrawer(false); }); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !drawer.hidden) setDrawer(false); });
  }

  /* ---------- favourites ---------- */
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-favorite-toggle]");
    if (!btn) return;
    e.preventDefault();
    fetch(btn.getAttribute("data-favorite-toggle"), { method: "POST", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.success) return;
        btn.classList.toggle("is-on", !!data.added);
        btn.classList.toggle("is-active", !!data.added);
        btn.setAttribute("aria-pressed", data.added ? "true" : "false");
        document.querySelectorAll("[data-favorite-count]").forEach(function (b) { b.textContent = data.count; b.hidden = !data.count; });
      })
      .catch(function () { /* nothing changed */ });
  });


  /* ---------- quantity steppers (product page) ---------- */
  document.querySelectorAll("[data-sm-qty]").forEach(function (group) {
    var input = group.querySelector("input[type=number]");
    group.querySelectorAll("[data-sm-qty-step]").forEach(function (b) {
      b.addEventListener("click", function () {
        var max = parseInt(input.getAttribute("max"), 10) || 9999;
        var next = (parseInt(input.value, 10) || 1) + parseInt(b.getAttribute("data-sm-qty-step"), 10);
        input.value = String(Math.min(max, Math.max(1, next)));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
  });

  /* ---------- checkout: Iraqi phone, delivery area, live delivery fee ---------- */
  var checkout = document.querySelector("[data-sm-checkout]");
  if (checkout) {
    var phone = checkout.querySelector("[data-sm-iq-phone]");
    var phoneErr = checkout.querySelector("[data-sm-phone-err]");
    var city = checkout.querySelector("[data-sm-city]");
    var normalizePhone = function (v) {
      var d = String(v || "").replace(/[٠-٩]/g, function (c) { return "٠١٢٣٤٥٦٧٨٩".indexOf(c); }).replace(/\D+/g, "");
      if (d.indexOf("964") === 0) d = "0" + d.slice(3);
      if (d.length === 10 && d[0] === "7") d = "0" + d;
      return d;
    };
    var phoneOk = function () { return /^07\d{9}$/.test(normalizePhone(phone.value)); };
    if (phone && !phone.readOnly) {
      phone.addEventListener("blur", function () {
        if (!phone.value.trim()) return;
        var ok = phoneOk();
        phone.setAttribute("aria-invalid", ok ? "false" : "true");
        if (phoneErr) phoneErr.hidden = ok;
        if (ok) phone.value = normalizePhone(phone.value);
      });
    }
    if (city && !city.value && savedArea) {
      Array.prototype.forEach.call(city.options, function (o) { if (o.value === savedArea) city.value = savedArea; });
    }
    var money = function (n) { return new Intl.NumberFormat("en-US").format(Number(n) || 0) + " د.ع"; };
    var refreshFee = function () {
      var map = cfg.shippingMap || {};
      var fee = city && city.value && map[city.value] !== undefined ? map[city.value] : (cfg.shippingDefault || 0);
      var ship = document.querySelector("[data-sm-ship]");
      var grand = document.querySelector("[data-sm-grand]");
      if (ship) ship.textContent = money(fee);
      if (grand) grand.textContent = money((Number(cfg.netSubtotal) || 0) + (Number(fee) || 0));
    };
    if (city) { city.addEventListener("change", refreshFee); if (city.value) refreshFee(); }
    checkout.addEventListener("submit", function (e) {
      var bad = null;
      checkout.querySelectorAll("[required]").forEach(function (f) {
        var empty = !String(f.value || "").trim();
        f.setAttribute("aria-invalid", empty ? "true" : "false");
        if (empty && !bad) bad = f;
      });
      if (phone && !phone.readOnly && !phoneOk()) {
        phone.setAttribute("aria-invalid", "true");
        if (phoneErr) phoneErr.hidden = false;
        bad = bad || phone;
      } else if (phone && !phone.readOnly) {
        phone.value = normalizePhone(phone.value);
      }
      if (bad) { e.preventDefault(); bad.focus(); return; }
      var go = checkout.querySelector("[type=submit]");
      if (go) { go.disabled = true; go.textContent = "جارٍ تأكيد الطلب…"; }
    });
  }

  /* ---------- recently viewed (kept in this browser only) and the comparison tray ---------- */
  function idList(key) {
    try { return (JSON.parse(store(key) || "[]") || []).map(Number).filter(function (n) { return n > 0; }); }
    catch (_) { return []; }
  }
  var VIEWED_KEY = "sm_viewed:" + slug;
  var COMPARE_KEY = "sm_compare:" + slug;
  var viewedSection = personalize ? document.querySelector("[data-sm-viewed]") : null;
  if (viewedSection) {
    var current = Number(viewedSection.getAttribute("data-sm-viewed"));
    var seen = idList(VIEWED_KEY).filter(function (n) { return n !== current; });
    store(VIEWED_KEY, JSON.stringify([current].concat(seen).slice(0, 12)));
    if (seen.length) {
      fetch(viewedSection.getAttribute("data-cards-url") + "?ids=" + seen.slice(0, 8).join(","), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          var rows = (data && data.rows) || [];
          if (!rows.length) return;
          var list = viewedSection.querySelector("[data-sm-viewed-list]");
          rows.forEach(function (p) {
            var card = el("a", { class: "sm-mini", href: p.url });
            if (p.image_url) card.appendChild(el("img", { src: p.image_url, alt: "", width: "96", height: "96", loading: "lazy" }));
            card.appendChild(el("span", { class: "sm-mini__name" }, p.name));
            if (p.price > 0) card.appendChild(el("strong", {}, Number(p.price).toLocaleString("en-US") + " " + (p.currency_label || "")));
            list.appendChild(card);
          });
          viewedSection.hidden = false;
        })
        .catch(function () { /* the section simply stays hidden */ });
    }
  }

  var compareBtn = document.querySelector("[data-sm-compare]");
  function compareBar(url, ids) {
    var bar = document.getElementById("smCompareBar");
    if (ids.length < 2) { if (bar) bar.remove(); return; }
    if (!bar) {
      bar = el("a", { id: "smCompareBar", class: "sm-compare-bar" });
      document.body.appendChild(bar);
    }
    bar.href = url + "?ids=" + ids.join(",");
    bar.textContent = ids.length === 2 ? "قارن منتجين" : "قارن " + ids.length + " منتجات";
  }
  if (compareBtn) {
    var cid = Number(compareBtn.getAttribute("data-sm-compare"));
    var curl = compareBtn.getAttribute("data-compare-url");
    var paint = function () {
      var ids = idList(COMPARE_KEY);
      var on = ids.indexOf(cid) >= 0;
      compareBtn.setAttribute("aria-pressed", on ? "true" : "false");
      compareBtn.textContent = on ? "✓ في المقارنة" : "+ أضف للمقارنة";
      compareBar(curl, ids);
    };
    compareBtn.addEventListener("click", function () {
      var ids = idList(COMPARE_KEY).filter(function (n) { return n !== cid; });
      if (compareBtn.getAttribute("aria-pressed") !== "true") ids = ids.concat([cid]).slice(-4);
      store(COMPARE_KEY, JSON.stringify(ids));
      paint();
    });
    paint();
  }

  var comparePage = document.querySelector("[data-sm-compare-page]");
  if (comparePage) {
    var diff = comparePage.querySelector("[data-sm-compare-diff]");
    if (diff) diff.addEventListener("change", function () { comparePage.classList.toggle("only-diff", diff.checked); });
    comparePage.addEventListener("click", function (e) {
      var rm = e.target.closest("[data-sm-compare-remove]");
      if (!rm) return;
      var gone = Number(rm.getAttribute("data-sm-compare-remove"));
      var params = new URLSearchParams(window.location.search);
      var ids = (params.get("ids") || "").split(",").map(Number).filter(function (n) { return n > 0 && n !== gone; });
      store(COMPARE_KEY, JSON.stringify(ids));
      params.set("ids", ids.join(","));
      window.location.search = params.toString();
    });
  }

  /* ---------- measuring recommendations: a click inside a recommendation section (anonymous) ---------- */
  function signal(payload) {
    if (!personalize) return;
    var url = "/shop/" + encodeURIComponent(slug) + "/api/events";
    var body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(url, new Blob([body], { type: "application/json" }))) return;
    } catch (_) { /* fall through */ }
    fetch(url, { method: "POST", body: body, headers: { "Content-Type": "application/json" }, keepalive: true, credentials: "same-origin" })
      .catch(function () {});
  }
  document.addEventListener("click", function (e) {
    var target = e.target.closest("a[href], [data-sf-add-cart]");
    var section = target && target.closest("[data-sm-rec]");
    if (!section) return;
    var card = target.closest("[data-product-id]");
    signal({ type: "rec_click", section: section.getAttribute("data-sm-rec"),
             product_id: card ? Number(card.getAttribute("data-product-id")) : null });
  });
  if (compareBtn) {
    compareBtn.addEventListener("click", function () {
      if (compareBtn.getAttribute("aria-pressed") === "true") signal({ type: "compare", product_id: Number(compareBtn.getAttribute("data-sm-compare")) });
    });
  }

  /* ---------- «أضف الباقة للسلة»: every available product of the bundle, the rest named back ---------- */
  function bundleToast(text, kind) {
    var wrap = document.getElementById("sfToastWrap");
    if (!wrap) return;
    var node = el("div", { class: "sf-toast " + (kind || "ok") }, text);
    wrap.appendChild(node);
    setTimeout(function () { node.remove(); }, 5000);
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-sm-add-bundle]");
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    fetch("/shop/" + encodeURIComponent(slug) + "/api/cart/add-bundle", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ bundle_id: Number(btn.getAttribute("data-sm-add-bundle")) })
    })
      .then(function (r) { return r.json().catch(function () { return null; }); })
      .then(function (data) {
        if (!data) { bundleToast("تعذّر الاتصال، حاول مرة أخرى", "err"); return; }
        var count = data.cart && data.cart.count;
        if (count !== undefined) {
          document.querySelectorAll("[data-sf-cart-count]").forEach(function (n) { n.textContent = String(count || 0); n.hidden = !count; });
        }
        var skipped = (data.skipped || []).map(function (s) { return s.name + " (" + s.reason + ")"; });
        bundleToast((data.message || data.error || "") + (skipped.length ? " — لم يُضف: " + skipped.join("، ") : ""),
                    data.success ? (skipped.length ? "warn" : "ok") : "err");
      })
      .catch(function () { bundleToast("تعذّر الاتصال، حاول مرة أخرى", "err"); })
      .then(function () { btn.disabled = false; });
  });

  /* ---------- real-user Core Web Vitals (LCP, CLS, INP) — anonymous, sent once when the page is hidden ---------- */
  if ("PerformanceObserver" in window && Math.random() < (cfg.vitalsSample || 0)) {
    var vit = { lcp: null, cls: 0, inp: null };
    var observe = function (type, fn, extra) {
      try {
        var o = new PerformanceObserver(function (list) { list.getEntries().forEach(fn); });
        o.observe(Object.assign({ type: type, buffered: true }, extra || {}));
      } catch (_) { /* not supported by this browser */ }
    };
    observe("largest-contentful-paint", function (e) { vit.lcp = e.startTime; });
    observe("layout-shift", function (e) { if (!e.hadRecentInput) vit.cls += e.value; });
    observe("event", function (e) { if (e.interactionId) vit.inp = Math.max(vit.inp || 0, e.duration); }, { durationThreshold: 40 });
    var path = location.pathname;
    var params = new URLSearchParams(location.search);
    var pageType = /\/product\//.test(path) ? "product" : /\/cart\/?$/.test(path) ? "cart" : /\/checkout/.test(path) ? "checkout"
      : /\/compare/.test(path) ? "compare" : params.get("q") ? "search" : params.get("badge") ? "category"
      : /^\/shop\/[^/]+\/?$/.test(path) ? "home" : "other";
    var sent = false;
    var sendVitals = function () {
      if (sent || document.visibilityState !== "hidden") return;
      sent = true;
      var body = JSON.stringify({ page: pageType, lcp: vit.lcp, cls: Math.round(vit.cls * 1000) / 1000, inp: vit.inp,
                                  mobile: window.matchMedia("(max-width: 767px)").matches });
      var url = "/shop/" + encodeURIComponent(slug) + "/api/vitals";
      try { if (navigator.sendBeacon(url, new Blob([body], { type: "application/json" }))) return; } catch (_) { /* fall back */ }
      fetch(url, { method: "POST", body: body, headers: { "Content-Type": "application/json" }, keepalive: true }).catch(function () {});
    };
    document.addEventListener("visibilitychange", sendVitals);
    window.addEventListener("pagehide", function () { sendVitals(); });
  }

  /* ---------- assistant: loaded when the browser is idle, never on the critical path ---------- */
  if (cfg.aiChatEnabled && Array.isArray(cfg.aiAssets)) {
    var loadAssistant = function () {
      var css = el("link", { rel: "stylesheet", href: cfg.aiAssets[0] });
      document.head.appendChild(css);
      var js = el("script", { src: cfg.aiAssets[1] });
      js.addEventListener("load", function () {
        var root = document.getElementById("smAiRoot");
        if (root) root.hidden = false;
      });
      document.body.appendChild(js);
    };
    var idle = window.requestIdleCallback || function (fn) { return setTimeout(fn, 1500); };
    window.addEventListener("load", function () { idle(loadAssistant); });
  }
})();
