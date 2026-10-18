import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { finora } from "@/api/finora";
import { toast } from "@/stores/toasts";

export const hrInput =
  "h-10 w-full rounded-control border border-line bg-white px-3 text-sm text-ink outline-none focus:border-violet/60 focus:ring-4 focus:ring-violet/10";
export const hrPrimary =
  "inline-flex h-10 items-center justify-center gap-2 rounded-control bg-maroon px-4 text-sm font-semibold text-white shadow-control hover:bg-maroon/90 disabled:opacity-45";
export const hrSecondary =
  "inline-flex h-10 items-center justify-center gap-2 rounded-control border border-line bg-white/80 px-4 text-sm text-ink hover:bg-violet-soft/50 disabled:opacity-45";
export function hrLocalDateTime(utc: string | null | undefined) {
  return utc ? new Date(Date.parse(utc) + 3 * 3600000).toISOString().slice(0, 16) : "";
}
export const labels: Record<string, string> = {
  active: "نشط",
  suspended: "موقوف",
  terminated: "منتهي الخدمة",
  leave: "إجازة",
  present: "حاضر",
  late: "متأخر",
  absent: "غائب",
  scheduled: "لم يبدأ الدوام",
  unscheduled: "بدون وردية",
  holiday: "عطلة",
  cancelled: "ملغى",
  pending: "بانتظار الموافقة",
  queued: "بانتظار المزامنة",
  approved: "معتمد",
  rejected: "مرفوض",
  draft: "مسودة",
  reviewed: "مراجع",
  paid: "مصروف",
  void: "ملغى",
  adjustment: "تسوية تحتاج مراجعة",
  repaying: "قيد التسديد",
  repaid: "مسدد",
  monthly: "شهري",
  weekly: "أسبوعي",
  daily: "يومي",
  hourly: "بالساعة",
  commission: "عمولات فقط",
  monthly_commission: "راتب وعمولات",
  full_time: "دوام كامل",
  part_time: "دوام جزئي",
  temporary: "مؤقت",
  review: "تقييم أداء",
  goal: "هدف",
  warning: "إجراء إداري",
  note: "ملاحظة",
  employee: "الموظف",
  create: "إضافة",
  update: "تعديل",
  payroll: "الرواتب",
  pay: "صرف",
  prepare: "احتساب",
  attendance: "الدوام",
  check_in: "حضور",
  check_out: "انصراف",
  shift: "الوردية",
  assign: "تعيين",
  department: "القسم",
  resource: "الملف الوظيفي",
  request: "طلب",
  correct: "تصحيح",
  advance: "السلفة",
  leave_type: "نوع الإجازة",
};
export function hrToday() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Baghdad",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}
export function HRBadge({ state }: { state: string }) {
  const tone = ["active", "present", "approved", "paid", "repaid"].includes(state)
    ? "bg-success-soft text-success"
    : ["absent", "rejected", "terminated"].includes(state)
      ? "bg-danger-soft text-danger"
      : ["late", "pending", "repaying"].includes(state)
        ? "bg-warning-soft text-warning"
        : "bg-violet-soft text-violet";
  return (
    <span className={`inline-flex rounded-control px-3 py-1 text-xs font-medium ${tone}`}>
      {labels[state] ?? state}
    </span>
  );
}
export function useHRCommand(onSaved?: (id: number, pending?: boolean) => void) {
  const client = useQueryClient();
  const requestId = useRef<string | null>(null);
  return useMutation({
    mutationFn: async ({ action, payload }: { action: string; payload: Record<string, unknown> }) => {
      requestId.current ??= crypto.randomUUID();
      return finora.hr.command(action, payload, requestId.current);
    },
    onSuccess: async (result) => {
      requestId.current = null;
      toast.success(result.pending ? "الطلب محفوظ محلياً وبانتظار المزامنة" : "تم حفظ العملية");
      await client.invalidateQueries({ queryKey: ["hr"] });
      onSaved?.(result.id, result.pending);
    },
  });
}
export function hours(minutes: number) {
  return `${Math.floor(minutes / 60)}س ${minutes % 60}د`;
}
