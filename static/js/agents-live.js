(function () {
  var map = null;
  var markers = {};
  var trails = {};
  var selectedId = null;
  var timer = null;

  function colorFor(freshness) {
    if (freshness === "live") return "#059669";
    if (freshness === "recent") return "#d97706";
    return "#94a3b8";
  }

  function ageLabel(seconds) {
    seconds = Number(seconds || 0);
    if (seconds < 60) return "قبل " + seconds + " ث";
    if (seconds < 3600) return "قبل " + Math.floor(seconds / 60) + " د";
    return "قبل " + Math.floor(seconds / 3600) + " س";
  }

  function ensureMap() {
    if (map) return;
    map = L.map("liveMap").setView([33.3152, 44.3661], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
      maxZoom: 19
    }).addTo(map);
  }

  function focusAgent(agentId) {
    selectedId = Number(agentId);
    document.querySelectorAll(".live-item").forEach(function (btn) {
      btn.classList.toggle("is-active", Number(btn.getAttribute("data-id")) === selectedId);
    });
    var marker = markers[selectedId];
    if (marker) {
      map.setView(marker.getLatLng(), 15);
      marker.openPopup();
    }
  }

  function renderList(agents) {
    var box = document.getElementById("liveList");
    if (!agents.length) {
      box.className = "live-empty";
      box.textContent = "لا يوجد مندوب يرسل موقعه حالياً. يظهر الموقع عندما يفتح المندوب بوابة التوصيل ويسمح بالموقع.";
      return;
    }
    box.className = "";
    box.innerHTML = agents.map(function (agent) {
      return '<button type="button" class="live-item' + (Number(agent.agent_id) === selectedId ? " is-active" : "") + '" data-id="' + agent.agent_id + '">' +
        '<strong><i class="live-dot ' + agent.freshness + '"></i>' + escapeHtml(agent.name) + "</strong>" +
        "<small>" + ageLabel(agent.age_seconds) + " · " + (agent.active_orders || 0) + " طلب نشط</small>" +
        "</button>";
    }).join("");
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function upsertMarkers(agents) {
    var seen = {};
    var bounds = [];
    agents.forEach(function (agent) {
      seen[agent.agent_id] = true;
      var latlng = [agent.lat, agent.lng];
      bounds.push(latlng);
      var html =
        "<strong>" + escapeHtml(agent.name) + "</strong><br>" +
        ageLabel(agent.age_seconds) + "<br>" +
        (agent.active_orders || 0) + " طلب نشط";
      if (markers[agent.agent_id]) {
        markers[agent.agent_id].setLatLng(latlng);
        markers[agent.agent_id].setPopupContent(html);
        markers[agent.agent_id].setStyle({ color: colorFor(agent.freshness), fillColor: colorFor(agent.freshness) });
      } else {
        markers[agent.agent_id] = L.circleMarker(latlng, {
          radius: 9,
          color: colorFor(agent.freshness),
          fillColor: colorFor(agent.freshness),
          fillOpacity: 0.9,
          weight: 2
        }).addTo(map).bindPopup(html);
        markers[agent.agent_id].on("click", function () { focusAgent(agent.agent_id); });
      }
      var trailPoints = (agent.trail || []).map(function (point) { return [point.lat, point.lng]; });
      if (trails[agent.agent_id]) {
        trails[agent.agent_id].setLatLngs(trailPoints);
      } else if (trailPoints.length > 1) {
        trails[agent.agent_id] = L.polyline(trailPoints, {
          color: colorFor(agent.freshness),
          weight: 3,
          opacity: 0.55
        }).addTo(map);
      }
      if (trails[agent.agent_id] && trailPoints.length <= 1) {
        trails[agent.agent_id].remove();
        delete trails[agent.agent_id];
      }
    });
    Object.keys(markers).forEach(function (id) {
      if (!seen[id]) {
        markers[id].remove();
        delete markers[id];
      }
    });
    Object.keys(trails).forEach(function (id) {
      if (!seen[id]) {
        trails[id].remove();
        delete trails[id];
      }
    });
    if (selectedId && markers[selectedId]) {
      focusAgent(selectedId);
    } else if (bounds.length && !selectedId) {
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
    }
  }

  function refresh() {
    fetch("/agents/live-positions", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var agents = (data && data.agents) || [];
        ensureMap();
        renderList(agents);
        upsertMarkers(agents);
      })
      .catch(function () {
        document.getElementById("liveList").className = "live-empty";
        document.getElementById("liveList").textContent = "تعذر تحميل المواقع. أعد المحاولة.";
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    ensureMap();
    document.getElementById("liveList").addEventListener("click", function (event) {
      var btn = event.target.closest(".live-item");
      if (btn) focusAgent(btn.getAttribute("data-id"));
    });
    document.getElementById("liveRefresh").addEventListener("click", refresh);
    refresh();
    timer = setInterval(refresh, 15000);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        if (timer) clearInterval(timer);
        timer = null;
      } else if (!timer) {
        refresh();
        timer = setInterval(refresh, 15000);
      }
    });
  });
})();
