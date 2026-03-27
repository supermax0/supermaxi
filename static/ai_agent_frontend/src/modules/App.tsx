import React, { useMemo, useState, useEffect, useRef } from "react";
import { ReactFlowProvider, type Node, type Edge } from "reactflow";
import { NodeEditor } from "./NodeEditor";
import { useEditorStore } from "./store";

const MIN_PANEL = 200;
const MAX_PANEL = 500;
const DEFAULT_LEFT = 300;
const DEFAULT_RIGHT = 280;
const COLLAPSED_WIDTH = 40;

const NODE_TYPES: Array<{ id: string; label: string; icon: string; description: string; color: string }> = [
  { id: "start", label: "Start", icon: "⏵", description: "بداية تدفق العمل", color: "#22c55e" },
  { id: "ai", label: "AI Agent", icon: "🤖", description: "محتوى ونصوص بالذكاء الاصطناعي", color: "#8b5cf6" },
  { id: "image", label: "Image Generator", icon: "🖼", description: "إنشاء صور من وصف نصي", color: "#ec4899" },
  { id: "caption", label: "Caption Generator", icon: "✏️", description: "كتابة تعليق أو وصف للمنشور", color: "#3b82f6" },
  { id: "publisher", label: "Publisher", icon: "📤", description: "نشر على المنصات المختارة", color: "#f97316" },
  { id: "scheduler", label: "Scheduler", icon: "⏰", description: "جدولة النشر لوقت محدد", color: "#06b6d4" },
  { id: "comment-listener", label: "Comment Listener", icon: "💬", description: "مراقبة التعليقات والتفاعل", color: "#eab308" },
  { id: "keyword-filter", label: "Keyword Filter", icon: "🔍", description: "فلترة التعليقات حسب كلمات مفتاحية", color: "#a855f7" },
  { id: "auto-reply", label: "Auto Reply", icon: "✨", description: "رد تلقائي على التعليقات", color: "#ef4444" },
  { id: "publish-reply", label: "Publish Reply", icon: "📣", description: "نشر الرد على التعليق (FB/IG/TikTok)", color: "#f59e0b" },
  { id: "rate-limiter", label: "Rate Limiter", icon: "⏱", description: "تأخير بين الردود وحد أقصى للدقيقة", color: "#14b8a6" },
  { id: "logging", label: "Logging", icon: "📋", description: "تسجيل الأحداث في comment_logs", color: "#78716c" },
  { id: "duplicate-protection", label: "Duplicate Protection", icon: "🛡", description: "عدم الرد مرتين على نفس التعليق", color: "#64748b" },
  { id: "memory_store", label: "Store Data", icon: "🧺", description: "تخزين حقل من البيانات في سياق الوكيل", color: "#10b981" },
  { id: "knowledge_base", label: "Knowledge / Catalog", icon: "📚", description: "رفع كتالوج المنتجات أو قاعدة معرفة للـ AI", color: "#6366f1" },
  { id: "whatsapp_listener", label: "WhatsApp Listener", icon: "📲", description: "استقبال رسائل واتساب (Webhook)", color: "#22c55e" },
  { id: "whatsapp_send", label: "WhatsApp Send", icon: "📱", description: "إرسال رسالة أو اتصال واتساب", color: "#16a34a" },
  { id: "telegram_listener", label: "Telegram Listener", icon: "📨", description: "استقبال رسائل تيليجرام (Webhook)", color: "#0ea5e9" },
  { id: "telegram_send", label: "Telegram Send", icon: "✈️", description: "إرسال رسالة تيليجرام", color: "#0284c7" },
  {
    id: "conversation_context",
    label: "محادثة (سياق)",
    icon: "💬",
    description: "تحديث سجل المحادثة في السياق بعد الإرسال (للحجز وعقدة AI التالية)",
    color: "#38bdf8",
  },
  { id: "sql_save_order", label: "SQL حفظ الطلب", icon: "🗄", description: "حفظ الطلب/البيانات في قاعدة البيانات (SQL)", color: "#0d9488" },
  { id: "end", label: "End", icon: "■", description: "إنهاء التدفق وحفظ السياق", color: "#64748b" },
];

