import type { LeadStage } from "./schemas";

export type Tone = "green" | "blue" | "violet" | "amber" | "red" | "neutral";

export const LEAD_STAGE_META: Record<LeadStage, { label: string; tone: Tone }> = {
  new: { label: "جديد", tone: "neutral" },
  engaged: { label: "عميل محتمل", tone: "violet" },
  qualified: { label: "عميل محتمل مؤهل", tone: "green" },
  proposal: { label: "عرض سعر", tone: "blue" },
  trial: { label: "حساب تجريبي", tone: "blue" },
  account_created: { label: "تم إنشاء الحساب", tone: "green" },
  setup: { label: "قيد الإعداد", tone: "blue" },
  onboarding: { label: "تهيئة", tone: "violet" },
  active_customer: { label: "عميل فعّال", tone: "green" },
  needs_human: { label: "يحتاج متابعة", tone: "red" },
  lost: { label: "مغلق", tone: "neutral" },
};

/**
 * Explicit lead lifecycle. Every transition is recorded server-side; the client uses this table
 * to validate optimistic updates and to refuse impossible moves.
 */
const NEXT: Record<LeadStage, readonly LeadStage[]> = {
  new: ["engaged", "qualified", "needs_human", "lost"],
  engaged: ["qualified", "proposal", "needs_human", "lost"],
  qualified: ["proposal", "trial", "account_created", "needs_human", "lost"],
  proposal: ["trial", "account_created", "needs_human", "lost"],
  trial: ["account_created", "setup", "needs_human", "lost"],
  account_created: ["setup", "onboarding", "needs_human"],
  setup: ["onboarding", "needs_human"],
  onboarding: ["active_customer", "needs_human"],
  active_customer: ["needs_human"],
  needs_human: [
    "engaged",
    "qualified",
    "proposal",
    "trial",
    "setup",
    "onboarding",
    "active_customer",
    "lost",
  ],
  lost: ["engaged"],
};

export function canMoveLead(from: LeadStage, to: LeadStage): boolean {
  return from !== to && NEXT[from].includes(to);
}
