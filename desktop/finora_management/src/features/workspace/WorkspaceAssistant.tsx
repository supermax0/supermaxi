import { Send, Sparkles } from "lucide-react";
import { useState } from "react";
import { useAssistant } from "@/features/assistant/state";
import { Panel } from "./WorkspacePrimitives";
export function Assistant({ order }: { scope: string; order?: number }) {
  const [text, setText] = useState("");
  const enabled = useAssistant((s) => s.settings.enabled);
  const show = (prompt: string) => {
    useAssistant.getState().show(prompt);
    setText("");
  };
  return (
    <Panel title="مساعد FINORA الذكي" icon={Sparkles} className="workspace-assistant" style={{ order }}>
      <p className="workspace-caption">
        {enabled
          ? "ذكاء محلي، بحث موثّق، ومقترحات تراجعها قبل الحفظ."
          : "دليل وتعليم تفاعلي جاهز. فعّل Ollama أو LM Studio للأسئلة المفتوحة."}
      </p>
      <form
        data-nontransactional
        className="workspace-assistant-input"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) show(text.trim());
        }}
      >
        <input
          aria-label="اسأل FINORA"
          placeholder="اسأل FINORA أو اطلب شرحاً…"
          value={text}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
        />
        <button aria-label="إرسال إلى مساعد FINORA" disabled={!text.trim()}>
          <Send size={18} />
        </button>
      </form>
      <div className="workspace-suggestions">
        {["اعرض طلبات اليوم", "مبيعات هذا الشهر", "المنتجات منخفضة المخزون"].map((suggestion) => (
          <button key={suggestion} onClick={() => show(suggestion)}>
            {suggestion}
          </button>
        ))}
        <button
          onClick={() => {
            useAssistant.setState({ open: true, tab: "learn" });
          }}
        >
          علّمني البرنامج
        </button>
      </div>
    </Panel>
  );
}
