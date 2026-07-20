(function () {
  "use strict";

  var dataEl = document.getElementById("sfProductsData");
  var tpl = document.getElementById("sfLuxuryCardTpl");
  var skeleton = document.getElementById("luxSkeleton");
  var emptyEl = document.getElementById("luxEmpty");
  var errorEl = document.getElementById("luxError");
  var searchInput = document.getElementById("luxSearch");
  var categorySelect = document.getElementById("luxCategory");
  var sortSelect = document.getElementById("luxSort");
  var minPriceInput = document.getElementById("luxMinPrice");
  var maxPriceInput = document.getElementById("luxMaxPrice");
  var filterToggle = document.getElementById("luxFilterToggle");
  var pricePanel = document.getElementById("luxPricePanel");

  function getGrids() {
    return Array.prototype.slice.call(document.querySelectorAll(".lux-section-grid"));
  }

  var grid = getGrids()[0] || null;

  var allProducts = [];
  var debounceTimer = null;

  function formatPrice(value) {
    var n = Number(value) || 0;
    if (n <= 0) return "";
    return new Intl.NumberFormat("ar-IQ").format(n) + " د.ع";
  }

  function parseProducts() {
    if (!dataEl) return [];
    try {
      var parsed = JSON.parse(dataEl.textContent || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      return null;
    }
  }

  function showState(which) {
    if (skeleton) skeleton.hidden = which !== "skeleton";
    if (which === "none" && skeleton) skeleton.hidden = true;
    if (emptyEl) emptyEl.hidden = which !== "empty";
    if (errorEl) errorEl.hidden = which !== "error";
    getGrids().forEach(function (g) { g.hidden = which === "error"; });
  }

  function hasSsrCards() {
    return getGrids().some(function (g) {
      return !!g.querySelector(".lux-product-card[data-product-id]");
    });
  }

  function productsFromDom() {
    var seen = {};
    var items = [];
    getGrids().forEach(function (g) {
      Array.prototype.slice.call(g.querySelectorAll(".lux-product-card[data-product-id]")).forEach(function (card) {
        var id = Number(card.getAttribute("data-product-id")) || 0;
        if (!id || seen[id]) return;
        seen[id] = true;
        var titleEl = card.querySelector(".lux-product-title");
        items.push({
          id: id,
          category: card.getAttribute("data-lux-category") || "",
          badge: card.getAttribute("data-lux-category") || "",
          price: Number(card.getAttribute("data-lux-price")) || 0,
          name: titleEl ? titleEl.textContent.trim() : "",
          brand: "",
          model: "",
          sku: "",
        });
      });
    });
    return items;
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function buildBadges(p) {
    var parts = [];
    if (p.discount_percent) parts.push('<span class="lux-badge lux-badge-sale">-' + escapeHtml(p.discount_percent) + '%</span>');
    if (p.is_new) parts.push('<span class="lux-badge lux-badge-new">جديد</span>');
    if (p.is_available === false) parts.push('<span class="lux-badge lux-badge-out">غير متوفر</span>');
    return parts.join("");
  }

  function buildMetaLine(p) {
    var parts = [];
    if (p.brand) parts.push('<span class="lux-product-brand">' + escapeHtml(p.brand) + "</span>");
    if (p.brand && p.model) parts.push('<span aria-hidden="true">-</span>');
    if (p.model) parts.push('<span class="lux-product-model">' + escapeHtml(p.model) + "</span>");
    if (!parts.length && p.short_specs) parts.push(escapeHtml(p.short_specs));
    if (!parts.length && p.badge) parts.push(escapeHtml(p.badge));
    if (!parts.length) return "";
    return '<p class="lux-product-meta-line">' + parts.join("") + "</p>";
  }

  function buildPriceBlock(p) {
    if (!p.price || p.price <= 0) {
      return '<span class="lux-price-muted">السعر غير متوفر</span>';
    }
    var html = '<span class="lux-price">' + escapeHtml(formatPrice(p.price)) + "</span>";
    if (p.old_price && p.old_price > p.price) {
      html += '<span class="lux-old-price">' + escapeHtml(formatPrice(p.old_price)) + "</span>";
    }
    return html;
  }

  function renderCard(p) {
    if (!tpl) return "";
    var dev = window.STOREFRONT_CONFIG && window.STOREFRONT_CONFIG.dev ? "?dev=1" : "";
    var url = String(p.url || "#") + dev;
    var firstLetter = String(p.name || "؟").charAt(0);
    var imageBlock = p.image_url
      ? '<img src="' + escapeHtml(p.image_url) + '" alt="' + escapeHtml(p.name) + '" loading="lazy">'
      : '<span class="lux-media-placeholder">' + escapeHtml(firstLetter) + "</span>";
    var category = String(p.category || p.badge || "");
    var price = String(Number(p.price) || 0);
    return tpl.innerHTML
      .replace(/\{\{ID\}\}/g, String(p.id))
      .replace(/\{\{CATEGORY\}\}/g, escapeHtml(category))
      .replace(/\{\{PRICE\}\}/g, price)
      .replace(/\{\{URL\}\}/g, escapeHtml(url))
      .replace(/\{\{NAME\}\}/g, escapeHtml(p.name))
      .replace(/\{\{IMAGE_BLOCK\}\}/g, imageBlock)
      .replace(/\{\{BADGES\}\}/g, buildBadges(p))
      .replace(/\{\{META_LINE\}\}/g, buildMetaLine(p))
      .replace(/\{\{PRICE_BLOCK\}\}/g, buildPriceBlock(p))
      .replace(/\{\{DISABLED\}\}/g, p.is_available === false ? "disabled" : "");
  }

  function getFilters() {
    return {
      q: (searchInput && searchInput.value ? searchInput.value : "").trim().toLowerCase(),
      category: categorySelect ? categorySelect.value : "",
      min: minPriceInput && minPriceInput.value !== "" ? Number(minPriceInput.value) : null,
      max: maxPriceInput && maxPriceInput.value !== "" ? Number(maxPriceInput.value) : null,
      sort: sortSelect ? sortSelect.value : "latest",
    };
  }

  function filterProducts(list, filters) {
    return list.filter(function (p) {
      if (filters.category) {
        var cat = String(p.category || p.badge || "");
        if (cat !== filters.category) return false;
      }
      if (filters.q) {
        var hay = (String(p.name || "") + " " + String(p.brand || "") + " " + String(p.model || "") + " " + String(p.sku || "")).toLowerCase();
        if (hay.indexOf(filters.q) === -1) return false;
      }
      var price = Number(p.price) || 0;
      if (filters.min !== null && !Number.isNaN(filters.min) && price < filters.min) return false;
      if (filters.max !== null && !Number.isNaN(filters.max) && filters.max > 0 && price > filters.max) return false;
      return true;
    });
  }

  function sortProducts(list, sortKey) {
    var items = list.slice();
    if (sortKey === "price_asc") {
      items.sort(function (a, b) { return (Number(a.price) || 0) - (Number(b.price) || 0); });
    } else if (sortKey === "price_desc") {
      items.sort(function (a, b) { return (Number(b.price) || 0) - (Number(a.price) || 0); });
    } else if (sortKey === "name_asc") {
      items.sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || ""), "ar"); });
    } else if (sortKey === "best_selling") {
      // No sales metric on storefront cards yet; fall back to latest ordering.
      items.sort(function (a, b) { return (Number(b.id) || 0) - (Number(a.id) || 0); });
    } else {
      items.sort(function (a, b) { return (Number(b.id) || 0) - (Number(a.id) || 0); });
    }
    return items;
  }

  function updateSectionCounts(visibleIds) {
    document.querySelectorAll("[data-section-count]").forEach(function (el) {
      var sid = el.getAttribute("data-section-count");
      var sectionGrid = document.getElementById("luxGrid-" + sid);
      if (!sectionGrid) return;
      var count = Array.prototype.slice.call(sectionGrid.querySelectorAll(".lux-product-card[data-product-id]"))
        .filter(function (card) { return !card.hidden; }).length;
      el.textContent = count + " منتج";
      var section = document.getElementById("luxSection-" + sid);
      if (section) section.hidden = count === 0;
    });
  }

  function applyFiltersToDom(sortedList) {
    var grids = getGrids();
    if (!grids.length) return;
    var visibleIds = {};
    sortedList.forEach(function (p) { visibleIds[String(p.id)] = true; });
    grids.forEach(function (g) {
      var cards = Array.prototype.slice.call(g.querySelectorAll(".lux-product-card[data-product-id]"));
      var byId = {};
      cards.forEach(function (card) {
        var id = card.getAttribute("data-product-id");
        byId[id] = card;
        card.hidden = !visibleIds[id];
      });
      sortedList.forEach(function (p) {
        var card = byId[String(p.id)];
        if (card && !card.hidden) g.appendChild(card);
      });
    });
    updateSectionCounts(visibleIds);
    if (!sortedList.length) showState("empty");
    else showState("none");
  }

  function renderGrid(list) {
    var grids = getGrids();
    if (!grids.length) return;
    if (!list.length) {
      showState("empty");
      grids.forEach(function (g) { g.innerHTML = ""; });
      updateSectionCounts({});
      return;
    }
    showState("none");
    grids[0].innerHTML = list.map(renderCard).join("");
    for (var i = 1; i < grids.length; i++) grids[i].innerHTML = "";
    updateSectionCounts({});
  }

  function applyFilters() {
    var filters = getFilters();
    var filtered = filterProducts(allProducts, filters);
    var sorted = sortProducts(filtered, filters.sort);
    if (hasSsrCards()) applyFiltersToDom(sorted);
    else renderGrid(sorted);
  }

  function debouncedApply() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(applyFilters, 300);
  }

  function initFilters() {
    if (searchInput) searchInput.addEventListener("input", debouncedApply);
    [categorySelect, sortSelect, minPriceInput, maxPriceInput].forEach(function (el) {
      if (el) el.addEventListener("change", applyFilters);
      if (el && el !== categorySelect && el !== sortSelect) el.addEventListener("input", debouncedApply);
    });
    if (filterToggle && pricePanel) {
      filterToggle.addEventListener("click", function () {
        var open = pricePanel.hasAttribute("hidden");
        if (open) pricePanel.removeAttribute("hidden");
        else pricePanel.setAttribute("hidden", "");
        filterToggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }
    document.querySelectorAll(".lux-nav-badge[data-lux-category]").forEach(function (link) {
      link.addEventListener("click", function () {
        var cat = link.getAttribute("data-lux-category") || "";
        if (categorySelect) categorySelect.value = cat;
        applyFilters();
      });
    });
  }

  function initViewToggle() {
    document.querySelectorAll(".lux-view-btn[data-lux-view]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var view = btn.getAttribute("data-lux-view") || "grid";
        document.querySelectorAll(".lux-view-btn").forEach(function (b) {
          var active = b === btn;
          b.classList.toggle("is-active", active);
          b.setAttribute("aria-pressed", active ? "true" : "false");
        });
        if (grid) grid.setAttribute("data-view", view);
        getGrids().forEach(function (g) { g.setAttribute("data-view", view); });
      });
    });
  }

  function initCartPage() {
    var page = document.getElementById("luxCartPage");
    if (!page) return;

    var cfg = window.STOREFRONT_CONFIG || {};
    var slug = cfg.tenantSlug || "";
    var devQ = cfg.dev ? "?dev=1" : "";
    var updateTimers = {};

    function apiUrl(path) {
      return "/shop/" + encodeURIComponent(slug) + "/api/" + path + devQ;
    }

    function formatMoney(n) {
      return new Intl.NumberFormat("ar-IQ").format(Number(n) || 0) + " د.ع";
    }

    function showToast(message, type) {
      var wrap = document.getElementById("sfToastWrap");
      if (!wrap) return;
      var el = document.createElement("div");
      el.className = "sf-toast " + (type || "ok");
      el.textContent = message;
      wrap.appendChild(el);
      setTimeout(function () { el.remove(); }, 3200);
    }

    function updateCartBadge(count) {
      document.querySelectorAll("[data-sf-cart-count]").forEach(function (node) {
        node.textContent = String(count || 0);
      });
    }

    function updateSummary(cart) {
      if (!cart) return;
      var subtotalEl = document.getElementById("luxCartSubtotal");
      var discountEl = document.getElementById("luxCartDiscount");
      var netEl = document.getElementById("luxCartNet");
      if (subtotalEl) subtotalEl.textContent = formatMoney(cart.subtotal);
      if (discountEl) {
        discountEl.textContent = (cart.discount_amount || 0) > 0
          ? "-" + formatMoney(cart.discount_amount).replace(" د.ع", "") + " د.ع"
          : formatMoney(0);
      }
      if (netEl) netEl.textContent = formatMoney(cart.net_subtotal);
      updateCartBadge(cart.count);
    }

    function findCartItem(cart, productId) {
      if (!cart || !cart.items) return null;
      for (var i = 0; i < cart.items.length; i++) {
        if (Number(cart.items[i].id) === Number(productId)) return cart.items[i];
      }
      return null;
    }

    function updateLineTotal(row, cartItem) {
      var totalEl = row.querySelector("[data-lux-line-total]");
      if (totalEl && cartItem) {
        totalEl.innerHTML = new Intl.NumberFormat("ar-IQ").format(cartItem.line_total || 0) + " <small>د.ع</small>";
      }
    }

    function syncCart(productId, qty, row) {
      if (row) row.classList.add("is-updating");
      return fetch(apiUrl("cart/update"), {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({ product_id: productId, quantity: qty }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { res: res, data: data };
          });
        })
        .then(function (result) {
          if (!result.res.ok || !result.data.success) {
            throw new Error(result.data.error || result.data.message || "تعذر تحديث السلة");
          }
          var cart = result.data.cart;
          updateSummary(cart);
          if (row) {
            if (qty <= 0) {
              row.remove();
              if (!page.querySelector("[data-lux-cart-item]")) window.location.reload();
            } else {
              updateLineTotal(row, findCartItem(cart, productId));
            }
          }
          return cart;
        })
        .catch(function (err) {
          showToast(err.message || "حدث خطأ", "err");
        })
        .finally(function () {
          if (row) row.classList.remove("is-updating");
        });
    }

    function scheduleSync(row, productId) {
      var input = row.querySelector(".lux-cart-qty-input");
      if (!input) return;
      clearTimeout(updateTimers[productId]);
      updateTimers[productId] = setTimeout(function () {
        var qty = parseInt(input.value, 10) || 0;
        var max = parseInt(input.getAttribute("max"), 10) || 999;
        qty = Math.min(max, Math.max(1, qty));
        input.value = String(qty);
        syncCart(productId, qty, row);
      }, 450);
    }

    page.querySelectorAll("[data-lux-cart-item]").forEach(function (row) {
      var productId = parseInt(row.getAttribute("data-product-id"), 10);
      var input = row.querySelector(".lux-cart-qty-input");
      var minusBtn = row.querySelector("[data-lux-cart-qty-minus]");
      var plusBtn = row.querySelector("[data-lux-cart-qty-plus]");
      var removeBtn = row.querySelector("[data-lux-cart-remove]");

      function bounds() {
        var max = input ? parseInt(input.getAttribute("max"), 10) : 999;
        if (!max || max < 1) max = 999;
        return { min: 1, max: max };
      }

      function setQty(next) {
        if (!input) return;
        var b = bounds();
        var value = Math.min(b.max, Math.max(b.min, next));
        input.value = String(value);
        scheduleSync(row, productId);
      }

      if (minusBtn) {
        minusBtn.addEventListener("click", function () {
          setQty((parseInt(input.value, 10) || 1) - 1);
        });
      }
      if (plusBtn) {
        plusBtn.addEventListener("click", function () {
          setQty((parseInt(input.value, 10) || 1) + 1);
        });
      }
      if (input) {
        input.addEventListener("change", function () {
          setQty(parseInt(input.value, 10) || 1);
        });
      }
      if (removeBtn) {
        removeBtn.addEventListener("click", function () {
          syncCart(productId, 0, row);
        });
      }
    });
  }

  function initProductDetail() {
    var detail = document.getElementById("luxProductDetail");
    if (!detail) return;

    var qtyInput = document.getElementById("sfQuantity");
    var minusBtn = detail.querySelector("[data-lux-qty-minus]");
    var plusBtn = detail.querySelector("[data-lux-qty-plus]");

    function qtyBounds() {
      var min = 1;
      var max = qtyInput ? parseInt(qtyInput.getAttribute("max"), 10) : 999;
      if (!max || max < 1) max = 999;
      return { min: min, max: max };
    }

    function setQty(next) {
      if (!qtyInput) return;
      var bounds = qtyBounds();
      var value = parseInt(qtyInput.value, 10) || bounds.min;
      value = Math.min(bounds.max, Math.max(bounds.min, next !== undefined ? next : value));
      qtyInput.value = String(value);
    }

    if (minusBtn) {
      minusBtn.addEventListener("click", function () {
        setQty((parseInt(qtyInput.value, 10) || 1) - 1);
      });
    }
    if (plusBtn) {
      plusBtn.addEventListener("click", function () {
        setQty((parseInt(qtyInput.value, 10) || 1) + 1);
      });
    }
    if (qtyInput) {
      qtyInput.addEventListener("change", function () { setQty(); });
      qtyInput.addEventListener("blur", function () { setQty(); });
    }

    var media = document.getElementById("luxPdMedia");
    if (media && media.querySelector(".lux-pd-main-img")) {
      media.addEventListener("click", function () {
        var zoomed = media.classList.toggle("is-zoomed");
        document.body.style.overflow = zoomed ? "hidden" : "";
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && media.classList.contains("is-zoomed")) {
          media.classList.remove("is-zoomed");
          document.body.style.overflow = "";
        }
      });
    }
  }

  var HERO_AUTO_MS = 5000;

  function initHeroCarousel() {
    var hero = document.getElementById("luxHero");
    if (!hero) return;
    var slider = document.getElementById("luxHeroSlider");
    var slides = hero.querySelectorAll(".lux-hero-slide");
    if (!slider || slides.length <= 1) return;
    var dotsWrap = document.getElementById("luxHeroDots");
    var prev = hero.querySelector(".lux-hero-prev");
    var next = hero.querySelector(".lux-hero-next");
    var index = 0;
    var autoTimer = null;
    var animTimer = null;

    function setPosition(i) {
      slider.style.transform = "translate3d(-" + (i * 100) + "%, 0, 0)";
    }

    function playEnterAnimation() {
      slides.forEach(function (slide) { slide.classList.remove("is-entering"); });
      var active = slides[index];
      if (!active) return;
      if (animTimer) clearTimeout(animTimer);
      active.classList.add("is-entering");
      animTimer = setTimeout(function () {
        active.classList.remove("is-entering");
      }, 700);
    }

    function go(to) {
      var nextIndex = (to + slides.length) % slides.length;
      if (nextIndex === index) return;
      index = nextIndex;
      setPosition(index);
      playEnterAnimation();
      if (dotsWrap) {
        dotsWrap.querySelectorAll(".lux-hero-dot").forEach(function (dot, i) {
          dot.classList.toggle("is-active", i === index);
        });
      }
    }

    function stopAuto() {
      if (autoTimer) {
        clearInterval(autoTimer);
        autoTimer = null;
      }
    }

    function startAuto() {
      stopAuto();
      autoTimer = setInterval(function () { go(index + 1); }, HERO_AUTO_MS);
    }

    setPosition(0);
    playEnterAnimation();

    if (dotsWrap) {
      dotsWrap.innerHTML = "";
      slides.forEach(function (_, i) {
        var dot = document.createElement("button");
        dot.type = "button";
        dot.className = "lux-hero-dot" + (i === 0 ? " is-active" : "");
        dot.setAttribute("aria-label", "الشريحة " + (i + 1));
        dot.addEventListener("click", function () { go(i); startAuto(); });
        dotsWrap.appendChild(dot);
      });
    }

    if (prev) prev.addEventListener("click", function () { go(index - 1); startAuto(); });
    if (next) next.addEventListener("click", function () { go(index + 1); startAuto(); });

    hero.addEventListener("mouseenter", stopAuto);
    hero.addEventListener("mouseleave", startAuto);
    hero.addEventListener("touchstart", stopAuto, { passive: true });
    hero.addEventListener("touchend", function () {
      setTimeout(startAuto, HERO_AUTO_MS);
    }, { passive: true });

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stopAuto();
      else startAuto();
    });

    startAuto();
  }

  function boot() {
    initProductDetail();
    initCartPage();
    var parsed = parseProducts();
    var ssr = hasSsrCards();
    if (parsed === null) {
      if (!ssr) {
        showState("error");
        initHeroCarousel();
        return;
      }
      allProducts = productsFromDom();
    } else {
      allProducts = parsed;
    }
    showState("none");
    applyFilters();
    initFilters();
    initViewToggle();
    initHeroCarousel();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
