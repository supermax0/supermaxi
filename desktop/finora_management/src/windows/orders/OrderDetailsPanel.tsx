import { useTimeFormat } from "@/stores/displayTime";
import { Banknote, Ban, ExternalLink, History, Pencil, Printer, UserRound, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { OrderRow } from "@/api/finora/orders";
import { finora, toFinoraError } from "@/api/finora";
import { IconButton } from "@/components/IconButton";
import { FeatureHelp } from "@/components/FeatureHelp";
import { DetailRow, SidePanel } from "@/components/SidePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { canReturnOrder, formatOrderDate, orderStatusStyle } from "@/features/orders/status";
import { collectionDue } from "@/features/orders/payment";
import { useOrderDetails, useOrderHistory } from "@/features/orders/useOrders";
import { cn } from "@/utils/cn";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";
import { formatIqd } from "@/utils/money";

interface OrderDetailsPanelProps {
  orderId: number | null;
  /** Grid row of the order: FINORA's details endpoint has no agent field, the grid row does. */
  row: OrderRow | null;
  canAssign: boolean;
  canPay: boolean;
  canCancel: boolean;
  canPrint: boolean;
  canEdit: boolean;
  canReturn: boolean;
  onReturn(orderId: number): void;
  onShippingReceipt(orderId: number): void;
  onEdit(orderId: number): void;
  onAssignAgent(orderId: number): void;
  onAssignShipping(orderId: number): void;
  onPay(orderId: number): void;
  onCancel(orderId: number): void;
  onPrint(orderId: number): void;
  onClose(): void;
}

type PanelTab = "details" | "history";

function HistoryList({ orderId, active }: { orderId: number | null; active: boolean }) {
  useTimeFormat();
  const history = useOrderHistory(orderId, active);
  if (history.isLoading) return <p className="py-6 text-center text-sm text-ink-faint">جارٍ تحميل السجل…</p>;
  if (history.error)
    return (
      <p role="alert" className="text-sm text-danger">
        {toFinoraError(history.error).message}
      </p>
    );
  if (!history.data?.length)
    return <p className="py-6 text-center text-sm text-ink-faint">لا توجد حركات مسجلة.</p>;
  return (
    <ol aria-label="سجل الحركات" className="relative space-y-3 border-s-2 border-violet-soft ps-4">
      {history.data.map((event) => (
        <li key={event.id} className="relative">
          <span className="absolute -start-[23px] top-1.5 h-3 w-3 rounded-full border-2 border-white bg-violet shadow-control" />
          <div className="rounded-control bg-white/85 px-3 py-2.5 ring-1 ring-line/60">
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm font-semibold text-ink">{event.movement}</p>
              <span className="ltr-isolate shrink-0 text-[11px] text-ink-faint">
                {event.created_at ? formatOrderDate(event.created_at.replace("T", " ")) : ""}
              </span>
            </div>
            {event.details && <p className="mt-1 text-xs leading-5 text-ink-soft">{event.details}</p>}
            <p className="mt-1 text-[11px] text-ink-faint">{event.employee ?? "النظام"}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function AssignButton({ label, onClick }: { label: string; onClick(): void }) {
  useTimeFormat();
  return (
    <button
      type="button"
      onClick={onClick}
      className="ms-2 rounded-full bg-violet-soft px-2.5 py-0.5 text-xs font-semibold text-violet-deep transition-colors hover:bg-violet hover:text-white"
    >
      {label}
    </button>
  );
}

export function OrderDetailsPanel({
  orderId,
  row,
  canAssign,
  canPay,
  canCancel,
  canPrint,
  canEdit,
  canReturn,
  onReturn,
  onShippingReceipt,
  onEdit,
  onAssignAgent,
  onAssignShipping,
  onPay,
  onCancel,
  onPrint,
  onClose,
}: OrderDetailsPanelProps) {
  useTimeFormat();
  const details = useOrderDetails(orderId);
  const order = details.data?.order;
  const [tab, setTab] = useState<PanelTab>("details");
  useEffect(() => setTab("details"), [orderId]);
  const due = order ? collectionDue(order.total ?? 0, order.paid_amount ?? 0, order.payment ?? "") : 0;
  const showPay = canPay && (row?.can_pay ?? due > 0);
  const showCancel = canCancel && Boolean(row?.can_cancel);
  const showReturn = canReturn && !!order && canReturnOrder(order);
  const canReceipt =
    canAssign &&
    !!order &&
    !order.return_summary &&
    !order.is_stock_locked &&
    !["راجع", "راجعة", "مرتجع", "ملغي"].includes((order.status ?? "").trim()) &&
    !["راجع", "راجعة", "مرتجع"].includes((order.payment ?? "").trim());

  const footer =
    orderId !== null && (showPay || showCancel || canPrint || showReturn) ? (
      <div className="flex flex-wrap items-center gap-2">
        {showPay && (
          <button
            type="button"
            onClick={() => onPay(orderId)}
            className="flex h-10 flex-1 items-center justify-center gap-2 rounded-control bg-gradient-to-l from-success to-[#0f8a5f] text-sm font-bold text-white shadow-control"
          >
            <Banknote size={16} aria-hidden />
            تسديد{due > 0 ? ` · ${formatIqd(due)}` : ""}
          </button>
        )}
        {canPrint && (
          <button
            type="button"
            onClick={() => onPrint(orderId)}
            className="flex h-10 items-center gap-1.5 rounded-control bg-white px-3.5 text-sm font-semibold text-ink ring-1 ring-line hover:bg-surface-sunken"
          >
            <Printer size={15} aria-hidden />
            طباعة
          </button>
        )}
        {showCancel && (
          <button
            type="button"
            onClick={() => onCancel(orderId)}
            className="flex h-10 items-center gap-1.5 rounded-control px-3 text-sm font-semibold text-danger hover:bg-danger-soft"
          >
            <Ban size={15} aria-hidden />
            إلغاء
          </button>
        )}
        {showReturn && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onReturn(orderId)}
              className="flex h-10 items-center gap-1.5 rounded-control bg-danger-soft px-3 text-sm font-semibold text-danger hover:bg-danger/15"
            >
              <Undo2 size={15} aria-hidden />
              إرجاع الطلب
            </button>
            <FeatureHelp
              label="شرح إرجاع الطلب"
              text="إرجاع كامل بعد استلام القطع: تختار فرع الاستلام وتراجع التأكيد، ثم يُحدث المخزون والدفعات والدين والأقساط والسجل دون تكرار. طلب «تم الطلب» يستخدم الإلغاء؛ الإرجاع الجزئي ليس ضمن هذه العملية."
            />
          </div>
        )}
      </div>
    ) : undefined;

  return (
    <SidePanel
      open={orderId !== null}
      title={orderId !== null ? `الطلب #${orderId}` : ""}
      subtitle={order ? <span className="ltr-isolate">{formatOrderDate(order.created_at)}</span> : undefined}
      onClose={onClose}
      footer={footer}
      actions={
        orderId !== null && (
          <>
            {canEdit && order?.can_edit_invoice && (
              <button
                type="button"
                onClick={() => onEdit(orderId)}
                className="flex h-8 items-center gap-1.5 rounded-control bg-violet-soft px-3 text-xs font-semibold text-violet-deep hover:bg-violet/15"
              >
                <Pencil size={14} />
                تعديل سريع
              </button>
            )}
            <IconButton
              label="فتح في FINORA"
              size="sm"
              onClick={() => {
                finora.orders
                  .openInFinora(orderId)
                  .catch((error: unknown) => toast.error(toFinoraError(error).message));
              }}
            >
              <ExternalLink size={15} />
            </IconButton>
          </>
        )
      }
    >
      <div
        role="tablist"
        aria-label="أقسام الطلب"
        className="mb-4 grid grid-cols-2 gap-1 rounded-control bg-surface-sunken p-1"
      >
        {(
          [
            { id: "details", label: "التفاصيل" },
            { id: "history", label: "سجل الحركات" },
          ] as const
        ).map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
            className={cn(
              "flex h-9 items-center justify-center gap-1.5 rounded-[10px] text-sm transition-[background-color,box-shadow,color] duration-200",
              tab === item.id ? "bg-white font-semibold text-violet-deep shadow-control" : "text-ink-soft",
            )}
          >
            {item.id === "history" && <History size={14} aria-hidden />}
            {item.label}
          </button>
        ))}
      </div>
      {tab === "history" && <HistoryList orderId={orderId} active={tab === "history"} />}
      {tab === "details" && details.isLoading && (
        <div className="space-y-3" aria-busy>
          {Array.from({ length: 6 }, (_, i) => (
            <span
              key={i}
              className="block h-4 animate-pulse rounded-full bg-line"
              style={{ width: `${90 - i * 9}%` }}
            />
          ))}
        </div>
      )}
      {tab === "details" && details.error && (
        <p role="alert" className="text-sm text-danger">
          {toFinoraError(details.error).message}
        </p>
      )}
      {tab === "details" && order && (
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <StatusBadge {...orderStatusStyle(order.status ?? "")} />
            <span className="text-xs text-ink-soft">{order.payment ?? ""}</span>
          </div>
          <section>
            <h3 className="mb-1 text-xs font-semibold text-ink-faint">العميل</h3>
            <DetailRow label="الاسم">{order.customer ?? "—"}</DetailRow>
            <DetailRow label="الهاتف">
              <span className="ltr-isolate">{order.phone ?? "—"}</span>
            </DetailRow>
            <DetailRow label="المحافظة">{order.city ?? "—"}</DetailRow>
            <DetailRow label="العنوان">{order.address ?? "—"}</DetailRow>
            {Boolean(order.returned_count) && (
              <DetailRow label="طلبات راجعة سابقاً">
                <span className="ltr-isolate text-danger">{order.returned_count}</span>
              </DetailRow>
            )}
          </section>
          <section>
            <h3 className="mb-1 text-xs font-semibold text-ink-faint">الشحن</h3>
            <DetailRow label="المندوب">
              <span className="inline-flex items-center gap-1.5">
                <UserRound
                  size={14}
                  className={row?.delivery_agent ? "text-violet" : "text-ink-faint"}
                  aria-hidden
                />
                <span className={row?.delivery_agent ? "font-semibold" : "text-ink-faint"}>
                  {row?.delivery_agent || "غير معيّن"}
                </span>
                {canAssign && !order.return_summary && orderId !== null && (
                  <AssignButton
                    label={row?.delivery_agent ? "تغيير" : "تعيين"}
                    onClick={() => onAssignAgent(orderId)}
                  />
                )}
              </span>
            </DetailRow>
            <DetailRow label="شركة النقل">
              <span className="inline-flex items-center gap-1.5">
                {order.shipping_company ?? "—"}
                {canAssign && !order.return_summary && orderId !== null && (
                  <AssignButton
                    label={order.shipping_company ? "تغيير" : "تعيين"}
                    onClick={() => onAssignShipping(orderId)}
                  />
                )}
              </span>
            </DetailRow>
            <div className="flex items-center gap-2 text-xs font-semibold text-ink-faint">
              رقم وصل / بوليصة شركة النقل
              <FeatureHelp
                label="شرح وصل شركة النقل"
                text="هذا رقم الوصل المطبوع من شركة النقل، وليس رقم فاتورة FINORA. يمكن إدخال وصل واحد للطلب أو وصل لكل قطعة، ويظهر في البحث والطباعة والسجل. حفظه لطلب تم الطلب أو معبأ ينقله إلى جاري الشحن وفق قواعد المخزون."
              />
            </div>
            <DetailRow label="الرقم">
              <span className="inline-flex max-w-full flex-wrap items-center gap-1.5">
                <span className="ltr-isolate break-all">{order.shipping_barcode || "—"}</span>
                {canReceipt && orderId !== null && (
                  <AssignButton
                    label={order.shipping_barcode ? "تعديل وصل شركة النقل" : "إضافة وصل شركة النقل"}
                    onClick={() => onShippingReceipt(orderId)}
                  />
                )}
              </span>
            </DetailRow>
            <DetailRow label="الموظف">{order.employee ?? "—"}</DetailRow>
            {order.branch_name && <DetailRow label="الفرع">{order.branch_name}</DetailRow>}
          </section>
          <section>
            {order.return_summary && (
              <div
                role="region"
                aria-label="تسوية المرتجعات"
                className="mb-3 rounded-control bg-warning-soft p-3 text-xs leading-6"
              >
                <h3 className="font-bold">تسوية المرتجعات</h3>
                <DetailRow label="أصل البيع">{formatIqd(order.return_summary.original_total)}</DetailRow>
                <DetailRow label="المرتجع">{formatIqd(order.return_summary.credit)}</DetailRow>
                <DetailRow label="صافي البيع">{formatIqd(order.return_summary.net_total)}</DetailRow>
                <p>المستندات: {order.return_summary.document_ids.map((id) => `#${id}`).join("، ")}</p>
                {order.return_summary.undated_collection_amount !== undefined && (
                  <p>
                    تحصيل قديم غير مؤرخ: {formatIqd(order.return_summary.undated_collection_amount)}. لم
                    يُسجّل كقبض جديد.
                  </p>
                )}
              </div>
            )}
            <h3 className="mb-2 text-xs font-semibold text-ink-faint">
              {order.return_summary ? "بنود أصل البيع" : "المنتجات"}
            </h3>
            <ul className="space-y-1.5">
              {details.data?.items.map((item) => (
                <li
                  key={item.id}
                  className="flex items-center gap-3 rounded-control bg-white/80 px-3 py-2.5 text-sm ring-1 ring-line/60"
                >
                  <span className="min-w-0 flex-1 truncate">
                    {item.name}
                    {item.variant_color ? (
                      <span className="text-ink-faint"> · {item.variant_color}</span>
                    ) : null}
                    {order.return_summary && (
                      <span className="block text-[11px] text-ink-faint">
                        راجع: {formatNumber(item.returned_qty ?? 0)} · المتبقي:{" "}
                        {formatNumber(item.remaining_qty ?? item.qty)}
                      </span>
                    )}
                  </span>
                  <span className="ltr-isolate text-ink-soft">×{formatNumber(item.qty)}</span>
                  <span className="ltr-isolate w-28 text-end font-medium">{formatIqd(item.total ?? 0)}</span>
                </li>
              ))}
            </ul>
          </section>
          <section>
            {Boolean(order.discount_amount) && (
              <DetailRow label="الخصم">
                <span className="ltr-isolate">{formatIqd(order.discount_amount ?? 0)}</span>
              </DetailRow>
            )}
            <DetailRow label="المسدد">
              <span className="ltr-isolate">{formatIqd((order.total ?? 0) - due)}</span>
            </DetailRow>
            {due > 0 && (
              <DetailRow label="المتبقي">
                <span className="ltr-isolate font-semibold text-warning">{formatIqd(due)}</span>
              </DetailRow>
            )}
            <DetailRow label="الإجمالي">
              <span className="ltr-isolate text-base font-bold">{formatIqd(order.total ?? 0)}</span>
            </DetailRow>
          </section>
          {order.note && (
            <section>
              <h3 className="mb-1 text-xs font-semibold text-ink-faint">ملاحظات</h3>
              <p className="rounded-control bg-surface-sunken px-3 py-2 text-sm leading-6 text-ink">
                {order.note}
              </p>
            </section>
          )}
        </div>
      )}
    </SidePanel>
  );
}
