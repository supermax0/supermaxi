import { useTimeFormat } from "@/stores/displayTime";
import {
  ArrowUpLeft,
  Building2,
  CalendarDays,
  CreditCard,
  FileText,
  Home,
  Loader2,
  MapPin,
  Pencil,
  Phone,
  Plus,
  Printer,
  RefreshCw,
  ShoppingCart,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { SupplierDetails, SupplierRow } from "@/api/finora/suppliers";
import { IconButton } from "@/components/IconButton";
import { DetailRow } from "@/components/SidePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/utils/cn";
import { formatNumber, formatDateTime } from "@/utils/format";
import { formatIqd } from "@/utils/money";
import { toast } from "@/stores/toasts";
import { useOffline } from "@/stores/offline";
import { supplierPrimary, supplierSecondary } from "./SupplierDialogs";

const TABS = [
  { id: "overview", label: "نظرة عامة", icon: Home },
  { id: "statement", label: "كشف الحساب", icon: FileText },
  { id: "purchases", label: "المشتريات", icon: ShoppingCart },
  { id: "payments", label: "الدفعات", icon: CreditCard },
  { id: "sales", label: "المبيعات للمورد", icon: ArrowUpLeft },
] as const;
type DetailTab = (typeof TABS)[number]["id"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  useTimeFormat();
  return (
    <section className="overflow-hidden rounded-panel border border-line/50 bg-white/75">
      <h3 className="border-b border-line/50 bg-surface-sunken/65 px-4 py-3 text-[13px] font-bold text-ink">
        {title}
      </h3>
      <div className="px-4 py-2">{children}</div>
    </section>
  );
}

function SmallStat({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  tone: "violet" | "azure" | "success" | "warning";
}) {
  useTimeFormat();
  const colors = {
    violet: "bg-violet-soft text-violet-deep",
    azure: "bg-azure-soft text-azure",
    success: "bg-success-soft text-success",
    warning: "bg-warning-soft text-warning",
  };
  return (
    <div className="min-w-0 rounded-control border border-line/60 bg-white/80 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-[10px]", colors[tone])}>
          <Icon size={17} />
        </span>
        <span className="ltr-isolate text-base font-bold">{value}</span>
      </div>
      <p className="mt-2 truncate text-[10px] text-ink-soft">{label}</p>
    </div>
  );
}

function EmptyRecords({ children }: { children: ReactNode }) {
  useTimeFormat();
  return (
    <div className="rounded-panel border border-dashed border-line bg-white/50 px-4 py-12 text-center">
      <FileText size={30} className="mx-auto mb-3 text-ink-faint/60" />
      <p className="text-sm text-ink-soft">{children}</p>
    </div>
  );
}

function InvoiceRecords({ details, sales = false }: { details: SupplierDetails; sales?: boolean }) {
  useTimeFormat();
  if (sales)
    return details.sales.length === 0 ? (
      <EmptyRecords>لا توجد مبيعات لهذا المورد</EmptyRecords>
    ) : (
      <div className="space-y-3">
        {details.sales.map((s) => (
          <div key={s.id} className="rounded-control border border-line/60 bg-white/85 p-4">
            <div className="flex justify-between gap-3">
              <span className="ltr-isolate font-bold">{s.invoice_no}</span>
              <span className="ltr-isolate text-sm font-semibold text-violet-deep">
                {formatIqd(s.grand_total)}
              </span>
            </div>
            <p className="mt-2 text-xs text-ink-soft">{s.products_label}</p>
            <p className="ltr-isolate mt-3 text-xs text-ink-faint">{formatDateTime(s.date)}</p>
          </div>
        ))}
      </div>
    );
  return details.purchases.length === 0 ? (
    <EmptyRecords>لا توجد فواتير شراء لهذا المورد</EmptyRecords>
  ) : (
    <div className="space-y-3">
      {details.purchases.map((p) => (
        <article key={p.id} className="rounded-control border border-line/60 bg-white/85 p-4">
          <div className="flex items-center justify-between gap-3">
            <span className="ltr-isolate font-bold">{p.invoice_no}</span>
            <StatusBadge
              tone={p.status === "draft" ? "neutral" : p.status === "cancelled" ? "danger" : "success"}
              label={p.status === "draft" ? "مسودة" : p.status === "cancelled" ? "ملغية" : "مستلمة"}
            />
          </div>
          <p className="mt-2 text-xs leading-5 text-ink-soft">{p.products_label}</p>
          <div className="mt-3 flex items-center justify-between gap-2 border-t border-line/60 pt-3">
            <span className="ltr-isolate text-xs text-ink-faint">{formatDateTime(p.date)}</span>
            <span className="ltr-isolate font-semibold">{formatIqd(p.grand_total)}</span>
          </div>
          {p.status !== "cancelled" && p.status !== "draft" && (
            <p className="mt-2 text-xs text-ink-soft">
              المتبقي على الفاتورة:{" "}
              <span className={cn("ltr-isolate", p.remaining_total > 0 ? "text-danger" : "text-success")}>
                {formatIqd(p.remaining_total)}
              </span>
            </p>
          )}
        </article>
      ))}
    </div>
  );
}

