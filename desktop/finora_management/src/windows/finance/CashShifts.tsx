import { useId, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Wallet, ArrowDownLeft, ArrowUpRight } from "lucide-react";
import { finora, toFinoraError } from "@/api/finora";
import type { CashShift } from "@/api/finora/cashShifts";
import type { FinanceMeta } from "@/api/finora/finance";
import { DataTable } from "@/components/DataTable";
import { SidePanel, DetailRow } from "@/components/SidePanel";
import { StatCard } from "@/components/StatCard";
import { FeatureHelp } from "@/components/FeatureHelp";
import { TablePagination } from "@/components/TablePagination";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";

const button = "h-10 rounded-control border border-line bg-white px-4 text-sm text-ink disabled:opacity-50";
const input = "h-11 w-full rounded-control border border-line bg-white px-3 text-sm text-ink";
const money = (value: number | null | undefined) => (value == null ? "—" : `${formatNumber(value)} د.ع`);
type Pending = {
  operation: "cash_shift.open" | "cash_shift.close";
  body: Record<string, string | number>;
  key: string;
};

export function CashShifts({ meta, online }: { meta?: FinanceMeta; online: boolean }) {
  const cache = useQueryClient();
  const formId = useId();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [branch, setBranch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [opening, setOpening] = useState(false);
  const [account, setAccount] = useState("");
  const [name, setName] = useState("");
  const [actual, setActual] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState("");
  const rows = useQuery({
    queryKey: ["finance", "cash-shifts", page, status, pageSize],
    queryFn: () => finora.cashShifts.list(page, status, pageSize),
    enabled: online,
  });
  const detail = useQuery({
    queryKey: ["finance", "cash-shift", selected],
    queryFn: () => {
      if (selected === null) throw Error("اختر وردية");
      return finora.cashShifts.details(selected);
    },
    enabled: online && selected !== null,
  });
  const row = detail.data;
  const accounts = meta?.accounts.filter((item) => item.type === "cash") || [];
  const reset = () => {
    setActual("");
    setReason("");
    setError("");
    setPending(null);
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    const parsed = Number(actual);
    if (!pending && (!actual.trim() || !Number.isSafeInteger(parsed) || parsed < 0)) {
      setError("أدخل النقد الفعلي كعدد صحيح غير سالب");
      return;
    }
    let request: Pending;
    if (pending) request = pending;
    else if (opening)
      request = {
        operation: "cash_shift.open",
        body: {
          treasury_account_id: Number(account),
          branch_id: Number(branch),
          opening_actual: parsed,
          name,
          reason,
        },
        key: crypto.randomUUID(),
      };
    else {
      if (!row?.preview) return;
      request = {
        operation: "cash_shift.close",
        body: { id: row.id, version: row.version, preview_token: row.preview.token, actual: parsed, reason },
        key: crypto.randomUUID(),
      };
    }
    setPending(request);
    setBusy(true);
    setError("");
    try {
      const result = await finora.cashShifts.command(request.operation, request.body, request.key);
      if (!result) throw Error("لم يصل مستند الوردية من الخادم");
      setOpening(false);
      setSelected(result.id);
      reset();
      await cache.invalidateQueries({ queryKey: ["finance"] });
      toast.success(result.status === "closed" ? "أُغلقت الوردية وحُفظ الفرق للمراجعة" : "فُتحت الوردية");
    } catch (cause) {
      const failure = toFinoraError(cause);
      setError(failure.message);
      if (!["network", "timeout", "invalid_response"].includes(failure.kind)) {
        setPending(null);
        await detail.refetch();
      }
    } finally {
      setBusy(false);
    }
  };
  const preview = row?.preview;
  const variance =
    actual.trim() && Number.isSafeInteger(Number(actual)) && preview
      ? Number(actual) - preview.expected
      : row?.variance;
  return (
    <section className="relative flex min-h-0 flex-1 flex-col gap-3" aria-label="ورديات الصندوق">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm">
          حالة الوردية{" "}
          <select
            className={input}
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="">كل الورديات</option>
            <option value="open">مفتوحة</option>
            <option value="closed">مغلقة</option>
          </select>
        </label>
        <FeatureHelp text="المتوقع = النقد الفعلي عند الافتتاح + تغير الرصيد المحاسبي منذ الافتتاح. فرق الافتتاح مستقل عن فرق الإقفال. تسجيل الفرق لا يصرف أو يقبض مالاً ولا يغيّر الربح. للصندوق المشترك وردية واحدة." />
        <div className="flex-1" />
        {meta?.capabilities["finance.create"] && (
          <button
            className={button}
            disabled={!online || pending !== null}
            onClick={() => {
              reset();
              setSelected(null);
              setOpening(true);
              setAccount(String(accounts[0]?.id || ""));
              setBranch(String(meta?.branches[0]?.id || ""));
              setName("");
            }}
          >
            فتح وردية
          </button>
        )}
        <button
          className={button}
          disabled={!online || busy}
          onClick={() => void cache.invalidateQueries({ queryKey: ["finance"] })}
        >
          تحديث الورديات
        </button>
      </div>
      {!online && <p role="status">اتصل بالخادم لعرض الورديات واعتماد النقد.</p>}
      <div className="min-h-0 flex-1">
        <DataTable<CashShift>
          label="سجل ورديات الصندوق"
          rows={rows.data?.items}
          loading={rows.isLoading}
          fetching={rows.isFetching}
          error={rows.error ? toFinoraError(rows.error).message : null}
          onRetry={() => void rows.refetch()}
          emptyTitle="لا توجد ورديات"
          onOpen={(item) => {
            if (pending) return;
            reset();
            setOpening(false);
            setSelected(item.id);
          }}
          columns={[
            { id: "id", header: "الرقم", cell: (item) => `CS-${item.id}` },
            { id: "name", header: "الوردية", cell: (item) => item.name },
            { id: "account", header: "الصندوق", cell: (item) => item.account_name },
            { id: "opener", header: "فتحها", cell: (item) => item.opened_by },
            { id: "status", header: "الحالة", cell: (item) => (item.status === "open" ? "مفتوحة" : "مغلقة") },
            { id: "opening", header: "الافتتاح الفعلي", cell: (item) => money(item.opening_actual) },
            { id: "actual", header: "الإقفال الفعلي", cell: (item) => money(item.actual) },
            { id: "variance", header: "فرق الإقفال", cell: (item) => money(item.variance) },
          ]}
        />
      </div>
      <TablePagination
        page={page}
        totalPages={Math.max(1, Math.ceil((rows.data?.total || 0) / pageSize))}
        total={rows.data?.total || 0}
        pageSize={pageSize}
        noun="وردية"
        onPage={setPage}
        onPageSize={(size) => {
          setPageSize(size);
          setPage(1);
        }}
      />
      <SidePanel
        open={opening || selected !== null}
        title={opening ? "افتتاح وردية الصندوق" : "تفاصيل وردية الصندوق"}
        onClose={() => {
          if (busy || pending) return;
          setOpening(false);
          setSelected(null);
          reset();
        }}
        footer={
          (opening || (row?.status === "open" && meta?.capabilities["finance.approve"])) && (
            <button
              className={button}
              form={formId}
              disabled={
                busy || !online || (!opening && !preview) || (!pending && detail.isFetching && !opening)
              }
              type="submit"
            >
              {busy
                ? "جارٍ الحفظ…"
                : pending
                  ? "إعادة إرسال نفس الطلب"
                  : opening
                    ? "تأكيد افتتاح الوردية"
                    : "تأكيد إغلاق الوردية"}
            </button>
          )
        }
      >
        {!opening && row && meta?.capabilities["finance.print"] && (
          <button
            className={button}
            disabled={!online}
            onClick={() =>
              void finora.finance
                .print("finance_cash_shift", row.id)
                .catch((cause) => toast.error(toFinoraError(cause).message))
            }
          >
            طباعة كشف الوردية
          </button>
        )}
        {detail.error && !opening && (
          <p role="alert">
            {toFinoraError(detail.error).message}
            <button className={button} onClick={() => void detail.refetch()}>
              إعادة تحميل الوردية
            </button>
          </p>
        )}
        {row && !opening && (
          <div className="grid gap-3">
            <DetailRow label="رقم الوردية" children={`CS-${row.id}`} />
            <DetailRow label="الصندوق" children={row.account_name} />
            <DetailRow label="الوردية" children={row.name} />
            <DetailRow label="فتحها" children={row.opened_by} />
            <DetailRow
              label="وقت الافتتاح"
              children={new Date(`${row.opened_at}Z`).toLocaleString("ar-IQ", { timeZone: "Asia/Baghdad" })}
            />
            <DetailRow label="الافتتاح المحاسبي" children={money(row.opening_ledger)} />
            <DetailRow label="الافتتاح الفعلي" children={money(row.opening_actual)} />
            <DetailRow label="فرق الافتتاح" children={money(row.opening_variance)} />
            <DetailRow label="سبب فرق الافتتاح" children={row.opening_reason || "—"} />
            <div className="grid gap-2">
              <StatCard
                label="الإقفال المتوقع"
                value={formatNumber(preview?.expected ?? row.expected ?? 0)}
                unit="د.ع"
                icon={Wallet}
                tone="violet"
              />
              <StatCard
                label="فرق الإقفال"
                value={variance == null ? "—" : formatNumber(variance)}
                unit="د.ع"
                icon={(variance || 0) < 0 ? ArrowUpRight : ArrowDownLeft}
                tone={(variance || 0) === 0 ? "success" : "warning"}
              />
            </div>
            <DetailRow
              label="صافي حركة الصندوق منذ الافتتاح"
              children={money(
                preview?.net_movement ?? (row.ledger == null ? null : row.ledger - row.opening_ledger),
              )}
            />
            {row.status === "closed" && (
              <>
                <DetailRow label="الإقفال الفعلي" children={money(row.actual)} />
                <DetailRow label="سبب الفرق" children={row.reason || "مطابق"} />
                <DetailRow label="أغلقها" children={row.closed_by || "—"} />
                <p className="text-sm">
                  سجل الإقفال محفوظ. الفروقات تحتاج مراجعة وسنداً مستقلاً إذا اعتُمدت تسويتها.
                </p>
              </>
            )}
            {row.ledger_changed_since_close && (
              <p role="status" className="text-sm text-warning">
                تغيّرت مصادر الصندوق بعد الإقفال. الأرقام أعلاه تخص لحظة الإقفال المحفوظة.
              </p>
            )}
          </div>
        )}
        {(opening || (row?.status === "open" && meta?.capabilities["finance.approve"])) && (
          <form
            id={formId}
            className="mt-4 grid gap-3"
            onSubmit={(event) => void save(event)}
            aria-label={opening ? "نموذج افتتاح الوردية" : "نموذج إغلاق الوردية"}
          >
            <fieldset disabled={busy || !!pending} className="grid gap-3">
              {opening && accounts.find((item) => item.id === Number(account))?.branch_id == null && (
                <label>
                  فرع الوردية
                  <select
                    className={input}
                    value={branch}
                    required
                    onChange={(event) => setBranch(event.target.value)}
                  >
                    <option value="">اختر الفرع</option>
                    {meta?.branches.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {opening && (
                <>
                  <label>
                    الصندوق النقدي
                    <select
                      className={input}
                      value={account}
                      onChange={(e) => setAccount(e.target.value)}
                      required
                    >
                      <option value="">اختر الصندوق</option>
                      {accounts.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name} · {money(item.balance)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    اسم الوردية
                    <input
                      className={input}
                      value={name}
                      maxLength={100}
                      onChange={(e) => setName(e.target.value)}
                      required
                    />
                  </label>
                </>
              )}
              <label>
                {opening ? "النقد الفعلي عند الافتتاح" : "النقد المعدود عند الإقفال"}
                <input
                  className={input}
                  inputMode="numeric"
                  value={actual}
                  onChange={(e) => setActual(e.target.value)}
                  required
                />
              </label>
              <label>
                سبب الفرق / الملاحظات
                <textarea
                  className={`${input} h-24 py-2`}
                  value={reason}
                  maxLength={1500}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
            </fieldset>
            {pending && !busy && (
              <p role="status">لم يصل تأكيد العملية. أعد إرسال الطلب نفسه لاسترجاع نتيجته دون تكرار.</p>
            )}
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
          </form>
        )}
      </SidePanel>
    </section>
  );
}
