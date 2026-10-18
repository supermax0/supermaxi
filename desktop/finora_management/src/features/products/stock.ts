import type { StockState } from "@/api/finora/products";
import type { Tone } from "@/components/StatusBadge";

export const STOCK_STYLES: Record<StockState, { label: string; tone: Tone }> = {
  available: { label: "متوفر", tone: "success" },
  low: { label: "منخفض", tone: "warning" },
  out: { label: "نفذ المخزون", tone: "danger" },
};
