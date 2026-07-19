(function () {
  const cfg = window.STOREFRONT_CONFIG || {};
  const slug = cfg.tenantSlug || "";
  const devQ = cfg.dev ? "?dev=1" : "";

  function apiUrl(path) {
    return `/shop/${encodeURIComponent(slug)}/api/${path}${devQ}`;
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
    });
  }

  async function addToCart(productId, quantity) {
    const res = await fetch(apiUrl("cart/add"), {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ product_id: productId, quantity: quantity || 1 }),
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
      btn.closest(".sf-detail-info, .lux-pd-info, .sf-product-card, .lux-product-card")?.querySelector("[name=quantity]");
    const qty = qtyInput ? parseInt(qtyInput.value, 10) || 1 : 1;
    btn.disabled = true;
    try {
      const data = await addToCart(productId, qty);
      showToast(data.message || "تمت الإضافة إلى السلة", "ok");
    } catch (err) {
      showToast(err.message || "حدث خطأ", "err");
    } finally {
      btn.disabled = false;
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
          main.src = src;
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
      if (paused) return;
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
