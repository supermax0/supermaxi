(function () {
  var map = null;
  var routeLine = null;
  var markers = [];
  var watchId = null;
  var lastFix = null;
  var lastSent = 0;
  var trackingTimer = null;
  var speaking = false;
  var steps = [];
  var stepIndex = 0;
  var activeOrderId = null;

  function orders() {
    var node = document.getElementById("da-orders");
    if (!node) return [];
    try { return JSON.parse(node.textContent || "[]"); } catch (e) { return []; }
  }

  function orderById(id) {
    id = Number(id);
    var list = orders();
    for (var i = 0; i < list.length; i++) {
      if (Number(list[i].id) === id) return list[i];
    }
    return null;
  }

  function loadLeaflet(done) {
    if (window.L) { done(); return; }
    var css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    var script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.onload = done;
    document.head.appendChild(script);
  }

  function beep() {
    try {
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.value = 0.05;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      setTimeout(function () { osc.stop(); ctx.close(); }, 140);
    } catch (e) {}
  }

  function speak(text) {
    if (!speaking || !text) return;
    if (!window.speechSynthesis) { beep(); return; }
    var utter = new SpeechSynthesisUtterance(text);
    utter.lang = "ar";
    var voices = window.speechSynthesis.getVoices() || [];
    var arabic = voices.filter(function (voice) { return (voice.lang || "").toLowerCase().indexOf("ar") === 0; })[0];
    if (!arabic) { beep(); return; }
    utter.voice = arabic;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
  }

  function clearMap() {
    markers.forEach(function (marker) { marker.remove(); });
    markers = [];
    if (routeLine) { routeLine.remove(); routeLine = null; }
  }

  function ensureMap(center) {
    var node = document.getElementById("agentMap");
    if (!window.L || !node) return;
    if (!map) {
      map = L.map(node).setView(center, 14);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap",
        maxZoom: 19
      }).addTo(map);
    } else {
      map.setView(center, 14);
    }
    setTimeout(function () { map.invalidateSize(); }, 180);
  }

  function addMarker(latlng, title) {
    var marker = L.marker(latlng).addTo(map);
    if (title) marker.bindPopup(title);
    markers.push(marker);
    return marker;
  }

  function openOrder(order) {
    activeOrderId = order.id;
    steps = [];
    stepIndex = 0;
    speaking = false;
    document.getElementById("mapStop").hidden = true;
    document.getElementById("mapTitle").textContent = "طلب #" + order.id;
    document.getElementById("mapStatus").textContent = order.location_label || order.address || "";
    var external = document.getElementById("mapExternal");
    if (order.location_url && String(order.location_url).indexOf("http") === 0) {
      external.hidden = false;
      external.href = order.location_url;
    } else {
      external.hidden = true;
    }
    document.getElementById("mapSheet").hidden = false;
    document.getElementById("mapStart").disabled = order.location_lat == null || order.location_lng == null;
    loadLeaflet(function () {
      var center = order.location_lat != null ? [order.location_lat, order.location_lng] : [33.3152, 44.3661];
      ensureMap(center);
      clearMap();
      if (order.location_lat != null) addMarker(center, order.customer_name || "الزبون");
      if (lastFix) addMarker([lastFix.lat, lastFix.lng], "موقعك");
    });
  }

  function distanceMeters(a, b) {
    var r = 6371000;
    var p1 = a.lat * Math.PI / 180;
    var p2 = b.lat * Math.PI / 180;
    var dp = (b.lat - a.lat) * Math.PI / 180;
    var dl = (b.lng - a.lng) * Math.PI / 180;
    var h = Math.sin(dp / 2) * Math.sin(dp / 2) + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
    return 2 * r * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function followSteps() {
    if (!speaking || !lastFix || !steps.length) return;
    var step = steps[stepIndex];
    if (!step) return;
    if (distanceMeters(lastFix, step) < 80) {
      speak(step.instruction);
      stepIndex += 1;
      if (stepIndex >= steps.length) speaking = false;
    }
  }

  function startRoute() {
    var order = orderById(activeOrderId);
    if (!order || order.location_lat == null) return;
    if (!lastFix) {
      document.getElementById("mapStatus").textContent = "فعّل الموقع أولاً";
      return;
    }
    var url = "/delivery-agent/route/" + order.id + "?from_lat=" + encodeURIComponent(lastFix.lat) + "&from_lng=" + encodeURIComponent(lastFix.lng);
    document.getElementById("mapStatus").textContent = "جاري حساب المسار…";
    fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      if (!data.success) {
        document.getElementById("mapStatus").textContent = data.error || "تعذر حساب الطريق";
        if (data.from && data.to && window.L && map) {
          clearMap();
          addMarker(data.from, "موقعك");
          addMarker(data.to, "الزبون");
          routeLine = L.polyline([data.from, data.to], { color: "#2563eb", dashArray: "6 6" }).addTo(map);
          map.fitBounds(routeLine.getBounds(), { padding: [20, 20] });
        }
        return;
      }
      steps = (data.steps || []).map(function (step) {
        return { lat: step.lat, lng: step.lng, instruction: step.instruction };
      });
      stepIndex = 0;
      speaking = true;
      document.getElementById("mapStop").hidden = false;
      var km = (data.distance || 0) / 1000;
      document.getElementById("mapStatus").textContent = "المسافة " + km.toFixed(1) + " كم";
      clearMap();
      addMarker(data.from, "موقعك");
      addMarker(data.to, "الزبون");
      if (data.line && data.line.length && window.L) {
        routeLine = L.polyline(data.line, { color: "#2563eb", weight: 5 }).addTo(map);
        map.fitBounds(routeLine.getBounds(), { padding: [20, 20] });
      }
      if (steps[0]) speak(steps[0].instruction);
      stepIndex = steps.length ? 1 : 0;
    }).catch(function () {
      document.getElementById("mapStatus").textContent = "تعذر حساب الطريق";
    });
  }

  function sendFix() {
    if (!lastFix || document.hidden) return;
    var now = Date.now();
    if (now - lastSent < 20000) return;
    lastSent = now;
    fetch("/delivery-agent/location", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastFix)
    }).catch(function () {});
  }

  function startTracking() {
    if (!navigator.geolocation || watchId != null) return;
    watchId = navigator.geolocation.watchPosition(function (pos) {
      if (document.hidden) return;
      lastFix = {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        heading: pos.coords.heading,
        speed: pos.coords.speed
      };
      followSteps();
      sendFix();
    }, function () {}, { enableHighAccuracy: true, maximumAge: 10000 });
    trackingTimer = setInterval(sendFix, 20000);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        if (trackingTimer) {
          clearInterval(trackingTimer);
          trackingTimer = null;
        }
      } else if (!trackingTimer) {
        trackingTimer = setInterval(sendFix, 20000);
        sendFix();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!document.getElementById("mapSheet")) return;
    document.body.addEventListener("click", function (event) {
      var button = event.target.closest("[data-open-map]");
      if (!button) return;
      var order = orderById(button.getAttribute("data-open-map"));
      if (order) openOrder(order);
    });
    document.getElementById("mapBack").addEventListener("click", function () {
      speaking = false;
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      document.getElementById("mapSheet").hidden = true;
    });
    document.getElementById("mapStart").addEventListener("click", startRoute);
    document.getElementById("mapStop").addEventListener("click", function () {
      speaking = false;
      document.getElementById("mapStop").hidden = true;
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    });
    startTracking();
  });
})();
