import { create } from "zustand";
import type { LocalAssistantSettings } from "@shared/localAssistant";
import { DEFAULT_LOCAL_ASSISTANT } from "@shared/localAssistant";
import type { WorkspaceTarget } from "@/features/workspace/state";

export interface AssistantSource {
  name: string;
  title: string;
  at: string;
  data: unknown;
  arguments: Record<string, unknown>;
}
export interface AssistantProposal {
  kind: "open" | "prepare";
  title: string;
  target?: WorkspaceTarget;
  action?: string;
  fields?: Record<string, unknown>;
}
export interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  at: number;
  sources?: AssistantSource[];
  proposals?: AssistantProposal[];
  guides?: string[];
  restored?: boolean;
}
interface AssistantState {
  open: boolean;
  tab: "chat" | "learn" | "search";
  prompt: string;
  settings: LocalAssistantSettings;
  hasToken: boolean;
  busy: boolean;
  status: string;
  error: string;
  scope: string;
  vaultScope: string;
  messages: AssistantMessage[];
  training: { id: string; step: number } | null;
  show(prompt?: string): void;
  close(): void;
  reset(scope: string): void;
}
export const useAssistant = create<AssistantState>()((set) => ({
  open: false,
  tab: "chat",
  prompt: "",
  settings: { ...DEFAULT_LOCAL_ASSISTANT },
  hasToken: false,
  busy: false,
  status: "",
  error: "",
  scope: "",
  vaultScope: "",
  messages: [],
  training: null,
  show(prompt = "") {
    set({ open: true, ...(prompt ? { prompt, tab: "chat" as const } : {}) });
  },
  close() {
    set({ open: false });
  },
  reset(scope) {
    set({
      scope,
      messages: [],
      prompt: "",
      vaultScope: "",
      busy: false,
      error: "",
      status: "",
      training: null,
    });
  },
}));
