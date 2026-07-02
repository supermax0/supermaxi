(function (global) {
  "use strict";

  var VIEWPORT_NO_ZOOM =
    "width=device-width, initial-scale=1.0, viewport-fit=cover";

  function ensureViewportMeta() {
    var meta = document.querySelector('meta[name="viewport"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = "viewport";
      document.head.appendChild(meta);
    }
    if (!meta.content || meta.content.indexOf("width=device-width") === -1) {
      meta.content = VIEWPORT_NO_ZOOM;
    }
  }

  function blockPinchGestures() {
    var opts = { passive: false };
    ["gesturestart", "gesturechange", "gestureend"].forEach(function (ev) {
      document.addEventListener(
        ev,
        function (e) {
          e.preventDefault();
        },
        opts
      );
    });
  }

  ensureViewportMeta();
  blockPinchGestures();

  global.FinoraNoZoom = {
    VIEWPORT: VIEWPORT_NO_ZOOM,
    ensureViewportMeta: ensureViewportMeta,
    blockPinchGestures: blockPinchGestures
  };
})(window);
