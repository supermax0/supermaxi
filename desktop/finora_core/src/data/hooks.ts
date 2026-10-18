import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useSyncExternalStore } from "react";
import { useAgent } from "../state/agent";
import { toast } from "../ui/toast";
import type { ActivityCategory, ActivityEvent, Conversation, CoreEvent, Message } from "./schemas";
import type { ConversationQuery, DataSource, MergeDecision, ShadowReplyLink } from "./source";

export const DataSourceContext = createContext<DataSource | null>(null);

export function useSource(): DataSource {
  const s = useContext(DataSourceContext);
  if (!s) throw new Error("DataSource missing: component rendered outside a configured backend");
  return s;
}

export const keys = {
  status: ["status"] as const,
  conversations: (q: ConversationQuery) => ["conversations", q] as const,
  messages: (id: string) => ["messages", id] as const,
  customer: (id: string) => ["customer", id] as const,
  activity: (c: ActivityCategory | "all") => ["activity", c] as const,
  approvals: ["approvals"] as const,
  shadow: (id: string) => ["shadow", id] as const,
  merges: ["merges"] as const,
};

export function useStatus() {
  const src = useSource();
  return useQuery({ queryKey: keys.status, queryFn: () => src.getStatus(), refetchInterval: 30_000 });
}

export function useConversations(q: ConversationQuery) {
  const src = useSource();
  return useQuery({
    queryKey: keys.conversations(q),
    queryFn: () => src.listConversations(q),
    placeholderData: (prev) => prev,
  });
}

export function useMessages(id: string | null) {
  const src = useSource();
  return useQuery({
    queryKey: keys.messages(id ?? ""),
    queryFn: () => src.listMessages(id ?? ""),
    enabled: id !== null,
  });
}

export function useCustomer(id: string | null) {
  const src = useSource();
  return useQuery({
    queryKey: keys.customer(id ?? ""),
    queryFn: () => src.getCustomer(id ?? ""),
    enabled: id !== null,
  });
}

export function useActivity(category: ActivityCategory | "all", enabled = true) {
  const src = useSource();
  return useQuery({ queryKey: keys.activity(category), queryFn: () => src.listActivity(category), enabled });
}

export function useApprovals() {
  const src = useSource();
  return useQuery({ queryKey: keys.approvals, queryFn: () => src.listApprovals() });
}

export function useSendMessage(conversationId: string) {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { text: string; key: string; shadow?: ShadowReplyLink }) =>
      src.sendMessage(conversationId, v.text, v.key, v.shadow),
    onSuccess: (msg, v) => {
      upsertMessage(qc, msg);
      if (v.shadow) void qc.invalidateQueries({ queryKey: keys.shadow(conversationId) });
    },
  });
}

/** Upload a reviewed attachment and keep the conversation cache in sync. */
export function useSendMedia(conversationId: string) {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (value: { file: File; key: string }) => src.sendMedia(conversationId, value.file, value.key),
    onSuccess: (message) => upsertMessage(qc, message),
    onError: () => void qc.invalidateQueries({ queryKey: keys.messages(conversationId) }),
  });
}

export function useAnalyzeMedia(conversationId: string) {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (value: { messageId: string; attachmentId: string }) =>
      src.analyzeAttachment(conversationId, value.messageId, value.attachmentId),
    onSuccess: (message) => upsertMessage(qc, message),
  });
}

/** Shadow Mode proposals for one conversation (newest first). */
export function useShadow(conversationId: string | null, enabled: boolean) {
  const src = useSource();
  return useQuery({
    queryKey: keys.shadow(conversationId ?? ""),
    queryFn: () => src.getShadow(conversationId ?? ""),
    enabled: enabled && conversationId !== null,
  });
}

export function useMergeSuggestions(enabled = true) {
  const src = useSource();
  return useQuery({ queryKey: keys.merges, queryFn: () => src.listMergeSuggestions(), enabled });
}

export function useDecideMerge() {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; decision: MergeDecision }) => src.decideMerge(v.id, v.decision),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.merges });
      void qc.invalidateQueries({ queryKey: ["customer"] });
    },
  });
}

export function useSetControl() {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { conversationId: string; control: "human" | "ai" }) =>
      src.setControl(v.conversationId, v.control),
    onSuccess: (conv) => {
      patchConversation(qc, conv);
      void qc.invalidateQueries({ queryKey: keys.messages(conv.id) });
    },
  });
}

export function useAddNote(conversationId: string) {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => src.addNote(conversationId, body),
    onSuccess: (profile) => qc.setQueryData(keys.customer(conversationId), profile),
  });
}

export function useDecideApproval() {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; decision: "approved" | "rejected"; planHash: string | null }) =>
      src.decideApproval(v.id, v.decision, v.planHash),
    // Success or a refused (changed) plan: either way the list must show the current plan version.
    onSettled: () => qc.invalidateQueries({ queryKey: keys.approvals }),
  });
}

