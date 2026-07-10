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

  document.querySelectorAll(".sf-thumb[data-full], .lux-pd-thumb[data-full]").forEach((thumb) => {
    thumb.addEventListener("click", () => {
      const main = document.getElementById("sfMainImage");
      const src = thumb.getAttribute("data-full");
      if (main && src) main.src = src;
      document.querySelectorAll(".lux-pd-thumb").forEach((t) => {
        const active = t === thumb;
        t.classList.toggle("is-active", active);
        t.setAttribute("aria-selected", active ? "true" : "false");
      });
    });
  });

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
