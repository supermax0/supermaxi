import type { PurchaseTab } from "@/api/finora/purchases";
import type { Tone } from "@/components/StatusBadge";

/** FINORA purchase state (draft / confirmed = stock received / cancelled) + remaining balance. */
export const PURCHASE_TAB_STYLES: Record<Exclude<PurchaseTab, "all">, { label: string; tone: Tone }> = {
  draft: { label: "مسودة", tone: "azure" },
  confirmed: { label: "مستلم", tone: "success" },
  unpaid: { label: "بانتظار الدفع", tone: "violet" },
  cancelled: { label: "ملغي", tone: "danger" },
};
