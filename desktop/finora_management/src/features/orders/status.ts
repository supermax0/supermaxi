/**
 * Display mapping for FINORA's stored order status values (utils/order_status.py).
 * Keys are FINORA's values; labels/colors are presentation only.
 */
import type { OrderTab } from "@/api/finora/orders";
import type { Tone } from "@/components/StatusBadge";

interface StatusStyle {
  label: string;
  tone: Tone;
}

const STATUS_STYLES: Record<string, StatusStyle> = {
  "تم الطلب": { label: "تم الطلب", tone: "azure" },
  معباة: { label: "معبأة", tone: "violet" },
  "جاري الشحن": { label: "جاري شحن", tone: "warning" },
  مشحون: { label: "جاري شحن", tone: "warning" },
  مشحونة: { label: "جاري شحن", tone: "warning" },
  "تم التوصيل": { label: "تم التوصيل", tone: "success" },
  واصل: { label: "تم التوصيل", tone: "success" },
  واصلة: { label: "تم التوصيل", tone: "success" },
  راجع: { label: "راجع", tone: "danger" },
  راجعة: { label: "راجع", tone: "danger" },
  مرتجع: { label: "راجع", tone: "danger" },
  ملغي: { label: "ملغي", tone: "danger" },
};

export function orderStatusStyle(value: string): StatusStyle {
  return STATUS_STYLES[value.trim()] ?? { label: value || "—", tone: "neutral" };
}

export function canReturnOrder(order: {
  status: string | null;
  payment_status?: string | null;
  payment?: string | null;
  is_stock_locked?: boolean | null;
  can_return?: boolean;
}): boolean {
  if (order.is_stock_locked) return false;
  if (order.can_return !== undefined) return order.can_return;
  const status = (order.status ?? "").trim();
  const returned = new Set(["راجع", "راجعة", "مرتجع"]);
  return (
    !!status &&
    !["تم الطلب", "ملغي"].includes(status) &&
    !returned.has(status) &&
    !returned.has((order.payment_status ?? order.payment ?? "").trim())
  );
}

export const ORDER_TAB_LABELS: Record<OrderTab, string> = {
  all: "الكل",
  ordered: "تم الطلب",
  packed: "معبأة",
  shipping: "جاري شحن",
  delivered: "تم التوصيل",
  returned: "راجع",
};

/** Permission FINORA requires to see each tab (routes/orders.py _ORDERS_PAGE_PERMISSIONS). */
export const ORDER_TAB_PERMISSIONS = {
  ordered: "can_see_orders_placed",
  packed: "can_see_orders_packed",
  shipping: "can_see_orders_shipped",
  delivered: "can_see_orders_delivered",
  returned: "can_see_orders_returned",
} as const;

/** Targets accepted by POST /orders/bulk-status, plus the return workflow. */
export const STATUS_TARGETS = [
  { value: "تم الطلب", label: "تم الطلب" },
  { value: "معباة", label: "معبأة" },
  { value: "جاري الشحن", label: "جاري شحن" },
  { value: "تم التوصيل", label: "تم التوصيل" },
] as const;
export const RETURN_TARGET = { value: "__return__", label: "راجع (إرجاع المخزون)" } as const;

/** "2026-10-07 10:25" → "07/10 10:25" */
const orderDateFormatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Baghdad",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function formatOrderDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}:\d{2}))?/.exec(value);
  if (!match) return value;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${match[3]}/${match[2]}`;
  if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(value)) return value;
  const iso = value.replace(" ", "T");
  const timestamp = new Date(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(timestamp.getTime())) return value;
  const parts = orderDateFormatter.formatToParts(timestamp);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("day")}/${part("month")} ${part("hour")}:${part("minute")}`;
}
