import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Send, Sparkles } from "lucide-react";
import { useState } from "react";
import { workspaceApi } from "@/api/finora/workspace";
import { toFinoraError } from "@/api/finora";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { Panel } from "./WorkspacePrimitives";
export function Assistant({ scope, order }: { scope: string; order?: number }) {
  const online = useConnection((s) => s.status === "online");
  const [text, setText] = useState("");
  const [answer, setAnswer] = useState("");
  const runtime = useQuery({
    queryKey: ["workspace", "assistant", scope],
    queryFn: workspaceApi.assistant,
    staleTime: 5 * 60_000,
    retry: false,
    enabled: online,
    placeholderData: undefined,
  });
  const ask = useMutation({
    mutationKey: ["workspace", "assistant-read"],
    mutationFn: workspaceApi.ask,
    onSuccess: (response) => {
      setAnswer(response.message);
      setText("");
    },
    onError: (error) => toast.error(toFinoraError(error).message),
  });
  const send = (message: string) => {
    if (online && !ask.isPending && message.trim()) ask.mutate(message.trim());
  };
  if (!runtime.data?.ready || !runtime.data.read_only) return null;
  return (
    <Panel title="مساعد FINORA الذكي" icon={Sparkles} className="workspace-assistant" style={{ order }}>
      <p className="workspace-caption">{runtime.data.notice}</p>
      <form
        data-nontransactional
        onSubmit={(e) => {
          e.preventDefault();
          send(text);
        }}
        className="workspace-assistant-input"
      >
        <input
          aria-label="اسأل FINORA"
          placeholder="اسأل FINORA عن بيانات عملك…"
          value={text}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          disabled={!online || ask.isPending}
        />
        <button aria-label="إرسال إلى مساعد FINORA" disabled={!online || ask.isPending || !text.trim()}>
          {ask.isPending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
        </button>
      </form>
      <div className="workspace-suggestions">
        {["اعرض طلبات اليوم", "مبيعات هذا الشهر", "المنتجات منخفضة المخزون"].map((suggestion) => (
          <button key={suggestion} disabled={!online || ask.isPending} onClick={() => send(suggestion)}>
            {suggestion}
          </button>
        ))}
      </div>
      {answer && (
        <div className="workspace-assistant-answer" role="status">
          {answer}
        </div>
      )}
      {!online && <p className="workspace-caption">المساعد يحتاج اتصالاً بالخادم.</p>}
    </Panel>
  );
}
