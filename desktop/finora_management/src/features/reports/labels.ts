import {
  Banknote,
  BarChart3,
  Boxes,
  FileText,
  Landmark,
  Receipt,
  ShoppingCart,
  TrendingUp,
  UsersRound,
  Wallet,
  Scale,
  type LucideIcon,
} from "lucide-react";
import type { ReportFilters, ReportPeriod, ReportSection } from "@/api/finora/reports";

export const PERIOD_LABELS: Record<ReportPeriod, string> = {
  today: "اليوم",
  yesterday: "أمس",
  this_week: "هذا الأسبوع",
  this_month: "هذا الشهر",
  last_month: "الشهر السابق",
  this_year: "هذه السنة",
  custom: "فترة مخصصة",
};

export const SECTION_INFO: Record<ReportSection, { title: string; icon: LucideIcon }> = {
  sales: { title: "المبيعات", icon: BarChart3 },
  profit: { title: "الأرباح والخسائر", icon: TrendingUp },
  expenses: { title: "المصاريف", icon: Receipt },
  cash: { title: "النقد والبنوك", icon: Landmark },
  customers: { title: "العملاء والديون", icon: UsersRound },
  purchases: { title: "المشتريات والموردين", icon: ShoppingCart },
  inventory: { title: "المخزون", icon: Boxes },
  invoices: { title: "الفواتير", icon: FileText },
  employees: { title: "الموظفون", icon: UsersRound },
  cashflow: { title: "التدفق النقدي", icon: Wallet },
  equity: { title: "المركز المالي وأين ذهبت الأرباح", icon: Scale },
};

export const KPI_ICONS: Record<string, LucideIcon> = {
  sales: ShoppingCart,
  net_profit: TrendingUp,
  expenses: Receipt,
  cash: Banknote,
  receivables: UsersRound,
  inventory: Boxes,
};

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function defaultFilters(today = new Date()): ReportFilters {
  return {
    period: "this_month",
    dateFrom: iso(new Date(today.getFullYear(), today.getMonth(), 1)),
    dateTo: iso(today),
    branchId: null,
    employeeId: null,
  };
}

const MONTHS = [
  "يناير",
  "فبراير",
  "مارس",
  "أبريل",
  "مايو",
  "يونيو",
  "يوليو",
  "أغسطس",
  "سبتمبر",
  "أكتوبر",
  "نوفمبر",
  "ديسمبر",
];

/** "2026-10-07" → "7 أكتوبر", "2026-10" → "أكتوبر 2026", "2026" → "2026". */
export function bucketLabel(key: string): string {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (day) return `${Number(day[3])} ${MONTHS[Number(day[2]) - 1] ?? ""}`;
  const month = /^(\d{4})-(\d{2})$/.exec(key);
  if (month) return `${MONTHS[Number(month[2]) - 1] ?? ""} ${month[1]}`;
  return key;
}

export const PAYMENT_LABELS: Record<string, string> = { cash: "نقدي", credit: "آجل", bank: "بنك" };
