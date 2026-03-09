import React from "react";
import { NodeEditor } from "./NodeEditor";

export const App: React.FC = () => {
  return (
    <div className="flex h-screen bg-bg text-white">
      <aside className="w-64 border-l border-slate-800 bg-panel/80 backdrop-blur px-4 py-6">
        <h2 className="mb-4 text-lg font-bold">عُقد العمل</h2>
        <ul className="space-y-2 text-sm text-slate-200">
          <li>Start</li>
          <li>AI Agent</li>
          <li>Image Generator</li>
          <li>Caption</li>
          <li>Publisher</li>
          <li>Scheduler</li>
          <li>Comment Listener</li>
          <li>Auto Reply</li>
          <li>End</li>
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

