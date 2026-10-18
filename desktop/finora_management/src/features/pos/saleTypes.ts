import { Banknote, CalendarClock, Landmark, type LucideIcon } from "lucide-react";
import type { SaleType } from "./cart";

export interface SaleTypeStyle {
  id: SaleType;
  label: string;
  hint: string;
  icon: LucideIcon;
  /** Active state (tinted background + text + ring). */
  active: string;
  /** Idle icon colour. */
  dot: string;
}

/** نقد = green (money in the drawer), أجل = amber (receivable), بنك = blue (transfer). */
export const SALE_TYPES: SaleTypeStyle[] = [
  {
    id: "cash",
    label: "نقد",
    hint: "يُسجَّل الدفع في صندوق الفرع",
    icon: Banknote,
    active: "bg-success-soft text-success ring-success/30",
    dot: "text-success",
  },
  {
    id: "credit",
    label: "أجل",
    hint: "يبقى الطلب ديناً على الزبون",
    icon: CalendarClock,
    active: "bg-warning-soft text-warning ring-warning/30",
    dot: "text-warning",
  },
  {
    id: "bank",
    label: "بنك",
    hint: "يُسجَّل الدفع في الحساب البنكي المختار",
    icon: Landmark,
    active: "bg-azure-soft text-azure ring-azure/30",
    dot: "text-azure",
  },
];
