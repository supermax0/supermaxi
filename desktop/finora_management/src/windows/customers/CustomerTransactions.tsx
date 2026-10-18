import { useMutation, useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Download, History, Printer, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { finora, toFinoraError } from "@/api/finora";
import type { CustomerTransaction, CustomerHistoricalRow } from "@/api/finora/customers";
import { FeatureHelp } from "@/components/FeatureHelp";
import { TablePagination } from "@/components/TablePagination";
import { useCan } from "@/stores/session";
import { useConnection } from "@/stores/connection";
import { useFinanceNavigation } from "@/stores/financeNavigation";
import { useOrderNavigation } from "@/stores/orderNavigation";
import { useWindowManager } from "@/stores/windowManager";
import { toast } from "@/stores/toasts";
import { formatIqd } from "@/utils/money";

const button =
  "flex h-10 items-center gap-2 rounded-control border border-line bg-white px-3 text-sm text-ink-soft hover:bg-violet-soft disabled:opacity-40";
const day = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Baghdad", dateStyle: "short" });
function date(value: string | null) {
  if (!value) return "غير محدد";
  if (value.length === 10) return value;
  return day.format(new Date(value.replace(" ", "T") + (/[Zz]|[+-]\d\d:\d\d$/.test(value) ? "" : "Z")));
}

export function CustomerTransactions({
  customerId,
  customerName,
  onClose,
  onSchedule,
  historical = false,
}: {
  customerId: number;
  customerName: string;
  onClose(): void;
  onSchedule(id: number): void;
  historical?: boolean;
}) {
  const [page, setPage] = useState(1),
    [size, setSize] = useState(25);
  const [from, setFrom] = useState(""),
    [to, setTo] = useState("");
  const dates = { ...(from ? { date_from: from } : {}), ...(to ? { date_to: to } : {}) };
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const online = useConnection((state) => state.status === "online");
  const canFinance = useCan("finance.view"),
    canOrders = useCan("can_see_orders");
  const history = useQuery<
    | Awaited<ReturnType<typeof finora.customers.transactions>>
    | Awaited<ReturnType<typeof finora.customers.accountHistory>>
  >({
    queryKey: [
      "customers",
      historical ? "account-history" : "transactions",
      customerId,
      page,
      size,
      from,
      to,
    ],
    queryFn: () =>
      historical
        ? finora.customers.accountHistory(customerId, page, size, dates)
        : finora.customers.transactions(customerId, page, size),
  });
  const coverage = history.data && "coverage" in history.data ? history.data.coverage : null;
  const print = useMutation({
    mutationFn: () =>
      historical
        ? finora.customers.printAccountHistory(customerId, dates)
        : finora.customers.printTransactions(customerId),
    onError: (error) => toast.error(toFinoraError(error).message),
  });
  const exportCsv = useMutation({
    mutationFn: async () => {
      const result = await (historical
        ? finora.customers.exportAccountHistory(customerId, dates)
        : finora.customers.exportTransactions(customerId));
      const url = URL.createObjectURL(new Blob([result.content], { type: "text/csv;charset=utf-8" }));
      try {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = result.filename;
        anchor.click();
      } finally {
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    },
    onError: (error) => toast.error(toFinoraError(error).message),
  });
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() => panel.current?.querySelector<HTMLElement>("button")?.focus());
    const handle = (event: KeyboardEvent) => {
      if (document.querySelector("[data-popover]")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRef.current();
      }
      if (event.key === "Tab") {
        const controls = panel.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),select:not(:disabled)",
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
  const open = (row: CustomerTransaction | CustomerHistoricalRow) => {
    if (row.voucher_id && canFinance) {
      useFinanceNavigation.getState().showVoucher(row.voucher_id);
      useWindowManager.getState().open("finance");
      onClose();
    } else if (row.invoice_id && canOrders) {
      useOrderNavigation.getState().open(row.invoice_id);
      useWindowManager.getState().open("orders");
      onClose();
    } else if (row.plan_id) {
      onSchedule(row.plan_id);
    }
  };
  return createPortal(
    <motion.div
      className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/20 p-5"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
    >
      <motion.div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={`${historical ? "كشف الحساب التاريخي" : "حركات التحصيل"} — ${customerName}`}
        dir="rtl"
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className="glass-solid flex h-[88vh] max-h-[92vh] w-[1160px] min-w-0 max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-panel shadow-panel"
      >
        <header className="flex items-center gap-3 border-b border-line/70 px-5 py-4">
          <span className="grid h-11 w-11 place-items-center rounded-control bg-violet-soft text-violet-deep">
            <History size={22} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="font-bold text-ink">
              {historical ? "كشف الحساب التاريخي" : "حركات التحصيل والتسويات"}
            </h2>
            <p className="truncate text-xs text-ink-faint">{customerName} · السندات والدفعات والعكس</p>
          </div>
          <FeatureHelp
            label={historical ? "شرح كشف الحساب التاريخي" : "شرح حركات التحصيل"}
            text={
              historical
                ? "الكشف يجمع أصول الديون الموثقة وتعديلها والتحصيل والتسويات والعكس. أرصدة الأيام لا تعرض إلا عندما يثبت التاريخ ويطابق الرصيد الحالي. السند وحصص أقساطه لا تتكرر، والطباعة والتصدير يشملان الفترة المختارة وكل صفحاتها."
                : "السند يظهر مرة واحدة؛ دفعة الفاتورة وحصص أقساطها جزء منه. التسوية تخفض الدين والرصيد المقدم بدون قبض جديد. العكس يبقى بجانب الأصل. الأرصدة المعروضة حالية، وصافي المستحق لا ينفذ تسوية تلقائية. غير محدد تعني أن المصدر لا يثبت النقد أو تاريخ القبض. الطباعة والتصدير يشملان جميع الصفحات."
            }
          />
          <button
            className={button}
            aria-label={historical ? "إغلاق كشف الحساب التاريخي" : "إغلاق حركات التحصيل"}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 p-5">
          {history.data && (
            <>
              <div className="grid grid-cols-3 gap-3">
                {[
                  ["الدين الحالي", history.data.summary.debt],
                  ["الرصيد المقدم", history.data.summary.advance],
                  ["صافي المستحق الحالي", history.data.summary.net_due],
                ].map(([label, amount]) => (
                  <div key={label} className="rounded-control border border-line bg-white p-3">
                    <p className="text-xs text-ink-faint">{label}</p>
                    <p className="ltr-isolate mt-1 text-lg font-bold text-ink">{formatIqd(Number(amount))}</p>
                  </div>
                ))}
              </div>
              {history.data.summary.unexplained_documents > 0 && (
                <p role="alert" className="rounded-control bg-warning-soft p-3 text-xs text-warning">
                  تفاصيل التحصيل ناقصة أو غير متطابقة في {history.data.summary.unexplained_documents} مستند؛
                  مجموع الفروقات {formatIqd(history.data.summary.unexplained_amount)}. تحتاج مراجعة، ولا تمثل
                  حركة قبض جديدة.
                </p>
              )}
            </>
          )}
          {historical && (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <label className="text-xs text-ink-soft">
                  من تاريخ
                  <input
                    aria-label="بداية فترة الكشف"
                    type="date"
                    value={from}
                    onChange={(event) => {
                      setFrom(event.target.value);
                      setPage(1);
                    }}
                    className="ms-2 h-10 rounded-control border border-line bg-white px-3 text-sm"
                  />
                </label>
                <label className="text-xs text-ink-soft">
                  إلى تاريخ
                  <input
                    aria-label="نهاية فترة الكشف"
                    type="date"
                    value={to}
                    onChange={(event) => {
                      setTo(event.target.value);
                      setPage(1);
                    }}
                    className="ms-2 h-10 rounded-control border border-line bg-white px-3 text-sm"
                  />
                </label>
                <FeatureHelp
                  label="شرح الرصيد التاريخي"
                  text="يضم أصل الدين وتخفيضه والتحصيل والمقدم والعكس من المستندات الموثقة، دون تكرار أقساط الفاتورة. الرصيد يظهر على آخر حركة لكل يوم؛ ترتيب السندات داخل اليوم لا يثبت ترتيبها اللحظي. إذا كان أصل قديم أو تاريخ ناقصاً، لا يظهر رصيد تاريخي مخمّن."
                />
              </div>
              {coverage && !coverage.complete && (
                <p role="status" className="rounded-control bg-amber-50 p-3 text-sm text-amber-800">
                  التاريخ غير مكتمل؛ الأرصدة التاريخية غير مثبتة. أصول ناقصة: {coverage.missing_origins}، غير
                  مؤرخ: {coverage.undated_movements}، مستندات مؤرشفة: {coverage.archived_documents}. فرق الدين
                  غير الموزع: {formatIqd(coverage.unplaced_debt)}.
                </p>
              )}
              {history.data && "opening_net" in history.data.summary && (
                <p className="text-sm text-ink-soft">
                  رصيد بداية الفترة:{" "}
                  {history.data.summary.opening_net === null
                    ? "غير مثبت"
                    : formatIqd(history.data.summary.opening_net)}{" "}
                  · نهاية الفترة:{" "}
                  {history.data.summary.closing_net === null
                    ? "غير مثبت"
                    : formatIqd(history.data.summary.closing_net)}
                </p>
              )}
            </>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button className={button} disabled={!online || print.isPending} onClick={() => print.mutate()}>
              <Printer size={16} />
              طباعة الحركات / PDF
            </button>
            <button
              className={button}
              disabled={!online || exportCsv.isPending}
              onClick={() => exportCsv.mutate()}
            >
              <Download size={16} />
              تصدير كل الحركات
            </button>
            <button
              className={button}
              disabled={!online || history.isFetching}
              onClick={() => void history.refetch()}
            >
              <RefreshCw size={16} />
              تحديث الحركات
            </button>
            {history.data && (
              <span className="ms-auto text-xs text-ink-faint">كما في {history.data.as_of}</span>
            )}
          </div>
          <div
            role="region"
            aria-label="جدول حركات التحصيل"
            className="min-h-0 min-w-0 flex-1 overflow-auto rounded-panel border border-line bg-white"
          >
            {history.isPending ? (
              <p role="status" className="p-6">
                جارٍ تحميل الحركات…
              </p>
            ) : history.isError ? (
              <div role="alert" className="p-6 text-danger">
                {toFinoraError(history.error).message}
                <button className={button} onClick={() => void history.refetch()}>
                  إعادة المحاولة
                </button>
              </div>
            ) : (
              <table className="w-full min-w-[850px] text-sm">
                <thead className="sticky top-0 z-10 bg-surface-sunken text-ink-soft">
                  <tr>
                    {[
                      "التاريخ",
                      "الحركة / المستند",
                      "المبلغ",
                      "حركة النقد",
                      "تغير الدين",
                      "تغير المقدم",
                      ...(historical ? ["رصيد نهاية اليوم"] : []),
                    ].map((label) => (
                      <th scope="col" key={label} className="px-3 py-3 text-start">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {history.data?.items.map((row) => (
                    <tr
                      key={`${row.kind}:${row.id}`}
                      className="border-t border-line/60 hover:bg-violet-soft/30"
                    >
                      <td className="whitespace-nowrap px-3 py-4 text-xs text-ink-soft">{date(row.date)}</td>
                      <td className="px-3 py-4">
                        <p className="font-semibold text-ink">{row.description}</p>
                        <button
                          className="mt-1 text-xs text-violet-deep disabled:text-ink-faint"
                          disabled={
                            !online ||
                            !(row.voucher_id ? canFinance : row.invoice_id ? canOrders : row.plan_id)
                          }
                          onClick={() => open(row)}
                        >
                          {row.document}
                        </button>
                        {row.status === "reversed" && <span className="ms-2 text-xs text-danger">معكوس</span>}
                      </td>
                      <td className="ltr-isolate whitespace-nowrap px-3 py-4 font-semibold">
                        {formatIqd(row.amount)}
                      </td>
                      <td className="ltr-isolate whitespace-nowrap px-3 py-4 text-ink-soft">
                        {row.cash === null ? "غير محدد" : formatIqd(row.cash)}
                      </td>
                      <td className="ltr-isolate whitespace-nowrap px-3 py-4 text-violet-deep">
                        {formatIqd(row.debt_change)}
                      </td>
                      <td className="ltr-isolate whitespace-nowrap px-3 py-4 text-ink-soft">
                        {formatIqd(row.advance_change)}
                      </td>
                      {historical && (
                        <td className="ltr-isolate whitespace-nowrap px-3 py-4 font-semibold text-ink">
                          {"net_balance" in row && row.net_balance !== null
                            ? formatIqd(row.net_balance)
                            : "—"}
                        </td>
                      )}
                    </tr>
                  ))}
                  {history.data?.total === 0 && (
                    <tr>
                      <td colSpan={historical ? 7 : 6} className="p-10 text-center text-ink-faint">
                        لا توجد حركات مسجلة.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>
        <footer className="border-t border-line/70 bg-white/70 px-5 pb-4">
          <TablePagination
            page={page}
            totalPages={Math.max(1, Math.ceil((history.data?.total ?? 0) / size))}
            total={history.data?.total ?? 0}
            pageSize={size}
            noun="حركة"
            onPage={setPage}
            onPageSize={(value) => {
              setSize(value);
              setPage(1);
            }}
          />
        </footer>
      </motion.div>
    </motion.div>,
    document.body,
  );
}
