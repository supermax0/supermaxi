(function () {
  "use strict";

  const ORBIT_COLORS = {
    blacklist: "#ef4444",
    vip: "#f59e0b",
    unpaid: "#fb923c",
    active: "#34d399",
    dormant: "#94a3b8",
  };

  const canvas = document.getElementById("brainCanvas");
  if (!canvas) return;

  const loadingEl = document.getElementById("brainLoading");
  const emptyEl = document.getElementById("brainEmpty");
  const hubStats = document.getElementById("brainHubStats");
  const legendEl = document.getElementById("brainLegend");
  const footerNote = document.getElementById("brainFooterNote");
  const stageEl = document.querySelector(".brain-stage");
  const panelEl = document.getElementById("brainPanel");
  const panelBody = document.getElementById("brainPanelBody");
  const searchInput = document.getElementById("brainSearch");
  const orbitFilter = document.getElementById("brainOrbitFilter");
  const tenantFilter = document.getElementById("brainTenantFilter");
  const refreshBtn = document.getElementById("brainRefresh");

  let raw = { orbits: [], planets: [], totals: {}, errors: [] };
  let nodes = [];
  let filtered = [];
  let selectedId = null;
  let width = 1;
  let height = 1;
  let worldRadius = 110;
  let animationId = 0;

  let renderer = null;
  let scene = null;
  let camera = null;
  let galaxy = null;
  let orbitGroup = null;
  let planetGroup = null;
  let raycaster = null;
  let pointer = null;
  let selectedHalo = null;
  let clock = null;

  const meshes = new Map();
  const materialCache = new Map();
  const geometryCache = new Map();
  const mouse = {
    down: false,
    x: 0,
    y: 0,
    moved: 0,
    targetRotX: -0.24,
    targetRotY: 0.18,
    zoom: 390,
  };

  function hasThree() {
    return typeof window.THREE !== "undefined";
  }

  function initThree() {
    if (!hasThree() || renderer) return;

    const THREE = window.THREE;
    scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x07111f, 0.0028);

    camera = new THREE.PerspectiveCamera(42, 1, 0.1, 1600);
    camera.position.set(0, 50, mouse.zoom);

    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.18;

    raycaster = new THREE.Raycaster();
    pointer = new THREE.Vector2();
    clock = new THREE.Clock();

    galaxy = new THREE.Group();
    orbitGroup = new THREE.Group();
    planetGroup = new THREE.Group();
    galaxy.add(orbitGroup, planetGroup);
    scene.add(galaxy);

    buildLighting();
    buildStarField();
    buildCentralCore();
    resize();
    animationId = requestAnimationFrame(frame);
  }

  function buildLighting() {
    const THREE = window.THREE;
    scene.add(new THREE.AmbientLight(0x9fb8ff, 0.58));

    const key = new THREE.DirectionalLight(0xffffff, 1.8);
    key.position.set(-120, 180, 160);
    scene.add(key);

    const rim = new THREE.PointLight(0x38bdf8, 2.7, 440);
    rim.position.set(160, -80, 130);
    scene.add(rim);

    const warm = new THREE.PointLight(0xf59e0b, 1.35, 360);
    warm.position.set(-170, 60, -100);
    scene.add(warm);
  }

  function buildStarField() {
    const THREE = window.THREE;
    const count = 1300;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const color = new THREE.Color();

    for (let i = 0; i < count; i++) {
      const radius = 260 + seeded(i, 1) * 520;
      const theta = seeded(i, 2) * Math.PI * 2;
      const phi = Math.acos(2 * seeded(i, 3) - 1);
      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.cos(phi) * 0.58;
      positions[i * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);

      color.setHSL(0.58 + seeded(i, 4) * 0.14, 0.55, 0.65 + seeded(i, 5) * 0.3);
      colors[i * 3] = color.r;
      colors[i * 3 + 1] = color.g;
      colors[i * 3 + 2] = color.b;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const mat = new THREE.PointsMaterial({
      size: 1.15,
      vertexColors: true,
      transparent: true,
      opacity: 0.82,
      depthWrite: false,
    });
    const stars = new THREE.Points(geo, mat);
    stars.name = "brain-stars";
    scene.add(stars);
  }

  function buildCentralCore() {
    const THREE = window.THREE;
    const core = new THREE.Group();
    core.name = "brain-core";

    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(16, 48, 48),
      new THREE.MeshStandardMaterial({
        color: 0x3b82f6,
        emissive: 0x1d4ed8,
        emissiveIntensity: 0.55,
        metalness: 0.25,
        roughness: 0.2,
      })
    );
    core.add(sphere);

    const shell = new THREE.Mesh(
      new THREE.SphereGeometry(20.5, 48, 48),
      new THREE.MeshBasicMaterial({
        color: 0x60a5fa,
        transparent: true,
        opacity: 0.12,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    core.add(shell);

    const ringMat = new THREE.MeshBasicMaterial({
      color: 0x93c5fd,
      transparent: true,
      opacity: 0.32,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    for (let i = 0; i < 3; i++) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(28 + i * 8, 0.35, 8, 160), ringMat);
      ring.rotation.x = Math.PI / 2 + i * 0.34;
      ring.rotation.y = i * 0.7;
      core.add(ring);
    }

    galaxy.add(core);
  }

  function formatMoney(n) {
    const v = Number(n) || 0;
    return v.toLocaleString("en-IQ") + " د.ع";
  }

  function planetSize(sales) {
    const v = Math.max(0, Number(sales) || 0);
    return 1.35 + Math.min(4.2, Math.log10(v + 10) * 0.92);
  }

  function orbitRadius(orbitKey, orbits) {
    const list = orbits && orbits.length ? orbits : raw.orbits;
    const found = list.find((o) => o.key === orbitKey);
    const r = found ? Number(found.radius) || 3 : 3;
    return worldRadius * (0.28 + r * 0.14);
  }

  function setLoading(on) {
    if (loadingEl) loadingEl.hidden = !on;
    if (refreshBtn) refreshBtn.classList.toggle("is-busy", on);
  }

  function buildLegend() {
    if (!legendEl) return;
    legendEl.innerHTML = (raw.orbits || [])
      .map((o) => {
        const count = (raw.totals && raw.totals.by_orbit && raw.totals.by_orbit[o.key]) || 0;
        const color = ORBIT_COLORS[o.key] || "#94a3b8";
        return (
          '<span class="brain-legend-chip">' +
          '<span class="brain-legend-dot" style="background:' +
          color +
          '"></span>' +
          escapeHtml(o.label) +
          " (" +
          count +
          ")</span>"
        );
      })
      .join("");
  }

  function fillFilters() {
    if (orbitFilter) {
      const keep = orbitFilter.value;
      orbitFilter.innerHTML = '<option value="">كل المدارات</option>';
      (raw.orbits || []).forEach((o) => {
        const opt = document.createElement("option");
        opt.value = o.key;
        opt.textContent = o.label;
        orbitFilter.appendChild(opt);
      });
      orbitFilter.value = keep || "";
    }

    if (tenantFilter) {
      const keep = tenantFilter.value;
      const map = new Map();
      (raw.planets || []).forEach((p) => {
        if (p.tenant_slug) map.set(p.tenant_slug, p.tenant_name || p.tenant_slug);
      });
      tenantFilter.innerHTML = '<option value="">كل الشركات</option>';
      Array.from(map.entries())
        .sort((a, b) => String(a[1]).localeCompare(String(b[1]), "ar"))
        .forEach(([slug, name]) => {
          const opt = document.createElement("option");
          opt.value = slug;
          opt.textContent = name;
          tenantFilter.appendChild(opt);
        });
      tenantFilter.value = keep || "";
    }
  }

  function applyFilters() {
    const q = ((searchInput && searchInput.value) || "").trim().toLowerCase();
    const orbit = (orbitFilter && orbitFilter.value) || "";
    const tenant = (tenantFilter && tenantFilter.value) || "";

    filtered = nodes.filter((n) => {
      if (orbit && n.orbit !== orbit) return false;
      if (tenant && n.tenant_slug !== tenant) return false;
      if (q) {
        const hay = ((n.name || "") + " " + (n.phone || "")).toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (emptyEl) emptyEl.hidden = filtered.length > 0 || (loadingEl && !loadingEl.hidden);
    updateHub();
    rebuildGalaxy();
  }

  function updateHub() {
    const t = raw.totals || {};
    const shown = filtered.length;
    const total = t.customers || 0;
    if (hubStats) {
      hubStats.innerHTML =
        shown.toLocaleString("en-IQ") +
        " كوكب ظاهر<br>" +
        (t.companies || 0) +
        " شركة · إجمالي " +
        total.toLocaleString("en-IQ");
    }
  }

  function layoutNodes() {
    const byOrbit = {};
    nodes.forEach((n) => {
      const k = n.orbit || "dormant";
      if (!byOrbit[k]) byOrbit[k] = [];
      byOrbit[k].push(n);
    });

    Object.keys(byOrbit).forEach((key) => {
      const group = byOrbit[key];
      group.forEach((n, i) => {
        const jitter = seeded(hashString(n.id), 7) * 0.18;
        n.angle0 = (i / Math.max(group.length, 1)) * Math.PI * 2 + jitter;
        n.speed = 0.42 + (hashString(n.id) % 54) / 100;
        n.radius = orbitRadius(key);
        n.size = planetSize(n.sales_total);
        n.hue = hashHue(n.tenant_slug || n.name);
        n.orbitColor = ORBIT_COLORS[key] || "#94a3b8";
        n.lane = (hashString(n.phone || n.id) % 100) / 100;
      });
    });
  }

  function rebuildGalaxy() {
    if (!renderer) return;
    clearGroup(orbitGroup);
    clearGroup(planetGroup);
    meshes.clear();
    selectedHalo = null;

    layoutNodes();
    buildOrbitMeshes();
    buildPlanetMeshes();
    window.__brainMeshCount = meshes.size;
  }

  function buildOrbitMeshes() {
    const THREE = window.THREE;
    (raw.orbits || []).forEach((o, index) => {
      const r = orbitRadius(o.key);
      const color = new THREE.Color(ORBIT_COLORS[o.key] || "#94a3b8");
      const points = [];
      const segments = 240;
      for (let i = 0; i <= segments; i++) {
        const a = (i / segments) * Math.PI * 2;
        points.push(new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r));
      }

      const geo = new THREE.BufferGeometry().setFromPoints(points);
      const line = new THREE.Line(
        geo,
        new THREE.LineBasicMaterial({
          color,
          transparent: true,
          opacity: 0.22,
          blending: THREE.AdditiveBlending,
        })
      );
      orbitGroup.add(line);

      const torus = new THREE.Mesh(
        new THREE.TorusGeometry(r, 0.24 + index * 0.02, 8, 220),
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.14,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        })
      );
      orbitGroup.add(torus);
    });
  }

  function buildPlanetMeshes() {
    const THREE = window.THREE;
    filtered.forEach((n) => {
      const color = new THREE.Color(n.orbitColor).lerp(new THREE.Color(0xffffff), 0.14 + n.lane * 0.18);
      const mesh = new THREE.Mesh(getSphereGeometry(n.size), getPlanetMaterial(n.orbit, color));
      mesh.userData.node = n;
      mesh.castShadow = false;
      mesh.receiveShadow = false;

      const glow = new THREE.Mesh(
        getSphereGeometry(n.size * 1.55),
        new THREE.MeshBasicMaterial({
          color: new THREE.Color(n.orbitColor),
          transparent: true,
          opacity: 0.08,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        })
      );
      glow.userData.ignorePick = true;
      mesh.add(glow);

      planetGroup.add(mesh);
      meshes.set(n.id, mesh);
    });
  }

  function getSphereGeometry(size) {
    const bucket = Math.round(size * 2) / 2;
    if (!geometryCache.has(bucket)) {
      geometryCache.set(bucket, new window.THREE.SphereGeometry(bucket, 32, 24));
    }
    return geometryCache.get(bucket);
  }

  function getPlanetMaterial(orbit, color) {
    const key = orbit + ":" + color.getHexString();
    if (materialCache.has(key)) return materialCache.get(key);
    const THREE = window.THREE;
    const orbitColor = new THREE.Color(ORBIT_COLORS[orbit] || "#94a3b8");
    const mat = new THREE.MeshStandardMaterial({
      color,
      emissive: orbitColor,
      emissiveIntensity: 0.16,
      metalness: 0.18,
      roughness: 0.42,
    });
    materialCache.set(key, mat);
    return mat;
  }

  function updatePlanetPositions(elapsed) {
    meshes.forEach((mesh, id) => {
      const n = mesh.userData.node;
      const angle = n.angle0 + elapsed * 0.08 * n.speed;
      const laneOffset = (n.lane - 0.5) * 10;
      const z = Math.sin(angle * 1.7 + n.lane * 4.2) * 4.5 + laneOffset * 0.55;
      mesh.position.set(Math.cos(angle) * n.radius, Math.sin(angle) * n.radius, z);
      mesh.rotation.y += 0.01 + n.speed * 0.002;
      mesh.rotation.x += 0.004;
    });

    if (selectedHalo && selectedId && meshes.has(selectedId)) {
      selectedHalo.position.copy(meshes.get(selectedId).position);
      selectedHalo.rotation.z += 0.018;
      selectedHalo.rotation.x += 0.008;
    }
  }

  function frame() {
    const elapsed = clock ? clock.getElapsedTime() : performance.now() * 0.001;
    if (galaxy) {
      mouse.targetRotX += (clamp(mouse.targetRotX, -0.92, 0.18) - mouse.targetRotX) * 0.08;
      galaxy.rotation.x += (mouse.targetRotX - galaxy.rotation.x) * 0.08;
      galaxy.rotation.z += (mouse.targetRotY - galaxy.rotation.z) * 0.08;
      galaxy.rotation.y += 0.0018;
      updatePlanetPositions(elapsed);
    }
    if (camera) {
      const targetZ = mouse.zoom;
      camera.position.z += (targetZ - camera.position.z) * 0.08;
      camera.lookAt(0, 0, 0);
    }
    renderer.render(scene, camera);
    animationId = requestAnimationFrame(frame);
  }

  function resize() {
    const wrap = canvas.parentElement;
    const rect = wrap.getBoundingClientRect();
    width = Math.max(320, Math.floor(rect.width));
    height = Math.max(420, Math.floor(rect.height || 520));
    worldRadius = Math.min(width, height) * 0.22;

    if (renderer && camera) {
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }
    rebuildGalaxy();
  }

  function pick(e) {
    if (!renderer || !camera || !raycaster) return null;
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(Array.from(meshes.values()), false);
    return hits.length ? hits[0].object.userData.node : null;
  }

  function orbitLabel(key) {
    const o = (raw.orbits || []).find((x) => x.key === key);
    return o ? o.label : key;
  }

  function openPanel(n) {
    selectedId = n.id;
    showSelection(n);
    if (stageEl) stageEl.classList.add("has-panel");
    if (panelEl) panelEl.hidden = false;
    if (!panelBody) return;

    const color = ORBIT_COLORS[n.orbit] || "#94a3b8";
    panelBody.innerHTML =
      '<div class="brain-panel-planet" style="--orbit-color:' +
      color +
      '"><span></span><strong>' +
      escapeHtml(n.name) +
      "</strong></div>" +
      '<dl class="brain-kv">' +
      "<dt>الاسم</dt><dd>" +
      escapeHtml(n.name) +
      "</dd>" +
      "<dt>الهاتف</dt><dd>" +
      escapeHtml(n.phone || "—") +
      "</dd>" +
      "<dt>المدينة</dt><dd>" +
      escapeHtml(n.city || "—") +
      "</dd>" +
      "<dt>الشركة</dt><dd>" +
      escapeHtml(n.tenant_name || n.tenant_slug) +
      "</dd>" +
      '<dt>المدار</dt><dd><span class="brain-orbit-badge"><span class="brain-legend-dot" style="background:' +
      color +
      '"></span>' +
      escapeHtml(orbitLabel(n.orbit)) +
      "</span></dd>" +
      "<dt>الفواتير</dt><dd>" +
      (n.invoice_count || 0) +
      "</dd>" +
      "<dt>المبيعات</dt><dd>" +
      formatMoney(n.sales_total) +
      "</dd>" +
      "<dt>متأخر</dt><dd>" +
      formatMoney(n.unpaid_total) +
      "</dd>" +
      "</dl>" +
      (n.tenant_slug
        ? '<a class="brain-panel-link" href="/superadmin/tenants" data-slug="' +
          escapeAttr(n.tenant_slug) +
          '"><i class="fas fa-building"></i> الشركات المسجلة</a>'
        : "");
  }

  function showSelection(n) {
    const THREE = window.THREE;
    if (selectedHalo) {
      planetGroup.remove(selectedHalo);
      selectedHalo.geometry.dispose();
      selectedHalo.material.dispose();
      selectedHalo = null;
    }
    const mesh = meshes.get(n.id);
    if (!mesh) return;
    selectedHalo = new THREE.Mesh(
      new THREE.TorusGeometry(n.size * 2.25, 0.32, 8, 96),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(n.orbitColor),
        transparent: true,
        opacity: 0.72,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    selectedHalo.position.copy(mesh.position);
      planetGroup.add(selectedHalo);
  }

  function closePanel() {
    selectedId = null;
    if (selectedHalo) {
      planetGroup.remove(selectedHalo);
      selectedHalo.geometry.dispose();
      selectedHalo.material.dispose();
      selectedHalo = null;
    }
    if (stageEl) stageEl.classList.remove("has-panel");
    if (panelEl) panelEl.hidden = true;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  async function loadData() {
    setLoading(true);
    if (emptyEl) emptyEl.hidden = true;
    try {
      const res = await fetch("/superadmin/brain/api", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error((data && data.error) || "فشل التحميل");
      }
      raw = data;
      nodes = (data.planets || []).map((p) => Object.assign({}, p));
      buildLegend();
      fillFilters();
      resize();
      applyFilters();

      const errCount = (data.errors || []).length;
      const notes = [];
      if (data.totals && data.totals.truncated) {
        notes.push(
          "تم عرض أعلى " +
            nodes.length.toLocaleString("en-IQ") +
            " زبوناً نشاطاً من أصل " +
            (data.totals.customers || 0)
        );
      }
      if (errCount) notes.push("تعذر قراءة " + errCount + " شركة");
      if (footerNote) footerNote.textContent = notes.join(" · ");
    } catch (err) {
      if (hubStats) hubStats.textContent = "تعذر التحميل";
      if (footerNote) footerNote.textContent = String(err.message || err);
      nodes = [];
      filtered = [];
      rebuildGalaxy();
      if (emptyEl) {
        emptyEl.hidden = false;
        const msg = emptyEl.querySelector("p");
        if (msg) msg.textContent = "تعذر جلب بيانات المجرة";
      }
    } finally {
      setLoading(false);
    }
  }

  function clearGroup(group) {
    if (!group) return;
    while (group.children.length) {
      const child = group.children.pop();
      child.traverse((obj) => {
        if (obj.geometry && !geometryCacheHas(obj.geometry)) obj.geometry.dispose();
        if (obj.material && !materialCacheHas(obj.material)) {
          if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose && m.dispose());
          else obj.material.dispose && obj.material.dispose();
        }
      });
    }
  }

  function geometryCacheHas(geometry) {
    for (const g of geometryCache.values()) if (g === geometry) return true;
    return false;
  }

  function materialCacheHas(material) {
    for (const m of materialCache.values()) if (m === material) return true;
    return false;
  }

  function hashString(str) {
    let h = 2166136261;
    const s = String(str || "");
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function hashHue(str) {
    return hashString(str) % 360;
  }

  function seeded(seed, salt) {
    let x = Math.sin((Number(seed) || 1) * 999 + salt * 77.7) * 10000;
    return x - Math.floor(x);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function bindEvents() {
    canvas.addEventListener("pointerdown", (e) => {
      mouse.down = true;
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.moved = 0;
      canvas.classList.add("is-dragging");
      canvas.setPointerCapture(e.pointerId);
    });

    canvas.addEventListener("pointermove", (e) => {
      if (!mouse.down) return;
      const dx = e.clientX - mouse.x;
      const dy = e.clientY - mouse.y;
      mouse.moved += Math.abs(dx) + Math.abs(dy);
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.targetRotY += dx * 0.006;
      mouse.targetRotX = clamp(mouse.targetRotX + dy * 0.004, -0.92, 0.18);
    });

    canvas.addEventListener("pointerup", (e) => {
      mouse.down = false;
      canvas.classList.remove("is-dragging");
      if (mouse.moved < 5) {
        const hit = pick(e);
        if (hit) openPanel(hit);
        else closePanel();
      }
    });

    canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        mouse.zoom = clamp(mouse.zoom + e.deltaY * 0.16, 240, 560);
      },
      { passive: false }
    );

    const closeBtn = document.getElementById("brainPanelClose");
    if (closeBtn) closeBtn.addEventListener("click", closePanel);
    if (searchInput) searchInput.addEventListener("input", applyFilters);
    if (orbitFilter) orbitFilter.addEventListener("change", applyFilters);
    if (tenantFilter) tenantFilter.addEventListener("change", applyFilters);
    if (refreshBtn) refreshBtn.addEventListener("click", loadData);
    window.addEventListener("resize", resize);
  }

  function boot() {
    if (!hasThree()) {
      if (loadingEl) loadingEl.hidden = true;
      if (emptyEl) {
        emptyEl.hidden = false;
        const msg = emptyEl.querySelector("p");
        if (msg) msg.textContent = "تعذر تشغيل محرك العرض ثلاثي الأبعاد";
      }
      return;
    }
    initThree();
    bindEvents();
    loadData();
  }

  boot();

  window.addEventListener("beforeunload", () => {
    if (animationId) cancelAnimationFrame(animationId);
    if (renderer) renderer.dispose();
  });
})();