export function useSetAutomationPaused() {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { paused: boolean; reason: string }) => src.setAutomationPaused(v.paused, v.reason),
    onSuccess: (s) => qc.setQueryData(keys.status, s),
  });
}

// ───────────────────────────── cache patching ─────────────────────────────

export function upsertMessage(qc: QueryClient, msg: Message) {
  const key = keys.messages(msg.conversationId);
  const state = qc.getQueryState(key);
  if (state && (state.data === undefined || state.fetchStatus === "fetching")) {
    // A REST load is in flight (or has no data yet): its response may predate this event. Never drop the event:
    // once that load settles, refetch so the server's ordered list (source of truth) includes it. (Refetching
    // immediately would be de-duplicated onto the in-flight request and return the stale list.)
    const inFlight = qc.getQueryCache().find({ queryKey: key })?.fetch() ?? Promise.resolve();
    void inFlight
      .catch(() => undefined)
      .then(() => qc.invalidateQueries({ queryKey: key, refetchType: "all" }));
    return;
  }
  qc.setQueryData<Message[]>(key, (prev) => {
    if (!prev) return prev;
    const i = prev.findIndex((m) => m.id === msg.id);
    if (i === -1) return [...prev, msg];
    const next = prev.slice();
    next[i] = msg;
    return next;
  });
}

function patchConversation(qc: QueryClient, conv: Conversation) {
  let missing = false;
  qc.setQueriesData<Conversation[]>({ queryKey: ["conversations"] }, (prev) => {
    if (!prev) return prev;
    const i = prev.findIndex((c) => c.id === conv.id);
    if (i === -1) {
      missing = true;
      return prev;
    }
    const before = prev[i];
    const next = prev.slice();
    next[i] = conv;
    // Only real activity reorders the list; agent-state churn does not (spec §11).
    if (before && before.lastActivityAt !== conv.lastActivityAt) {
      next.sort((a, b) => b.lastActivityAt.localeCompare(a.lastActivityAt));
    }
    return next;
  });
  if (missing) void qc.invalidateQueries({ queryKey: ["conversations"] });
}

function prependActivity(qc: QueryClient, e: ActivityEvent) {
  for (const key of [keys.activity("all"), keys.activity(e.category)]) {
    qc.setQueryData<ActivityEvent[]>(key, (prev) => (prev ? [e, ...prev].slice(0, 400) : prev));
  }
}

/** Bridges realtime hints into the query cache and the agent store. */
export function useRealtimeBridge(onEvent?: (e: CoreEvent) => void) {
  const src = useSource();
  const qc = useQueryClient();
  const apply = useAgent((s) => s.apply);
  useEffect(() => {
    const off = src.subscribe((e) => {
      switch (e.type) {
        case "agent.status":
          apply(e.status);
          qc.setQueryData(keys.status, (prev: unknown) =>
            prev && typeof prev === "object" ? { ...prev, agent: e.status } : prev,
          );
          break;
        case "conversation.updated":
          patchConversation(qc, e.conversation);
          break;
        case "message.received":
        case "message.sent":
        case "message.updated":
          upsertMessage(qc, e.message);
          break;
        case "customer.updated":
          void qc.invalidateQueries({ queryKey: ["account"] });
          void qc.invalidateQueries({ queryKey: ["customer"] });
          void qc.invalidateQueries({ queryKey: keys.merges });
          break;
        case "shadow.proposal":
          void qc.invalidateQueries({ queryKey: keys.shadow(e.proposal.conversationId) });
          break;
        case "approval.required":
        case "approval.resolved":
          void qc.invalidateQueries({ queryKey: ["account"] });
          void qc.invalidateQueries({ queryKey: keys.approvals });
          break;
        case "support.issue":
          void qc.invalidateQueries({ queryKey: ["support-issues"] });
          if (e.issue.status === "open") toast.info(`${e.issue.title} · ${e.issue.customerName}`);
          break;
        case "activity":
          prependActivity(qc, e.event);
          break;
        case "status":
          qc.setQueryData(keys.status, e.status);
          break;
        case "resync":
          void qc.invalidateQueries();
          break;
      }
      onEvent?.(e);
    });
    // After reconnect, resync from REST: the server DB is the source of truth.
    const resync = () => void qc.invalidateQueries();
    window.addEventListener("online", resync);
    return () => {
      off();
      window.removeEventListener("online", resync);
    };
  }, [src, qc, apply, onEvent]);
}

function subscribeOnline(cb: () => void) {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => {
    window.removeEventListener("online", cb);
    window.removeEventListener("offline", cb);
  };
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine,
    () => true,
  );
}
