import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { CalendarClock, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { finora, toFinoraError } from "@/api/finora";
import type { CustomerSchedule, ScheduleEdit } from "@/api/finora/customers";
import { ConfirmDialog } from "@/components/Dialog";
import { FeatureHelp } from "@/components/FeatureHelp";
import { MoneyInput } from "@/components/MoneyInput";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { formatIqd } from "@/utils/money";
import { CustomerPlanBuilder } from "./CustomerPlanBuilder";

const field =
  "h-10 w-full rounded-control border border-line bg-white px-3 text-sm outline-none focus:border-violet/50 disabled:bg-surface-sunken disabled:text-ink-faint";
const historyTime = new Intl.DateTimeFormat("ar-IQ-u-nu-latn", {
  dateStyle: "short",
  timeStyle: "short",
  hour12: true,
  timeZone: "Asia/Baghdad",
});

export function CustomerScheduleEditor({
  customerId,
  planId,
  onClose,
}: {
  customerId: number;
  planId: number;
  onClose(): void;
}) {
  const [generation, setGeneration] = useState(0);
  const [partition, setPartition] = useState(false);
  const loadingPanel = useRef<HTMLDivElement>(null);
  const query = useQuery({
    queryKey: ["customers", "schedule", customerId, planId],
    queryFn: () => finora.customers.schedule(customerId, planId),
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    if (query.data) return;
    const previous = document.activeElement as HTMLElement | null;
    loadingPanel.current?.querySelector<HTMLElement>("button")?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onClose();
      } else if (event.key === "Tab") {
        const controls = loadingPanel.current?.querySelectorAll<HTMLButtonElement>("button");
        const first = controls?.[0],
          last = controls?.[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", handle, true);
    return () => {
      window.removeEventListener("keydown", handle, true);
      previous?.focus({ preventScroll: true });
    };
  }, [query.data, onClose]);
  if (partition && query.data)
    return (
      <CustomerPlanBuilder
        customerId={customerId}
        planId={planId}
        onClose={() => setPartition(false)}
        onSaved={() => {
          setPartition(false);
          setGeneration((value) => value + 1);
        }}
      />
    );
  if (query.data)
    return (
      <ScheduleForm
        key={generation}
        initial={query.data}
        onClose={onClose}
        onPartition={() => setPartition(true)}
        onReload={async () => {
          const next = await query.refetch();
          if (next.data && !next.error) setGeneration((value) => value + 1);
        }}
      />
    );
  return createPortal(
    <div className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/20 p-5">
      <div
        ref={loadingPanel}
        role="dialog"
        aria-modal="true"
        aria-label={`جدولة الأقساط #${planId}`}
        className="glass-solid w-[520px] max-w-full rounded-panel p-6"
      >
        <h2 className="font-bold text-ink">جدولة الأقساط #{planId}</h2>
        {query.isError ? (
          <p role="alert" className="my-4 text-danger">
            {toFinoraError(query.error).message}
          </p>
        ) : (
          <p className="my-4 text-ink-soft">جارٍ تحميل الجدول…</p>
        )}
        {query.isError && (
          <button className={field} onClick={() => void query.refetch()}>
            إعادة المحاولة
          </button>
        )}
        <button className="mt-4 text-sm text-violet-deep" onClick={onClose}>
          إغلاق
        </button>
      </div>
    </div>,
    document.body,
  );
}

function ScheduleForm({
  initial,
  onClose,
  onReload,
  onPartition,
}: {
  initial: CustomerSchedule;
  onClose(): void;
  onReload(): Promise<void>;
  onPartition(): void;
}) {
  const cache = useQueryClient();
  const online = useConnection((state) => state.status === "online");
  const [source, setSource] = useState(initial);
  const [rows, setRows] = useState(initial.installments.map(({ id, date, total }) => ({ id, date, total })));
  const [reason, setReason] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [discard, setDiscard] = useState<"close" | "reload" | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const panel = useRef<HTMLFormElement>(null);
  const key = useRef(crypto.randomUUID());
  const sent = useRef<ScheduleEdit | null>(null);
  const original = source.installments.map(({ id, date, total }) => ({ id, date, total }));
  const dirty = JSON.stringify(rows) !== JSON.stringify(original) || reason.trim().length > 0;
  const total = rows.reduce((sum, row) => sum + row.total, 0);
  const valid =
    total === source.total &&
    reason.trim().length >= 3 &&
    rows.every((row) => {
      const current = source.installments.find((item) => item.id === row.id);
      return (
        current &&
        row.date &&
        row.total >= current.paid &&
        (row.total > 0 ||
          (row.total === 0 &&
            current.total === 0 &&
            current.paid === 0 &&
            source.protected_ids?.includes(row.id)))
      );
    });
  const save = useMutation({
    mutationFn: () => {
      sent.current ??= { revision: source.revision, reason, installments: rows.map((row) => ({ ...row })) };
      return finora.customers.reschedule(source.customer_id, source.id, sent.current, key.current);
    },
    onSuccess: (updated) => {
      setSource(updated);
      setRows(updated.installments.map(({ id, date, total }) => ({ id, date, total })));
      setReason("");
      setUncertain(false);
      sent.current = null;
      key.current = crypto.randomUUID();
      cache.setQueryData(["customers", "schedule", updated.customer_id, updated.id], updated);
      void Promise.all([
        cache.invalidateQueries({ queryKey: ["customers"] }),
        cache.invalidateQueries({ queryKey: ["finance"] }),
        cache.invalidateQueries({ queryKey: ["reports"] }),
      ]);
      toast.success("تم حفظ جدولة الأقساط دون تغيير أصل الدين أو المدفوع");
    },
    onError: (error) => {
      const kind = toFinoraError(error).kind;
      const unknown =
        kind === "network" || kind === "timeout" || kind === "server" || kind === "invalid_response";
      setUncertain(unknown);
      if (!unknown) sent.current = null;
    },
  });
  const locked = save.isPending || uncertain || refreshing;
  const close = () => {
    if (!locked) {
      if (dirty) setDiscard("close");
      else onClose();
    }
  };
  const closeRef = useRef(close);
  closeRef.current = close;
  const discardRef = useRef(discard);
  discardRef.current = discard;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => panel.current?.querySelector<HTMLElement>("button")?.focus());
    const handle = (event: KeyboardEvent) => {
      if (discardRef.current || document.querySelector("[data-popover]")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRef.current();
      } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        panel.current?.requestSubmit();
      } else if (event.key === "Tab") {
        const controls = panel.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), summary",
        );
        const first = controls?.[0],
          last = controls?.[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", handle, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handle, true);
      previous?.focus({ preventScroll: true });
    };
  }, []);
  const reload = async () => {
    setRefreshing(true);
    try {
      await onReload();
    } finally {
      setRefreshing(false);
    }
  };
  return createPortal(
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/20 p-5"
      >
        <motion.form
          ref={panel}
          role="dialog"
          aria-modal="true"
          aria-label={`جدولة الأقساط #${source.id}`}
          dir="rtl"
          initial={{ opacity: 0, y: 12, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          className="glass-solid flex max-h-[92vh] w-[940px] max-w-full flex-col overflow-hidden rounded-panel shadow-panel"
          onSubmit={(event) => {
            event.preventDefault();
            if (online && !save.isPending && !refreshing && (valid || uncertain)) save.mutate();
          }}
        >
          <header className="flex items-center gap-3 border-b border-line/70 px-5 py-4">
            <span className="grid h-11 w-11 place-items-center rounded-control bg-violet-soft text-violet-deep">
              <CalendarClock size={22} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="font-bold text-ink">جدولة الأقساط #{source.id}</h2>
              <p className="text-xs text-ink-faint">
                {source.invoice_id ? `فاتورة #${source.invoice_id}` : "دين مستقل"} · تعديل توزيع المتبقي
                ومواعيد الاستحقاق
              </p>
            </div>
            <FeatureHelp
              label="شرح إعادة الجدولة"
              text="تغيّر قيمة الأقساط المتبقية ومواعيدها، مع بقاء أصل الدين ومجموع المدفوع ثابتين. القسط المسدد يبقى محفوظاً، ولا يجوز خفض قسط دون مدفوعه. لا تنشأ حركة صندوق أو إيراد. سبب التعديل والجدول السابق محفوظان، وأي تحصيل أحدث يتطلب تحميل الجدول من جديد."
            />
            <button
              type="button"
              disabled={locked}
              aria-label="إغلاق الجدولة"
              onClick={close}
              className="rounded-control p-2 text-ink-soft hover:bg-surface-sunken disabled:opacity-40"
            >
              <X size={19} />
            </button>
          </header>
          <div className="min-h-0 space-y-5 overflow-y-auto p-5">
            <div className="grid grid-cols-3 gap-3">
              {[
                ["أصل الدين", source.total],
                ["المدفوع المحفوظ", source.paid],
                ["المتبقي", source.total - source.paid],
              ].map(([label, value]) => (
                <div key={label} className="rounded-control border border-line bg-white p-3">
                  <p className="text-xs text-ink-faint">{label}</p>
                  <p className="ltr-isolate mt-1 font-bold text-ink">{formatIqd(Number(value))}</p>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                disabled={locked || dirty || !online}
                onClick={onPartition}
                className="rounded-control border border-line bg-white px-4 py-2 text-sm text-violet-deep disabled:opacity-40"
              >
                تغيير عدد الأقساط المتاحة
              </button>
              <FeatureHelp
                label="شرح تغيير عدد الأقساط"
                text="قسّم الأقساط التي لم ترتبط بدفعة سابقة. الأقساط المرتبطة بالسداد أو العكس تبقى محفوظة. احفظ تعديلك الحالي أو أعد تحميل الجدول قبل فتح التقسيم."
              />
            </div>
            <div className="overflow-x-auto rounded-panel border border-line bg-white">
              <table className="w-full min-w-[560px] text-sm">
                <caption className="sr-only">تعديل جدول الأقساط</caption>
                <thead className="bg-surface-sunken text-ink-soft">
                  <tr>
                    {["القسط", "الاستحقاق", "قيمة القسط", "المدفوع", "المتبقي"].map((label) => (
                      <th key={label} className="px-3 py-3 text-start">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => {
                    const current = source.installments[index];
                    if (!current) return null;
                    const paid = current.paid === current.total;
                    return (
                      <tr key={row.id} className="border-t border-line/60">
                        <td className="px-3 py-3">
                          <strong>#{current.number}</strong>
                          {paid && <p className="mt-1 text-xs text-success">مسدد</p>}
                        </td>
                        <td className="px-3 py-3">
                          <input
                            type="date"
                            aria-label={`استحقاق القسط ${current.number}`}
                            value={row.date}
                            disabled={locked || paid}
                            className={field}
                            onChange={(event) =>
                              setRows((all) =>
                                all.map((item) =>
                                  item.id === row.id ? { ...item, date: event.target.value } : item,
                                ),
                              )
                            }
                          />
                        </td>
                        <td className="px-3 py-3">
                          <fieldset disabled={locked || paid}>
                            <MoneyInput
                              label={`قيمة القسط ${current.number}`}
                              value={row.total}
                              onChange={(value) =>
                                setRows((all) =>
                                  all.map((item) => (item.id === row.id ? { ...item, total: value } : item)),
                                )
                              }
                              className="w-32"
                            />
                          </fieldset>
                        </td>
                        <td className="ltr-isolate px-3 py-3 text-ink-soft">{formatIqd(current.paid)}</td>
                        <td className="ltr-isolate px-3 py-3 font-semibold text-violet-deep">
                          {formatIqd(Math.max(0, row.total - current.paid))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p
              className={total === source.total ? "text-sm text-ink-soft" : "text-sm text-danger"}
              role={total === source.total ? undefined : "alert"}
            >
              مجموع الجدول: {formatIqd(total)} · المطلوب: {formatIqd(source.total)}
            </p>
            <label className="block text-sm font-semibold text-ink">
              سبب إعادة الجدولة
              <textarea
                aria-label="سبب إعادة الجدولة"
                value={reason}
                maxLength={500}
                minLength={3}
                required
                disabled={locked}
                className={`${field} mt-2 h-20 resize-none py-2`}
                placeholder="مثلاً: طلب العميل تأجيل موعد الاستحقاق"
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            {save.isError && (
              <p role="alert" className="rounded-control bg-danger-soft p-3 text-sm text-danger">
                {toFinoraError(save.error).message}
              </p>
            )}
            {uncertain && (
              <p className="rounded-control bg-warning-soft p-3 text-sm text-warning">
                نتيجة الحفظ غير مؤكدة؛ أعد نفس الحفظ. بعد إعادة تشغيل البرنامج راجع طلبات الحفظ المحفوظة في
                صفحة العملاء.
              </p>
            )}
            <details className="rounded-panel border border-line bg-white p-4">
              <summary className="cursor-pointer font-semibold text-ink">
                تاريخ تعديل الجدولة ({source.history_total})
              </summary>
              {source.history.length === 0 ? (
                <p className="mt-3 text-sm text-ink-faint">لم تجرِ تعديلات على هذه الجدولة.</p>
              ) : (
                <div className="mt-3 space-y-3">
                  {source.history.map((entry) => (
                    <article key={entry.id} className="rounded-control bg-surface-sunken p-3 text-sm">
                      <p className="font-semibold text-ink">{entry.reason}</p>
                      <p className="my-1 text-xs text-ink-faint">
                        {entry.actor} ·{" "}
                        <time dateTime={entry.date}>{historyTime.format(new Date(entry.date))}</time>
                      </p>
                      {entry.after
                        .filter((row) => {
                          const before = entry.before.find((item) => item.id === row.id);
                          return !before || before.date !== row.date || before.total !== row.total;
                        })
                        .map((row) => {
                          const before = entry.before.find((item) => item.id === row.id);
                          return (
                            <p key={row.id} className="text-xs leading-6 text-ink-soft">
                              {before ? `قسط #${row.number}` : `قسط جديد #${row.number}`}: {before?.date} ←{" "}
                              {row.date} · {formatIqd(before?.total ?? 0)} ← {formatIqd(row.total)}
                            </p>
                          );
                        })}
                      {entry.before
                        .filter((row) => !entry.after.some((item) => item.id === row.id))
                        .map((row) => (
                          <p key={`removed-${row.id}`} className="text-xs leading-6 text-ink-soft">
                            أُلغي قسط غير مرتبط بدفعات #{row.number} · {formatIqd(row.total)}
                          </p>
                        ))}
                    </article>
                  ))}
                </div>
              )}
              {source.history_total > source.history.length && (
                <p className="mt-2 text-xs text-ink-faint">
                  عرض آخر {source.history.length} تعديل من {source.history_total}.
                </p>
              )}
            </details>
          </div>
          <footer className="flex items-center justify-between gap-3 border-t border-line/70 bg-white/70 px-5 py-4">
            <button
              type="submit"
              disabled={!online || save.isPending || refreshing || (!valid && !uncertain)}
              className="h-11 rounded-control bg-gradient-to-l from-violet to-violet-deep px-5 text-sm font-semibold text-white disabled:opacity-45"
            >
              {save.isPending ? "جارٍ الحفظ…" : uncertain ? "إعادة محاولة نفس الحفظ" : "حفظ الجدولة"}
            </button>
            <button
              type="button"
              disabled={locked || !online}
              onClick={() => (dirty ? setDiscard("reload") : void reload())}
              className="flex h-10 items-center gap-2 rounded-control px-3 text-sm text-violet-deep hover:bg-violet-soft disabled:opacity-40"
            >
              <RefreshCw size={16} />
              تحميل أحدث جدول
            </button>
          </footer>
        </motion.form>
      </motion.div>
      <ConfirmDialog
        open={discard !== null}
        title="تعديلات غير محفوظة"
        message={
          discard === "reload"
            ? "تحميل الجدول الأحدث يلغي التعديلات التي لم تحفظ."
            : "إغلاق النافذة يلغي التعديلات التي لم تحفظ."
        }
        confirmLabel={discard === "reload" ? "تحميل الجدول" : "إغلاق دون حفظ"}
        onClose={() => setDiscard(null)}
        onConfirm={() => {
          const action = discard;
          setDiscard(null);
          if (action === "reload") void reload();
          else onClose();
        }}
      />
    </>,
    document.body,
  );
}
