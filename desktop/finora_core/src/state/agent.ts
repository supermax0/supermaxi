import { create } from "zustand";
import type { AgentState, Channel } from "../data/schemas";
import { transition } from "../orb/orbMachine";

interface AgentStore {
  state: AgentState;
  label: string | null;
  conversationId: string | null;
  channel: Channel | null;
  /**
   * Apply a server agent status. The server is the source of truth: an illegal transition (usually a missed
   * event during reconnect) is logged as a resync and then accepted, so the orb never gets stuck.
   */
  apply: (next: {
    state: AgentState;
    label: string | null;
    conversationId: string | null;
    channel: Channel | null;
  }) => void;
}

export const useAgent = create<AgentStore>((set, get) => ({
  state: "idle",
  label: null,
  conversationId: null,
  channel: null,
  apply: (next) => {
    const current = get().state;
    transition(current, next.state, (from, to) =>
      console.warn(`[finora-core] orb resync: unexpected transition ${from} → ${to}`),
    );
    set({ state: next.state, label: next.label, conversationId: next.conversationId, channel: next.channel });
  },
}));
