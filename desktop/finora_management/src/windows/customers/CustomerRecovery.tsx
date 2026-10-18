import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, RefreshCw } from "lucide-react";
import type { SavedCustomerCommand } from "@shared/customerRecovery";
import { finora, toFinoraError } from "@/api/finora";
import { FeatureHelp } from "@/components/FeatureHelp";
import { SidePanel } from "@/components/SidePanel";
import { useConnection } from "@/stores/connection";
import { useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";
import { useState } from "react";

const button =
  "inline-flex items-center justify-center gap-2 rounded-control border border-line bg-white px-4 py-2 text-sm text-violet-deep transition-colors hover:bg-violet-soft disabled:opacity-50";
function details(item: SavedCustomerCommand) {
  const body = item.request.body;
  const data = body && typeof body === "object" && !Array.isArray(body) ? body : {};
  const customer = /\/customers\/(\d+)\//.exec(item.request.path)?.[1];
  const target = /\/(invoices|plans)\/(\d+)\//.exec(item.request.path);
  const label = item.request.path.endsWith("/debts")
    ? "تسجيل دين افتتاحي"
    : item.request.path.endsWith("/commands")
      ? data.operation === "update"
        ? "تعديل ملف العميل"
        : "إضافة عميل"
      : item.request.path.endsWith("/repartition")
        ? "تقسيم الأقساط"
        : target?.[1] === "invoices"
          ? "إنشاء جدول فاتورة"
          : "تعديل جدول الأقساط";
  return { data, label, customer, target };
}

export function CustomerRecovery({
  active,
  onRecovered,
  editing = false,
}: {
  active: boolean;
  onRecovered(id: number): void;
  editing?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const online = useConnection((s) => s.status === "online");
  const scope = useSession(
    (s) =>
      s.session &&
      [
        s.session.tenant.slug,
        s.session.tenant.id,
        s.session.user.id,
        s.session.branch?.id,
        s.session.branch_scope,
        s.session.permissions.join(","),
      ].join(":"),
  );
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["customer-recovery", scope],
    queryFn: finora.customers.savedCommands,
    enabled: active,
    refetchInterval: active ? 5000 : false,
  });
  const recover = useMutation({
    mutationFn: finora.customers.recoverCommand,
    onSuccess: (id) => {
      void Promise.all(
        ["customer-recovery", "customers", "finance", "reports", "orders", "pos"].map((name) =>
          cache.invalidateQueries({ queryKey: [name] }),
        ),
      );
      toast.success("تم تأكيد طلب الحفظ الأصلي وتحديث ملف العميل");
      setOpen(false);
      onRecovered(id);
    },
    onError: () => void query.refetch(),
  });
  const items = query.data?.items ?? [];
  const selected = items.find((item) => item.key === selectedKey) ?? items[0];
  if (!items.length && !query.data?.error && !query.isError) return null;
  return (
    <>
      <div
        className="flex shrink-0 items-center justify-between gap-3 rounded-control border border-warning/20 bg-warning-soft px-4 py-2.5 text-sm"
        role="status"
      >
        <span className="flex items-center gap-2 text-ink-soft">
          <Clock3 size={17} />
          {items.length
            ? `${formatNumber(items.length)} طلب حفظ يحتاج تأكيد`
            : "تعذّر فتح طلبات الحفظ المحفوظة"}
          <FeatureHelp
            label="شرح استرجاع طلبات الحفظ"
            text="نحفظ طلب العميل مشفراً على هذا الجهاز قبل إرساله. إذا انقطع الاتصال أو أُغلق البرنامج قبل تأكيد النتيجة، افتح الطلب وراجع بياناته ثم أعد نفس الطلب. يبقى رقم العملية نفسه لمنع التكرار. يتطلب الاسترجاع اتصالاً وصلاحياتك الحالية، ولا ينفذ تلقائياً."
          />
        </span>
        <button
          className={button}
          disabled={editing}
          title={editing ? "أغلق نموذج العميل أولاً؛ بياناته تبقى في النموذج أثناء التحرير" : undefined}
          onClick={() => setOpen(true)}
        >
          طلبات الحفظ المحفوظة
        </button>
      </div>
      {open && (
        <SidePanel
          open
          layer={40}
          title="طلبات الحفظ المحفوظة"
          subtitle="طلباتك على هذا الجهاز ضمن الشركة والفرع الحاليين"
          onClose={() => {
            if (!recover.isPending) setOpen(false);
          }}
          footer={
            <div className="space-y-2">
              {selected && (
                <>
                  <p className="text-xs text-ink-soft">
                    الطلب المختار: {details(selected).label}
                    {details(selected).customer && ` · العميل #${details(selected).customer}`}
                  </p>
                  <button
                    className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-control bg-gradient-to-l from-violet to-violet-deep px-4 text-sm font-semibold text-white disabled:opacity-50"
                    disabled={!online || recover.isPending}
                    onClick={() => recover.mutate(selected.key)}
                  >
                    <RefreshCw
                      size={15}
                      className={recover.isPending ? "animate-spin motion-reduce:animate-none" : ""}
                    />
                    {recover.isPending ? "جارٍ تأكيد الطلب…" : "تأكيد نفس الطلب"}
                  </button>
                </>
              )}
              <button
                className={`${button} w-full`}
                disabled={recover.isPending}
                onClick={() => void query.refetch()}
              >
                تحديث الطلبات
              </button>
            </div>
          }
        >
          <p className="mb-4 rounded-control bg-violet-soft p-3 text-sm leading-7 text-ink-soft">
            راجع البيانات ثم اضغط «تأكيد نفس الطلب» لاسترجاع نتيجته برقم العملية الأصلي ومنع التكرار. لا تضف
            طلباً بديلاً قبل التأكيد.
          </p>
          {!online && (
            <p role="status" className="mb-3 text-warning">
              يلزم الاتصال لاسترجاع نتيجة الحفظ.
            </p>
          )}
          {(query.data?.error || query.isError) && (
            <p role="alert" className="mb-3 text-danger">
              {query.data?.error ?? toFinoraError(query.error).message}
            </p>
          )}
          {recover.error && (
            <p role="alert" className="mb-3 rounded-control bg-danger-soft p-3 text-danger">
              {toFinoraError(recover.error).message} يبقى الطلب محفوظاً للمراجعة وإعادة المحاولة.
            </p>
          )}
          <div className="space-y-3">
            {items.map((item) => {
              const { label, data, customer, target } = details(item);
              const fields =
                data.data && typeof data.data === "object" && !Array.isArray(data.data) ? data.data : null;
              return (
                <article
                  key={item.key}
                  className={`rounded-panel border bg-white p-4 ${selected?.key === item.key ? "border-violet/40" : "border-line"}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-ink">{label}</h3>
                    <span className="rounded-full bg-violet-soft px-2 py-1 text-xs text-violet-deep">
                      {item.state === "confirmed" ? "وصل رد الخادم" : "النتيجة غير مؤكدة"}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-ink-soft">
                    {customer
                      ? `العميل #${customer}`
                      : fields
                        ? String(fields.name ?? "")
                        : `العميل #${data.id ?? "—"}`}{" "}
                    {target && ` · ${target[1] === "invoices" ? "فاتورة" : "جدول"} #${target[2]}`}
                  </p>
                  {fields && (
                    <dl className="mt-3 space-y-1 text-sm text-ink-soft">
                      {Object.entries(fields).map(([name, value]) => (
                        <div key={name} className="break-words">
                          <dt className="inline">
                            {{
                              name: "الاسم",
                              phone: "الهاتف",
                              phone2: "هاتف إضافي",
                              city: "المدينة",
                              address: "العنوان",
                              notes: "الملاحظات",
                            }[name] ?? name}
                            :{" "}
                          </dt>
                          <dd className="inline">{String(value || "—")}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {typeof data.reason === "string" && (
                    <p className="mt-2 break-words text-sm text-ink-soft">{data.reason}</p>
                  )}
                  {typeof data.source_reference === "string" && (
                    <p className="mt-2 break-words text-sm text-ink-soft">المرجع: {data.source_reference}</p>
                  )}
                  {typeof data.amount === "number" && (
                    <p className="mt-2 text-sm font-semibold">{formatNumber(data.amount)} د.ع</p>
                  )}
                  {typeof data.count === "number" && (
                    <p className="mt-2 text-sm text-ink-soft">
                      {formatNumber(data.count)} قسط · أول استحقاق {String(data.first_due_date)} ·{" "}
                      {data.interval === "weekly" ? "أسبوعي" : "شهري"}
                    </p>
                  )}
                  {Array.isArray(data.installments) && (
                    <div className="mt-3 max-h-48 overflow-auto rounded-control border border-line">
                      <table className="w-full text-sm">
                        <thead className="bg-violet-soft">
                          <tr>
                            <th className="p-2">القسط</th>
                            <th className="p-2">الموعد المطلوب</th>
                            <th className="p-2">المبلغ</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.installments.map((raw, index) => {
                            if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
                            return (
                              <tr key={index} className="border-t border-line">
                                <td className="p-2">#{String(raw.id)}</td>
                                <td className="p-2 ltr-isolate">{String(raw.date)}</td>
                                <td className="p-2 ltr-isolate">{formatNumber(Number(raw.total))} د.ع</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <p className="my-3 text-xs text-ink-faint">
                    محفوظ {new Date(item.created).toLocaleString("ar-IQ")}
                  </p>
                  {items.length > 1 && (
                    <button
                      className={button}
                      aria-pressed={selected?.key === item.key}
                      disabled={recover.isPending}
                      onClick={() => setSelectedKey(item.key)}
                    >
                      {selected?.key === item.key ? "الطلب مختار" : "اختيار هذا الطلب"}
                    </button>
                  )}
                </article>
              );
            })}
          </div>
        </SidePanel>
      )}
    </>
  );
}