function Statement({ details }: { details: SupplierDetails }) {
  useTimeFormat();
  const records = [
    ...details.purchases
      .filter((p) => p.status !== "draft" && p.status !== "cancelled")
      .map((p) => ({
        key: `p-${p.id}`,
        date: p.date,
        label: "فاتورة شراء",
        reference: p.invoice_no,
        amount: p.grand_total,
        tone: "text-maroon",
      })),
    ...details.payments.map((p) => ({
      key: `pay-${p.id}`,
      date: p.date.slice(0, 10),
      label: p.payment_method === "offset" ? "تسوية ببيع للمورد" : "دفعة للمورد",
      reference: p.document_number || `#${p.id}`,
      amount: p.amount,
      tone: "text-success",
    })),
  ].sort((a, b) => b.date.localeCompare(a.date));
  return (
    <div className="space-y-4">
      <Section title="ملخص الحساب">
        <DetailRow label="الرصيد الافتتاحي">
          <span className="ltr-isolate">{formatIqd(details.supplier.opening_balance)}</span>
        </DetailRow>
        <DetailRow label="إجمالي حساب المورد">
          <span className="ltr-isolate">{formatIqd(details.supplier.total_debt)}</span>
        </DetailRow>
        <DetailRow label="إجمالي المسدد والتسويات">
          <span className="ltr-isolate text-success">{formatIqd(details.supplier.total_paid)}</span>
        </DetailRow>
        <DetailRow label={details.supplier.remaining < 0 ? "رصيد لنا عند المورد" : "المستحق للمورد"}>
          <span className="ltr-isolate font-bold">{formatIqd(Math.abs(details.supplier.remaining))}</span>
        </DetailRow>
      </Section>
      {records.length === 0 ? (
        <EmptyRecords>لا توجد حركات مسجلة لهذا المورد</EmptyRecords>
      ) : (
        <Section title="فواتير الشراء والدفعات">
          {records.map((r) => (
            <div key={r.key} className="flex items-center gap-3 border-b border-line/50 py-3 last:border-0">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-control bg-violet-soft text-violet">
                <FileText size={17} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{r.label}</p>
                <p className="ltr-isolate mt-1 text-[11px] text-ink-faint">
                  {r.reference} · {formatDateTime(r.date)}
                </p>
              </div>
              <span className={cn("ltr-isolate text-sm font-semibold", r.tone)}>
                {formatNumber(r.amount)}
              </span>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

export function SupplierDetailsPanel({
  data,
  loading,
  error,
  online,
  onClose,
  onRetry,
  onEdit,
  onPay,
  onPurchase,
  onSell,
}: {
  data?: SupplierDetails;
  loading: boolean;
  error: string | null;
  online: boolean;
  onClose(): void;
  onRetry(): void;
  onEdit(s: SupplierRow): void;
  onPay(): void;
  onPurchase(s: SupplierRow): void;
  onSell(): void;
}) {
  useTimeFormat();
  const [tab, setTab] = useState<DetailTab>("overview");
  const offlineAvailable = useOffline((s) => s.status.available);
  const s = data?.supplier;
  const print = () => {
    if (s) void finora.suppliers.printStatement(s.id).catch((e: unknown) => toastError(e));
  };
  return (
    <aside
      className="supplier-details glass-solid flex min-h-0 flex-col overflow-hidden rounded-panel"
      aria-label="تفاصيل المورد"
    >
      <header className="flex items-center gap-2 px-5 pb-2 pt-4">
        <div className="flex-1">
          <button
            type="button"
            className={cn(supplierSecondary, "h-9 px-3 text-xs")}
            disabled={!s || !online}
            onClick={() => s && onEdit(s)}
          >
            <Pencil size={14} />
            تعديل
          </button>
        </div>
        <IconButton label="طباعة كشف الحساب" size="sm" disabled={!s || !online} onClick={print}>
          <Printer size={16} />
        </IconButton>
        <IconButton label="إغلاق التفاصيل" size="sm" onClick={onClose}>
          <X size={18} />
        </IconButton>
      </header>
      {loading && !s && (
        <div role="status" className="grid flex-1 place-items-center text-ink-soft">
          <div className="text-center">
            <Loader2 size={26} className="mx-auto mb-3 animate-spin text-violet" />
            جارٍ تحميل حساب المورد…
          </div>
        </div>
      )}
      {error && (
        <div role="alert" className="mx-4 mt-2 rounded-control bg-danger-soft p-4 text-sm text-danger">
          <p>{error}</p>
          <button
            type="button"
            className="mt-3 inline-flex items-center gap-2 font-semibold"
            onClick={onRetry}
          >
            <RefreshCw size={15} />
            إعادة المحاولة
          </button>
        </div>
      )}
      {s && data && (
        <>
          <div className="px-5 pb-4 pt-2">
            <div className="flex items-center gap-3">
              <span className="grid h-14 w-14 shrink-0 place-items-center rounded-panel bg-gradient-to-br from-violet-soft to-azure-soft text-ink-soft">
                <Building2 size={28} strokeWidth={1.7} />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-[21px] font-bold text-ink">{s.name}</h2>
                <p className="mt-1 truncate text-xs text-ink-soft">{s.address || "مورد مسجل في FINORA"}</p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-ink-soft">
              {s.phone && (
                <span className="inline-flex items-center gap-1.5">
                  <Phone size={14} />
                  <span className="ltr-isolate text-ink">{s.phone}</span>
                </span>
              )}
              <StatusBadge
                tone={s.remaining < 0 ? "violet" : s.remaining > 0 ? "warning" : "success"}
                label={s.remaining < 0 ? "لنا رصيد" : s.remaining > 0 ? "له مستحقات" : "الحساب مسدد"}
              />
            </div>
            <div className="mt-5 flex gap-2">
              <button
                type="button"
                className={cn(supplierPrimary, "min-w-0 flex-1 px-3 text-xs")}
                disabled={!online}
                onClick={() => onPurchase(s)}
              >
                <Plus size={16} />
                إضافة فاتورة شراء
              </button>
              <button
                type="button"
                className={cn(supplierSecondary, "min-w-0 flex-1 px-3 text-xs")}
                disabled={!online || s.remaining <= 0}
                onClick={onPay}
              >
                <Wallet size={16} />
                تسجيل دفعة
              </button>
            </div>
          </div>
          <div className="mx-5 mb-4 grid grid-cols-3 rounded-control bg-gradient-to-l from-violet-soft/80 via-maroon-soft/55 to-warning-soft/55 py-4 text-center">
            <SummaryValue label="إجمالي المشتريات" value={s.total_purchases} color="text-violet-deep" />
            <SummaryValue label="المسدد والتسويات" value={s.total_paid} color="text-maroon" />
            <SummaryValue
              label={s.remaining < 0 ? "رصيد لنا" : "المستحق حالياً"}
              value={Math.abs(s.remaining)}
              color={s.remaining < 0 ? "text-success" : "text-warning"}
            />
          </div>
          <nav
            role="tablist"
            aria-label="تفاصيل حساب المورد"
            className="mx-4 flex shrink-0 overflow-x-auto rounded-control border border-line/60 bg-white/70 p-1"
          >
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                role="tab"
                type="button"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={cn(
                  "flex flex-1 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-[10px] px-2 py-3 text-[10.5px] font-semibold transition-colors",
                  tab === id
                    ? "bg-violet-soft text-violet-deep shadow-control"
                    : "text-ink-soft hover:bg-surface-sunken",
                )}
              >
                <Icon size={13} />
                {label}
              </button>
            ))}
          </nav>
          <div
            role="tabpanel"
            aria-label={TABS.find((t) => t.id === tab)?.label}
            className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
          >
            {tab === "overview" && (
              <>
                <Section title="معلومات المورد">
                  <DetailRow label="اسم المورد">{s.name}</DetailRow>
                  <DetailRow label="الهاتف">
                    <span className="ltr-isolate">{s.phone || "—"}</span>
                  </DetailRow>
                  <DetailRow label="هاتف إضافي">
                    <span className="ltr-isolate">{s.phone2 || "—"}</span>
                  </DetailRow>
                  <DetailRow label="العنوان">
                    <span className="inline-flex items-center gap-2">
                      <MapPin size={14} className="shrink-0 text-violet" />
                      {s.address || "—"}
                    </span>
                  </DetailRow>
                  <DetailRow label="تاريخ الإضافة">
                    <span className="ltr-isolate">{s.created_at.slice(0, 10) || "—"}</span>
                  </DetailRow>
                  {s.member_count > 1 && (
                    <DetailRow label="سجلات الفروع">
                      <span className="ltr-isolate">{s.member_count}</span>
                    </DetailRow>
                  )}
                </Section>
                <Section title="إحصائيات سريعة">
                  <div className="grid grid-cols-2 gap-2 py-2">
                    <SmallStat
                      icon={ShoppingCart}
                      label="فواتير الشراء المستلمة"
                      value={formatNumber(s.purchase_count)}
                      tone="success"
                    />
                    <SmallStat
                      icon={Wallet}
                      label="الدفعات والتسويات"
                      value={formatNumber(s.payment_count)}
                      tone="violet"
                    />
                    <SmallStat
                      icon={ArrowUpLeft}
                      label="فواتير البيع للمورد"
                      value={formatNumber(data.sales.length)}
                      tone="azure"
                    />
                    <SmallStat
                      icon={CalendarDays}
                      label="آخر تعامل"
                      value={<span className="text-[11px]">{s.last_transaction || "—"}</span>}
                      tone="warning"
                    />
                  </div>
                </Section>
              </>
            )}
            {tab === "statement" && <Statement details={data} />}
            {tab === "purchases" && <InvoiceRecords details={data} />}
            {tab === "sales" && (
              <>
                <div className="flex items-center justify-between gap-3 rounded-control border border-line/60 bg-white/70 px-3 py-3">
                  <div>
                    <p className="text-sm font-semibold text-ink">فواتير البيع للمورد</p>
                    <p className="mt-1 text-[11px] text-ink-faint">تُخصم قيمة البيع من حساب المورد</p>
                  </div>
                  <button
                    type="button"
                    disabled={!online && !offlineAvailable}
                    onClick={onSell}
                    className={cn(supplierPrimary, "h-10 shrink-0 px-3 text-xs")}
                  >
                    <Plus size={15} />
                    بيع للمورد
                  </button>
                </div>
                <InvoiceRecords details={data} sales />
              </>
            )}
            {tab === "payments" &&
              (data.payments.length === 0 ? (
                <EmptyRecords>لا توجد دفعات مسجلة لهذا المورد</EmptyRecords>
              ) : (
                data.payments.map((p) => (
                  <article key={p.id} className="rounded-control border border-line/60 bg-white/85 p-4">
                    <div className="flex justify-between gap-3">
                      <StatusBadge
                        tone={p.payment_method === "offset" ? "violet" : "success"}
                        label={p.payment_method === "offset" ? "تسوية ببيع" : "دفعة"}
                      />
                      <span className="ltr-isolate font-bold text-success">{formatIqd(p.amount)}</span>
                    </div>
                    <p className="ltr-isolate mt-3 text-xs text-ink-faint">
                      {p.date.slice(0, 10)} · {p.document_number || `#${p.id}`}
                    </p>
                    {p.note && <p className="mt-2 text-xs leading-5 text-ink-soft">{p.note}</p>}
                    {p.invoice_labels.length > 0 && (
                      <p className="mt-2 text-xs text-ink-soft">
                        الفواتير: <span className="ltr-isolate">{p.invoice_labels.join("، ")}</span>
                      </p>
                    )}
                  </article>
                ))
              ))}
          </div>
          <footer className="border-t border-line/60 px-4 py-3 text-center text-[11px] text-ink-faint">
            جميع المبالغ بالدينار العراقي
          </footer>
        </>
      )}
    </aside>
  );
}

function SummaryValue({ label, value, color }: { label: string; value: number; color: string }) {
  useTimeFormat();
  return (
    <div className="min-w-0 border-e border-white/80 px-1.5 last:border-0">
      <p className={cn("text-[10px]", color)}>{label}</p>
      <p className={cn("ltr-isolate mt-1 text-[15px] font-bold", color)}>{formatNumber(value)}</p>
    </div>
  );
}

function toastError(error: unknown) {
  // The same error path as every other native print action.
  toast.error(toFinoraError(error).message);
}
