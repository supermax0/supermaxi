import type { PurchaseRow } from "@/api/finora/purchases";
import { DetailRow, SidePanel } from "@/components/SidePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { formatNumber } from "@/utils/format";
import { formatIqd } from "@/utils/money";
import { PURCHASE_TAB_STYLES } from "@/features/purchases/status";

const MODE_LABELS: Record<string, string> = { cash: "نقدي", credit: "آجل", mixed: "مختلط" };

export function PurchaseDetailsPanel({
  purchase,
  onClose,
}: {
  purchase: PurchaseRow | null;
  onClose(): void;
}) {
  return (
    <SidePanel
      open={purchase !== null}
      title={purchase?.invoice_no ?? ""}
      subtitle={purchase ? `${purchase.supplier} · ${purchase.date}` : undefined}
      onClose={onClose}
    >
      {purchase && (
        <div className="space-y-5">
          <div className="flex justify-center">
            <StatusBadge {...PURCHASE_TAB_STYLES[purchase.tab]} />
          </div>
          <section>
            <DetailRow label="المورد">{purchase.supplier || "—"}</DetailRow>
            <DetailRow label="فاتورة المورد">
              <span className="ltr-isolate">{purchase.supplier_invoice_no || "—"}</span>
            </DetailRow>
            <DetailRow label="طريقة الشراء">
              {MODE_LABELS[purchase.purchase_mode] ?? purchase.purchase_mode}
            </DetailRow>
          </section>
          <section>
            <h3 className="mb-2 text-xs font-semibold text-ink-faint">الأصناف</h3>
            <ul className="space-y-1.5">
              {purchase.items.map((item, index) => (
                <li
                  key={`${item.product_id ?? "x"}-${index}`}
                  className="flex items-center gap-3 rounded-control bg-white/80 px-3 py-2.5 text-sm ring-1 ring-line/60"
                >
                  <span className="min-w-0 flex-1 truncate">
                    {item.product}
                    {item.color ? <span className="text-ink-faint"> · {item.color}</span> : null}
                  </span>
                  <span className="ltr-isolate text-ink-soft">×{formatNumber(item.quantity)}</span>
                  <span className="ltr-isolate w-28 text-end font-medium">{formatIqd(item.line_total)}</span>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <DetailRow label="الإجمالي">
              <span className="ltr-isolate text-base font-bold">{formatIqd(purchase.grand_total)}</span>
            </DetailRow>
            <DetailRow label="المدفوع">
              <span className="ltr-isolate">{formatIqd(purchase.paid_total)}</span>
            </DetailRow>
            <DetailRow label="المتبقي">
              <span className={`ltr-isolate ${purchase.remaining_total > 0 ? "text-warning" : ""}`}>
                {formatIqd(purchase.remaining_total)}
              </span>
            </DetailRow>
          </section>
          {purchase.payments.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-semibold text-ink-faint">الدفعات</h3>
              <ul className="space-y-1.5">
                {purchase.payments.map((payment, index) => (
                  <li
                    key={index}
                    className="flex items-center justify-between rounded-control bg-white/80 px-3 py-2.5 text-sm ring-1 ring-line/60"
                  >
                    <span>
                      {payment.account_name || payment.payment_method || "دفعة"}
                      <span className="ltr-isolate ms-2 text-xs text-ink-faint">{payment.paid_at}</span>
                    </span>
                    <span className="ltr-isolate font-medium">{formatIqd(payment.amount)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {purchase.notes && (
            <section>
              <h3 className="mb-1 text-xs font-semibold text-ink-faint">ملاحظات</h3>
              <p className="rounded-control bg-surface-sunken px-3 py-2 text-sm leading-6">
                {purchase.notes}
              </p>
            </section>
          )}
        </div>
      )}
    </SidePanel>
  );
}
