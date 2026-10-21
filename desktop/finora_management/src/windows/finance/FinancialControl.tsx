import { useTimeFormat } from "@/stores/displayTime";
import { useId, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Wallet, Landmark, ChartNoAxesCombined, Scale } from "lucide-react";
import { finora, toFinoraError } from "@/api/finora";
import type { ControlSource, ControlSnapshot } from "@/api/finora/financialControl";
import { DataTable } from "@/components/DataTable";
import { StatCard } from "@/components/StatCard";
import { SidePanel, DetailRow } from "@/components/SidePanel";
import { FeatureHelp } from "@/components/FeatureHelp";
import { TablePagination } from "@/components/TablePagination";
import { useWindowManager } from "@/stores/windowManager";
import { toast } from "@/stores/toasts";
import { formatNumber, formatDateTime } from "@/utils/format";

const button = "h-10 rounded-control border border-line bg-white px-3 text-sm text-ink disabled:opacity-50";
const input = "h-11 w-full rounded-control border border-line bg-white px-3 text-sm text-ink";
const money = (value: number | null | undefined) =>
  value == null ? "غير مربوط" : `${formatNumber(value)} د.ع`;
type Body = Parameters<typeof finora.financialControl.measure>[0];
type SourceRow = ControlSource & { id: number };

