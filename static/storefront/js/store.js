(function () {
  const cfg = window.STOREFRONT_CONFIG || {};
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const motionByElement = new WeakMap();
  const imageRevision = new WeakMap();
  const activeMotion = new Set();
  function animateFeedback(element, frames, duration = 260) {
    if (!element || reducedMotion.matches || typeof element.animate !== "function") return;
    motionByElement.get(element)?.cancel();
    const animation = element.animate(frames, { duration, easing: "cubic-bezier(.22, 1, .36, 1)" });
    motionByElement.set(element, animation);
    activeMotion.add(animation);
    const cleanup = () => {
      activeMotion.delete(animation);
      if (motionByElement.get(element) === animation) motionByElement.delete(element);
    };
    animation.addEventListener("finish", cleanup, { once: true });
    animation.addEventListener("cancel", cleanup, { once: true });
  }
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) activeMotion.forEach((animation) => animation.cancel());
  });
  function updateOptionImage(main, src) {
    if (!main) return;
    const changed = main.getAttribute("src") !== src;
    const revision = (imageRevision.get(main) || 0) + 1;
    if (changed) imageRevision.set(main, revision);
    main.classList.remove("is-fading");
    main.hidden = !src;
    if (!src) { motionByElement.get(main)?.cancel(); main.removeAttribute("src"); return; }
    if (!changed) return;
    motionByElement.get(main)?.cancel();
    main.src = src;
    const reveal = () => {
      if (imageRevision.get(main) === revision && main.getAttribute("src") === src && !main.hidden) {
        animateFeedback(main, [{ opacity: .35, transform: "scale(.975)" }, { opacity: 1, transform: "scale(1)" }], 320);
      }
    };
    if (main.decode) main.decode().then(reveal, reveal);
    else reveal();
  }
  const slug = cfg.tenantSlug || "";
  const devQ = cfg.dev ? "?dev=1" : "";
  const saleProductsEl = document.getElementById("sfSaleProductsData");
  let saleProducts = [];
  try {
    saleProducts = JSON.parse(saleProductsEl?.textContent || "[]");
  } catch (_) {
    saleProducts = [];
  }

  function apiUrl(path) {
    return `/shop/${encodeURIComponent(slug)}/api/${path}${devQ}`;
  }

  // The page embeds only the products it renders. A product that is not among them (cart upsell, AI chat link…)
  // is fetched on demand, once, so colour / exchange rules are still applied before adding it.
  async function ensureProduct(productId) {
    let product = saleProducts.find((p) => Number(p.id) === Number(productId));
    if (product) return product;
    try {
      const res = await fetch(apiUrl(`product/${productId}/options`), { headers: { "X-Requested-With": "XMLHttpRequest" } });
      const data = await res.json();
      if (res.ok && data.success && data.product) {
        saleProducts.push(data.product);
        product = data.product;
      }
    } catch (_) {
      /* the server still validates the addition; options simply stay unknown */
    }
    return product;
  }

  function showToast(message, type) {
    const wrap = document.getElementById("sfToastWrap");
    if (!wrap) return;
    const el = document.createElement("div");
    el.className = `sf-toast ${type || "ok"}`;
    el.textContent = message;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }

  function updateCartBadge(count) {
    document.querySelectorAll("[data-sf-cart-count]").forEach((node) => {
      node.textContent = String(count || 0);
      if (cfg.v2) node.hidden = !count;
    });
  }

  function chooseSaleOptions(productId) {
    const product = saleProducts.find((p) => Number(p.id) === Number(productId));
    if (!product) return { sale_mode: "normal", color: "", trade_in_source_product_id: null };
    let color = "";
    if (product.has_colors) {
      const names = (product.colors || []).map((c) => c.name || c).filter(Boolean);
      const picker = document.querySelector(`[data-sf-color-picker][data-product-id="${productId}"]`);
      if (!picker) {
        // a colour / size is picked on the product page (its buttons), never in a browser prompt
        if (product.url) window.location.href = product.url;
        throw new Error("اختر اللون أو المقاس من صفحة المنتج");
      }
      const selected = picker?.querySelector('[data-sf-color][aria-pressed="true"]');
      if (picker?.querySelector("[data-sf-option-axis]") && !selected) throw new Error("أكمل اختيار صفات المنتج أولاً");
      if (selected && Number(selected.dataset.qty) <= 0 && picker.dataset.reservation !== "1")
        throw new Error("هذا الخيار غير متوفر حالياً؛ اختر خياراً آخر");
      if (!selected) {
        picker.scrollIntoView({ behavior: "smooth", block: "center" });
        picker.classList.add("is-attention");
        setTimeout(() => picker.classList.remove("is-attention"), 1600);
        throw new Error("اختر اللون أو المقاس أولاً");
      }
      const picked = selected.dataset.sfColor;
      color = String(picked || "").trim();
      if (!names.includes(color)) throw new Error("يجب اختيار خيار صحيح");
    }
    // Online orders are always a normal sale; «استبدال» is done by the cashier in the shop.
    return { sale_mode: "normal", color };
  }

  async function addToCart(productId, quantity, options) {
    const res = await fetch(apiUrl("cart/add"), {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({
        product_id: productId,
        quantity: quantity || 1,
        ...(options || {}),
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || data.message || "تعذرت الإضافة إلى السلة");
    }
    updateCartBadge(data.cart?.count || 0);
    return data;
  }

  document.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-sf-add-cart]");
    if (!btn) return;
    event.preventDefault();
    if (btn.disabled) return;
    const productId = parseInt(btn.getAttribute("data-sf-add-cart"), 10);
    const qtyInput =
      btn.closest("form")?.querySelector("[name=quantity]") ||
      document.querySelector(`[form="${btn.closest("form")?.id}"][name=quantity]`) ||
      btn.closest(".sf-detail-info, .lux-pd-info, .sf-product-card, .lux-product-card")?.querySelector("[name=quantity]") ||
      (document.querySelector(`[data-sf-color-picker][data-product-id="${productId}"]`) ? document.querySelector('#sfQuantity, [name=quantity][form="sfAddForm"]') : null);
    const product = await ensureProduct(productId);
    if (product?.option_axes?.length && !document.querySelector(`[data-sf-color-picker][data-product-id="${productId}"]`) && product.url) {
      window.location.assign(product.url);
      return;
    }
    const qty = qtyInput ? parseInt(qtyInput.value, 10) || 1 : 1;
    btn.disabled = true;
    btn.classList.add("is-loading");
    btn.setAttribute("aria-busy", "true");
    try {
      const options = chooseSaleOptions(productId);
      const data = await addToCart(productId, qty, options);
      showToast(data.message || "تمت الإضافة إلى السلة", "ok");
      animateFeedback(btn, [{ transform: "scale(.97)" }, { transform: "scale(1.025)", offset: .55 }, { transform: "scale(1)" }], 300);
    } catch (err) {
      showToast(err.message || "حدث خطأ", "err");
    } finally {
      btn.classList.remove("is-loading");
      btn.removeAttribute("aria-busy");
      const picker = document.querySelector(`[data-sf-color-picker][data-product-id="${productId}"]`);
      const selected = picker?.querySelector('[data-sf-color][aria-pressed="true"]');
      btn.disabled = (!!picker?.querySelector("[data-sf-option-axis]") && !selected) || (!!selected && Number(selected.dataset.qty) <= 0 && picker.dataset.reservation !== "1");
    }
  });

  document.querySelectorAll(".lux-pd-thumb, .sf-thumb[data-full]:not(.lux-pd-thumb)").forEach((thumb) => {
    thumb.addEventListener("click", () => {
      const media = document.getElementById("luxPdMedia");
      const main = document.getElementById("sfMainImage");
      const videoStage = document.getElementById("sfVideoStage");
      const nativeVideo = document.getElementById("sfProductVideo");
      const ytFrame = document.getElementById("sfVideoFrame");
      const kind = thumb.getAttribute("data-media") || "image";
      const src = thumb.getAttribute("data-full");

      document.querySelectorAll(".lux-pd-thumb").forEach((t) => {
        const active = t === thumb;
        t.classList.toggle("is-active", active);
        t.setAttribute("aria-selected", active ? "true" : "false");
      });

      if (kind === "video" && videoStage) {
        if (media) media.setAttribute("data-mode", "video");
        if (main) main.hidden = true;
        videoStage.hidden = false;
        if (ytFrame) {
          const embed = ytFrame.getAttribute("data-src") || "";
          if (embed && ytFrame.getAttribute("src") !== embed) ytFrame.setAttribute("src", embed);
        }
        if (nativeVideo) {
          try { nativeVideo.play(); } catch (_) { /* autoplay may be blocked */ }
        }
        if (window.__luxGalleryPause) window.__luxGalleryPause();
        return;
      }

      if (media) media.setAttribute("data-mode", "image");
      if (videoStage) videoStage.hidden = true;
      if (nativeVideo) {
        try { nativeVideo.pause(); } catch (_) {}
      }
      if (ytFrame) ytFrame.removeAttribute("src");
      if (main) {
        main.hidden = false;
        if (src) main.src = src;
      }
      if (window.__luxGalleryResume) window.__luxGalleryResume();
    });
  });

  (function setupGalleryAutoplay() {
    const gallery = document.querySelector("#luxProductDetail .lux-pd-gallery");
    const imageThumbs = Array.from(
      document.querySelectorAll("#luxProductDetail .lux-pd-thumb[data-media='image'][data-full]")
    );
    if (!gallery || imageThumbs.length < 2) return;

    const INTERVAL_MS = 5000;
    let timer = null;
    let paused = false;

    function activeIndex() {
      const idx = imageThumbs.findIndex((t) => t.classList.contains("is-active"));
      return idx >= 0 ? idx : 0;
    }

    function showIndex(nextIndex) {
      const thumb = imageThumbs[nextIndex];
      if (!thumb) return;
      const main = document.getElementById("sfMainImage");
      const media = document.getElementById("luxPdMedia");
      const videoStage = document.getElementById("sfVideoStage");
      const nativeVideo = document.getElementById("sfProductVideo");
      const ytFrame = document.getElementById("sfVideoFrame");
      const src = thumb.getAttribute("data-full");

      if (media) media.setAttribute("data-mode", "image");
      if (videoStage) videoStage.hidden = true;
      if (nativeVideo) {
        try { nativeVideo.pause(); } catch (_) {}
      }
      if (ytFrame) ytFrame.removeAttribute("src");

      if (main && src) {
        main.hidden = false;
        main.classList.add("is-fading");
        window.setTimeout(() => {
          if (!paused) main.src = src;
          main.classList.remove("is-fading");
        }, 160);
      }
      document.querySelectorAll("#luxProductDetail .lux-pd-thumb").forEach((t) => {
        const active = t === thumb;
        t.classList.toggle("is-active", active);
        t.setAttribute("aria-selected", active ? "true" : "false");
      });
    }

    function tick() {
      if (paused || document.querySelector("[data-sf-option-axis]") || document.querySelector('[data-sf-color-picker] [aria-pressed="true"]')) return;
      const media = document.getElementById("luxPdMedia");
      if (media && media.getAttribute("data-mode") === "video") return;
      const next = (activeIndex() + 1) % imageThumbs.length;
      showIndex(next);
    }

    function start() {
      stop();
      timer = window.setInterval(tick, INTERVAL_MS);
    }

    function stop() {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    }

    window.__luxGalleryPause = function () {
      paused = true;
      stop();
    };

    window.__luxGalleryResume = function () {
      paused = false;
      start();
    };

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        stop();
      } else if (!paused) {
        start();
      }
    });

    start();
  })();

  document.querySelectorAll("[data-sf-color-picker]").forEach((picker) => {
    const buttons = Array.from(picker.querySelectorAll("[data-sf-color]"));
    const axes = Array.from(picker.querySelectorAll("[data-sf-option-axis]"));
    const attrs = new Map(buttons.map((button) => [button, JSON.parse(button.dataset.attributes || "{}") ]));
    const palette = {
      "أسود": "#25252b", "اسود": "#25252b", black: "#25252b", "أبيض": "#ffffff", "ابيض": "#ffffff", white: "#ffffff",
      "أحمر": "#d94358", "احمر": "#d94358", red: "#d94358", "أزرق": "#4078d4", "ازرق": "#4078d4", blue: "#4078d4",
      "أخضر": "#368463", "اخضر": "#368463", green: "#368463", "أصفر": "#f1cd55", "اصفر": "#f1cd55", yellow: "#f1cd55",
      "وردي": "#ec9cbe", "زهري": "#ec9cbe", pink: "#ec9cbe", "بنفسجي": "#9364b9", purple: "#9364b9",
      "برتقالي": "#ef9545", orange: "#ef9545", "بني": "#825943", brown: "#825943", "بيج": "#dcc9a8", beige: "#dcc9a8",
      "رمادي": "#9399a2", gray: "#9399a2", grey: "#9399a2", "فضي": "#c3c7cf", silver: "#c3c7cf",
      "ذهبي": "#d8b552", gold: "#d8b552", "كحلي": "#263b60", navy: "#263b60", "سماوي": "#87c8e9",
      "زيتي": "#788056", "عنابي": "#852d49", "كريمي": "#f2e9d8", "تركوازي": "#43b6b1", "فيروزي": "#43b6b1",
    };
    const swatch = (value) => {
      const normalized = String(value).trim().toLowerCase().replace(/[\u064b-\u065f\u0640]/g, "");
      return /^#[\da-f]{3}([\da-f]{3})?$/i.test(normalized) ? normalized : palette[normalized];
    };
    const axisValue = (axis) => axis.dataset.value || "";
    const syncChoices = () => axes.forEach((axis) => {
      const choices = Array.from(axis.querySelectorAll("[data-sf-option-value]"));
      choices.forEach((choice) => {
        const possible = buttons.filter((button) => attrs.get(button)[axis.dataset.sfOptionAxis] === choice.dataset.sfOptionValue &&
          axes.every((other) => other === axis || !axisValue(other) || attrs.get(button)[other.dataset.sfOptionAxis] === axisValue(other)));
        const unavailable = picker.dataset.reservation !== "1" && !possible.some((button) => Number(button.dataset.qty) > 0);
        choice.disabled = !possible.length;
        choice.classList.toggle("is-unavailable", unavailable);
        choice.setAttribute("aria-checked", String(axisValue(axis) === choice.dataset.sfOptionValue));
        choice.setAttribute("aria-description", !possible.length ? "غير متاح مع الاختيارات الحالية" : (unavailable ? "غير متوفر حالياً" : ""));
        choice.title = `${choice.dataset.sfOptionValue}${unavailable ? " — غير متوفر" : ""}`;
        choice.tabIndex = -1;
      });
      const focused = choices.find((choice) => !choice.disabled && choice.getAttribute("aria-checked") === "true") || choices.find((choice) => !choice.disabled);
      if (focused) focused.tabIndex = 0;
      axis.querySelector("[data-sf-axis-value]").textContent = axisValue(axis) || `اختر ${axis.dataset.sfOptionAxis}`;
      axis.querySelector("[data-sf-axis-clear]").hidden = !axisValue(axis);
    });
    const prices = (matching) => {
      const values = matching.map((button) => Number(button.dataset.price)).filter((value) => Number.isFinite(value) && value > 0);
      if (!values.length) return;
      const min = Math.min(...values), max = Math.max(...values);
      const formatted = min === max ? min.toLocaleString("en-US") : `${min.toLocaleString("en-US")} – ${max.toLocaleString("en-US")}`;
      const updatePrice = (price, text) => {
        if (price.textContent === text) return;
        price.textContent = text;
        animateFeedback(price, [{ opacity: .4, transform: "translateY(5px)" }, { opacity: 1, transform: "translateY(0)" }]);
      };
      document.querySelectorAll(".lux-pd-price, [data-sf-option-price]").forEach((price) => updatePrice(price, `${formatted} ${picker.dataset.currency || "د.ع"}`));
      document.querySelectorAll(".lux-pd-mobile-bar-price strong").forEach((price) => updatePrice(price, formatted));
      document.querySelectorAll(".lux-pd-old-price, .lux-pd-save").forEach((node) => { node.hidden = true; });
    };
    const updateStatus = (text, state) => {
      const status = picker.querySelector("[data-sf-option-status]");
      if (!status) return;
      const changed = status.textContent !== text;
      status.textContent = text;
      status.dataset.state = state;
      if (changed) animateFeedback(status, [{ opacity: .5, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }]);
    };
    const select = (button) => {
      buttons.forEach((option) => option.setAttribute("aria-pressed", String(option === button)));
      const label = picker.querySelector("[data-sf-color-label]");
      if (label) label.textContent = button.dataset.sfColor;
      prices([button]);
      updateStatus(Number(button.dataset.qty) > 0 ? `متوفر ${button.dataset.qty} قطعة` : (picker.dataset.reservation === "1" ? "متاح للطلب" : "غير متوفر حالياً"), Number(button.dataset.qty) > 0 || picker.dataset.reservation === "1" ? "available" : "unavailable");
      const src = button.dataset.image || picker.dataset.baseImage;
      const main = document.getElementById("sfMainImage");
      updateOptionImage(main, src);
      if (main) {
        main.alt = `${picker.dataset.productName} — ${button.dataset.sfColor}`;
      }
      const placeholder = document.getElementById("sfMainPlaceholder");
      if (placeholder) placeholder.hidden = !!src;
      document.getElementById("luxPdMedia")?.setAttribute("data-mode", "image");
      const video = document.getElementById("sfVideoStage");
      if (video) video.hidden = true;
      document.getElementById("sfProductVideo")?.pause();
      document.getElementById("sfVideoFrame")?.removeAttribute("src");
      window.__luxGalleryPause?.();
      document.querySelectorAll(".lux-pd-thumb").forEach((thumb) => {
        const active = thumb.dataset.full === src;
        thumb.classList.toggle("is-active", active);
        thumb.setAttribute("aria-selected", String(active));
      });
      const unavailable = Number(button.dataset.qty) <= 0 && picker.dataset.reservation !== "1";
      document.querySelectorAll(".lux-pd-stock-text").forEach((node) => { node.textContent = unavailable ? "غير متوفر حالياً" : (Number(button.dataset.qty) > 0 ? `متوفر ${button.dataset.qty} قطعة` : "متاح للطلب"); });
      document.querySelectorAll(".lux-pd-stock-low, .lux-pd-stock-qty").forEach((node) => { node.hidden = true; });
      document.querySelectorAll(".lux-pd-stock-dot").forEach((node) => { node.classList.toggle("in", !unavailable); node.classList.toggle("out", unavailable); });
      document.querySelectorAll(`[data-sf-add-cart="${picker.dataset.productId}"]`).forEach((add) => { add.disabled = unavailable; });
      const quantity = document.querySelector('#sfQuantity, [name=quantity][form="sfAddForm"]');
      if (quantity) {
        quantity.max = picker.dataset.reservation === "1" ? "9999" : String(Math.max(1, Number(button.dataset.qty)));
        quantity.value = String(Math.min(Math.max(1, Number(quantity.value) || 1), Number(quantity.max)));
      }
    };
    const refresh = () => {
      const matching = buttons.filter((button) => axes.every((axis) => !axisValue(axis) || attrs.get(button)[axis.dataset.sfOptionAxis] === axisValue(axis)));
      buttons.forEach((button) => { button.hidden = !matching.includes(button); button.setAttribute("aria-pressed", "false"); });
      prices(matching);
      if (matching.length === 1 && axes.some((axis) => axisValue(axis))) {
        axes.forEach((axis) => { if (!axisValue(axis)) axis.dataset.value = attrs.get(matching[0])[axis.dataset.sfOptionAxis] || ""; });
        select(matching[0]);
      } else {
        document.querySelectorAll(".lux-pd-stock-text").forEach((node) => { node.textContent = "حدد الخيار لعرض التوفّر"; });
        document.querySelectorAll(".lux-pd-stock-low, .lux-pd-stock-qty").forEach((node) => { node.hidden = true; });
        updateStatus(matching.length ? "أكمل اختيار الصفات لتحديد السعر والتوفّر النهائي" : "هذه التركيبة غير متوفرة", matching.length ? "pending" : "unavailable");
        document.querySelectorAll(`[data-sf-add-cart="${picker.dataset.productId}"]`).forEach((add) => { add.disabled = true; });
        const label = picker.querySelector("[data-sf-color-label]"); if (label) label.textContent = "";
        const main = document.getElementById("sfMainImage");
        const src = matching.find((button) => button.dataset.image)?.dataset.image || picker.dataset.baseImage;
        updateOptionImage(main, src);
      }
      syncChoices();
    };
    axes.forEach((axis) => {
      const values = [...new Set(buttons.map((button) => attrs.get(button)[axis.dataset.sfOptionAxis]).filter(Boolean))];
      const group = axis.querySelector("[role=radiogroup]");
      const isColor = /^(اللون|لون|color|colour)$/i.test(axis.dataset.sfOptionAxis.trim());
      values.forEach((value, index) => {
        const choice = document.createElement("button"), disc = document.createElement("span");
        choice.type = "button";
        choice.className = `sf-option-choice${isColor ? " is-color" : (value.length > 3 ? " is-long" : "")}`;
        choice.dataset.sfOptionValue = value;
        choice.style.setProperty("--sf-choice-index", Math.min(index, 5));
        choice.setAttribute("role", "radio");
        choice.setAttribute("aria-label", value);
        choice.setAttribute("aria-checked", "false");
        disc.className = "sf-option-disc";
        disc.setAttribute("aria-hidden", "true");
        if (isColor) {
          const fill = swatch(value);
          if (fill) choice.style.setProperty("--sf-swatch", fill);
          else disc.textContent = value.slice(0, 1);
        } else disc.textContent = value;
        choice.appendChild(disc);
        if (isColor) {
          const label = document.createElement("span"); label.textContent = value; choice.appendChild(label);
        }
        choice.addEventListener("click", () => {
          axis.dataset.value = value;
          refresh();
          animateFeedback(disc, [{ transform: "scale(.9)" }, { transform: "scale(1.09)", offset: .55 }, { transform: "scale(1)" }], 300);
        });
        choice.addEventListener("keydown", (event) => {
          if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const eligible = Array.from(group.querySelectorAll("button:not(:disabled)"));
          const index = eligible.indexOf(choice);
          const rtl = getComputedStyle(group).direction === "rtl";
          const forward = event.key === "ArrowDown" || event.key === (rtl ? "ArrowLeft" : "ArrowRight");
          const target = event.key === "Home" ? eligible[0] : event.key === "End" ? eligible[eligible.length - 1] : eligible[(index + (forward ? 1 : -1) + eligible.length) % eligible.length];
          if (target) { target.click(); target.focus(); }
        });
        group.appendChild(choice);
      });
      const clear = document.createElement("button");
      clear.type = "button"; clear.className = "sf-option-clear"; clear.dataset.sfAxisClear = "";
      clear.textContent = "مسح"; clear.setAttribute("aria-label", `مسح اختيار ${axis.dataset.sfOptionAxis}`);
      clear.addEventListener("click", () => { axis.dataset.value = ""; refresh(); });
      axis.querySelector(".sf-option-heading").appendChild(clear);
    });
    buttons.forEach((button) => button.addEventListener("click", () => {
      axes.forEach((axis) => { axis.dataset.value = attrs.get(button)[axis.dataset.sfOptionAxis] || ""; });
      if (axes.length) refresh();
      select(button);
      if (!axes.length) animateFeedback(button.querySelector(".sf-option-disc"), [{ transform: "scale(.9)" }, { transform: "scale(1.09)", offset: .55 }, { transform: "scale(1)" }], 300);
    }));
    if (axes.length) refresh();
    else {
      buttons.forEach((button) => {
        button.classList.add("sf-legacy-swatch");
        button.classList.toggle("is-unavailable", Number(button.dataset.qty) <= 0 && picker.dataset.reservation !== "1");
        const disc = document.createElement("span"); disc.className = "sf-option-disc"; disc.setAttribute("aria-hidden", "true");
        const fill = swatch(button.dataset.sfColor);
        if (fill) button.style.setProperty("--sf-swatch", fill); else disc.textContent = button.dataset.sfColor.slice(0, 1);
        button.querySelector("img, .sf-color-no-photo")?.replaceWith(disc);
      });
      const first = buttons.find((button) => Number(button.dataset.qty) > 0) || buttons[0];
      if (first) select(first);
    }
  });

  const mobileBar = document.getElementById("luxPdMobileBar");
  const buyBlock = document.getElementById("luxPdBuy");
  if (mobileBar && buyBlock && "IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries.some((e) => e.isIntersecting);
        mobileBar.classList.toggle("is-visible", !visible);
      },
      { threshold: 0.15 }
    );
    io.observe(buyBlock);
  }

  const couponForm = document.getElementById("sfCouponForm");
  if (couponForm) {
    couponForm.addEventListener("submit", async (event) => {
      if (!cfg.useAjaxCoupon) return;
      event.preventDefault();
      const action = event.submitter?.value || "apply";
      const codeInput = couponForm.querySelector("[name=coupon_code]");
      const body = action === "remove" ? { action: "remove" } : { action: "apply", coupon_code: codeInput?.value || "" };
      const res = await fetch(apiUrl("coupon"), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      showToast(data.message || (data.success ? "تم" : "فشل"), data.success ? "ok" : "err");
      if (data.success) window.location.reload();
    });
  }
})();
