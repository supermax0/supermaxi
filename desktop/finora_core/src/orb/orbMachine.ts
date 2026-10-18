import type { AgentState, Channel } from "../data/schemas";

/**
 * Explicit orb state machine. The server reports agent states; the desktop only accepts
 * transitions listed here so the orb can never jump into a visually incoherent state.
 */
const ANY_TO: readonly AgentState[] = ["error", "offline", "idle"];

const ALLOWED: Record<AgentState, readonly AgentState[]> = {
  idle: ["message_received", "reading", "approval_required"],
  message_received: ["reading", "thinking"],
  reading: ["thinking", "searching", "replying"],
  thinking: ["searching", "executing", "replying", "approval_required", "waiting_customer"],
  searching: ["thinking", "executing", "replying", "approval_required"],
  replying: ["completed", "waiting_customer", "executing"],
  executing: ["completed", "replying", "approval_required"],
  waiting_customer: ["message_received", "reading", "completed"],
  approval_required: ["executing", "completed", "replying"],
  completed: ["message_received", "reading"],
  error: ["reading", "thinking", "executing"],
  offline: [],
};

export function canTransition(from: AgentState, to: AgentState): boolean {
  if (from === to) return true;
  if (ANY_TO.includes(to)) return true;
  return ALLOWED[from].includes(to);
}

/**
 * Returns the next state, or the current one if the requested transition is illegal.
 * Illegal transitions are reported through `onRejected` so they are logged, never silently swallowed.
 */
export function transition(
  from: AgentState,
  to: AgentState,
  onRejected?: (from: AgentState, to: AgentState) => void,
): AgentState {
  if (canTransition(from, to)) return to;
  onRejected?.(from, to);
  return from;
}

/** Visual parameters per state, consumed by the shader. All values are lerped on the GPU side. */
export interface OrbVisual {
  /** Flow speed of the internal ribbons. */
  speed: number;
  /** Brightness of the inner light. */
  energy: number;
  /** Pulse amplitude (0 = steady). */
  pulse: number;
  /** 0 = brand palette, 1 = warm amber (attention), -1 = desaturated (offline). */
  tint: number;
  /** Orbit speed of the particles. */
  orbit: number;
}

export const ORB_VISUALS: Record<AgentState, OrbVisual> = {
  idle: { speed: 0.18, energy: 0.55, pulse: 0.0, tint: 0, orbit: 0.12 },
  message_received: { speed: 0.42, energy: 0.85, pulse: 0.55, tint: 0, orbit: 0.3 },
  reading: { speed: 0.36, energy: 0.78, pulse: 0.2, tint: 0, orbit: 0.26 },
  thinking: { speed: 0.6, energy: 0.9, pulse: 0.3, tint: 0, orbit: 0.42 },
  searching: { speed: 0.72, energy: 0.88, pulse: 0.15, tint: 0, orbit: 0.55 },
  replying: { speed: 0.5, energy: 0.95, pulse: 0.35, tint: 0, orbit: 0.36 },
  executing: { speed: 0.85, energy: 1.0, pulse: 0.25, tint: 0, orbit: 0.65 },
  waiting_customer: { speed: 0.22, energy: 0.6, pulse: 0.1, tint: 0, orbit: 0.14 },
  approval_required: { speed: 0.3, energy: 0.85, pulse: 0.6, tint: 1, orbit: 0.18 },
  completed: { speed: 0.26, energy: 0.9, pulse: 0.0, tint: 0, orbit: 0.2 },
  error: { speed: 0.12, energy: 0.6, pulse: 0.4, tint: 1, orbit: 0.06 },
  offline: { speed: 0.06, energy: 0.35, pulse: 0.0, tint: -1, orbit: 0.03 },
};

const CHANNEL_NAME: Record<Channel, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  telegram: "Telegram",
};

/**
 * Text shown in the status bubble. Execution status only — never model reasoning.
 * The server may provide a more specific label (e.g. "يجهز إعدادات العيادة"); it wins when present.
 */
export function statusLabel(
  state: AgentState,
  opts: { channel: Channel | null; serverLabel: string | null; hasConversations: boolean },
): string {
  if (opts.serverLabel && state !== "idle" && state !== "offline") return opts.serverLabel;
  const ch = opts.channel ? CHANNEL_NAME[opts.channel] : null;
  switch (state) {
    case "idle":
      return opts.hasConversations ? "بإنتظار الرسائل الجديدة" : "بإنتظار أول رسالة";
    case "message_received":
      return ch ? `رسالة جديدة من ${ch}` : "رسالة جديدة";
    case "reading":
      return ch ? `يقرأ رسالة جديدة من ${ch}` : "يقرأ رسالة جديدة";
    case "thinking":
      return "يحلل احتياج العميل";
    case "searching":
      return "يبحث في نظام FINORA";
    case "replying":
      return "يجهز الرد";
    case "executing":
      return "ينفذ الإجراء";
    case "waiting_customer":
      return "بانتظار رد العميل";
    case "approval_required":
      return "بانتظار موافقتك";
    case "completed":
      return "تم الرد ✓";
    case "error":
      return "تعذر إكمال العملية";
    case "offline":
      return "غير متصل";
  }
}

/** States that show the animated ellipsis (work in progress). */
export function isBusy(state: AgentState): boolean {
  return (
    state === "idle" ||
    state === "message_received" ||
    state === "reading" ||
    state === "thinking" ||
    state === "searching" ||
    state === "replying" ||
    state === "executing"
  );
}