export const App: React.FC = () => {
  const meta = useEditorStore((s) => s.meta);
  const setMeta = useEditorStore((s) => s.setMeta);
  const { selectedNode } = useEditorStore((s) => ({
    selectedNode: s.nodes.find((n) => n.id === s.selectedNodeId),
  }));
  const nodes = useEditorStore((s) => s.nodes);
  const edges = useEditorStore((s) => s.edges);
  const updateNodeData = useEditorStore((s) => s.updateNodeData);
  const getGraphPayload = useEditorStore((s) => s.getGraphPayload);
  const loadFromGraph = useEditorStore((s) => s.loadFromGraph);
  const reset = useEditorStore((s) => s.reset);

  const [isSaving, setIsSaving] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [nodeLibraryOpen, setNodeLibraryOpen] = useState(false);
  const [workflowSearch, setWorkflowSearch] = useState("");
  const [workflowListOpen, setWorkflowListOpen] = useState(false);
  const [workflowsList, setWorkflowsList] = useState<Array<{ id: number; agent_id: number; name: string; description?: string; is_active?: boolean; graph?: { nodes?: Node[]; edges?: Edge[] } }>>([]);
  const [testMode, setTestMode] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [leftPanelWidth, setLeftPanelWidth] = useState(DEFAULT_LEFT);
  const [rightPanelWidth, setRightPanelWidth] = useState(DEFAULT_RIGHT);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [resizing, setResizing] = useState<"left" | "right" | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const [dirty, setDirty] = useState(false);

  const effectiveLeftWidth = leftCollapsed ? COLLAPSED_WIDTH : leftPanelWidth;
  const effectiveRightWidth = rightCollapsed ? COLLAPSED_WIDTH : rightPanelWidth;

  useEffect(() => {
    if (resizing === null) return;
    const isRtl = document.documentElement.dir === "rtl" || document.documentElement.getAttribute("dir") === "rtl";
    const onMove = (e: MouseEvent) => {
      const grid = gridRef.current;
      if (!grid) return;
      const rect = grid.getBoundingClientRect();
      if (resizing === "left") {
        const raw = isRtl ? rect.right - e.clientX : e.clientX - rect.left;
        setLeftPanelWidth(Math.min(MAX_PANEL, Math.max(MIN_PANEL, raw)));
      } else {
        const raw = isRtl ? e.clientX - rect.left : rect.right - e.clientX;
        setRightPanelWidth(Math.min(MAX_PANEL, Math.max(MIN_PANEL, raw)));
      }
    };
    const onUp = () => setResizing(null);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [resizing]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setUserMenuOpen(false);
        setNodeLibraryOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const apiBase = useMemo(
    () => ((window as any).AI_AGENT_API_BASE as string) || "/autoposter/api",
    [],
  );
  /** Fixed base for workflow API to avoid duplicated /api in path (e.g. /autoposter/api/api/workflows). */
  const workflowsApiBase = "/autoposter/api";

  const loginUrl = useMemo(
    () => ((window as any).AUTOPOSTER_LOGIN_URL as string) || "/login",
    [],
  );

  const settingsUrl = useMemo(
    () => ((window as any).AI_AGENT_SETTINGS_URL as string) || "/autoposter#settings",
    [],
  );

  useEffect(() => {
    const loadInitialWorkflow = async () => {
      try {
        const params = new URLSearchParams(window.location.search);
        const workflowId = params.get("workflow_id");
        if (workflowId) {
          const res = await fetch(`${workflowsApiBase}/workflows?workflow_id=${workflowId}`);
          if (!res.ok) return;
          const data = await res.json();
          const wf = data.workflow as {
            id: number;
            agent_id: number;
            name: string;
            description?: string;
            is_active?: boolean;
            graph?: { nodes?: Node[]; edges?: Edge[] };
          };
          if (!wf) return;
          const graph = wf.graph || {};
          const nodes = (graph.nodes || []) as Node[];
          const edges = (graph.edges || []) as Edge[];
          loadFromGraph({
            nodes: nodes.length ? nodes : [{ id: "start-1", type: "start", position: { x: 0, y: 0 }, data: { label: "Start" } }],
            edges: edges || [],
            id: wf.id,
            agentId: wf.agent_id,
            meta: {
              name: wf.name,
              description: wf.description || "",
              isActive: wf.is_active !== false,
            },
          });
          return;
        }

        const mode = params.get("mode");
        if (mode === "comment-reply") {
          createCommentReplyAgent();
          return;
        }
        if (mode === "telegram-comment-reply") {
          createTelegramCommentReplyAgent();
          return;
        }
        // mode === "new" أو بدون mode: نترك الـ initialNodes كما هي

        const res = await fetch(`${workflowsApiBase}/workflows`);
        if (!res.ok) return;
        const data = await res.json();
        const workflows = (data.workflows || []) as Array<{
          id: number;
          agent_id: number;
          name: string;
          description?: string;
          is_active?: boolean;
          graph?: { nodes?: Node[]; edges?: Edge[] };
        }>;
        if (!workflows.length) return;
        const wf = workflows[0];
        const graph = wf.graph || {};
        const nodes = (graph.nodes || []) as Node[];
        const edges = (graph.edges || []) as Edge[];
        if (!nodes.length) return;
        loadFromGraph({
          nodes,
          edges,
          id: wf.id,
          agentId: wf.agent_id,
          meta: {
            name: wf.name,
            description: wf.description || "",
            isActive: wf.is_active !== false,
          },
        });
      } catch {
        // ignore initial load errors
      }
    };
    loadInitialWorkflow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  // علّم أن هناك تغييرات على الجراف (nodes / edges) ليتم الحفظ التلقائي
  useEffect(() => {
    if (!meta.id) return;
    setDirty(true);
  }, [nodes, edges, meta.id]);

  const createCommentReplyAgent = () => {
    const nodes: Node[] = [
      {
        id: "start-1",
        type: "start",
        position: { x: 0, y: 0 },
        data: { label: "Start" },
      },
      {
        id: "comment-1",
        type: "comment-listener",
        position: { x: 0, y: 140 },
        data: {
          label: "Comment Listener",
          platforms: ["facebook"],
          mode: "all",
        },
      },
      {
        id: "auto-reply-1",
        type: "auto-reply",
        position: { x: 0, y: 300 },
        data: {
          label: "Auto Reply",
          mode: "ai_generated",
          template:
            "شكرًا على تعليقك {{comment_text}} 🤍\nإذا تحب تفاصيل أكثر راسلنا على الخاص أو زر موقعنا.",
          tone: "friendly",
          language: "ar",
          platforms: ["facebook"],
        },
      },
      {
        id: "end-1",
        type: "end",
        position: { x: 0, y: 460 },
        data: { label: "End" },
      },
    ];

    const edges: Edge[] = [
      { id: "e-start-comment", source: "start-1", target: "comment-1", sourceHandle: "out", targetHandle: "in" },
      { id: "e-comment-auto", source: "comment-1", target: "auto-reply-1", sourceHandle: "out", targetHandle: "in" },
      { id: "e-auto-end", source: "auto-reply-1", target: "end-1", sourceHandle: "out", targetHandle: "in" },
    ];

    loadFromGraph({
      nodes,
      edges,
      meta: {
        name: "وكيل الرد على التعليقات",
        description: "وكيل مخصص لقراءة تعليقات فيسبوك والرد عليها تلقائياً.",
      },
    });
  };

  /** قالب تيليجرام المتقدّم: فلتر + منع تكرار update + معدّل لكل محادثة + ذاكرة + AI + إرسال + سجل */
  const createTelegramCommentReplyAgent = () => {
    const nodes: Node[] = [
      {
        id: "tg-listener",
        type: "telegram_listener",
        position: { x: 300, y: 0 },
        data: {
          label: "Telegram Listener",
          bot_token: "",
          enabled: false,
          subtitle: "Bot Token + تفعيل Webhook",
        },
      },
      {
        id: "filter",
        type: "keyword-filter",
        position: { x: 300, y: 115 },
        data: {
          label: "فلتر كلمات",
          keywords: [] as string[],
          subtitle: "فارغ = كل الرسائل؛ أو كلمات (سعر، طلب، استفسار)",
        },
      },
      {
        id: "dup",
        type: "duplicate-protection",
        position: { x: 300, y: 230 },
        data: {
          label: "منع تكرار التحديث",
          use_telegram_update_id: true,
          subtitle: "نفس update_id من تيليجرام لا يُعالج مرتين",
        },
      },
      {
        id: "rate",
        type: "rate-limiter",
        position: { x: 300, y: 345 },
        data: {
          label: "محدد المعدّل",
          delay_between_replies: 1.5,
          max_replies_per_minute: 25,
          per_chat: true,
          subtitle: "لكل محادثة على حدة",
        },
      },
      {
        id: "conv",
        type: "conversation_context",
        position: { x: 300, y: 460 },
        data: {
          label: "سياق المحادثة",
          max_chars: 8000,
          include_current_message: true,
          include_last_reply: true,
          subtitle: "ذاكرة الجلسة + آخر رد",
        },
      },
      {
        id: "ai",
        type: "ai",
        position: { x: 300, y: 590 },
        data: {
          label: "AI — رد للزبون",
          task: "reply_comment",
          language: "ar",
          tone: "مهني ودود وواضح",
          temperature: 0.38,
          max_tokens: 1000,
          prompt:
            "أنت ممثل خدمة عملاء عبر تيليجرام. ردّ بلهجة مهنية ولطيفة وموجزة.\nاعتمد على سجل المحادثة في تعليمات النظام للتماسك؛ لا تتناقض مع ما سبق.\nلا تكرّر ترحيباً طويلاً في كل رسالة.\n\nآخر رسالة من الزبون:\n{{message_text}}",
        },
      },
      {
        id: "tg-send",
        type: "telegram_send",
        position: { x: 300, y: 720 },
        data: {
          label: "Telegram Send",
          chat_id: "{{chat_id}}",
          template: "{{reply_text}}",
          send_product_images: false,
          subtitle: "إرسال الرد",
        },
      },
      {
        id: "log",
        type: "logging",
        position: { x: 300, y: 835 },
        data: {
          label: "تسجيل في السجلات",
          subtitle: "comment_logs",
        },
      },
      {
        id: "end-1",
        type: "end",
        position: { x: 300, y: 950 },
        data: { label: "End", subtitle: "انتهاء" },
      },
    ];

    const edges: Edge[] = [
      { id: "e1", source: "tg-listener", target: "filter", sourceHandle: "out", targetHandle: "in" },
      { id: "e2", source: "filter", target: "dup", sourceHandle: "out", targetHandle: "in" },
      { id: "e3", source: "dup", target: "rate", sourceHandle: "out", targetHandle: "in" },
      { id: "e4", source: "rate", target: "conv", sourceHandle: "out", targetHandle: "in" },
      { id: "e5", source: "conv", target: "ai", sourceHandle: "out", targetHandle: "in" },
      { id: "e6", source: "ai", target: "tg-send", sourceHandle: "out", targetHandle: "in" },
      { id: "e7", source: "tg-send", target: "log", sourceHandle: "out", targetHandle: "in" },
      { id: "e8", source: "log", target: "end-1", sourceHandle: "out", targetHandle: "in" },
    ];

    loadFromGraph({
      nodes,
      edges,
      meta: {
        name: "تيليجرام: رد احترافي",
        description:
          "فلتر كلمات، منع معالجة نفس التحديث مرتين، معدّد لكل محادثة، ذاكرة، AI، إرسال، تسجيل.",
      },
    });
  };

  const handleDragStart = (event: React.DragEvent<HTMLLIElement>, nodeType: string) => {
    event.dataTransfer.setData("application/reactflow", nodeType);
    event.dataTransfer.effectAllowed = "move";
  };

  const showToast = (type: "success" | "error", message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3500);
  };

  const ensureAgentId = async (): Promise<number | null> => {
    try {
      const res = await fetch(`${apiBase}/agents`);
      if (!res.ok) return null;
      const data = await res.json();
      const first = data.agents?.[0];
      if (first?.id) {
        setMeta({ agentId: first.id });
        return first.id as number;
      }
      const createRes = await fetch(`${apiBase}/agents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Agent افتراضي" }),
      });
      if (!createRes.ok) return null;
      const created = await createRes.json();
      if (created.agent?.id) {
        setMeta({ agentId: created.agent.id });
        return created.agent.id as number;
      }
    } catch (e) {
      // ignore – سيتم عرض رسالة للمستخدم
    }
    return null;
  };

  const handleSave = async () => {
    const { meta: currentMeta, nodes, edges } = getGraphPayload();
    if (!nodes.length) {
      showToast("error", "أضف على الأقل عقدة واحدة قبل الحفظ.");
      return;
    }
    setIsSaving(true);
    try {
      const agentId = currentMeta.agentId || (await ensureAgentId());
      if (!agentId) {
        showToast("error", "تعذر العثور على Agent لاستخدامه مع هذا الوورك فلو.");
        return;
      }

      const payload = {
        agent_id: agentId,
        name: currentMeta.name || "وورك فلو بدون اسم",
        description: currentMeta.description || "",
        is_active: currentMeta.isActive,
        graph: {
          nodes: nodes.map((n) => ({
            id: n.id,
            type: n.type,
            data: n.data,
            position: n.position,
          })),
          edges: edges.map((e) => ({
            id: e.id,
            source: e.source,
            target: e.target,
            sourceHandle: (e as any).sourceHandle,
            targetHandle: (e as any).targetHandle,
          })),
        },
      };

      if (currentMeta.id) {
        const res = await fetch(`${workflowsApiBase}/workflows/${currentMeta.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error("فشل تحديث الوورك فلو");
        const data = await res.json();
        setMeta({ id: data.workflow?.id, agentId });
        showToast("success", "تم حفظ الوورك فلو بنجاح.");
      } else {
        const res = await fetch(`${workflowsApiBase}/workflows`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error("فشل إنشاء الوورك فلو");
        const data = await res.json();
        setMeta({ id: data.workflow?.id, agentId });
        showToast("success", "تم إنشاء الوورك فلو وحفظه.");
      }
      setDirty(false);
    } catch (err) {
      showToast("error", "حدث خطأ أثناء حفظ الوورك فلو.");
    } finally {
      setIsSaving(false);
    }
  };

  // الحفظ التلقائي مع تأخير بسيط (debounce)
  useEffect(() => {
    if (!dirty) return;
    if (!meta.id) return;
    const timer = window.setTimeout(() => {
      // لا ننتظر النتيجة، الهدف حفظ أفضل ما يمكن في الخلفية
      void handleSave();
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [dirty, nodes, edges, meta.id]);

  // حماية إضافية عند إغلاق الصفحة: إن كان هناك تغييرات غير محفوظة نحاول حفظها أو تحذير المستخدم
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirty || !meta.id) return;
      // محاولة حفظ سريعة في الخلفية
      void handleSave();
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
    // لا نضيف handleSave في التبعيات لتجنب إعادة ربط المستمع كثيراً
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, meta.id]);

  const handleRun = async () => {
    const { meta: currentMeta } = getGraphPayload();
    if (!currentMeta.id) {
      showToast("error", "احفظ الوورك فلو أولاً قبل تشغيله.");
      return;
    }
    setIsRunning(true);
    try {
      const res = await fetch(`${workflowsApiBase}/workflows/${currentMeta.id}/run`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("failed");
      showToast("success", "تم إرسال الوورك فلو للتنفيذ.");
    } catch {
      showToast("error", "تعذر تشغيل الوورك فلو.");
    } finally {
      setIsRunning(false);
    }
  };

  const handleMetaChange = (field: "name" | "description") => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setMeta({ [field]: e.target.value });
  };

  const handleNodeLabelChange = (value: string) => {
    if (!selectedNode) return;
    const extra: Record<string, unknown> = {};
    if (selectedNode.type === "ai") {
      extra.name = value;
    }
    updateNodeData(selectedNode.id, { label: value, ...extra });
  };

  const handleNodeTopicChange = (value: string) => {
    if (!selectedNode) return;
    const key = selectedNode.type === "image" ? "prompt" : "topic";
    updateNodeData(selectedNode.id, { [key]: value });
  };

  const handleAiFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      if (!selectedNode || selectedNode.type !== "ai") return;
      const value =
        e.target.type === "number"
          ? (e.target as HTMLInputElement).valueAsNumber || 0
          : e.target.value;
      updateNodeData(selectedNode.id, { [field]: value });
    };

  const handleAiTemperatureChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selectedNode || selectedNode.type !== "ai") return;
    const value = parseFloat(e.target.value);
    updateNodeData(selectedNode.id, { temperature: isNaN(value) ? 0.7 : value });
  };

  const handleImageFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLTextAreaElement | HTMLSelectElement>) => {
      if (!selectedNode || selectedNode.type !== "image") return;
      updateNodeData(selectedNode.id, { [field]: e.target.value });
    };

  const handleCaptionFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLTextAreaElement | HTMLSelectElement | HTMLInputElement>) => {
      if (!selectedNode || selectedNode.type !== "caption") return;
      const value =
        e.target.type === "number"
          ? (e.target as HTMLInputElement).valueAsNumber || 0
          : e.target.value;
      updateNodeData(selectedNode.id, { [field]: value });
    };

  const handlePublisherFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLTextAreaElement | HTMLSelectElement | HTMLInputElement>) => {
      if (!selectedNode || selectedNode.type !== "publisher") return;
      const value =
        e.target.type === "number"
          ? (e.target as HTMLInputElement).valueAsNumber || 0
          : e.target.value;
      updateNodeData(selectedNode.id, { [field]: value });
    };

  const handlePublisherPlatformToggle = (platform: string) => {
    if (!selectedNode || selectedNode.type !== "publisher") return;
    const current: string[] = (selectedNode.data as any)?.platforms || [];
    const exists = current.includes(platform);
    const next = exists ? current.filter((p) => p !== platform) : [...current, platform];
    updateNodeData(selectedNode.id, { platforms: next });
  };

  const handleSchedulerFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) => {
      if (!selectedNode || selectedNode.type !== "scheduler") return;
      updateNodeData(selectedNode.id, { [field]: e.target.value });
    };

  const handleCommentListenerPlatformToggle = (platform: string) => {
    if (!selectedNode || selectedNode.type !== "comment-listener") return;
    const current: string[] = (selectedNode.data as any)?.platforms || [];
    const next = current.includes(platform)
      ? current.filter((p) => p !== platform)
      : [...current, platform];
    updateNodeData(selectedNode.id, { platforms: next });
  };

  const handleCommentListenerFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLSelectElement | HTMLTextAreaElement | HTMLInputElement>) => {
      if (!selectedNode || selectedNode.type !== "comment-listener") return;
      updateNodeData(selectedNode.id, { [field]: e.target.value });
    };

  const [commentsPreview, setCommentsPreview] = useState<
    Array<{ platform: string; comment_id: string; username?: string; text: string; timestamp?: string }>
  >([]);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [commentsError, setCommentsError] = useState<string | null>(null);

  const handleLoadCommentsPreview = async () => {
    if (!selectedNode || selectedNode.type !== "comment-listener") return;
    const data = selectedNode.data as any;
    const platforms: string[] = data.platforms || ["facebook"];
    const platform = (platforms[0] || "facebook") as string;

    const postIdKey = platform === "facebook" ? "post_id" : platform === "instagram" ? "media_id" : "video_id";
    const idValue = (data[postIdKey] as string | undefined)?.trim();
    if (!idValue) {
      setCommentsError(
        platform === "facebook"
          ? "أدخل معرف منشور فيسبوك (post_id) أولاً."
          : platform === "instagram"
          ? "أدخل معرف منشور إنستغرام (media_id) أولاً."
          : "أدخل معرف فيديو تيك توك (video_id) أولاً.",
      );
      setCommentsPreview([]);
      return;
    }

    setCommentsLoading(true);
    setCommentsError(null);
    try {
      const body: any = { platform, limit: 10 };
      body[postIdKey] = idValue;
      const res = await fetch("/social-ai/api/comments/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || "فشل جلب التعليقات.");
      }
      const json = await res.json();
      if (!json.success) {
        throw new Error(json.error || "فشل جلب التعليقات.");
      }
      setCommentsPreview(json.comments || []);
    } catch (e: any) {
      setCommentsError(e.message || "فشل جلب التعليقات.");
      setCommentsPreview([]);
    } finally {
      setCommentsLoading(false);
    }
  };

  const handleAutoReplyFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLSelectElement | HTMLTextAreaElement>) => {
      if (!selectedNode || selectedNode.type !== "auto-reply") return;
      updateNodeData(selectedNode.id, { [field]: e.target.value });
    };

  const handleAutoReplyPlatformToggle = (platform: string) => {
    if (!selectedNode || selectedNode.type !== "auto-reply") return;
    const current: string[] = (selectedNode.data as any)?.platforms || [];
    const next = current.includes(platform)
      ? current.filter((p) => p !== platform)
      : [...current, platform];
    updateNodeData(selectedNode.id, { platforms: next });
  };

  const handleMessagingFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      if (
        !selectedNode ||
        (selectedNode.type !== "whatsapp_send" &&
          selectedNode.type !== "telegram_send" &&
          selectedNode.type !== "whatsapp_listener" &&
          selectedNode.type !== "telegram_listener")
      )
        return;
      const value =
        e.target.type === "number"
          ? (e.target as HTMLInputElement).valueAsNumber || 0
          : e.target.value;
      updateNodeData(selectedNode.id, { [field]: value });
    };

  const handleMemoryFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      if (!selectedNode || selectedNode.type !== "memory_store") return;
      updateNodeData(selectedNode.id, { [field]: e.target.value });
    };

  const handleKnowledgeFieldChange =
    (field: string) =>
    (e: React.ChangeEvent<HTMLTextAreaElement | HTMLSelectElement | HTMLInputElement>) => {
      if (!selectedNode || selectedNode.type !== "knowledge_base") return;
      const value =
        e.target.type === "number"
          ? (e.target as HTMLInputElement).valueAsNumber || 0
          : e.target.value;
      updateNodeData(selectedNode.id, { [field]: value });
    };

  return (
    <div
      className={`wf-app-root flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden text-[#e5e7eb] bg-[#0b1220]${
        isRunning ? " wf-running" : ""
      }`}
      dir="rtl"
    >
      <header
        className="flex h-16 shrink-0 items-center justify-between gap-4 border-b border-[#1e293b] bg-[#0b1220] px-4"
        style={{ height: "64px" }}
        role="banner"
      >
        <div className="flex flex-col gap-0.5 min-w-0">
          <h1 className="text-base font-semibold text-slate-200 shrink-0" id="main-title">
            AI Agent Builder
          </h1>
          <div className="text-[11px] text-slate-400 truncate max-w-xs">
            الوكيل الحالي:{" "}
            <span className="text-slate-200">
              {meta.name && meta.name.trim() ? meta.name.trim() : "وورك فلو جديد"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-1 justify-center max-w-xl flex-wrap">
          <button
            type="button"
            className="rounded-lg border border-[#22c55e] bg-[#22c55e]/10 px-3 py-2 text-xs font-medium text-[#22c55e] hover:bg-[#22c55e]/20"
            onClick={() => { reset(); setWorkflowListOpen(false); }}
            aria-label="وورك فلو جديد"
          >
            + وورك فلو جديد
          </button>
          <div className="relative">
            <button
              type="button"
              className="rounded-lg border border-[#1e293b] bg-[#0f172a] px-3 py-2 text-sm text-[#e5e7eb] hover:bg-[#1e293b] min-w-[140px] text-right"
              onClick={async () => {
                if (!workflowListOpen) {
                  try {
                    const res = await fetch(`${workflowsApiBase}/workflows`);
                    if (res.ok) {
                      const data = await res.json();
                      setWorkflowsList((data.workflows || []) as typeof workflowsList);
                    }
                  } catch {
                    setWorkflowsList([]);
                  }
                }
                setWorkflowListOpen((v) => !v);
              }}
              aria-label="اختر وورك فلو"
              aria-expanded={workflowListOpen}
            >
              اختر وورك فلو ▼
            </button>
            {workflowListOpen && (
              <>
                <div className="fixed inset-0 z-10" aria-hidden onClick={() => setWorkflowListOpen(false)} />
                <div className="absolute left-0 rtl:right-0 rtl:left-auto top-full mt-1 z-20 w-64 max-h-60 overflow-y-auto rounded-lg border border-[#1e293b] bg-[#111827] py-1 shadow-lg">
                  <input
                    className="w-full px-3 py-2 text-xs border-b border-[#1e293b] bg-transparent text-[#e5e7eb] placeholder:text-slate-500 focus:outline-none"
                    placeholder="بحث..."
                    value={workflowSearch}
                    onChange={(e) => setWorkflowSearch(e.target.value)}
                  />
                  {workflowsList
                    .filter((wf) => !workflowSearch.trim() || (wf.name || "").toLowerCase().includes(workflowSearch.toLowerCase()))
                    .map((wf) => (
                      <button
                        key={wf.id}
                        type="button"
                        className="w-full text-right px-3 py-2 text-sm text-slate-200 hover:bg-[#1e293b] border-b border-[#1e293b]/50 last:border-0"
                        onClick={() => {
                          const graph = wf.graph || {};
                          const nodes = (graph.nodes || []) as Node[];
                          const edges = (graph.edges || []) as Edge[];
                          loadFromGraph({
                            nodes: nodes.length ? nodes : [{ id: "start-1", type: "start", position: { x: 0, y: 0 }, data: { label: "Start" } }],
                            edges: edges || [],
                            id: wf.id,
                            agentId: wf.agent_id,
                            meta: { name: wf.name, description: wf.description || "", isActive: wf.is_active !== false },
                          });
                          setWorkflowListOpen(false);
                        }}
                      >
                        {wf.name || `وورك فلو #${wf.id}`}
                      </button>
                    ))}
                  {workflowsList.length === 0 && (
                    <div className="px-3 py-4 text-xs text-slate-500">لا يوجد وورك فلو. أنشئ واحداً من «+ وورك فلو جديد» ثم احفظه.</div>
                  )}
                </div>
              </>
            )}
          </div>
          <input
            className="w-full max-w-[180px] rounded-lg border border-[#1e293b] bg-[#0f172a] px-3 py-2 text-sm text-[#e5e7eb] placeholder:text-slate-500 focus:border-[#22c55e] focus:outline-none"
            placeholder="اسم الوورك فلو"
            value={meta.name}
            onChange={handleMetaChange("name")}
            aria-label="اسم الوورك فلو"
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <a
            href="/social-ai/telegram/inbox"
            className="hidden md:inline-flex rounded-lg border border-[#0ea5e9] bg-[#0ea5e9]/10 px-3 py-2 text-xs font-medium text-[#38bdf8] hover:bg-[#0ea5e9]/20"
          >
            محادثات تيليجرام
          </a>
          <button
            type="button"
            className="hidden md:inline-flex rounded-lg border border-[#1e293b] bg-[#1e293b] px-3 py-2 text-xs font-medium text-slate-300 hover:bg-[#334155]"
            onClick={createCommentReplyAgent}
          >
            قالب وكيل رد التعليقات
          </button>
          <button
            type="button"
            className="hidden lg:inline-flex rounded-lg border border-[#0ea5e9]/50 bg-[#0c4a6e]/30 px-3 py-2 text-xs font-medium text-sky-200 hover:bg-[#0c4a6e]/50"
            onClick={createTelegramCommentReplyAgent}
            title="Listener → فلتر كلمات → AI → إرسال (مثل قالب التعليقات)"
          >
            قالب وكيل رد تيليجرام
          </button>
          <button
            type="button"
            className="rounded-lg border border-[#1e293b] bg-[#1e293b] px-3 py-2 text-sm font-medium text-[#e5e7eb] hover:bg-[#334155] disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
            onClick={handleSave}
            disabled={isSaving}
            aria-label={isSaving ? "جارٍ الحفظ" : "حفظ"}
          >
            {isSaving ? "جارٍ الحفظ..." : "حفظ"}
          </button>
          <button
            type="button"
            className="rounded-lg px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
            style={{ background: "linear-gradient(135deg, #22c55e, #4ade80)", borderRadius: "8px", padding: "8px 14px" }}
            onClick={handleRun}
            disabled={isRunning}
            aria-label={isRunning ? "جارٍ التشغيل" : "تشغيل الآن"}
          >
            {isRunning ? "جارٍ التشغيل..." : "تشغيل الآن"}
          </button>
          <button
            type="button"
            onClick={() => setTestMode((v) => !v)}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${testMode ? "bg-[#22c55e]/20 text-[#22c55e] border border-[#22c55e]" : "border border-[#1e293b] bg-[#1e293b] text-slate-300 hover:bg-[#334155]"}`}
            title="وضع الاختبار"
            aria-pressed={testMode}
            aria-label="وضع الاختبار"
          >
            وضع اختبار
          </button>
          <div className="relative">
            <button
              type="button"
              onClick={() => setUserMenuOpen((v) => !v)}
              className="flex items-center gap-2 rounded-lg border border-[#1e293b] bg-[#1e293b] px-3 py-2 text-sm text-slate-300 hover:bg-[#334155]"
              aria-label="قائمة المستخدم"
              aria-expanded={userMenuOpen}
              aria-haspopup="true"
            >
              <span className="w-6 h-6 rounded-full bg-slate-600 flex items-center justify-center text-xs">م</span>
              <span className="hidden sm:inline">المستخدم</span>
            </button>
            {userMenuOpen && (
              <>
                <div className="fixed inset-0 z-10" aria-hidden onClick={() => setUserMenuOpen(false)} />
                <div className="absolute left-0 rtl:right-0 rtl:left-auto top-full mt-1 z-20 min-w-[140px] rounded-lg border border-[#1e293b] bg-[#111827] py-1 shadow-lg" role="menu">
                  <div className="px-3 py-2 text-xs text-slate-400 border-b border-[#1e293b]">الحساب</div>
                  <button
                    type="button"
                    className="w-full text-right px-3 py-2 text-sm text-slate-200 hover:bg-[#1e293b]"
                    role="menuitem"
                    onClick={() => {
                      setUserMenuOpen(false);
                      window.location.href = settingsUrl;
                    }}
                  >
                    الإعدادات
                  </button>
                  <button
                    type="button"
                    className="w-full text-right px-3 py-2 text-sm text-slate-200 hover:bg-[#1e293b]"
                    role="menuitem"
                    onClick={async () => {
                      setUserMenuOpen(false);
                      try {
                        await fetch(`${apiBase}/logout`, { method: "POST" });
                      } catch {
                        // تجاهل الأخطاء البسيطة، سيتم إعادة التوجيه على أي حال
                      }
                      window.location.href = loginUrl;
                    }}
                  >
                    تسجيل الخروج
                  </button>
                </div>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={() => setNodeLibraryOpen((v) => !v)}
            className="xl:hidden rounded-lg border border-[#1e293b] bg-[#1e293b] px-3 py-2 text-sm font-medium text-slate-300 hover:bg-[#334155]"
            title="مكتبة العقد"
            aria-label="مكتبة العقد"
          >
            مكتبة العقد
          </button>
        </div>
      </header>
      <div
        ref={gridRef}
        className="wf-grid-narrow grid min-h-0 min-w-0 flex-1 w-full overflow-hidden select-none"
        style={{
          gridTemplateColumns: `${effectiveLeftWidth}px 6px 1fr 6px ${effectiveRightWidth}px`,
          gridAutoRows: "1fr",
        }}
      >
        <aside
          className="wf-panel-settings flex min-h-0 flex-col overflow-hidden border-e border-[#1f2937] bg-[#111827]"
          style={{ padding: leftCollapsed ? 0 : 16 }}
          aria-label="إعدادات العقدة"
        >
          {leftCollapsed ? (
            <div className="flex h-full w-full flex-col items-center justify-center gap-1 border-e border-[#1f2937] bg-[#111827] py-2">
              <button
                type="button"
                onClick={() => setLeftCollapsed(false)}
                className="rounded p-1.5 text-slate-400 hover:bg-[#1e293b] hover:text-[#e5e7eb]"
                title="توسيع إعدادات العقدة"
                aria-label="توسيع إعدادات العقدة"
              >
                <span className="inline-block rotate-90 whitespace-nowrap text-[10px] font-medium">إعدادات</span>
              </button>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-2 border-b border-[#1e293b] pb-2 mb-2">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">إعدادات العقدة</h2>
                <button
                  type="button"
                  onClick={() => setLeftCollapsed(true)}
                  className="rounded p-1 text-slate-500 hover:bg-[#1e293b] hover:text-slate-300 rtl:rotate-180"
                  title="تصغير لوحة الإعدادات"
                  aria-label="تصغير لوحة الإعدادات"
                >
                  ◀
                </button>
              </div>
              <div className="flex-1 overflow-y-auto min-h-0 px-4 pb-4">
            {!selectedNode && (
              <div className="space-y-2 text-xs text-slate-400">
                <p>
                  اختر عقدة من الكانفس لعرض إعداداتها هنا (الاسم، التعليمات، الموديل، المدخلات،
                  المخرجات...).
                </p>
                <p className="rounded bg-amber-900/30 border border-amber-700/40 p-2 text-[11px] text-amber-200/90">
                  <strong className="text-amber-200">حفظ الوكيل:</strong> استخدم زر «حفظ» في الشريط العلوي لحفظ الوورك فلو. بعد الحفظ يمكنك تشغيله بزر «تشغيل الآن».
                </p>
                <button
                  type="button"
                  className="w-full rounded-lg border border-[#22c55e] bg-[#22c55e]/20 px-3 py-2 text-xs font-medium text-[#22c55e] hover:bg-[#22c55e]/30"
                  onClick={handleSave}
                  disabled={isSaving}
                >
                  {isSaving ? "جارٍ الحفظ..." : "حفظ الوورك فلو"}
                </button>
                <p className="rounded bg-slate-800/60 p-2 text-[11px] text-slate-400">
                  <strong className="text-slate-300">ربط العقد:</strong> اسحب من النقطة الدائرية
                  أسفل عقدة إلى النقطة فوق العقدة التالية لإنشاء تسلسل الوورك فلو.
                </p>
              </div>
            )}
            {selectedNode && (
              <div className="space-y-4 text-xs text-[#e5e7eb]">
                <div className="rounded-lg border border-[#334155] bg-[#0f172a] p-3">
                  <div className="mb-1.5 text-[11px] font-medium text-slate-400">الإعدادات الأساسية</div>
                  <div className="mb-2 text-[11px] text-slate-500">نوع العقدة: {selectedNode.type}</div>
                  <label className="mb-1 block text-[11px] text-slate-400">الاسم الظاهر</label>
                  <input
                    className="w-full rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                    value={(selectedNode.data as any)?.label || ""}
                    onChange={(e) => handleNodeLabelChange(e.target.value)}
                  />
                </div>
                {(selectedNode.type === "ai" || selectedNode.type === "image") && (
                  <div>
                    <label className="mb-1 block text-[11px] text-slate-400">
                      {selectedNode.type === "image"
                        ? "وصف الصورة (prompt)"
                        : "موضوع / وصف المنشور"}
                    </label>
                    <textarea
                      className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                      value={
                        (selectedNode.data as any)?.[
                          selectedNode.type === "image" ? "prompt" : "topic"
                        ] || ""
                      }
                      onChange={(e) => handleNodeTopicChange(e.target.value)}
                    />
                  </div>
                )}

                {selectedNode.type === "start" && (
                  <>
                    <div className="rounded-lg border border-[#334155] bg-[#0f172a] p-3">
                      <div className="mb-2 text-[11px] font-medium text-slate-400">إعدادات عقدة البداية</div>
                    <div className="space-y-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          الموضوع الابتدائي (اختياري)
                        </label>
                        <textarea
                          className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                          placeholder="مثال: عرض المنتج الجديد، أو موضوع البوست اليوم..."
                          value={(selectedNode.data as any)?.topic || ""}
                          onChange={(e) => updateNodeData(selectedNode.id, { topic: e.target.value })}
                        />
                        <p className="mt-1 text-[10px] text-slate-500">
                          يُضاف إلى سياق الوورك فلو كقيمة {"{{topic}}"} للعقد التالية.
                        </p>
                      </div>
                    </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "sql_save_order" && (
                  <>
                    <div className="rounded-lg border border-[#0d9488]/50 bg-[#0d9488]/5 p-3">
                      <div className="mb-2 text-[11px] font-medium text-[#0d9488]">حفظ الحجز / الطلب (قاعدة الشركة)</div>
                      <p className="text-[10px] text-slate-400 mb-2">
                        يُنشئ زبوناً إن لزم، ثم فاتورة (<code className="bg-[#1e293b] px-1 rounded">invoice</code>) بحالة قابلة للتعديل، مع سطر بيع (
                        <code className="bg-[#1e293b] px-1 rounded">order_item</code>
                        ). يعمل على خادم Flask عند تشغيل الوورك فلو. استخدم عقدة AI بنوع مهمة «حجز» أو مرّر الحقول في السياق، أو JSON في رد الـ AI.
                      </p>
                      <label className="flex items-center gap-2 text-[11px] text-slate-300 mb-2">
                        <input
                          type="checkbox"
                          checked={(selectedNode.data as any)?.skip_if_incomplete !== false}
                          onChange={(e) => updateNodeData(selectedNode.id, { skip_if_incomplete: e.target.checked })}
                        />
                        عدم إفشال الوورك فلو إن لم يكتمل الحجز (مُوصى به لتيليجرام — يمنع رسالة «تعذّر إكمال الطلب» بعد كل رد)
                      </label>
                      <div className="space-y-1.5 mb-2">
                        <div className="text-[10px] text-slate-500 font-medium">مدخلات السياق أو JSON في رد الـ AI:</div>
                        <ul className="text-[10px] text-slate-400 list-disc list-inside space-y-0.5">
                          <li><code className="bg-[#1e293b] px-1 rounded">name</code> / <code className="bg-[#1e293b] px-1 rounded">customer_name</code></li>
                          <li><code className="bg-[#1e293b] px-1 rounded">phone</code> — إن غاب يُستخدم <code className="bg-[#1e293b] px-1 rounded">tg-{"{chat_id}"}</code></li>
                          <li><code className="bg-[#1e293b] px-1 rounded">product_id</code> أو <code className="bg-[#1e293b] px-1 rounded">product_name</code></li>
                          <li><code className="bg-[#1e293b] px-1 rounded">quantity</code>، <code className="bg-[#1e293b] px-1 rounded">price</code> (اختياري)</li>
                        </ul>
                      </div>
                      <label className="mb-1 block text-[11px] text-slate-400">قناة افتراضية (channel)</label>
                      <input
                        className="w-full rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#0d9488] focus:outline-none mb-2"
                        placeholder="مثال: telegram, whatsapp"
                        value={(selectedNode.data as any)?.channel_default ?? ""}
                        onChange={(e) => updateNodeData(selectedNode.id, { channel_default: e.target.value })}
                      />
                      <label className="mb-1 block text-[11px] text-slate-400">حالة الفاتورة (invoice_status)</label>
                      <input
                        className="w-full rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#0d9488] focus:outline-none mb-2"
                        placeholder="مثال: حجز"
                        value={(selectedNode.data as any)?.invoice_status ?? "حجز"}
                        onChange={(e) => updateNodeData(selectedNode.id, { invoice_status: e.target.value })}
                      />
                      <label className="flex items-center gap-2 text-[11px] text-slate-300 mb-2">
                        <input
                          type="checkbox"
                          checked={(selectedNode.data as any)?.deduct_stock !== false}
                          onChange={(e) => updateNodeData(selectedNode.id, { deduct_stock: e.target.checked })}
                        />
                        خصم الكمية من المخزون عند الحجز
                      </label>
                      <label className="flex items-center gap-2 text-[11px] text-slate-300 mb-3">
                        <input
                          type="checkbox"
                          checked={Boolean((selectedNode.data as any)?.require_phone)}
                          onChange={(e) => updateNodeData(selectedNode.id, { require_phone: e.target.checked })}
                        />
                        إلزامي: رقم هاتف حقيقي (لا يكفي معرف تيليجرام)
                      </label>
                      <a
                        href="/orders"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 rounded-lg bg-[#0d9488] px-3 py-2 text-xs font-medium text-white hover:bg-[#0f766e] transition-colors"
                      >
                        📋 عرض جدول البيانات (الطلبات)
                      </a>
                      <p className="mt-1.5 text-[10px] text-slate-500">
                        صفحة الطلبات تعرض كل البيانات التي يدخلها الذكاء الاصطناعي عبر هذه العقدة.
                      </p>
                    </div>
                  </>
                )}

                {selectedNode.type === "conversation_context" && (
                  <>
                    <div className="rounded-lg border border-[#38bdf8]/40 bg-[#0c4a6e]/20 p-3">
                      <div className="mb-2 text-[11px] font-medium text-[#38bdf8]">سياق المحادثة للعقد التالية</div>
                      <p className="text-[10px] text-slate-400 mb-2">
                        ضع هذه العقدة بعد <strong className="text-slate-300">Telegram Send</strong> لتحديث{" "}
                        <code className="bg-[#1e293b] px-1 rounded">conversation_history</code> في السياق (يشمل آخر رد
                        أُرسل). ثم عقدة <strong className="text-slate-300">AI</strong> بمهمة «حجز» ثم{" "}
                        <strong className="text-slate-300">SQL حفظ الطلب</strong>.
                      </p>
                      <label className="mb-1 block text-[11px] text-slate-400">أقصى طول للنص (حرف)</label>
                      <input
                        type="number"
                        min={500}
                        max={50000}
                        className="w-full rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#38bdf8] focus:outline-none mb-2"
                        value={(selectedNode.data as any)?.max_chars ?? 6000}
                        onChange={(e) =>
                          updateNodeData(selectedNode.id, { max_chars: e.target.valueAsNumber || 6000 })
                        }
                      />
                      <label className="flex items-center gap-2 text-[11px] text-slate-300 mb-2">
                        <input
                          type="checkbox"
                          checked={(selectedNode.data as any)?.include_current_message !== false}
                          onChange={(e) =>
                            updateNodeData(selectedNode.id, { include_current_message: e.target.checked })
                          }
                        />
                        إدراج رسالة الزبون الحالية في السياق
                      </label>
                      <label className="flex items-center gap-2 text-[11px] text-slate-300">
                        <input
                          type="checkbox"
                          checked={(selectedNode.data as any)?.include_last_reply !== false}
                          onChange={(e) =>
                            updateNodeData(selectedNode.id, { include_last_reply: e.target.checked })
                          }
                        />
                        إدراج آخر رد أُرسل (telegram_message / reply_text)
                      </label>
                    </div>
                  </>
                )}

                {selectedNode.type === "end" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات عقدة النهاية
                    </div>
                    <div className="space-y-2">
                      <p className="text-[10px] text-slate-500">
                        عند الوصول لهذه العقدة يتم حفظ لقطة من السياق في سجل التنفيذ وإنهاء الوورك فلو.
                      </p>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          ملاحظة (اختياري)
                        </label>
                        <input
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs focus:border-rose-500 focus:outline-none"
                          placeholder="وصف أو تسمية لهذا النهاية..."
                          value={(selectedNode.data as any)?.note || ""}
                          onChange={(e) => updateNodeData(selectedNode.id, { note: e.target.value })}
                        />
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "ai" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات المهمة
                    </div>
                    <div className="space-y-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">نوع المهمة</label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.task || "generate_post"}
                          onChange={handleAiFieldChange("task")}
                        >
                          <option value="generate_post">توليد منشور كامل</option>
                          <option value="write_caption">كتابة كابشن</option>
                          <option value="reply_comment">رد على تعليق</option>
                          <option value="generate_topic">توليد أفكار موضوع</option>
                          <option value="booking">حجز للزبائن (يُخرج JSON للطلب)</option>
                          <option value="custom">مخصص</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          قالب الـ Prompt
                        </label>
                        <textarea
                          className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                          placeholder="مثال: أنشئ منشوراً تسويقياً عن {{topic}}"
                          value={(selectedNode.data as any)?.prompt || ""}
                          onChange={handleAiFieldChange("prompt")}
                        />
                        <div className="mt-1 text-[10px] text-slate-500">
                          يمكنك استخدام متغيرات من الوورك فلو مثل {"{{topic}}"} وسيتم استبدالها من
                          الـ context.
                        </div>
                      </div>
                    </div>

                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات النموذج
                    </div>
                    <div className="space-y-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          مفتاح API خاص بهذه العقدة (اختياري)
                        </label>
                        <input
                          type="password"
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          placeholder="اتركه فارغاً لاستخدام المفتاح الافتراضي من الإعدادات"
                          value={(selectedNode.data as any)?.api_key || ""}
                          onChange={handleAiFieldChange("api_key")}
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">Model</label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.model || "gpt-4o-mini"}
                          onChange={handleAiFieldChange("model")}
                        >
                          <option value="gpt-4o-mini">gpt-4o-mini</option>
                          <option value="gpt-4.1">gpt-4.1</option>
                          <option value="gpt-4o">gpt-4o</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          Temperature ({(selectedNode.data as any)?.temperature ?? 0.7})
                        </label>
                        <input
                          type="range"
                          min={0}
                          max={1}
                          step={0.05}
                          value={(selectedNode.data as any)?.temperature ?? 0.7}
                          onChange={handleAiTemperatureChange}
                          className="w-full"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          Max Tokens
                        </label>
                        <input
                          type="number"
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          min={32}
                          max={2000}
                          value={(selectedNode.data as any)?.max_tokens ?? 500}
                          onChange={handleAiFieldChange("max_tokens")}
                        />
                      </div>
                    </div>

                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات المحتوى
                    </div>
                    <div className="space-y-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">اللغة</label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.language || "ar"}
                          onChange={handleAiFieldChange("language")}
                        >
                          <option value="ar">العربية</option>
                          <option value="en">English</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">الأسلوب</label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.tone || "marketing"}
                          onChange={handleAiFieldChange("tone")}
                        >
                          <option value="marketing">تسويقي</option>
                          <option value="friendly">ودود</option>
                          <option value="professional">مهني</option>
                          <option value="casual">بسيط</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          الفئة المستهدفة
                        </label>
                        <input
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          placeholder="أصحاب المتاجر، طلاب، ..."
                          value={(selectedNode.data as any)?.target_audience || ""}
                          onChange={handleAiFieldChange("target_audience")}
                        />
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "image" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات الصورة
                    </div>
                    <div className="space-y-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          قالب الـ Prompt
                        </label>
                        <textarea
                          className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                          placeholder="مثال: أنشئ صورة إعلانية عن {{topic}}"
                          value={(selectedNode.data as any)?.prompt || ""}
                          onChange={handleImageFieldChange("prompt")}
                        />
                        <div className="mt-1 text-[10px] text-slate-500">
                          يمكن استخدام متغيرات من الوورك فلو مثل {"{{topic}}"} وسيتم
                          استبدالها من الـ context.
                        </div>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          نمط الصورة (Style)
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.style || "photorealistic"}
                          onChange={handleImageFieldChange("style")}
                        >
                          <option value="photorealistic">Photorealistic</option>
                          <option value="illustration">Illustration</option>
                          <option value="3d">3D render</option>
                          <option value="minimal">Minimal</option>
                          <option value="cinematic">Cinematic</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          المقاس (Size)
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.size || "1024x1024"}
                          onChange={handleImageFieldChange("size")}
                        >
                          <option value="1024x1024">1024x1024</option>
                          <option value="1536x1024">1536x1024</option>
                          <option value="1792x1024">1792x1024</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          مزوّد الخدمة
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.provider || "nanobanana"}
                          onChange={handleImageFieldChange("provider")}
                        >
                          <option value="openai">OpenAI</option>
                          <option value="nanobanana">Nano Banana</option>
                        </select>
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "caption" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات الكابشن
                    </div>
                    <div className="space-y-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          مصدر النص
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.source || "{{text}}"}
                          onChange={handleCaptionFieldChange("source")}
                        >
                          <option value="{{text}}">
                            من مخرجات AI ({"{{text}}"})
                          </option>
                          <option value="{{topic}}">
                            من الموضوع ({"{{topic}}"})
                          </option>
                          <option value="custom">نص مخصص</option>
                        </select>
                      </div>
                      {(selectedNode.data as any)?.source === "custom" && (
                        <div>
                          <label className="mb-1 block text-[11px] text-slate-400">
                            النص الأساسي
                          </label>
                          <textarea
                            className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                            value={(selectedNode.data as any)?.source_custom || ""}
                            onChange={handleCaptionFieldChange("source_custom")}
                          />
                        </div>
                      )}
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">الأسلوب</label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.style || "marketing"}
                          onChange={handleCaptionFieldChange("style")}
                        >
                          <option value="marketing">تسويقي</option>
                          <option value="short">قصير ومباشر</option>
                          <option value="storytelling">حكائي (Storytelling)</option>
                          <option value="informative">معلوماتي</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">اللغة</label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.language || "arabic"}
                          onChange={handleCaptionFieldChange("language")}
                        >
                          <option value="arabic">العربية</option>
                          <option value="english">English</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          الحد الأقصى للطول
                        </label>
                        <input
                          type="number"
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          min={50}
                          max={500}
                          value={(selectedNode.data as any)?.max_length ?? 200}
                          onChange={handleCaptionFieldChange("max_length")}
                        />
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "publisher" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات النشر
                    </div>
                    <div className="space-y-3">
                      <div>
                        <div className="mb-1 text-[11px] text-slate-400">المنصات</div>
                        <div className="flex flex-wrap gap-2">
                          {["facebook", "instagram", "tiktok"].map((p) => {
                            const selected = ((selectedNode.data as any)?.platforms || []).includes(
                              p,
                            );
                            return (
                              <button
                                key={p}
                                type="button"
                                onClick={() => handlePublisherPlatformToggle(p)}
                                className={`rounded-full px-3 py-1 text-[11px] ${
                                  selected
                                    ? "bg-emerald-600 text-white"
                                    : "bg-slate-800 text-slate-300"
                                }`}
                              >
                                {p}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          صفحات محددة (اختياري)
                        </label>
                        <input
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          placeholder="معرف الصفحة أو أكثر مفصولة بفاصلة، مثال: 123456,789012"
                          value={((selectedNode.data as any)?.account_ids as string[] | undefined)?.join(", ") ?? ""}
                          onChange={(e) => {
                            if (!selectedNode || selectedNode.type !== "publisher") return;
                            const raw = (e.target.value || "").trim();
                            const account_ids = raw ? raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean) : [];
                            updateNodeData(selectedNode.id, { account_ids: account_ids.length ? account_ids : undefined });
                          }}
                        />
                        <p className="mt-1 text-[10px] text-slate-500">
                          اتركه فارغاً لينشر على كل الحسابات المربوطة للمنصة. حدّد معرفات الصفحات لتجنب النشر على صفحات غير مرغوبة.
                        </p>
                      </div>

                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          نوع المنشور
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.post_type || "image_post"}
                          onChange={handlePublisherFieldChange("post_type")}
                        >
                          <option value="image_post">Image post</option>
                          <option value="video_post">Video post</option>
                          <option value="reel">Reel</option>
                          <option value="story">Story</option>
                        </select>
                      </div>

                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          مصدر الكابشن
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.caption_source || "{{text}}"}
                          onChange={handlePublisherFieldChange("caption_source")}
                        >
                          <option value="{{text}}">
                            من ناتج AI ({"{{text}}"})
                          </option>
                          <option value="{{caption}}">
                            من الكابشن الحالي ({"{{caption}}"})
                          </option>
                          <option value="custom">مخصص</option>
                        </select>
                      </div>

                      {(selectedNode.data as any)?.caption_source === "custom" && (
                        <div>
                          <label className="mb-1 block text-[11px] text-slate-400">
                            كابشن مخصص
                          </label>
                          <textarea
                            className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                            value={(selectedNode.data as any)?.caption_custom || ""}
                            onChange={handlePublisherFieldChange("caption_custom")}
                          />
                        </div>
                      )}

                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          مصدر الصورة
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.image_source || "{{image_url}}"}
                          onChange={handlePublisherFieldChange("image_source")}
                        >
                          <option value="{{image_url}}">
                            من مولّد الصور ({"{{image_url}}"})
                          </option>
                          <option value="custom_url">رابط صورة مخصص</option>
                        </select>
                      </div>

                      {(selectedNode.data as any)?.image_source === "custom_url" && (
                        <div>
                          <label className="mb-1 block text-[11px] text-slate-400">
                            رابط الصورة
                          </label>
                          <input
                            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                            value={(selectedNode.data as any)?.image_custom_url || ""}
                            onChange={handlePublisherFieldChange("image_custom_url")}
                          />
                        </div>
                      )}

                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          وضع النشر
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.publish_mode || "publish_now"}
                          onChange={handlePublisherFieldChange("publish_mode")}
                        >
                          <option value="publish_now">نشر الآن</option>
                          <option value="draft">حفظ كمسودة</option>
                          <option value="schedule">جدولة</option>
                        </select>
                      </div>
                      <p className="text-[10px] text-slate-500 border-t border-slate-800 pt-2">
                        لظهور المنشور للعامة: ربط صفحة فيسبوك (وليس الحساب الشخصي)، وتحقّق من إعدادات الصفحة في فيسبوك أن الجمهور الافتراضي = عام.
                      </p>
                    </div>
                  </>
                )}

                {selectedNode.type === "scheduler" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات الجدولة
                    </div>
                    <div className="space-y-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          نوع الجدولة
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.schedule_type || "daily"}
                          onChange={handleSchedulerFieldChange("schedule_type")}
                        >
                          <option value="once">مرة واحدة</option>
                          <option value="daily">يومي</option>
                          <option value="weekly">أسبوعي</option>
                          <option value="monthly">شهري</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          الوقت
                        </label>
                        <input
                          type="time"
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.time || "20:00"}
                          onChange={handleSchedulerFieldChange("time")}
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          التايم زون
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.timezone || "Asia/Baghdad"}
                          onChange={handleSchedulerFieldChange("timezone")}
                        >
                          <option value="Asia/Baghdad">Asia/Baghdad</option>
                          <option value="Asia/Riyadh">Asia/Riyadh</option>
                          <option value="Asia/Dubai">Asia/Dubai</option>
                          <option value="Africa/Cairo">Africa/Cairo</option>
                          <option value="Europe/Istanbul">Europe/Istanbul</option>
                          <option value="UTC">UTC</option>
                        </select>
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "comment-listener" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات مراقبة التعليقات
                    </div>
                    <div className="space-y-3">
                      <div>
                        <div className="mb-1 text-[11px] text-slate-400">المنصات</div>
                        <div className="flex flex-wrap gap-2">
                          {["facebook", "instagram", "tiktok"].map((p) => {
                            const selected = ((selectedNode.data as any)?.platforms || []).includes(
                              p,
                            );
                            return (
                              <button
                                key={p}
                                type="button"
                                onClick={() => handleCommentListenerPlatformToggle(p)}
                                className={`rounded-full px-3 py-1 text-[11px] ${
                                  selected ? "bg-amber-600 text-white" : "bg-slate-800 text-slate-300"
                                }`}
                              >
                                {p}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          كلمات التريغر (سطر لكل كلمة)
                        </label>
                        <textarea
                          className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                          placeholder="price&#10;how much&#10;buy"
                          value={
                            Array.isArray((selectedNode.data as any)?.keywords)
                              ? (selectedNode.data as any).keywords.join("\n")
                              : (selectedNode.data as any)?.keywords || ""
                          }
                          onChange={(e) =>
                            updateNodeData(selectedNode.id, {
                              keywords: e.target.value
                                .split("\n")
                                .map((s) => s.trim())
                                .filter(Boolean),
                            })
                          }
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          وضع المراقبة
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.mode || "keywords_only"}
                          onChange={handleCommentListenerFieldChange("mode")}
                        >
                          <option value="all_comments">كل التعليقات</option>
                          <option value="keywords_only">فقط عند وجود كلمات التريغر</option>
                        </select>
                      </div>
                      <div className="mt-3 border-t border-slate-800 pt-3">
                        <div className="mb-2 text-[11px] font-semibold text-slate-400">
                          معاينة التعليقات (Facebook / Instagram / TikTok)
                        </div>
                        <div className="space-y-2">
                          <input
                            className="w-full rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                            placeholder="معرف منشور فيسبوك (post_id) أو media_id / video_id حسب المنصة الأولى المختارة"
                            value={
                              (() => {
                                const data = selectedNode.data as any;
                                const platforms: string[] = data.platforms || ["facebook"];
                                const platform = (platforms[0] || "facebook") as string;
                                const key =
                                  platform === "facebook"
                                    ? "post_id"
                                    : platform === "instagram"
                                    ? "media_id"
                                    : "video_id";
                                return data[key] || "";
                              })()
                            }
                            onChange={(e) => {
                              const data = selectedNode.data as any;
                              const platforms: string[] = data.platforms || ["facebook"];
                              const platform = (platforms[0] || "facebook") as string;
                              const key =
                                platform === "facebook"
                                  ? "post_id"
                                  : platform === "instagram"
                                  ? "media_id"
                                  : "video_id";
                              updateNodeData(selectedNode.id, { [key]: e.target.value });
                            }}
                          />
                          <button
                            type="button"
                            onClick={handleLoadCommentsPreview}
                            className="w-full rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500 disabled:opacity-60 disabled:cursor-not-allowed"
                            disabled={commentsLoading}
                          >
                            {commentsLoading ? "جارٍ جلب التعليقات..." : "عرض التعليقات الأخيرة"}
                          </button>
                          {commentsError && (
                            <div className="rounded border border-rose-500/60 bg-rose-900/40 px-2 py-1 text-[10px] text-rose-100">
                              {commentsError}
                            </div>
                          )}
                          {!!commentsPreview.length && (
                            <div className="max-h-40 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900/60 p-2 text-[11px] text-slate-200 space-y-1.5">
                              {commentsPreview.map((c) => (
                                <div
                                  key={`${c.platform}-${c.comment_id}`}
                                  className="rounded bg-slate-800/70 px-2 py-1.5"
                                >
                                  <div className="flex items-center justify-between gap-2">
                                    <span className="text-[10px] text-slate-400">
                                      {c.username || "بدون اسم"} • {c.platform}
                                    </span>
                                    {c.timestamp && (
                                      <span className="text-[9px] text-slate-500">
                                        {new Date(c.timestamp).toLocaleString()}
                                      </span>
                                    )}
                                  </div>
                                  <div className="mt-0.5 text-[11px] text-slate-100">
                                    {c.text || ""}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                          {!commentsLoading && !commentsError && !commentsPreview.length && (
                            <div className="rounded border border-dashed border-slate-700/70 bg-slate-900/40 px-2 py-2 text-[10px] text-slate-500">
                              أدخل معرف المنشور واضغط على زر &quot;عرض التعليقات الأخيرة&quot; لعرض عينة من تعليقات هذا المنشور.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "auto-reply" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات الرد التلقائي
                    </div>
                    <div className="space-y-3">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          نمط الرد
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs focus:border-indigo-500 focus:outline-none"
                          value={(selectedNode.data as any)?.mode || "template"}
                          onChange={handleAutoReplyFieldChange("mode")}
                        >
                          <option value="ai_generated">مولّد بالذكاء الاصطناعي</option>
                          <option value="template">قالب ثابت</option>
                        </select>
                      </div>

                      {(selectedNode.data as any)?.mode === "ai_generated" && (
                        <div className="space-y-2 rounded border border-slate-700/60 bg-slate-900/50 p-2">
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              نبرة الرد
                            </label>
                            <select
                              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none"
                              value={(selectedNode.data as any)?.tone || "friendly"}
                              onChange={handleAutoReplyFieldChange("tone")}
                            >
                              <option value="friendly">ودي</option>
                              <option value="formal">رسمي</option>
                              <option value="professional">احترافي</option>
                            </select>
                          </div>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              لغة الرد
                            </label>
                            <select
                              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none"
                              value={(selectedNode.data as any)?.language || "ar"}
                              onChange={handleAutoReplyFieldChange("language")}
                            >
                              <option value="ar">العربية</option>
                              <option value="en">English</option>
                            </select>
                          </div>
                        </div>
                      )}

                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          قالب الرد
                        </label>
                        <textarea
                          className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                          placeholder="شكراً لتعليقك! سنتواصل قريباً. أو: السعر هو {{price}}"
                          value={(selectedNode.data as any)?.template || ""}
                          onChange={handleAutoReplyFieldChange("template")}
                        />
                        <p className="mt-1 text-[10px] text-slate-500">
                          متغيرات: {"{{comment_text}}"}, {"{{topic}}"}, {"{{price}}"}, ...
                        </p>
                      </div>

                      <div>
                        <div className="mb-1.5 text-[11px] text-slate-400">المنصات</div>
                        <div className="flex flex-wrap gap-2">
                          {["facebook", "instagram", "tiktok"].map((p) => {
                            const selected = ((selectedNode.data as any)?.platforms || []).includes(
                              p,
                            );
                            return (
                              <button
                                key={p}
                                type="button"
                                onClick={() => handleAutoReplyPlatformToggle(p)}
                                className={`rounded-full px-3 py-1.5 text-[11px] transition-colors ${
                                  selected
                                    ? "bg-indigo-600 text-white"
                                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                                }`}
                              >
                                {p}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "keyword-filter" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات فلتر الكلمات المفتاحية
                    </div>
                    <div className="space-y-2">
                      <label className="mb-1 block text-[11px] text-slate-400">
                        الكلمات المفتاحية (سطر واحد لكل كلمة — إذا وُجدت في التعليق يُمرّر للتالي)
                      </label>
                      <textarea
                        className="h-[100px] w-full resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                        placeholder="price&#10;buy&#10;how much"
                        value={
                          Array.isArray((selectedNode.data as any)?.keywords)
                            ? (selectedNode.data as any).keywords.join("\n")
                            : ""
                        }
                        onChange={(e) =>
                          updateNodeData(selectedNode.id, {
                            keywords: e.target.value
                              .split("\n")
                              .map((s) => s.trim().toLowerCase())
                              .filter(Boolean),
                          })
                        }
                      />
                    </div>
                  </>
                )}

                {selectedNode.type === "publish-reply" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      نشر الرد على التعليق
                    </div>
                    <p className="mt-1 text-[10px] text-slate-500">
                      ينشر نص الرد من العقدة السابقة (reply_text أو ai_reply) على المنصة حسب حقل platform في السياق (facebook / instagram / tiktok).
                    </p>
                  </>
                )}

                {selectedNode.type === "rate-limiter" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      حد المعدل
                    </div>
                    <div className="space-y-2">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">التأخير بين الردود (ثانية)</label>
                        <input
                          type="number"
                          min={1}
                          max={60}
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.delay_between_replies ?? 5}
                          onChange={(e) =>
                            updateNodeData(selectedNode.id, {
                              delay_between_replies: Math.max(1, Math.min(60, parseInt(e.target.value, 10) || 5)),
                            })
                          }
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">أقصى ردود في الدقيقة</label>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.max_replies_per_minute ?? 20}
                          onChange={(e) =>
                            updateNodeData(selectedNode.id, {
                              max_replies_per_minute: Math.max(1, Math.min(100, parseInt(e.target.value, 10) || 20)),
                            })
                          }
                        />
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "logging" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      تسجيل الأحداث
                    </div>
                    <p className="mt-1 text-[10px] text-slate-500">
                      يحفظ الحدث (platform, comment_id, username, comment_text, ai_reply) في جدول comment_logs.
                    </p>
                  </>
                )}

                {selectedNode.type === "duplicate-protection" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      حماية من التكرار
                    </div>
                    <p className="mt-1 text-[10px] text-slate-500">
                      يتحقق من أن التعليق لم يُرد عليه مسبقاً؛ إذا وُجد في السجل يتم تخطي نشر الرد.
                    </p>
                  </>
                )}

                {selectedNode.type === "memory_store" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      عقدة تخزين البيانات
                    </div>
                    <div className="space-y-3">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          اسم الحقل الذي تريد تخزينه في السياق
                        </label>
                        <input
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          placeholder="مثال: customer_phone أو last_order"
                          value={(selectedNode.data as any)?.key || ""}
                          onChange={handleMemoryFieldChange("key")}
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          قيمة الحقل (تدعم المتغيرات من الوورك فلو)
                        </label>
                        <textarea
                          className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                          placeholder="مثال: {{from_phone}} أو {{message_text}} أو نص ثابت"
                          value={(selectedNode.data as any)?.value_template || ""}
                          onChange={handleMemoryFieldChange("value_template")}
                        />
                        <p className="mt-1 text-[10px] text-slate-500">
                          عند التنفيذ سيتم تقييم المتغيرات ثم تخزين النتيجة في السياق بنفس اسم الحقل حتى تستخدمها العقد التالية.
                        </p>
                      </div>
                    </div>
                  </>
                )}

                {selectedNode.type === "knowledge_base" && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      عقدة كتالوج / قاعدة معرفة
                    </div>
                    <div className="space-y-3">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          مصدر المعرفة
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none"
                          value={(selectedNode.data as any)?.source || "manual"}
                          onChange={handleKnowledgeFieldChange("source")}
                        >
                          <option value="manual">إدخال يدوي / ملف</option>
                          <option value="inventory">جلب تلقائي من المخزون</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          وضع التحديث
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none"
                          value={(selectedNode.data as any)?.mode || "replace"}
                          onChange={handleKnowledgeFieldChange("mode")}
                        >
                          <option value="replace">استبدال المعرفة الحالية بهذا الكتالوج</option>
                          <option value="append">إضافة على المعرفة الحالية</option>
                        </select>
                      </div>
                      {(selectedNode.data as any)?.source === "inventory" && (
                        <>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              وضع المخزون للـ AI
                            </label>
                            <select
                              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none"
                              value={(selectedNode.data as any)?.inventory_mode || "match"}
                              onChange={handleKnowledgeFieldChange("inventory_mode")}
                            >
                              <option value="match">فقط المنتجات المطابقة لسؤال العميل (مُستحسن)</option>
                              <option value="full">عرض كامل المخزون (ثقيل على السياق)</option>
                            </select>
                          </div>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              حجم البحث في المخزون (عدد المنتجات الممسوحة للمطابقة)
                            </label>
                            <input
                              type="number"
                              min={50}
                              max={5000}
                              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none"
                              value={(selectedNode.data as any)?.inventory_pool ?? (selectedNode.data as any)?.inventory_limit ?? 800}
                              onChange={handleKnowledgeFieldChange("inventory_pool")}
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              أقصى عدد منتجات مطابقة تُمرَّر للـ AI
                            </label>
                            <input
                              type="number"
                              min={1}
                              max={30}
                              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none"
                              value={(selectedNode.data as any)?.match_limit || 8}
                              onChange={handleKnowledgeFieldChange("match_limit")}
                            />
                          </div>
                          <label className="flex items-center gap-2 text-[11px] text-slate-300">
                            <input
                              type="checkbox"
                              checked={Boolean((selectedNode.data as any)?.include_inactive || false)}
                              onChange={(e) => updateNodeData(selectedNode.id, { include_inactive: e.target.checked })}
                            />
                            تضمين المنتجات غير الفعالة
                          </label>
                          <p className="text-[10px] text-slate-500">
                            يُطابق المنتجات حسب كلمات رسالة العميل وسياق المحادثة، ثم يمرّر التفاصيل للذكاء. إذا وُجدت صورة للمنتج في المخزون يمكن إرسالها من عقدة Telegram Send.
                          </p>
                        </>
                      )}
                      {(selectedNode.data as any)?.source !== "inventory" && (
                        <>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          رفع ملف (PDF، Excel، أو ملف نصي)
                        </label>
                        <input
                          type="file"
                          accept=".pdf,.xlsx,.xls,.txt,.csv"
                          className="w-full text-[10px] file:mr-2 file:rounded file:border-0 file:bg-indigo-600 file:px-2 file:py-1 file:text-white file:text-xs"
                          onChange={async (e) => {
                            const file = e.target.files?.[0];
                            if (!file || !selectedNode) return;
                            const form = new FormData();
                            form.append("file", file);
                            try {
                              const res = await fetch("/social-ai/api/knowledge/extract", { method: "POST", body: form });
                              const data = await res.json();
                              if (data.success && typeof data.catalog === "string") {
                                const mode = (selectedNode.data as any)?.mode || "replace";
                                const prev = (selectedNode.data as any)?.catalog || "";
                                const catalog = mode === "append" ? (prev ? prev + "\n" + data.catalog : data.catalog) : data.catalog;
                                updateNodeData(selectedNode.id, { catalog });
                              } else {
                                alert(data.error || "فشل استخراج النص");
                              }
                            } catch (err) {
                              alert("خطأ في رفع الملف");
                            }
                            e.target.value = "";
                          }}
                        />
                        <p className="mt-1 text-[10px] text-slate-500">
                          PDF، xlsx، xls، txt أو csv. سيُستخرج النص ويُملأ في الحقل أدناه.
                        </p>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          نص الكتالوج / المنتجات
                        </label>
                        <textarea
                          className="h-[140px] w-full resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                          placeholder="يمكنك لصق قائمة المنتجات، المواصفات، الأسعار، الأسئلة الشائعة... أو رفع ملف أعلاه."
                          value={(selectedNode.data as any)?.catalog || ""}
                          onChange={handleKnowledgeFieldChange("catalog")}
                        />
                        <p className="mt-1 text-[10px] text-slate-500">
                          هذه البيانات تُمرَّر كمعرفة إضافية لعقد الـ AI داخل نفس الوكيل.
                        </p>
                      </div>
                        </>
                      )}
                    </div>
                  </>
                )}

                {(selectedNode.type === "whatsapp_send" || selectedNode.type === "telegram_send") && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات {selectedNode.type === "whatsapp_send" ? "واتساب (إرسال)" : "تيليجرام (إرسال)"}
                    </div>
                    <div className="space-y-3">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          رقم / معرف المستلم
                        </label>
                        <input
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          placeholder={
                            selectedNode.type === "whatsapp_send"
                              ? "مثال: +9647XXXXXXXXX"
                              : "اتركه فارغاً أو {{chat_id}} للرد على نفس الزبون"
                          }
                          value={(selectedNode.data as any)?.to || ""}
                          onChange={handleMessagingFieldChange("to")}
                        />
                        {selectedNode.type === "telegram_send" && (
                          <>
                            <p className="mt-1 text-[10px] text-slate-500">
                              الرد على محادثة الويبهوك يذهب تلقائياً لمرسل الرسالة. رقم ثابت هنا يرسل لذلك الحساب
                              فقط وليس لمن يكتب للبوت.
                            </p>
                            <label className="mt-2 flex items-center gap-2 text-[11px] text-slate-300">
                              <input
                                type="checkbox"
                                checked={Boolean((selectedNode.data as any)?.send_to_fixed_recipient)}
                                onChange={(e) =>
                                  updateNodeData(selectedNode.id, {
                                    send_to_fixed_recipient: e.target.checked,
                                  })
                                }
                              />
                              إجبار الإرسال لرقم «المستلم» أعلاه (تجربة / إعلان لحساب محدد)
                            </label>
                          </>
                        )}
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          نوع الإجراء
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.mode || "message"}
                          onChange={handleMessagingFieldChange("mode")}
                        >
                          <option value="message">رسالة</option>
                          <option value="call">اتصال</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          نص الرسالة / ملاحظة الاتصال
                        </label>
                        <textarea
                          className="h-[72px] w-full max-h-[100px] resize-none overflow-y-auto rounded-lg border border-[#334155] bg-[#1e293b] px-2 py-1.5 text-xs text-[#e5e7eb] focus:border-[#22c55e] focus:outline-none"
                          placeholder="يمكنك استخدام متغيرات مثل {{caption}} أو {{comment_text}}"
                          value={(selectedNode.data as any)?.template || ""}
                          onChange={handleMessagingFieldChange("template")}
                        />
                      </div>
                      {selectedNode.type === "telegram_send" && (
                        <>
                          <label className="flex items-center gap-2 text-[11px] text-slate-300">
                            <input
                              type="checkbox"
                              checked={(selectedNode.data as any)?.send_product_images !== false}
                              onChange={(e) =>
                                updateNodeData(selectedNode.id, { send_product_images: e.target.checked })
                              }
                            />
                            إرسال صور المنتجات المطابقة (إن وُجد رابط صورة في المخزون)
                          </label>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              أقصى عدد صور بعد الرسالة
                            </label>
                            <input
                              type="number"
                              min={0}
                              max={10}
                              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                              value={(selectedNode.data as any)?.max_product_photos ?? 5}
                              onChange={handleMessagingFieldChange("max_product_photos")}
                            />
                          </div>
                        </>
                      )}
                    </div>
                  </>
                )}

                {(selectedNode.type === "whatsapp_listener" || selectedNode.type === "telegram_listener") && (
                  <>
                    <div className="mt-2 border-t border-slate-800 pt-2 text-[11px] font-semibold text-slate-400">
                      إعدادات {selectedNode.type === "whatsapp_listener" ? "واتساب (Listener)" : "تيليجرام (Listener)"}
                    </div>
                    <div className="space-y-3">
                      {selectedNode.type === "whatsapp_listener" && (
                        <div>
                          <label className="mb-1 block text-[11px] text-slate-400">
                            Phone Number ID (واتساب كلاود)
                          </label>
                          <input
                            className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                            placeholder="مثال: 123456789012345"
                            value={(selectedNode.data as any)?.phone_id || ""}
                            onChange={handleMessagingFieldChange("phone_id")}
                          />
                        </div>
                      )}
                      {selectedNode.type === "telegram_listener" && (
                        <>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              Bot Token
                            </label>
                            <input
                              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                              placeholder="مثال: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
                              value={(selectedNode.data as any)?.bot_token || ""}
                              onChange={handleMessagingFieldChange("bot_token")}
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              عنوان السيرفر (اختياري)
                            </label>
                            <input
                              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                              placeholder="مثال: https://finora.company"
                              value={(selectedNode.data as any)?.base_url || ""}
                              onChange={handleMessagingFieldChange("base_url")}
                            />
                            <p className="mt-1 text-[10px] text-slate-500">
                              نفس عنوان الموقع في المتصفح (مثلاً https://www.finora.company). يجب أن يكون النطاق عاماً وقابلاً للوصول من الإنترنت.
                            </p>
                          </div>
                        </>
                      )}
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          حالة الـ Webhook
                        </label>
                        <select
                          className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                          value={(selectedNode.data as any)?.enabled === true ? "on" : "off"}
                          onChange={async (e) => {
                            if (!selectedNode || (selectedNode.type !== "telegram_listener" && selectedNode.type !== "whatsapp_listener")) return;
                            const newOn = e.target.value === "on";
                            if (selectedNode.type === "telegram_listener") {
                              const botToken = ((selectedNode.data as any)?.bot_token as string)?.trim();
                              const baseUrl = ((selectedNode.data as any)?.base_url as string)?.trim();
                              if (newOn) {
                                if (!botToken) {
                                  alert("أدخل Bot Token أولاً ثم اختر مفعل.");
                                  return;
                                }
                                const wfId = meta?.id;
                                if (!wfId) {
                                  alert("احفظ الوورك فلو أولاً (زر حفظ) حتى يُربط Webhook بالوورك فلو.");
                                  return;
                                }
                                try {
                                  const res = await fetch("/social-ai/api/telegram/set-webhook", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({
                                      bot_token: botToken,
                                      workflow_id: wfId,
                                      ...(baseUrl ? { base_url: baseUrl } : {}),
                                    }),
                                  });
                                  const data = await res.json();
                                  if (data.ok) {
                                    updateNodeData(selectedNode.id, {
                                      enabled: true,
                                      webhook_registered_url: data.webhook_url || "",
                                      webhook_last_verify: {
                                        url_matches: true,
                                        expected_url: data.webhook_url || "",
                                        checked_at: new Date().toISOString(),
                                      },
                                    });
                                  } else {
                                    alert(data.error || "فشل تفعيل Webhook");
                                  }
                                } catch (err) {
                                  alert("خطأ في الاتصال. تأكد من حفظ الوورك فلو ثم جرّب مرة أخرى.");
                                }
                              } else {
                                if (botToken) {
                                  try {
                                    await fetch("/social-ai/api/telegram/delete-webhook", {
                                      method: "POST",
                                      headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify({ bot_token: botToken }),
                                    });
                                  } catch {
                                    // ignore network errors when disabling webhook
                                  }
                                }
                                updateNodeData(selectedNode.id, { enabled: false });
                              }
                            } else {
                              updateNodeData(selectedNode.id, { enabled: newOn });
                            }
                          }}
                        >
                          <option value="on">مفعل</option>
                          <option value="off">معطّل</option>
                        </select>
                        {selectedNode.type === "telegram_listener" && (
                          <>
                            <p className="mt-1 text-[10px] text-slate-500">
                              عند اختيار &quot;مفعل&quot; يُسجَّل عنوان الاستقبال عند تيليجرام مباشرة. عرض العقدة «مفعل»
                              سابقاً كان افتراضياً دون تحقق — استخدم الزر أدناه للتأكد من تيليجرام.
                            </p>
                            <button
                              type="button"
                              className="mt-2 w-full rounded border border-sky-600/60 bg-slate-900 px-2 py-1.5 text-[11px] text-sky-300 hover:bg-slate-800"
                              onClick={async () => {
                                if (!selectedNode || selectedNode.type !== "telegram_listener") return;
                                const botToken = ((selectedNode.data as any)?.bot_token as string)?.trim();
                                const baseUrl = ((selectedNode.data as any)?.base_url as string)?.trim();
                                const wfId = meta?.id;
                                if (!botToken) {
                                  alert("أدخل Bot Token أولاً.");
                                  return;
                                }
                                if (!wfId) {
                                  alert("احفظ الوورك فلو أولاً.");
                                  return;
                                }
                                try {
                                  const res = await fetch("/social-ai/api/telegram/webhook-info", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({
                                      bot_token: botToken,
                                      workflow_id: wfId,
                                      ...(baseUrl ? { base_url: baseUrl } : {}),
                                    }),
                                  });
                                  const j = await res.json();
                                  if (!j.ok) {
                                    alert(j.error || "فشل التحقق");
                                    return;
                                  }
                                  const matches = j.url_matches;
                                  const exp = j.expected_webhook_url || "";
                                  const cur = j.current_url || "";
                                  const pend = j.pending_update_count ?? 0;
                                  const err = j.last_error_message || "";
                                  updateNodeData(selectedNode.id, {
                                    webhook_last_verify: {
                                      url_matches: matches === true ? true : matches === false ? false : undefined,
                                      expected_url: exp,
                                      telegram_url: cur,
                                      pending_update_count: pend,
                                      last_error_message: err,
                                      checked_at: new Date().toISOString(),
                                    },
                                  });
                                  if (matches === null || matches === undefined) {
                                    alert(
                                      `تعذّر مقارنة الرابط (أضف «عنوان السيرفر» أو BASE_URL).\n\nعند تيليجرام الآن: ${cur || "(فارغ)"}\nتحديثات معلقة: ${pend}`,
                                    );
                                    return;
                                  }
                                  alert(
                                    matches
                                      ? `تيليجرام يستقبل على نفس رابط هذا الوورك فلو.\n${cur}\n(تحديثات معلقة: ${pend})`
                                      : `الرابط عند تيليجرام لا يطابق المطلوب لهذا الوورك فلو.\n\nعند تيليجرام: ${cur || "(فارغ)"}\n\nالمتوقع: ${exp || "(أضف عنوان السيرفر في العقدة)"}\n\n${err ? `آخر خطأ: ${err}` : ""}`,
                                  );
                                } catch {
                                  alert("خطأ اتصال بالخادم.");
                                }
                              }}
                            >
                              تحقق من تيليجرام (getWebhookInfo)
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
              </div>
            </>
          )}
        </aside>
        <div
          className="wf-resizer flex shrink-0 cursor-col-resize items-center justify-center bg-transparent hover:bg-[#1e293b]/50 transition-colors"
          onMouseDown={() => setResizing("left")}
          role="separator"
          aria-orientation="vertical"
          aria-label="تغيير عرض لوحة الإعدادات"
          style={{ width: 6 }}
        >
          <div className="h-8 w-0.5 rounded-full bg-[#334155] group-hover:bg-[#38bdf8]" />
        </div>
        <section className="wf-panel-canvas flex h-full min-h-0 flex-col overflow-hidden bg-[#0b1220]" aria-label="منطقة الوورك فلو">
          <div className="reactflow-wrapper h-full w-full min-h-0">
            <ReactFlowProvider>
              <NodeEditor />
            </ReactFlowProvider>
          </div>
        </section>
        <div
          className="wf-resizer flex shrink-0 cursor-col-resize items-center justify-center bg-transparent hover:bg-[#1e293b]/50 transition-colors"
          onMouseDown={() => setResizing("right")}
          role="separator"
          aria-orientation="vertical"
          aria-label="تغيير عرض مكتبة العقد"
          style={{ width: 6 }}
        >
          <div className="h-8 w-0.5 rounded-full bg-[#334155]" />
        </div>
        <aside className="wf-panel-node-library wf-node-library-in-grid flex flex-col border-s border-[#1e293b] bg-[#111827] overflow-hidden" aria-label="مكتبة العقد">
          {rightCollapsed ? (
            <div className="flex h-full w-full flex-col items-center justify-center gap-1 border-s border-[#1e293b] bg-[#111827] py-2">
              <button
                type="button"
                onClick={() => setRightCollapsed(false)}
                className="rounded p-1.5 text-slate-400 hover:bg-[#1e293b] hover:text-[#e5e7eb]"
                title="توسيع مكتبة العقد"
                aria-label="توسيع مكتبة العقد"
              >
                <span className="inline-block -rotate-90 whitespace-nowrap text-[10px] font-medium">مكتبة العقد</span>
              </button>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-2 border-b border-[#1e293b] pb-2 mb-2 p-4 pb-2">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400" id="node-library-title">مكتبة العقد</h2>
                <button
                  type="button"
                  onClick={() => setRightCollapsed(true)}
                  className="rounded p-1 text-slate-500 hover:bg-[#1e293b] hover:text-slate-300 rtl:rotate-180"
                  title="تصغير مكتبة العقد"
                  aria-label="تصغير مكتبة العقد"
                >
                  ▶
                </button>
              </div>
              <ul className="flex flex-1 flex-col gap-3 overflow-y-auto p-4 pt-0" aria-labelledby="node-library-title">
                {NODE_TYPES.map((node) => (
                  <li
                    key={node.id}
                    draggable
                    onDragStart={(event) => handleDragStart(event, node.id)}
                    className="wf-node-card flex cursor-move flex-col gap-1.5 rounded-[12px] border border-[#1e293b] bg-[#0f172a] p-3 text-sm transition-all duration-200 hover:scale-[1.02] hover:shadow-lg active:scale-[0.98]"
                    style={{ borderInlineStart: `4px solid ${node.color}`, boxShadow: "0 4px 12px rgba(0,0,0,0.2)" }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-lg" aria-hidden>{node.icon}</span>
                      <span className="font-semibold text-[#e5e7eb]">{node.label}</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-snug pr-6">{node.description}</p>
                  </li>
                ))}
              </ul>
            </>
          )}
        </aside>
      </div>
      <div
        className={`wf-node-library-overlay fixed top-16 bottom-0 z-40 w-[280px] border-[#334155] bg-[#111827] shadow-xl transition-transform ${nodeLibraryOpen ? "translate-x-0" : "-translate-x-full rtl:translate-x-full"} left-0 border-l rtl:left-auto rtl:right-0 rtl:border-r`}
      >
        <div className="flex items-center justify-between border-b border-[#334155] p-3">
          <h2 className="text-xs font-semibold uppercase text-slate-400">مكتبة العقد</h2>
          <button type="button" onClick={() => setNodeLibraryOpen(false)} className="rounded p-1 text-slate-400 hover:bg-[#334155] hover:text-white">
            ×
          </button>
        </div>
        <ul className="flex flex-col gap-3 p-4">
          {NODE_TYPES.map((node) => (
            <li
              key={node.id}
              draggable
              onDragStart={(e) => handleDragStart(e, node.id)}
              className="wf-node-card flex cursor-move flex-col gap-1.5 rounded-[12px] border border-[#334155] bg-[#0f172a] p-3 text-sm transition-all duration-200 hover:scale-[1.02] hover:shadow-lg active:scale-[0.98]"
              style={{ borderInlineStart: `4px solid ${node.color}`, boxShadow: "0 4px 12px rgba(0,0,0,0.2)" }}
            >
              <div className="flex items-center gap-2">
                <span className="text-lg" aria-hidden>{node.icon}</span>
                <span className="font-semibold text-[#e5e7eb]">{node.label}</span>
              </div>
              <p className="text-[11px] text-slate-400 leading-snug pr-6">{node.description}</p>
            </li>
          ))}
        </ul>
      </div>
      {nodeLibraryOpen && (
        <button
          type="button"
          aria-label="إغلاق"
          className="xl:hidden fixed inset-0 z-30 bg-black/50"
          onClick={() => setNodeLibraryOpen(false)}
        />
      )}
      {toast && (
        <div
          className={`pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded border px-4 py-2 text-xs shadow-lg ${
            toast.type === "success"
              ? "border-emerald-500 bg-emerald-900/80 text-emerald-100"
              : "border-rose-500 bg-rose-900/80 text-rose-100"
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
};

