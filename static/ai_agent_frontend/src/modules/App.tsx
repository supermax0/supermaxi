import React, { useMemo, useState } from "react";
import { ReactFlowProvider } from "reactflow";
import { NodeEditor } from "./NodeEditor";
import { useEditorStore } from "./store";

const NODE_TYPES = [
  { id: "start", label: "Start" },
  { id: "ai", label: "AI Agent" },
  { id: "image", label: "Image Generator" },
  { id: "caption", label: "Caption Generator" },
  { id: "publisher", label: "Publisher" },
  { id: "scheduler", label: "Scheduler" },
  { id: "comment-listener", label: "Comment Listener" },
  { id: "auto-reply", label: "Auto Reply" },
  { id: "end", label: "End" },
];

export const App: React.FC = () => {
  const meta = useEditorStore((s) => s.meta);
  const setMeta = useEditorStore((s) => s.setMeta);
  const { selectedNodeId, selectedNode } = useEditorStore((s) => ({
    selectedNodeId: s.selectedNodeId,
    selectedNode: s.nodes.find((n) => n.id === s.selectedNodeId),
  }));
  const updateNodeData = useEditorStore((s) => s.updateNodeData);
  const getGraphPayload = useEditorStore((s) => s.getGraphPayload);

  const [isSaving, setIsSaving] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const apiBase = useMemo(
    () => (window as any).AI_AGENT_API_BASE || "/autoposter/api",
    [],
  );

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
        const res = await fetch(`${apiBase}/workflows/${currentMeta.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error("فشل تحديث الوورك فلو");
        const data = await res.json();
        setMeta({ id: data.workflow?.id, agentId });
        showToast("success", "تم حفظ الوورك فلو بنجاح.");
      } else {
        const res = await fetch(`${apiBase}/workflows`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error("فشل إنشاء الوورك فلو");
        const data = await res.json();
        setMeta({ id: data.workflow?.id, agentId });
        showToast("success", "تم إنشاء الوورك فلو وحفظه.");
      }
    } catch (err) {
      showToast("error", "حدث خطأ أثناء حفظ الوورك فلو.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleRun = async () => {
    const { meta: currentMeta } = getGraphPayload();
    if (!currentMeta.id) {
      showToast("error", "احفظ الوورك فلو أولاً قبل تشغيله.");
      return;
    }
    setIsRunning(true);
    try {
      const res = await fetch(`${apiBase}/workflows/${currentMeta.id}/run`, {
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
    updateNodeData(selectedNode.id, { label: value });
  };

  const handleNodeTopicChange = (value: string) => {
    if (!selectedNode) return;
    const key = selectedNode.type === "image" ? "prompt" : "topic";
    updateNodeData(selectedNode.id, { [key]: value });
  };

  return (
    <div className="flex h-full text-white">
      <aside className="w-64 border-l border-slate-800 bg-panel/80 backdrop-blur px-4 py-6">
        <h2 className="mb-4 text-lg font-bold">عُقد العمل</h2>
        <ul className="space-y-2 text-sm text-slate-200">
          {NODE_TYPES.map((node) => (
            <li
              key={node.id}
              draggable
              onDragStart={(event) => handleDragStart(event, node.id)}
              className="cursor-move rounded border border-slate-700 bg-slate-800/60 px-3 py-2 text-xs hover:border-emerald-500 hover:bg-slate-700"
            >
              {node.label}
            </li>
          ))}
        </ul>
      </aside>
      <main className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-800 bg-panel/80 px-4 py-2">
          <div className="flex items-center gap-3">
            <h1 className="text-base font-semibold">AI Agent Workflow Builder</h1>
            <input
              className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
              placeholder="اسم الوورك فلو"
              value={meta.name}
              onChange={handleMetaChange("name")}
            />
          </div>
          <div className="space-x-2 space-x-reverse">
            <button
              className="rounded bg-slate-700 px-3 py-1 text-sm hover:bg-slate-600 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={handleSave}
              disabled={isSaving}
            >
              {isSaving ? "جارٍ الحفظ..." : "حفظ"}
            </button>
            <button
              className="rounded bg-emerald-600 px-3 py-1 text-sm hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={handleRun}
              disabled={isRunning}
            >
              {isRunning ? "جارٍ التشغيل..." : "تشغيل الآن"}
            </button>
            <button className="rounded border border-slate-600 px-3 py-1 text-sm hover:bg-slate-800">
              وضع اختبار
            </button>
          </div>
        </header>
        <div className="flex flex-1 gap-4 bg-[#050816] p-4">
          <section className="flex-1 rounded-lg border border-slate-800 bg-slate-950/60">
            <ReactFlowProvider>
              <NodeEditor />
            </ReactFlowProvider>
          </section>
          <aside className="w-80 border-r border-slate-800 bg-panel/80 px-4 py-4">
            <h2 className="mb-2 text-sm font-semibold">إعدادات العقدة</h2>
            {!selectedNode && (
              <p className="text-xs text-slate-300">
                اختر عقدة من الكانفس لعرض إعداداتها هنا (الاسم، التعليمات، الموديل، المدخلات،
                المخرجات...).
              </p>
            )}
            {selectedNode && (
              <div className="space-y-3 text-xs text-slate-200">
                <div>
                  <div className="mb-1 text-[11px] text-slate-400">نوع العقدة</div>
                  <div className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px]">
                    {selectedNode.type}
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">الاسم الظاهر</label>
                  <input
                    className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                    value={(selectedNode.data as any)?.label || ""}
                    onChange={(e) => handleNodeLabelChange(e.target.value)}
                  />
                </div>
                {(selectedNode.type === "start" ||
                  selectedNode.type === "ai" ||
                  selectedNode.type === "image") && (
                  <div>
                    <label className="mb-1 block text-[11px] text-slate-400">
                      {selectedNode.type === "image"
                        ? "وصف الصورة (prompt)"
                        : "موضوع / وصف المنشور"}
                    </label>
                    <textarea
                      className="h-20 w-full resize-none rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs focus:border-emerald-500 focus:outline-none"
                      value={
                        (selectedNode.data as any)?.[
                          selectedNode.type === "image" ? "prompt" : "topic"
                        ] || ""
                      }
                      onChange={(e) => handleNodeTopicChange(e.target.value)}
                    />
                  </div>
                )}
              </div>
            )}
          </aside>
        </div>
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
      </main>
    </div>
  );
};

