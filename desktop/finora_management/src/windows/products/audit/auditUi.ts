import { hasDesktopBridge } from "@/services/bridge";
import { productImageUrl } from "@/api/finora/products";

export const auditButton =
  "min-h-11 rounded-control border border-line bg-white/80 px-3 text-sm text-ink-soft transition-colors hover:bg-violet-soft disabled:opacity-50";
export const auditPrimary =
  "min-h-11 rounded-control bg-gradient-to-l from-violet to-violet-deep px-4 text-sm font-semibold text-white shadow-control transition-[opacity,transform] active:scale-[0.98] disabled:opacity-50 motion-reduce:transition-none";
export function auditImageUrl(url: string, server: string | null) {
  if (hasDesktopBridge()) return productImageUrl(url, server);
  if (!url) return null;
  try {
    const resolved = new URL(url, window.location.origin);
    return resolved.origin === window.location.origin ? resolved.href : null;
  } catch {
    return null;
  }
}
export const auditActionLabels: Record<string, string> = {
  create: "إنشاء الجلسة",
  begin_count: "بدء العد",
  save_count: "تثبيت العدد",
  cancel_count: "إلغاء إدخال غير مثبت",
  save_offline_count: "تثبيت عد محلي مؤرخ",
  prepare_offline: "تنزيل لقطة للعد",
  discard_offline_count: "إسقاط عد محلي بسبب موثق",
  investigate: "فحص الأدلة",
  review_line: "مراجعة الفرق",
  exclude: "استبعاد / إعادة صنف",
  submit: "إرسال للمراجعة",
  reopen: "إعادة فتح العد",
  approve: "اعتماد الجرد",
  post: "ترحيل تسويات الجرد",
  transfer_draft: "إنشاء مسودة تحويل للمراجعة",
  release_ticket: "إغلاق إدخال مفتوح بمراجعة المسؤول",
};
export const auditMovementLabels: Record<string, string> = {
  inventory_count_adjustment: "تسوية جرد معتمدة",
  count: "تسوية جرد",
  purchase: "استلام شراء",
  sale: "بيع",
  order_sale: "بيع",
  invoice: "حركة فاتورة",
  return: "مرتجع",
  order_return: "مرتجع",
  stock_transfer: "تحويل مخزون",
  transfer_send: "إرسال تحويل",
  transfer_receive: "استلام تحويل",
  adjust: "تعديل مخزون",
  manual_adjustment: "تعديل يدوي",
  unclassified_adjustment: "تعديل يحتاج مراجعة مصدره",
  opening: "رصيد افتتاحي",
};
