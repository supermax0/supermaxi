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
  let flowLinksSvg = null;
  let windowTrayEl = null;
  let lastWorkspaceWindows = [];
  const openAuxWindowIds = new Set();

  const rootEl = document.getElementById("workspace-root");
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
  const commandSelect = document.getElementById("ws-command-select");
  const commandRun = document.getElementById("ws-command-run");
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
    syncCommandControls();
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
    syncCommandControls();
  }

  function updateCourierButton() {
    if (!btnCourierAnalysis) return;
    const busy = courierAnalysisClient && courierAnalysisClient.isBusy();
    btnCourierAnalysis.disabled = busy || !hasActiveDocument();
    syncCommandControls();
  }

  function setCourierBusy(busy) {
    if (!btnCourierAnalysis) return;
    btnCourierAnalysis.disabled = busy || !hasActiveDocument();
    btnCourierAnalysis.textContent = busy ? "جاري التحليل..." : "تحليل كشف التسديد قراءة فقط";
    btnCourierAnalysis.classList.toggle("ws-btn-loading", busy);
    syncCommandControls();
  }

  function setUploadBusy(busy) {
    if (btnUpload) {
      btnUpload.disabled = busy;
      btnUpload.textContent = busy ? "جاري الرفع..." : "رفع مستند";
      btnUpload.classList.toggle("ws-btn-loading", busy);
    }
    syncCommandControls();
  }

  function commandTarget(value) {
    return {
      upload: btnUpload,
      intelligence: btnIntelligence,
      courier: btnCourierAnalysis,
      workflow: btnWorkflow,
      select_workflow: btnSelectWorkflow,
      mock: btnRun,
      cancel: btnCancel,
    }[value];
  }

  function syncCommandControls() {
    if (!commandSelect || !commandRun) return;
    [...commandSelect.options].forEach((opt) => {
      const target = commandTarget(opt.value);
      opt.disabled = Boolean(target && target.disabled);
    });
    const selectedTarget = commandTarget(commandSelect.value);
    commandRun.disabled = Boolean(selectedTarget && selectedTarget.disabled);
  }

  function runSelectedCommand() {
    if (!commandSelect) return;
    const target = commandTarget(commandSelect.value);
    if (!target || target.disabled) return;
    target.click();
  }

  function selectMainReportWindow(windows) {
    const list = windows || [];
    return (
      list.find((w) => w.type === "courier_settlement_analysis") ||
      list.find((w) => w.type === "live_report") ||
      null
    );
  }

  function isMainWorkspaceWindow(windowSpec, reportWindow, docWindow) {
    if (!windowSpec) return false;
    return Boolean(
      (reportWindow && windowSpec.id === reportWindow.id) ||
      (docWindow && windowSpec.id === docWindow.id)
    );
  }

  function windowLabel(windowSpec) {
    const labels = {
      assistant_notes: "ملاحظات LEON",
      courier_rows: "الصفوف",
      courier_issues: "المشاكل",
      financial_preview: "مالية",
      document_intelligence: "فهم المستند",
      raw_table_preview: "الجداول",
      workflow_selector: "نوع العمل",
      approval_panel: "الموافقة",
      session_timeline: "الأحداث",
    };
    return labels[windowSpec.type] || windowSpec.title || windowSpec.type || "نافذة";
  }

  function escHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  function mergeWindowList(existing, nextWindow) {
    const list = [...(existing || [])];
    const idx = list.findIndex((w) => w.id === nextWindow.id);
    if (idx >= 0) list[idx] = nextWindow;
    else list.push(nextWindow);
    return list;
  }

  function normalizeWorkspaceWindows(windows) {
    const list = windows || [];
    const doc = list.find((w) => w.type === "document_viewer");
    const report = selectMainReportWindow(list);
    const auxiliary = list
      .filter((w) => !isMainWorkspaceWindow(w, report, doc))
      .filter((w) => openAuxWindowIds.has(w.id))
      .map((w) => ({ ...w, ui_auxiliary: true }));
    return [report, doc, ...auxiliary].filter(Boolean);
  }

  function ensureWindowTray() {
    if (windowTrayEl || !canvasEl) return windowTrayEl;
    windowTrayEl = document.createElement("div");
    windowTrayEl.id = "ws-window-tray";
    windowTrayEl.className = "ws-window-tray";
    canvasEl.appendChild(windowTrayEl);
    windowTrayEl.addEventListener("click", (event) => {
      const button = event.target.closest("[data-window-id]");
      if (!button) return;
      const id = button.dataset.windowId;
      if (!id) return;
      if (openAuxWindowIds.has(id)) {
        openAuxWindowIds.delete(id);
      } else {
        openAuxWindowIds.add(id);
      }
      renderWorkspaceWindows(lastWorkspaceWindows);
    });
    return windowTrayEl;
  }

  function renderWindowTray(windows) {
    const tray = ensureWindowTray();
    if (!tray) return;
    const list = windows || [];
    const doc = list.find((w) => w.type === "document_viewer");
    const report = selectMainReportWindow(list);
    const auxiliary = list.filter((w) => !isMainWorkspaceWindow(w, report, doc));
    if (!auxiliary.length) {
      tray.hidden = true;
      tray.innerHTML = "";
      return;
    }

    tray.hidden = false;
    tray.innerHTML = `
      <span class="ws-window-tray-title">النوافذ</span>
      <div class="ws-window-tray-list">
        ${auxiliary
          .map((w) => {
            const active = openAuxWindowIds.has(w.id);
            return `<button type="button" class="ws-window-tray-btn ${active ? "active" : ""}" data-window-id="${escHtml(w.id)}">${escHtml(windowLabel(w))}</button>`;
          })
          .join("")}
      </div>
    `;
  }

  function ensureFlowLinksSvg() {
    if (flowLinksSvg || !canvasEl) return flowLinksSvg;
    flowLinksSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    flowLinksSvg.setAttribute("id", "ws-flow-links");
    flowLinksSvg.setAttribute("class", "ws-flow-links");
    flowLinksSvg.setAttribute("aria-hidden", "true");
    flowLinksSvg.innerHTML = `
      <defs>
        <marker id="ws-flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z"></path>
        </marker>
      </defs>
      <path class="ws-flow-path ws-flow-path-preview" data-flow-path="preview"></path>
      <path class="ws-flow-path ws-flow-path-report" data-flow-path="report"></path>
    `;
    canvasEl.insertBefore(flowLinksSvg, canvasEl.firstChild);
    return flowLinksSvg;
  }

  function setFlowPath(name, start, end) {
    const svg = ensureFlowLinksSvg();
    const path = svg && svg.querySelector(`[data-flow-path="${name}"]`);
    if (!path || !start || !end) return;
    const midX = (start.x + end.x) / 2;
    path.setAttribute("d", `M ${start.x} ${start.y} C ${midX} ${start.y}, ${midX} ${end.y}, ${end.x} ${end.y}`);
  }

  function syncFlowScene() {
    if (!canvasEl || !windowManager || !avatar) return;
    rootEl?.classList.add("ws-flow-mode");
    avatar.moveTo(0.5, 0.52);

    const svg = ensureFlowLinksSvg();
    const canvasRect = canvasEl.getBoundingClientRect();
    svg.setAttribute("viewBox", `0 0 ${canvasRect.width} ${canvasRect.height}`);

    const docEntry = [...windowManager.windows.entries()].find(([, el]) => {
      const spec = JSON.parse(el.dataset.spec || "{}");
      return spec.type === "document_viewer";
    });
    const reportEntry = [...windowManager.windows.entries()].find(([, el]) => {
      const spec = JSON.parse(el.dataset.spec || "{}");
      return spec.type === "courier_settlement_analysis" || spec.type === "live_report";
    });
    const avatarCore = avatar.el && avatar.el.querySelector(".ws-leon-core");
    if (!docEntry || !reportEntry || !avatarCore) {
      svg.classList.add("ws-flow-links-hidden");
      return;
    }

    svg.classList.remove("ws-flow-links-hidden");
    const docRect = docEntry[1].getBoundingClientRect();
    const reportRect = reportEntry[1].getBoundingClientRect();
    const avatarRect = avatarCore.getBoundingClientRect();
    const circle = {
      x: avatarRect.left + avatarRect.width / 2 - canvasRect.left,
      y: avatarRect.top + avatarRect.height / 2 - canvasRect.top,
    };
    setFlowPath(
      "preview",
      { x: docRect.left - canvasRect.left, y: docRect.top + docRect.height / 2 - canvasRect.top },
      circle
    );
    setFlowPath(
      "report",
      circle,
      { x: reportRect.right - canvasRect.left, y: reportRect.top + reportRect.height / 2 - canvasRect.top }
    );
  }

  function renderWorkspaceWindows(windows) {
    lastWorkspaceWindows = windows || [];
    const visible = normalizeWorkspaceWindows(windows);
    renderWindowTray(windows);
    windowManager.renderWindows(visible);
    requestAnimationFrame(syncFlowScene);
  }

  function applyWorkspaceEvent(data) {
    if (!data || !windowManager) return;
    if (data.type === "window.opened" && data.payload && data.payload.window) {
      renderWorkspaceWindows(mergeWindowList(lastWorkspaceWindows, data.payload.window));
      return;
    }
    if (data.type === "window.updated" && data.payload && data.payload.windows) {
      renderWorkspaceWindows(data.payload.windows);
      return;
    }
    windowManager.applyEvent(data);
    requestAnimationFrame(syncFlowScene);
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
    renderWorkspaceWindows(windows);
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
    renderWorkspaceWindows(windows);
  }

  function renderFromSession(session) {
    if (!session) return;
    setStatus(session.status);
    const windows = ensureTimelineWindow(session);
    renderWorkspaceWindows(windows);
    avatar.applyState(session.avatar_state || {});
    avatar.moveTo(0.5, 0.52);
    updateIntelligenceButton();
    updateCourierButton();
    if (btnRun) {
      btnRun.disabled = session.status === "running" || session.status === "completed";
    }
    syncCommandControls();
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
        applyWorkspaceEvent(data);
      } else if (data.type === "report.appended") {
        // On replay we only re-hydrate the streaming report; window state is
        // already authoritative from the session GET, so we do not re-apply
        // replayed window/workflow events (which could resurrect stale cards).
        applyWorkspaceEvent(data);
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
        renderWorkspaceWindows(withTimeline);
        store.patchSession({ windows: data.payload.windows });
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

    eventStream.on("courier.posting.approval_required", () => {
      avatar.setMode("waiting_approval");
      avatar.speak("التنفيذ يحتاج موافقة صريحة.");
    });

    eventStream.on("courier.posting.started", () => {
      avatar.setMode("matching");
      avatar.speak("بدأ تنفيذ الصفوف المطابقة السليمة.");
    });

    eventStream.on("courier.posting.completed", () => {
      avatar.setMode("success");
      avatar.speak("اكتمل التنفيذ الآمن.");
      refreshSession();
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
      onCourierPostingApprove: async (spec) => {
        const analysisId = spec && spec.props && spec.props.analysisId;
        if (!analysisId || !courierAnalysisClient) return;
        try {
          await courierAnalysisClient.approvePosting(analysisId);
          avatar.setMode("success");
          avatar.speak("تم تنفيذ الطلبات المطابقة السليمة فقط.");
          await refreshSession();
        } catch (e) {
          alert(e.message || "فشل تنفيذ كشف التسديد");
        }
      },
      onCourierPostingReject: async (spec) => {
        const analysisId = spec && spec.props && spec.props.analysisId;
        if (!analysisId || !courierAnalysisClient) return;
        try {
          await courierAnalysisClient.cancelPosting(analysisId);
        } catch (e) {
          alert(e.message || "تعذر إلغاء الموافقة");
        }
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
      onSettle: async (spec) => {
        const aid = spec && spec.props && spec.props.analysisId;
        if (!aid) return;
        try {
          await courierAnalysisClient.preparePosting(aid);
          avatar.setMode("waiting_approval");
          avatar.speak("راجِع المعاينة ثم وافق على التنفيذ الآمن.");
        } catch (e) {
          alert(e.message || "تعذر تجهيز موافقة التنفيذ");
        }
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
    if (commandSelect) commandSelect.addEventListener("change", syncCommandControls);
    if (commandRun) commandRun.addEventListener("click", runSelectedCommand);
    window.addEventListener("ws:upload-request", () => uploadManager.openPicker());
    window.addEventListener("ws:upload-files", (event) => {
      const files = event.detail && event.detail.files ? event.detail.files : [];
      uploadManager.uploadCurrentSessionFiles(files);
    });
    window.addEventListener("ws:hide-window", (event) => {
      const id = event.detail && event.detail.windowId;
      if (!id) return;
      openAuxWindowIds.delete(id);
      renderWorkspaceWindows(lastWorkspaceWindows);
    });
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
        if (avatar) avatar.moveTo(0.5, 0.52);
        syncFlowScene();
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
