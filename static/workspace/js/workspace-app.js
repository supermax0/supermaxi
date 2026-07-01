/**
 * Finora AI Workspace — Phase 1–3.
 */
(function () {
  const API = "/workspace/api";
  const IS_DEV = new URLSearchParams(window.location.search).get("dev") === "1";

  const store = new WorkspaceSessionStore();
  let windowManager = null;
  let avatar = null;
  let eventStream = null;
  let canvas = null;
  let uploadManager = null;
  let workflowClient = null;
  let documentIntelligenceClient = null;
  let courierAnalysisClient = null;
  let timelineStore = null;
  let progressPanel = null;

  const statusPill = document.getElementById("ws-status-pill");
  const btnUpload = document.getElementById("btn-upload");
  const btnIntelligence = document.getElementById("btn-intelligence");
  const btnCourierAnalysis = document.getElementById("btn-courier-analysis");
  const btnWorkflow = document.getElementById("btn-workflow");
  const btnSelectWorkflow = document.getElementById("btn-select-workflow");
  const btnNextStep = document.getElementById("btn-next-step");
  const btnNew = document.getElementById("btn-new-session");
  const btnRun = document.getElementById("btn-run-mock");
  const btnCancel = document.getElementById("btn-cancel");
  const canvasEl = document.getElementById("ws-canvas");
  const windowsLayer = document.getElementById("ws-windows-layer");
  const avatarLayer = document.getElementById("ws-avatar-layer");

  function setStatus(status) {
    const labels = {
      created: "جاهز",
      ready: "جاهز",
      running: "قيد التشغيل",
      waiting_user: "بانتظار المستخدم",
      waiting_approval: "بانتظار الموافقة",
      completed: "مكتمل",
      cancelled: "ملغي",
      failed: "فشل",
    };
    statusPill.textContent = labels[status] || status || "جاهز";
    statusPill.className = "ws-status-pill";
    if (status === "running") statusPill.classList.add("ws-status-running");
    if (status === "completed") statusPill.classList.add("ws-status-completed");
    if (status === "cancelled") statusPill.classList.add("ws-status-cancelled");
    if (status === "waiting_approval" || status === "waiting_user") {
      statusPill.classList.add("ws-status-running");
    }
  }

  function setIntelligenceBusy(busy) {
    if (!btnIntelligence) return;
    btnIntelligence.disabled = busy || !hasActiveDocument();
    btnIntelligence.textContent = busy ? "جاري الفهم..." : "فهم المستند";
    btnIntelligence.classList.toggle("ws-btn-loading", busy);
  }

  function hasActiveDocument() {
    const session = store.getSession();
    if (!session) return false;
    if (session.active_document) return true;
    const meta = session.metadata || {};
    return Boolean(meta.active_document_id) || (session.documents && session.documents.length > 0);
  }

  function updateIntelligenceButton() {
    if (!btnIntelligence) return;
    const busy = documentIntelligenceClient && documentIntelligenceClient.isBusy();
    btnIntelligence.disabled = busy || !hasActiveDocument();
  }

  function updateCourierButton() {
    if (!btnCourierAnalysis) return;
    const busy = courierAnalysisClient && courierAnalysisClient.isBusy();
    btnCourierAnalysis.disabled = busy || !hasActiveDocument();
  }

  function setCourierBusy(busy) {
    if (!btnCourierAnalysis) return;
    btnCourierAnalysis.disabled = busy || !hasActiveDocument();
    btnCourierAnalysis.textContent = busy ? "جاري التحليل..." : "تحليل كشف التسديد قراءة فقط";
    btnCourierAnalysis.classList.toggle("ws-btn-loading", busy);
  }

  function setUploadBusy(busy) {
    if (btnUpload) {
      btnUpload.disabled = busy;
      btnUpload.textContent = busy ? "جاري الرفع..." : "رفع مستند";
      btnUpload.classList.toggle("ws-btn-loading", busy);
    }
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
      const code = data.error || `HTTP ${res.status}`;
      if (code === "not_found") {
        throw new Error("SESSION_NOT_FOUND");
      }
      throw new Error(data.message || code);
    }
    return data;
  }

  function ensureTimelineWindow(session) {
    const windows = session.windows || [];
    if (!IS_DEV) {
      return windows.filter((w) => w.type !== "session_timeline");
    }
    if (windows.some((w) => w.type === "session_timeline")) return windows;
    return [
      ...windows,
      {
        id: "win_timeline_1",
        type: "session_timeline",
        title: "سجل الأحداث",
        status: "ready",
        position: { x: 40, y: 420, width: 360, height: 200 },
        placement: "bottom",
        z_index: 8,
        props: { items: timelineStore.items },
        interactive: false,
      },
    ];
  }

  function patchDocumentViewerLoading(loading) {
    const session = store.getSession();
    if (!session || !session.windows) return;
    const windows = session.windows.map((w) => {
      if (w.type !== "document_viewer") return w;
      return {
        ...w,
        status: loading ? "loading" : w.status,
        props: { ...(w.props || {}), loading },
      };
    });
    windowManager.renderWindows(windows);
  }

  function showDocumentViewerError(message) {
    const session = store.getSession();
    if (!session || !session.windows) return;
    const windows = session.windows.map((w) => {
      if (w.type !== "document_viewer") return w;
      return {
        ...w,
        status: "error",
        props: { ...(w.props || {}), loading: false, error: message },
      };
    });
    windowManager.renderWindows(windows);
  }

  function renderFromSession(session) {
    if (!session) return;
    setStatus(session.status);
    const windows = ensureTimelineWindow(session);
    windowManager.renderWindows(windows);
    avatar.applyState(session.avatar_state || {});
    updateIntelligenceButton();
    updateCourierButton();
    if (btnRun) {
      btnRun.disabled = session.status === "running" || session.status === "completed";
    }
  }

  function onSessionUpdate(session) {
    store.setSession(session);
    renderFromSession(session);
  }

  function connectStream(sessionId, replayFromStart = false) {
    if (eventStream) eventStream.disconnect();
    LiveReportWindow.resetDedup();
    eventStream = new WorkspaceEventStream(sessionId);
    if (replayFromStart) {
      // Recovery: report is empty but the cursor is ahead — replay everything
      // so the live report re-fills. Non-report replayed events are ignored.
      eventStream.lastEventId = 0;
    }

    eventStream.onAny((data) => {
      if (timelineStore.addFromEvent(data)) {
        windowManager.updateTimelineItems(timelineStore.items);
      }
      if (!data._fromReplay) {
        windowManager.applyEvent(data);
      } else if (data.type === "report.appended") {
        // On replay we only re-hydrate the streaming report; window state is
        // already authoritative from the session GET, so we do not re-apply
        // replayed window/workflow events (which could resurrect stale cards).
        windowManager.applyEvent(data);
      }
    });

    eventStream.on("workflow.started", (data) => {
      if (data._fromReplay) return;
      const title = (data.payload && data.payload.title) || "";
      windowManager.applyEvent({
        type: "report.appended",
        payload: { line: `— بدأ سير عمل جديد${title ? ": " + title : ""} —` },
      });
    });

    eventStream.on("avatar.updated", (data) => {
      if (data.payload && data.payload.avatar_state) {
        avatar.applyState(data.payload.avatar_state);
        store.patchSession({ avatar_state: data.payload.avatar_state });
      }
    });

    eventStream.on("window.updated", (data) => {
      if (data.payload && data.payload.windows) {
        const withTimeline = ensureTimelineWindow({ windows: data.payload.windows });
        windowManager.renderWindows(withTimeline);
        store.patchSession({ windows: withTimeline });
      }
    });

    eventStream.on("document.preview.ready", () => {
      setUploadBusy(false);
      updateIntelligenceButton();
    });

    eventStream.on("document.intelligence.started", () => {
      avatar.setMode("reading_document");
      avatar.speak("أبدأ قراءة المستند مبدئياً.");
    });

    eventStream.on("document.intelligence.completed", () => {
      avatar.setMode("success");
    });

    eventStream.on("document.intelligence.failed", (data) => {
      avatar.setMode("warning");
      const err = (data.payload && data.payload.error) || "فشل تحليل المستند";
      avatar.speak(err);
    });

    eventStream.on("courier.analysis.started", () => {
      avatar.setMode("matching");
      avatar.speak("أهلاً، جاري تحليل كشف شركة التوصيل ومطابقة الطلبات...");
      if (progressPanel) {
        progressPanel.reset();
        progressPanel.show();
        progressPanel.markActive("read");
      }
    });

    eventStream.on("courier.rows.parsed", () => {
      if (progressPanel) progressPanel.markActive("match");
    });

    eventStream.on("courier.matching.started", () => {
      avatar.setMode("matching");
      if (progressPanel) progressPanel.markActive("match");
    });

    eventStream.on("courier.issues.detected", () => {
      if (progressPanel) progressPanel.markActive("fees");
    });

    eventStream.on("courier.financial_preview.ready", () => {
      if (progressPanel) progressPanel.markActive("profit");
    });

    eventStream.on("courier.analysis.completed", () => {
      avatar.setMode("success");
      avatar.speak("اكتمل تحليل كشف التسديد — نتائج قراءة فقط.");
      updateCourierButton();
      if (progressPanel) {
        progressPanel.completeAll();
        setTimeout(() => progressPanel.hide(), 2500);
      }
    });

    eventStream.on("courier.analysis.failed", (data) => {
      avatar.setMode("warning");
      avatar.speak((data.payload && data.payload.error) || "فشل تحليل الكشف");
      if (progressPanel) progressPanel.hide();
    });

    eventStream.on("session.completed", () => {
      setStatus("completed");
      if (btnRun) btnRun.disabled = true;
      refreshSession();
    });

    eventStream.on("session.cancelled", () => {
      setStatus("cancelled");
      if (btnRun) btnRun.disabled = true;
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

  async function recoverMissingSession() {
    console.warn("Workspace session missing — creating a new session");
    try {
      await createSession();
      alert("انتهت صلاحية الجلسة السابقة. تم إنشاء جلسة جديدة.");
    } catch (err) {
      alert(err.message || "تعذّر إنشاء جلسة جديدة");
    }
  }

  async function init() {
    canvas = new WorkspaceCanvas(canvasEl);
    timelineStore = new SessionTimelineStore();
    windowManager = new WorkspaceWindowManager(windowsLayer);
    if (window.WorkspaceLayoutDirector) {
      windowManager.setLayoutDirector(
        new WorkspaceLayoutDirector(() => canvas.getSize())
      );
    }
    avatar = new LeonAvatarAdapter(avatarLayer, canvas);
    if (window.WorkspaceProgressPanel) {
      progressPanel = new WorkspaceProgressPanel(canvasEl);
    }

    workflowClient = new WorkspaceWorkflowClient({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onSessionUpdate,
      onWaiting: (kind) => setStatus(kind === "approval" ? "waiting_approval" : "waiting_user"),
      onError: (err) => {
        if (String(err.message || "").includes("الجلسة غير موجودة")) {
          recoverMissingSession();
          return;
        }
        alert(err.message);
      },
    });

    windowManager.setWorkflowHandlers({
      onApprove: async () => {
        await workflowClient.submitApproval(true);
        const s = store.getSession();
        if (s && s.status !== "completed") {
          await workflowClient.runNextStep();
        }
      },
      onReject: async () => {
        await workflowClient.submitApproval(false);
      },
      onSelectWorkflow: async (type) => {
        try {
          if (type === "unknown_document") {
            await workflowClient.startWorkflow("unknown_document");
            await workflowClient.runUntilBlocked(false);
          } else {
            await workflowClient.startWorkflow(type);
            await workflowClient.runUntilBlocked();
          }
        } catch (e) {
          if (e.message === "SESSION_NOT_FOUND") {
            await recoverMissingSession();
          } else {
            alert(e.message);
          }
        }
      },
    });

    uploadManager = new WorkspaceUploadManager({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onStart: () => {
        setUploadBusy(true);
        patchDocumentViewerLoading(true);
      },
      onSuccess: (data) => {
        setUploadBusy(false);
        if (data.session) onSessionUpdate(data.session);
        updateIntelligenceButton();
      },
      onError: (err) => {
        setUploadBusy(false);
        showDocumentViewerError(err.message || "فشل رفع المستند");
      },
    });

    documentIntelligenceClient = new DocumentIntelligenceClient({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onSessionUpdate,
      onStart: () => setIntelligenceBusy(true),
      onComplete: () => {
        setIntelligenceBusy(false);
        updateIntelligenceButton();
      },
      onError: (err) => {
        setIntelligenceBusy(false);
        updateIntelligenceButton();
        alert(err.message || "فشل فهم المستند");
      },
    });

    courierAnalysisClient = new CourierAnalysisClient({
      apiBase: API,
      getSessionId: () => (store.getSession() || {}).id,
      onSessionUpdate,
      onStart: () => setCourierBusy(true),
      onComplete: () => {
        setCourierBusy(false);
        updateCourierButton();
      },
      onError: (err) => {
        setCourierBusy(false);
        updateCourierButton();
        alert(err.message || "فشل تحليل كشف التسديد");
      },
    });

    windowManager.setCourierHandlers({
      loadRows: async (analysisId, filter, bodyEl) => {
        const status = filter === "all" ? undefined : filter;
        const data = await courierAnalysisClient.getRows(analysisId, { status, page_size: 100 });
        CourierRowsWindow.showRows(bodyEl.closest(".ws-courier-rows") ? bodyEl.parentElement : bodyEl, data.rows);
      },
      loadIssues: async (analysisId, bodyEl) => {
        const data = await courierAnalysisClient.getIssues(analysisId);
        CourierIssuesWindow.showIssues(bodyEl, data.issues);
      },
      loadReportIssues: async (analysisId, bodyEl) => {
        try {
          const data = await courierAnalysisClient.getIssues(analysisId);
          CourierSettlementAnalysisWindow.patchFromEvent(bodyEl, { issues: data.issues || [] });
        } catch (e) {
          /* keep placeholder */
        }
      },
      onExport: () => {
        window.print();
      },
      onFilter: async (spec, filter) => {
        const aid = (spec.props || {}).analysisId;
        if (!aid) return;
        const data = await courierAnalysisClient.getRows(aid, {
          status: filter === "all" ? undefined : filter,
          page_size: 100,
        });
        const winEl = [...windowManager.windows.values()].find((el) => {
          const s = JSON.parse(el.dataset.spec || "{}");
          return s.type === "courier_rows" && (s.props || {}).analysisId === aid;
        });
        if (winEl) {
          CourierRowsWindow.showRows(winEl.querySelector(".ws-window-body"), data.rows);
        }
      },
    });

    store.subscribe(renderFromSession);

    if (btnUpload) btnUpload.addEventListener("click", () => uploadManager.openPicker());
    window.addEventListener("ws:upload-request", () => uploadManager.openPicker());
    window.addEventListener("ws:show-issues-details", () => {
      const win = [...windowManager.windows.entries()].find(([, el]) => {
        const s = JSON.parse(el.dataset.spec || "{}");
        return s.type === "courier_issues" || s.type === "courier_settlement_analysis";
      });
      if (win) windowManager.focusWindow(win[0]);
    });

    if (btnIntelligence) {
      btnIntelligence.addEventListener("click", async () => {
        try {
          await documentIntelligenceClient.runForActiveSessionDocument();
        } catch (e) {
          /* onError */
        }
      });
    }

    if (btnCourierAnalysis) {
      btnCourierAnalysis.addEventListener("click", async () => {
        try {
          await courierAnalysisClient.runForSession();
        } catch (e) {
          /* onError */
        }
      });
    }

    if (btnWorkflow) {
      btnWorkflow.addEventListener("click", async () => {
        try {
          btnWorkflow.disabled = true;
          await workflowClient.startWorkflow("mock_workspace");
          await workflowClient.runUntilBlocked();
        } catch (e) {
          if (e.message === "SESSION_NOT_FOUND") {
            await recoverMissingSession();
          } else {
            alert(e.message);
          }
        } finally {
          btnWorkflow.disabled = false;
        }
      });
    }

    if (btnSelectWorkflow) {
      btnSelectWorkflow.addEventListener("click", async () => {
        try {
          await workflowClient.startWorkflow("unknown_document");
          await workflowClient.runNextStep();
        } catch (e) {
          if (e.message === "SESSION_NOT_FOUND") {
            await recoverMissingSession();
          } else {
            alert(e.message);
          }
        }
      });
    }

    if (btnNextStep && IS_DEV) {
      btnNextStep.hidden = false;
      btnNextStep.addEventListener("click", async () => {
        try {
          await workflowClient.runNextStep();
        } catch (e) {
          alert(e.message);
        }
      });
    }

    if (btnNew) {
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
    }

    const btnFocus = document.getElementById("btn-focus");
    if (btnFocus) {
      btnFocus.addEventListener("click", () => {
        document.getElementById("workspace-root").classList.toggle("ws-focus");
      });
    }

    const btnFullscreen = document.getElementById("btn-fullscreen");
    if (btnFullscreen) {
      btnFullscreen.addEventListener("click", () => {
        if (document.fullscreenElement) {
          document.exitFullscreen();
        } else {
          document.documentElement.requestFullscreen?.();
        }
      });
    }

    const chatInput = document.getElementById("ws-chat-input");
    const chatSend = document.getElementById("ws-chat-send");
    function sendChat() {
      const text = (chatInput.value || "").trim();
      if (!text) return;
      chatInput.value = "";
      avatar.speak(text.length > 90 ? text.slice(0, 90) + "…" : text);
      setTimeout(() => {
        avatar.setMode("thinking");
        avatar.speak(
          "المساعد النصي التفاعلي غير مفعّل بعد. استخدم أزرار التحليل قراءة فقط في الأعلى."
        );
      }, 1200);
    }
    if (chatSend) chatSend.addEventListener("click", sendChat);
    if (chatInput) {
      chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendChat();
      });
    }

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

    let _resizeTimer = null;
    window.addEventListener("resize", () => {
      if (windowManager) windowManager.relayout();
      clearTimeout(_resizeTimer);
      _resizeTimer = setTimeout(() => {
        const session = store.getSession();
        if (session && session.avatar_state) {
          avatar.applyState(session.avatar_state);
        }
      }, 120);
    });

    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session");

    try {
      if (sessionId) {
        const data = await api(`/sessions/${sessionId}`);
        store.setSession(data.session);
        renderFromSession(data.session);
        const reportWin = (data.session.windows || []).find((w) => w.type === "live_report");
        const reportEmpty = !reportWin || !((reportWin.props || {}).lines || []).length;
        connectStream(sessionId, reportEmpty);
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
