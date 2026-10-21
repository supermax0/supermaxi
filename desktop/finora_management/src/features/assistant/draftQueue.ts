import { useEffect, useRef } from "react";
import { create } from "zustand";
import { useSession } from "@/stores/session";
import { useWorkspace, sessionScope } from "@/features/workspace/state";
import type { DraftKind } from "./draftSchema";
import { toast } from "@/stores/toasts";
const scope = () =>
  JSON.stringify([useWorkspace.getState().identity, sessionScope(useSession.getState().session)]);
interface Pending {
  kind: DraftKind;
  fields: Record<string, unknown>;
  scope: string;
  expires: number;
}
export const useAssistantDraft = create<{ pending: Pending | null }>()(() => ({ pending: null }));
export function queueAssistantDraft(kind: DraftKind, fields: Record<string, unknown>, ttl = 10000) {
  const pending = { kind, fields, scope: scope(), expires: Date.now() + ttl };
  useAssistantDraft.setState({ pending });
  window.setTimeout(() => {
    if (useAssistantDraft.getState().pending !== pending) return;
    useAssistantDraft.setState({ pending: null });
    toast.info(
      "لم تكتمل تعبئة المقترح خلال المهلة. راجع النموذج الأصلي أو اطلب تجهيز المقترح مرة ثانية؛ لم يتم حفظ أي عملية.",
    );
  }, ttl);
}
/** Only a newly opened original editor consumes this single-use RAM handoff. */
export function useAssistantDraftFields(
  kind: DraftKind,
  ready: boolean,
  apply: (fields: Record<string, unknown>) => void,
) {
  const pending = useAssistantDraft((s) => s.pending);
  const handler = useRef(apply);
  handler.current = apply;
  useEffect(() => {
    if (!ready || !pending || pending.kind !== kind) return;
    useAssistantDraft.setState({ pending: null });
    if (pending.scope === scope() && Date.now() < pending.expires) handler.current(pending.fields);
  }, [kind, ready, pending]);
}
