/**
 * Finora AI Workspace — main application (Phase 1).
 */
(function () {
  const API = "/workspace/api";

  const store = new WorkspaceSessionStore();
  let windowManager = null;
  let avatar = null;
  let eventStream = null;
  let canvas = null;

  const statusPill = document.getElementById("ws-status-pill");
  const btnNew = document.getElementById("btn-new-session");
  const btnRun = document.getElementById("btn-run-mock");
  const btnCancel = document.getElementById("btn-cancel");
  const canvasEl = document.getElementById("ws-canvas");
  const windowsLayer = document.getElementById("ws-windows-layer");
  const avatarLayer = document.getElementById("ws-avatar-layer");

  function setStatus(status) {
    const labels = {
      created: "جاهز",
      running: "قيد التشغيل",
      completed: "مكتمل",
      cancelled: "ملغي",
      failed: "فشل",
    };
    statusPill.textContent = labels[status] || status || "جاهز";
    statusPill.className = "ws-status-pill";
    if (status === "running") statusPill.classList.add("ws-status-running");
    if (status === "completed") statusPill.classList.add("ws-status-completed");
    if (status === "cancelled") statusPill.classList.add("ws-status-cancelled");
  }

  function updateUrl(sessionId) {
    const url = new URL(window.location.href);
    url.searchParams.set("session", sessionId);
    window.history.replaceState({}, "", url);
  }

  async function api(path, options = {}) {
    const res = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "same-origin",
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.message || data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  function renderFromSession(session) {
    if (!session) return;
    setStatus(session.status);
    windowManager.renderWindows(session.windows || []);
    avatar.applyState(session.avatar_state || {});
    btnRun.disabled = session.status === "running" || session.status === "completed";
  }

  function connectStream(sessionId) {
    if (eventStream) eventStream.disconnect();
    eventStream = new WorkspaceEventStream(sessionId);

    eventStream.onAny((data) => {
      windowManager.applyEvent(data);
    });

    eventStream.on("avatar.updated", (data) => {
      if (data.payload && data.payload.avatar_state) {
        avatar.applyState(data.payload.avatar_state);
      }
    });

    eventStream.on("window.updated", (data) => {
      if (data.payload && data.payload.windows) {
        windowManager.renderWindows(data.payload.windows);
        store.patchSession({ windows: data.payload.windows });
      }
    });

    eventStream.on("window.opened", (data) => {
      if (data.payload && data.payload.window) {
        windowManager.openWindow(data.payload.window);
      }
    });

    eventStream.on("session.completed", () => {
      setStatus("completed");
      btnRun.disabled = true;
      refreshSession();
    });

    eventStream.on("session.cancelled", () => {
      setStatus("cancelled");
      btnRun.disabled = true;
    });

    eventStream.connect();
  }

  async function refreshSession() {
    const session = store.getSession();
    if (!session) return;
    const data = await api(`/sessions/${session.id}`);
    store.setSession(data.session);
    renderFromSession(data.session);
  }

  async function createSession() {
    const data = await api("/sessions", { method: "POST", body: JSON.stringify({}) });
    store.setSession(data.session);
    updateUrl(data.session.id);
    renderFromSession(data.session);
    connectStream(data.session.id);
    return data.session;
  }

  async function init() {
    canvas = new WorkspaceCanvas(canvasEl);
    windowManager = new WorkspaceWindowManager(windowsLayer);
    avatar = new LeonAvatarAdapter(avatarLayer, canvas);

    store.subscribe(renderFromSession);

    btnNew.addEventListener("click", async () => {
      try {
        btnNew.disabled = true;
        await createSession();
      } catch (e) {
        alert(e.message);
      } finally {
        btnNew.disabled = false;
      }
    });

    btnRun.addEventListener("click", async () => {
      const session = store.getSession();
      if (!session) return;
      try {
        btnRun.disabled = true;
        setStatus("running");
        await api(`/sessions/${session.id}/run-mock`, { method: "POST", body: "{}" });
      } catch (e) {
        alert(e.message);
        btnRun.disabled = false;
      }
    });

    btnCancel.addEventListener("click", async () => {
      const session = store.getSession();
      if (!session) return;
      try {
        await api(`/sessions/${session.id}/cancel`, { method: "POST", body: "{}" });
        await refreshSession();
      } catch (e) {
        alert(e.message);
      }
    });

    window.addEventListener("resize", () => {
      const session = store.getSession();
      if (session && session.avatar_state) {
        avatar.applyState(session.avatar_state);
      }
    });

    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session");

    try {
      if (sessionId) {
        const data = await api(`/sessions/${sessionId}`);
        store.setSession(data.session);
        renderFromSession(data.session);
        connectStream(sessionId);
      } else {
        await createSession();
      }
    } catch (e) {
      console.warn("Session load failed, creating new", e);
      await createSession();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
