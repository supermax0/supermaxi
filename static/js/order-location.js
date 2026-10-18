(function () {
  var pin = { lat: null, lng: null };
  var map = null;
  var marker = null;
  var inputEl = null;

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

  function parseText(value) {
    var text = (value || "").trim();
    var match = text.match(/^(-?\d{1,3}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)$/);
    if (!match) return null;
    var lat = Number(match[1]);
    var lng = Number(match[2]);
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
    return { lat: lat, lng: lng };
  }

  function place(lat, lng) {
    pin.lat = lat;
    pin.lng = lng;
    if (!map) return;
    var point = [lat, lng];
    if (!marker) marker = L.marker(point).addTo(map);
    else marker.setLatLng(point);
    map.setView(point, 15);
  }

  window.OrderLocationPin = {
    bind: function (inputId, mapId, lat, lng) {
      inputEl = document.getElementById(inputId);
      var mapNode = document.getElementById(mapId);
      if (!inputEl || !mapNode) return;
      pin.lat = lat == null || lat === "" ? null : Number(lat);
      pin.lng = lng == null || lng === "" ? null : Number(lng);
      loadLeaflet(function () {
        if (map) { map.remove(); map = null; marker = null; }
        var start = pin.lat != null && pin.lng != null ? [pin.lat, pin.lng] : [33.3152, 44.3661];
        map = L.map(mapNode).setView(start, pin.lat != null ? 15 : 11);
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: "&copy; OpenStreetMap",
          maxZoom: 19
        }).addTo(map);
        if (pin.lat != null && pin.lng != null) place(pin.lat, pin.lng);
        map.on("click", function (event) {
          place(event.latlng.lat, event.latlng.lng);
          if (inputEl) inputEl.value = event.latlng.lat.toFixed(6) + ", " + event.latlng.lng.toFixed(6);
        });
        setTimeout(function () { map.invalidateSize(); }, 200);
      });
      inputEl.addEventListener("change", function () {
        var found = parseText(inputEl.value);
        if (found) place(found.lat, found.lng);
      });
    },
    read: function () {
      if (inputEl) {
        var found = parseText(inputEl.value);
        if (found) return found;
      }
      return { lat: pin.lat, lng: pin.lng };
    }
  };
})();
