/**
 * Central registry of workflow node types: allowed types, config schema hints, and defaults.
 * Used by graph validator and runner for consistent contracts.
 */

export type NodeTypeCategory = "trigger" | "action" | "logic" | "io" | "end";

export interface NodeTypeSpec {
  id: string;
  label: string;
  category: NodeTypeCategory;
  /** Whether this backend (Node) can execute this type. Unknown types fail at run. */
  runnerImplemented: boolean;
  /** Default data applied when node is created (optional). */
  defaultData?: Record<string, unknown>;
  /** Optional: required fields for config (for future schema-driven validation). */
  requiredFields?: string[];
}

/** All node types that may appear in a graph. Runner only executes runnerImplemented=true. */
export const NODE_REGISTRY: NodeTypeSpec[] = [
  { id: "start", label: "Start", category: "trigger", runnerImplemented: true, defaultData: { label: "Start" } },
  { id: "end", label: "End", category: "end", runnerImplemented: true, defaultData: { label: "End" } },
  { id: "condition", label: "Condition", category: "logic", runnerImplemented: true, requiredFields: ["expr"] },
  { id: "router_agent", label: "Router Agent", category: "action", runnerImplemented: true },
  { id: "ai_extractor", label: "AI Extractor", category: "action", runnerImplemented: true },
  { id: "knowledge_agent", label: "Knowledge Agent", category: "action", runnerImplemented: true },
  { id: "sales_agent", label: "Sales Agent", category: "action", runnerImplemented: true },
  { id: "fallback_safety", label: "Fallback Safety", category: "action", runnerImplemented: true },
  { id: "sql_save_order", label: "SQL Save Order", category: "io", runnerImplemented: true },
  { id: "telegram_reply", label: "Telegram Reply", category: "io", runnerImplemented: true },
  // Frontend-only / Flask-runner types (runner does not implement; will fail at run if executed by Node)
  { id: "ai", label: "AI Agent", category: "action", runnerImplemented: false },
  { id: "image", label: "Image Generator", category: "action", runnerImplemented: false },
  { id: "caption", label: "Caption Generator", category: "action", runnerImplemented: false },
  { id: "publisher", label: "Publisher", category: "action", runnerImplemented: false },
  { id: "scheduler", label: "Scheduler", category: "action", runnerImplemented: false },
  { id: "comment-listener", label: "Comment Listener", category: "trigger", runnerImplemented: false },
  { id: "keyword-filter", label: "Keyword Filter", category: "logic", runnerImplemented: false },
  { id: "auto-reply", label: "Auto Reply", category: "action", runnerImplemented: false },
  { id: "publish-reply", label: "Publish Reply", category: "action", runnerImplemented: false },
  { id: "rate-limiter", label: "Rate Limiter", category: "logic", runnerImplemented: false },
  { id: "logging", label: "Logging", category: "action", runnerImplemented: false },
  { id: "duplicate-protection", label: "Duplicate Protection", category: "logic", runnerImplemented: false },
  { id: "memory_store", label: "Store Data", category: "action", runnerImplemented: false },
  { id: "knowledge_base", label: "Knowledge Base", category: "action", runnerImplemented: false },
  { id: "whatsapp_listener", label: "WhatsApp Listener", category: "trigger", runnerImplemented: false },
  { id: "whatsapp_send", label: "WhatsApp Send", category: "io", runnerImplemented: false },
  { id: "telegram_listener", label: "Telegram Listener", category: "trigger", runnerImplemented: false },
  { id: "telegram_send", label: "Telegram Send", category: "io", runnerImplemented: false },
];

const ALLOWED_NODE_IDS = new Set(NODE_REGISTRY.map((s) => s.id));

export function isAllowedNodeType(type: string): boolean {
  return ALLOWED_NODE_IDS.has(type);
}

export function getNodeSpec(type: string): NodeTypeSpec | undefined {
  return NODE_REGISTRY.find((s) => s.id === type);
}

export function isRunnerImplemented(type: string): boolean {
  const spec = getNodeSpec(type);
  return spec?.runnerImplemented ?? false;
}