export function FinancialControl({
  online,
  canMeasure,
  canPrint,
  onAccount,
  onLoans,
}: {
  online: boolean;
  canMeasure: boolean;
  canPrint: boolean;
  onAccount: (id: number) => void;
  onLoans: () => void;
}) {
  useTimeFormat();
  const cache = useQueryClient(),
    formId = useId();
  const [tab, setTab] = useState<"current" | "snapshots">("current");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [selected, setSelected] = useState<number | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [pair, setPair] = useState<{ start: number; end: number } | null>(null);
  const [opening, setOpening] = useState(false);
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [counts, setCounts] = useState<Record<string, { actual: string; evidence: string }>>({});
  const [pending, setPending] = useState<{ body: Body; key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const current = useQuery({
    queryKey: ["finance", "control", "current"],
    queryFn: () => finora.financialControl.current(),
    enabled: online,
  });
  const snapshots = useQuery({
    queryKey: ["finance", "control", "snapshots", page, pageSize],
    queryFn: () => finora.financialControl.list(page, pageSize),
    enabled: online && tab === "snapshots",
  });
  const detail = useQuery({
    queryKey: ["finance", "control", "snapshot", selected],
    queryFn: () => {
      if (selected === null) throw Error("اختر معاينة");
      return finora.financialControl.details(selected);
    },
    enabled: online && selected !== null,
  });
  const comparison = useQuery({
    queryKey: ["finance", "control", "comparison", pair],
    queryFn: () => {
      if (!pair) throw Error("اختر معاينتين");
      return finora.financialControl.compare(pair.start, pair.end);
    },
    enabled: online && pair !== null,
  });
  const treasuries = current.data?.rows.filter((row) => row.treasury_account_id !== undefined) || [];
  const close = () => {
    if (busy || pending) return;
    setOpening(false);
    setSelected(null);
    setError("");
  };
  const navigate = (row: ControlSource) => {
    if (row.treasury_account_id !== undefined) onAccount(row.treasury_account_id);
    else if (row.key.includes("loan") || row.key === "employee_advance") onLoans();
    else if (row.key === "inventory") useWindowManager.getState().open("products");
    else if (row.key === "receivable" || row.key === "customer_advance")
      useWindowManager.getState().open("customers");
    else if (["payable", "supplier_advance"].includes(row.key)) useWindowManager.getState().open("suppliers");
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    let request = pending;
    if (!request) {
      const values = treasuries.map((row) => ({
        id: row.treasury_account_id ?? 0,
        actual: Number(counts[String(row.treasury_account_id)]?.actual),
        evidence: counts[String(row.treasury_account_id)]?.evidence || "",
      }));
      if (
        values.some(
          (value) => !Number.isSafeInteger(value.actual) || !counts[String(value.id)]?.actual.trim(),
        )
      ) {
        setError("أكمل العد أو رصيد الكشف لكل حساب بأرقام صحيحة");
        return;
      }
      request = { body: { name, reason, treasury_counts: values }, key: crypto.randomUUID() };
    }
    setPending(request);
    setBusy(true);
    setError("");
    try {
      const result = await finora.financialControl.measure(request.body, request.key);
      if (!result) throw Error("لم يصل مستند المعاينة");
      setPending(null);
      setOpening(false);
      setSelected(result.id);
      setTab("snapshots");
      await cache.invalidateQueries({ queryKey: ["finance", "control"] });
      toast.success("حُفظت المعاينة دون تغيير الأرصدة أو القيود");
    } catch (cause) {
      const failure = toFinoraError(cause);
      setError(failure.message);
      if (!["network", "timeout", "invalid_response"].includes(failure.kind)) setPending(null);
    } finally {
      setBusy(false);
    }
  };
  const result = comparison.data;
  return (
    <section
      className="relative flex min-h-0 flex-1 flex-col gap-3 [@media(max-height:700px)]:h-auto [@media(max-height:700px)]:flex-none"
      aria-label="الرقابة المالية والمطابقة"
    >
      <div className="flex flex-wrap gap-2">
        <button className={button} aria-pressed={tab === "current"} onClick={() => setTab("current")}>
          المصادر الحالية
        </button>
        <button className={button} aria-pressed={tab === "snapshots"} onClick={() => setTab("snapshots")}>
          المعاينات والمطابقة
        </button>
        <FeatureHelp text="المعاينة تحفظ عد النقد وكشوف البنوك، وتقرأ المخزون والذمم والأصول الأخرى من السجلات التشغيلية. المطابقة تقارن تغير صافي الأصول بالربح بعد فصل رأس المال والسحوبات والتسويات الافتتاحية. لا تثبت المعاينة جرداً فعلياً أو تحصيل الديون؛ حفظها لا يرحّل مالاً أو يصحح رصيداً تلقائياً." />
        <div className="flex-1" />
        {canMeasure && (
          <button
            className={button}
            disabled={!online || !current.data || current.isFetching || !!pending}
            onClick={() => {
              setName("");
              setReason("");
              setCounts({});
              setError("");
              setSelected(null);
              setOpening(true);
            }}
          >
            معاينة معدودة جديدة
          </button>
        )}
        <button
          className={button}
          disabled={!online}
          onClick={() => void cache.invalidateQueries({ queryKey: ["finance", "control"] })}
        >
          تحديث الرقابة
        </button>
      </div>
      {!online && <p role="status">عرض المركز المالي وحفظ العد يتطلبان اتصالاً بالخادم.</p>}
      {current.error && (
        <p role="alert" className="text-sm text-danger">
          {toFinoraError(current.error).message}
        </p>
      )}
      {tab === "current" ? (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-4">
            <StatCard
              label="صافي الأصول من المصادر المسجلة"
              value={formatNumber(current.data?.registered.net_assets || 0)}
              unit="د.ع"
              icon={Wallet}
              tone="violet"
              loading={current.isLoading}
            />
            <StatCard
              label="صافي الأصول من القيود"
              value={formatNumber(current.data?.ledger.net_assets || 0)}
              unit="د.ع"
              icon={Landmark}
              tone="azure"
              loading={current.isLoading}
            />
            <StatCard
              label="فرق المركز المسجل"
              value={formatNumber(
                (current.data?.registered.net_assets || 0) - (current.data?.ledger.net_assets || 0),
              )}
              unit="د.ع"
              icon={Scale}
              tone="warning"
              loading={current.isLoading}
            />
            <StatCard
              label="الربح المحاسبي المتراكم"
              value={formatNumber(current.data?.ledger.profit || 0)}
              unit="د.ع"
              icon={ChartNoAxesCombined}
              tone="success"
              loading={current.isLoading}
            />
          </div>
          {!!current.data?.coverage_issues.length && (
            <details className="rounded-control bg-warning-soft p-3 text-sm text-warning">
              <summary>تحتاج مراجعة: {current.data.coverage_issues.length} مصدر أو رصيد</summary>
              <ul className="mt-2 grid gap-1">
                {current.data.coverage_issues.map((issue, index) => (
                  <li key={`${issue.key}:${index}`}>
                    {issue.message} · {money(issue.amount)}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="text-xs text-ink-muted">
            الأرقام المسجلة حالية. المعاينة المعدودة تتطلب إدخال النقد وكشف كل حساب؛ لا يُفترض أن الرصيد
            المسجل هو المبلغ الفعلي.
          </p>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden [@media(max-height:700px)]:h-60 [@media(max-height:700px)]:flex-none">
            <DataTable<SourceRow>
              label="مصادر المركز المالي"
              rows={current.data?.rows.map((row, index) => ({ ...row, id: index + 1 }))}
              loading={current.isLoading}
              fetching={current.isFetching}
              error={current.error ? toFinoraError(current.error).message : null}
              onRetry={() => void current.refetch()}
              emptyTitle="لا توجد مصادر مالية"
              onOpen={navigate}
              columns={[
                { id: "name", header: "المصدر / فتح العملية", cell: (row) => row.name },
                { id: "type", header: "النوع", cell: (row) => (row.type === "asset" ? "أصل" : "التزام") },
                { id: "source", header: "المصدر المسجل", cell: (row) => money(row.target) },
                { id: "book", header: "القيود", cell: (row) => money(row.current) },
                { id: "diff", header: "الفرق", cell: (row) => money(row.difference) },
              ]}
            />
          </div>
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-sm">
              من معاينة
              <input
                className={input}
                inputMode="numeric"
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </label>
            <label className="text-sm">
              إلى معاينة
              <input
                className={input}
                inputMode="numeric"
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </label>
            <button
              className={button}
              disabled={
                !online ||
                !Number.isSafeInteger(Number(start)) ||
                !Number.isSafeInteger(Number(end)) ||
                Number(start) <= 0 ||
                Number(end) <= Number(start)
              }
              onClick={() => setPair({ start: Number(start), end: Number(end) })}
            >
              مطابقة المعاينتين
            </button>
          </div>
          {comparison.error && (
            <p role="alert" className="text-danger">
              {toFinoraError(comparison.error).message}
            </p>
          )}
          {result && (
            <details open className="rounded-control border border-line p-3 text-sm">
              <summary className={result.matched ? "text-success" : "text-warning"}>
                {result.matched ? "مطابقة موثقة" : "توجد فروقات أو حدود قياس تحتاج مراجعة"} ·{" "}
                {result.start.name} ← {result.end.name}
              </summary>
              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <DetailRow label="تغير صافي الأصول">{money(result.net_assets_change)}</DetailRow>
                <DetailRow label="رأس المال المضاف">{money(result.capital)}</DetailRow>
                <DetailRow label="سحوبات المالك">{money(result.owner_drawings)}</DetailRow>
                <DetailRow label="تسويات افتتاحية">{money(result.opening_adjustments)}</DetailRow>
                <DetailRow label="حركات حقوق ملكية أخرى">{money(result.other_equity)}</DetailRow>
                <DetailRow label="الربح من تغير المركز">{money(result.derived_profit)}</DetailRow>
                <DetailRow label="الربح من القيود">{money(result.accounting_profit)}</DetailRow>
                <DetailRow label="فرق المطابقة">{money(result.difference)}</DetailRow>
              </div>
              <p className="mt-2 text-xs">{result.note}</p>
              {canPrint && (
                <button
                  className={button}
                  disabled={!online}
                  onClick={() =>
                    void finora.financialControl
                      .printComparison(result.start.id, result.end.id)
                      .catch((cause) => toast.error(toFinoraError(cause).message))
                  }
                >
                  طباعة المطابقة
                </button>
              )}
              {!!result.coverage_issues.length && (
                <p className="mt-2 text-warning">
                  المصادر غير المكتملة أو غير المطابقة: {result.coverage_issues.length}. راجع تفاصيل
                  المعاينتين.
                </p>
              )}
            </details>
          )}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden [@media(max-height:700px)]:h-60 [@media(max-height:700px)]:flex-none">
            <DataTable<ControlSnapshot>
              label="سجل معاينات المركز المالي"
              rows={snapshots.data?.items}
              loading={snapshots.isLoading}
              fetching={snapshots.isFetching}
              error={snapshots.error ? toFinoraError(snapshots.error).message : null}
              onRetry={() => void snapshots.refetch()}
              emptyTitle="لا توجد معاينات معدودة"
              onOpen={(row) => {
                if (!pending) {
                  setSelected(row.id);
                  setOpening(false);
                }
              }}
              columns={[
                { id: "id", header: "الرقم", cell: (row) => `FC-${row.id}` },
                { id: "name", header: "المعاينة", cell: (row) => row.name },
                {
                  id: "date",
                  header: "الوقت",
                  cell: (row) => formatDateTime(`${row.created_at}Z`),
                },
                { id: "net", header: "صافي الأصول بعد قياس السيولة", cell: (row) => money(row.net_assets) },
                { id: "issues", header: "ملاحظات القياس", cell: (row) => row.coverage_issues_count },
              ]}
            />
          </div>
          <TablePagination
            className="ps-28"
            page={page}
            pageSize={pageSize}
            total={snapshots.data?.total || 0}
            totalPages={Math.max(1, Math.ceil((snapshots.data?.total || 0) / pageSize))}
            noun="معاينة"
            onPage={setPage}
            onPageSize={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      )}
      <SidePanel
        open={opening || selected !== null}
        title={opening ? "معاينة معدودة للمركز المالي" : "تفاصيل معاينة المركز المالي"}
        onClose={close}
        footer={
          opening && (
            <button className={button} disabled={!online || busy} type="submit" form={formId}>
              {busy ? "جارٍ الحفظ…" : pending ? "إعادة إرسال نفس المعاينة" : "حفظ المعاينة دون ترحيل"}
            </button>
          )
        }
      >
        {!opening && selected !== null && detail.data && canPrint && (
          <button
            className={button}
            disabled={!online}
            onClick={() =>
              void finora.financialControl
                .printSnapshot(selected)
                .catch((cause) => toast.error(toFinoraError(cause).message))
            }
          >
            طباعة المعاينة
          </button>
        )}
        {opening ? (
          <form id={formId} className="grid gap-3" onSubmit={(event) => void save(event)}>
            <p className="text-sm">
              أدخل النقد المعدود ورصيد كشف البنك الآن. الأرقام تبقى أدلة ولا تغير الصندوق أو الربح. عند تكرار
              مصرف بفروع متعددة، أدخل الحصة الخاصة بكل حساب وسجل دليل توزيع الكشف؛ لا تكرر الرصيد الكامل في كل
              فرع.
            </p>
            <fieldset className="grid gap-3" disabled={busy || !!pending}>
              <label>
                اسم المعاينة
                <input
                  className={input}
                  maxLength={100}
                  value={name}
                  required
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              <label>
                سبب المعاينة
                <textarea
                  className={`${input} h-20 py-2`}
                  maxLength={1500}
                  value={reason}
                  required
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              {treasuries.map((row) => {
                const id = String(row.treasury_account_id);
                const value = counts[id] || { actual: "", evidence: "" };
                return (
                  <div key={id} className="grid gap-2 rounded-control border border-line p-3">
                    <strong className="text-sm">
                      {row.name} · المسجل {money(row.target)}
                    </strong>
                    <label>
                      {row.treasury_type === "cash" ? "النقد المعدود" : "رصيد كشف الحساب"} · {row.name}
                      <input
                        className={input}
                        inputMode="numeric"
                        value={value.actual}
                        required
                        onChange={(event) =>
                          setCounts({ ...counts, [id]: { ...value, actual: event.target.value } })
                        }
                      />
                    </label>
                    <label>
                      دليل العد / الكشف · {row.name}
                      <input
                        className={input}
                        maxLength={1000}
                        value={value.evidence}
                        required
                        onChange={(event) =>
                          setCounts({ ...counts, [id]: { ...value, evidence: event.target.value } })
                        }
                      />
                    </label>
                  </div>
                );
              })}
            </fieldset>
            {pending && !busy && (
              <p role="status">لم يصل تأكيد الخادم. أعد نفس الطلب لاسترجاع نتيجته دون إنشاء معاينة ثانية.</p>
            )}
            {error && (
              <p role="alert" className="text-danger">
                {error}
              </p>
            )}
          </form>
        ) : (
          <>
            {detail.error && <p role="alert">{toFinoraError(detail.error).message}</p>}
            {detail.data && (
              <div className="grid gap-3">
                <DetailRow label="الرقم">FC-{detail.data.id}</DetailRow>
                <DetailRow label="المعاينة">{detail.data.name}</DetailRow>
                <DetailRow label="سجلها">{detail.data.created_by}</DetailRow>
                <DetailRow label="السبب">{detail.data.reason}</DetailRow>
                <DetailRow label="صافي الأصول بعد قياس السيولة">{money(detail.data.net_assets)}</DetailRow>
                {detail.data.data.treasury_counts.map((count) => (
                  <div key={count.id} className="rounded-control border border-line p-3 text-sm">
                    <strong>{count.name}</strong>
                    <DetailRow label="المسجل">{money(count.registered)}</DetailRow>
                    <DetailRow label="المعدود / الكشف">{money(count.actual)}</DetailRow>
                    <DetailRow label="الفرق">{money(count.difference)}</DetailRow>
                    <p>{count.evidence}</p>
                  </div>
                ))}
                {detail.data.data.coverage_issues.map((issue, index) => (
                  <p key={`${issue.key}:${index}`} className="text-sm text-warning">
                    {issue.message} · {money(issue.amount)}
                  </p>
                ))}
                <div className="flex gap-2">
                  <button
                    className={button}
                    onClick={() => {
                      setStart(String(detail.data?.id));
                      setSelected(null);
                    }}
                  >
                    بداية المقارنة
                  </button>
                  <button
                    className={button}
                    onClick={() => {
                      setEnd(String(detail.data?.id));
                      setSelected(null);
                    }}
                  >
                    نهاية المقارنة
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </SidePanel>
    </section>
  );
}
