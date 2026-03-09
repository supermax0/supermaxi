import React from "react";
import { NodeEditor } from "./NodeEditor";

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
  const handleDragStart = (event: React.DragEvent<HTMLLIElement>, nodeType: string) => {
    event.dataTransfer.setData("application/reactflow", nodeType);
    event.dataTransfer.effectAllowed = "move";
  };

  return (
    <div className="flex h-screen bg-bg text-white">
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
        <header className="flex items-center justify-between border-b border-slate-800 bg-panel/80 px-4 py-3">
          <h1 className="text-base font-semibold">AI Agent Workflow Builder</h1>
          <div className="space-x-2 space-x-reverse">
            <button className="rounded bg-slate-700 px-3 py-1 text-sm hover:bg-slate-600">
              حفظ
            </button>
            <button className="rounded bg-emerald-600 px-3 py-1 text-sm hover:bg-emerald-500">
              تشغيل الآن
            </button>
            <button className="rounded border border-slate-600 px-3 py-1 text-sm hover:bg-slate-800">
              وضع اختبار
            </button>
          </div>
        </header>
        <div className="flex flex-1">
          <section className="flex-1">
            <NodeEditor />
          </section>
          <aside className="w-80 border-r border-slate-800 bg-panel/80 px-4 py-4">
            <h2 className="mb-2 text-sm font-semibold">إعدادات العقدة</h2>
            <p className="text-xs text-slate-300">
              اختر عقدة من الكانفس لعرض إعداداتها هنا (الاسم، التعليمات، الموديل، المدخلات،
              المخرجات...).
            </p>
          </aside>
        </div>
      </main>
    </div>
  );
};

