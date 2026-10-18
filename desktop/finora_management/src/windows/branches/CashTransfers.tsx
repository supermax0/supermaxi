import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Check, HandCoins, Loader2, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { CashTransfer } from "@/api/finora/branchCash";
import { DataTable, type Column } from "@/components/DataTable";
import { ConfirmDialog } from "@/components/Dialog";
import { Field } from "@/components/FilterPanel";
import { MoneyInput } from "@/components/MoneyInput";
import { SearchBox } from "@/components/SearchBox";
import { StatusTabs } from "@/components/StatusTabs";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { Money } from "../shipping/shared";
import {
  SupplierModal,
  supplierInput,
  supplierPrimary,
  supplierSecondary,
} from "../suppliers/SupplierDialogs";

type Filter = "open" | "completed" | "closed";
const FILTERS: Array<{ id: Filter; label: string }> = [
  { id: "open", label: "بانتظار الإجراء" },
  { id: "completed", label: "مكتملة" },
  { id: "closed", label: "مرفوضة / ملغاة" },
];
const TONE: Record<string, string> = {
  pending: "bg-warning-soft text-warning",
  approved: "bg-violet-soft text-violet-deep",
  posting: "bg-azure-soft text-azure",
  completed: "bg-success-soft text-success",
  rejected: "bg-danger-soft text-danger",
  cancelled: "bg-surface-sunken text-ink-faint",
};

/** Cash moves between branches by a document: request → approval → receipt confirmation (one posting). */
export function CashTransfers({ enabled }: { enabled: boolean }) {
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const [filter, setFilter] = useState<Filter>("open");
  const [searchText, setSearchText] = useState("");
  const search = useDebouncedValue(searchText, 250);
  const [composer, setComposer] = useState(false);
  const [asking, setAsking] = useState<{ doc: CashTransfer; action: "reject" | "cancel" } | null>(null);
  const [reason, setReason] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);

  const list = useQuery({
    queryKey: ["branches", "cash", filter, search],
    queryFn: async () => {
      if (filter === "open") return finora.branchCash.list("open", search);
      if (filter === "completed") return finora.branchCash.list("completed", search);
      const [rejected, cancelled] = await Promise.all([
        finora.branchCash.list("rejected", search),
        finora.branchCash.list("cancelled", search),
      ]);
      return { ...rejected, rows: [...rejected.rows, ...cancelled.rows].sort((a, b) => b.id - a.id) };
    },
    enabled,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["branches"] });
  const act = useMutation({
    mutationFn: (input: {
      id: number;
      action: "approve" | "receive" | "reject" | "cancel";
      reason?: string;
    }) => finora.branchCash.act(input.id, input.action, input.reason),
    onSuccess: async (res, input) => {
      toast.success(
        input.action === "receive"
          ? `رُحِّل التحويل ${res.transfer.number}: خرج المبلغ من ${res.transfer.from_account} ودخل ${res.transfer.to_account}`
          : input.action === "approve"
            ? `اعتُمد التحويل ${res.transfer.number} — بانتظار تأكيد الاستلام`
            : `أُغلق التحويل ${res.transfer.number}`,
      );
      setAsking(null);
      setReason("");
      await Promise.all([refresh(), client.invalidateQueries({ queryKey: ["finance"] })]);
    },
    onError: (e: unknown) => {
      setAsking(null);
      toast.error(toFinoraError(e).message);
      void refresh();
    },
  });

  const rows = list.data?.rows ?? [];
  const opened = rows.find((r) => r.id === openId) ?? null;
  const columns = useMemo<Column<CashTransfer>[]>(
    () => [
      {
        id: "number",
        header: "السند",
        width: "17%",
        cell: (t) => (
          <div className="min-w-0">
            <p className="ltr-isolate truncate text-right font-bold">{t.number}</p>
            <p className="truncate text-[11px] text-ink-faint">{t.reason}</p>
          </div>
        ),
      },
      {
        id: "route",
        header: "من ← إلى",
        width: "27%",
        cell: (t) => (
          <div className="min-w-0 text-[12px]">
            <p className="truncate">
              {t.from_branch} · <span className="text-ink-faint">{t.from_account}</span>
            </p>
            <p className="truncate">
              ← {t.to_branch} · <span className="text-ink-faint">{t.to_account}</span>
            </p>
          </div>
        ),
      },
      {
        id: "amount",
        header: "المبلغ",
        width: "16%",
        cell: (t) => <Money value={t.amount} className="font-bold" />,
      },
      {
        id: "date",
        header: "التاريخ",
        width: "12%",
        minTableWidth: 760,
        cell: (t) => <span className="ltr-isolate text-[12px]">{t.transfer_date}</span>,
      },
      {
        id: "state",
        header: "الحالة",
        width: "17%",
        cell: (t) => (
          <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-semibold", TONE[t.status])}>
            {t.status_label}
          </span>
        ),
      },
      { id: "actions", header: "الإجراء", width: "17%", cell: (t) => actions(t) },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [online, act.isPending],
  );
  function actions(t: CashTransfer) {
    return (
      <div className="flex gap-1.5">
        {t.can_approve && (
          <button
            type="button"
            className={cn(supplierPrimary, "h-8 px-3 text-xs")}
            disabled={!online || act.isPending}
            onClick={(e) => {
              e.stopPropagation();
              act.mutate({ id: t.id, action: "approve" });
            }}
          >
            <Check size={14} /> اعتماد
          </button>
        )}
        {t.can_receive && (
          <button
            type="button"
            className={cn(supplierPrimary, "h-8 px-3 text-xs")}
            disabled={!online || act.isPending}
            onClick={(e) => {
              e.stopPropagation();
              act.mutate({ id: t.id, action: "receive" });
            }}
          >
            <HandCoins size={14} /> تأكيد الاستلام
          </button>
        )}
        {(t.can_reject || t.can_cancel) && (
          <button
            type="button"
            aria-label={`${t.can_reject ? "رفض" : "إلغاء"} ${t.number}`}
            className="grid h-8 w-8 place-items-center rounded-[10px] border border-line/70 bg-white/75 text-ink-soft hover:bg-danger-soft hover:text-danger"
            disabled={!online || act.isPending}
            onClick={(e) => {
              e.stopPropagation();
              setAsking({ doc: t, action: t.can_reject ? "reject" : "cancel" });
            }}
          >
            <X size={15} />
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex shrink-0 flex-wrap items-center gap-2">
        <StatusTabs<Filter> label="التحويلات النقدية" value={filter} tabs={FILTERS} onChange={setFilter} />
        <SearchBox
          value={searchText}
          onChange={setSearchText}
          busy={list.isFetching}
          placeholder="رقم السند أو المرجع أو السبب…"
          className="min-w-[220px] flex-1"
        />
        <button
          type="button"
          className={supplierPrimary}
          disabled={!online}
          onClick={() => setComposer(true)}
        >
          <Plus size={17} /> تحويل أموال
        </button>
      </div>
      <p className="mb-3 flex shrink-0 items-center gap-1.5 text-[12px] text-ink-faint">
        <ArrowLeftRight size={14} /> لا تتحرك الأموال إلا عند تأكيد الاستلام، وبقيد متوازن؛ التحويل ليس
        مصروفاً ولا إيراداً ولا يدخل الأرباح.
      </p>
      <div className="flex min-h-0 flex-1 gap-4">
        <div className="min-w-0 flex-1">
          <DataTable
            label="التحويلات النقدية"
            columns={columns}
            rows={rows}
            loading={list.isPending}
            fetching={list.isFetching}
            error={list.error ? toFinoraError(list.error).message : null}
            onRetry={() => void list.refetch()}
            emptyTitle="لا توجد تحويلات نقدية هنا"
            emptyHint="اضغط «تحويل أموال» لإنشاء طلب بين صندوقين."
            activeId={openId}
            onOpen={(t) => setOpenId(t.id)}
          />
        </div>
        {opened && (
          <aside
            aria-label="مسار التحويل"
            className="glass flex w-[300px] shrink-0 flex-col gap-3 rounded-panel p-4"
          >
            <header className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <h3 className="ltr-isolate truncate text-right text-sm font-bold">{opened.number}</h3>
                <p className="text-[12px] text-ink-faint">{opened.status_label}</p>
              </div>
              <button
                type="button"
                aria-label="إغلاق"
                className="text-ink-faint"
                onClick={() => setOpenId(null)}
              >
                <X size={16} />
              </button>
            </header>
            <ol className="space-y-2 text-[12px]">
              {opened.events.map((e, i) => (
                <li key={i} className="rounded-control bg-surface-sunken/60 px-3 py-2">
                  <p className="font-semibold text-ink">
                    {{
                      create: "طلب التحويل",
                      approve: "اعتماد",
                      receive: "تأكيد الاستلام والترحيل",
                      reject: "رفض",
                      cancel: "إلغاء",
                      reconcile: "تسوية آلية",
                    }[e.action] ?? e.action}
                  </p>
                  <p className="text-ink-faint">
                    {e.name} · <span className="ltr-isolate">{e.at}</span>
                  </p>
                  {e.reason && <p className="mt-1 text-ink-soft">{e.reason}</p>}
                </li>
              ))}
            </ol>
            <p className="text-[12px] text-ink-soft">
              {opened.posted
                ? `رُحِّل ${formatNumber(opened.amount)} د.ع بحركتين متوازنتين`
                : "لم يُرحَّل أي مبلغ بعد."}
            </p>
          </aside>
        )}
      </div>

      {composer && <CashComposer onClose={() => setComposer(false)} onDone={() => void refresh()} />}
      <ConfirmDialog
        open={asking !== null}
        title={asking?.action === "reject" ? "رفض التحويل" : "إلغاء التحويل"}
        tone="danger"
        busy={act.isPending}
        message={
          <div className="space-y-2">
            <p>
              التحويل <strong className="ltr-isolate">{asking?.doc.number}</strong> لن يُرحَّل أي مبلغ منه.
            </p>
            <input
              aria-label="سبب الإغلاق"
              className={supplierInput}
              placeholder="اكتب السبب"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        }
        confirmLabel={asking?.action === "reject" ? "رفض" : "إلغاء التحويل"}
        onClose={() => {
          setAsking(null);
          setReason("");
        }}
        onConfirm={() => asking && act.mutate({ id: asking.doc.id, action: asking.action, reason })}
      />
    </div>
  );
}

function CashComposer({ onClose, onDone }: { onClose(): void; onDone(): void }) {
  const online = useConnection((s) => s.status === "online");
  const meta = useQuery({ queryKey: ["branches", "cash", "meta"], queryFn: () => finora.branchCash.meta() });
  const [operationId] = useState(() => crypto.randomUUID());
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState(0);
  const [reason, setReason] = useState("");
  const [reference, setReference] = useState("");
  const [now, setNow] = useState(false);

  const accounts = meta.data?.accounts ?? [];
  const sources = accounts.filter((a) => a.can_send_from);
  const fromId = Number(from || sources[0]?.id || 0);
  const source = accounts.find((a) => a.id === fromId);
  const targets = accounts.filter((a) => a.id !== fromId);
  const toId = Number(to || targets[0]?.id || 0);
  const short = source?.balance != null && amount > source.balance;

  const save = useMutation({
    mutationFn: () =>
      finora.branchCash.create({
        from_account_id: fromId,
        to_account_id: toId,
        amount,
        reason: reason.trim(),
        reference: reference.trim(),
        operation_id: operationId,
        ...(now ? { execute_now: true } : {}),
      }),
    onSuccess: (res) => {
      toast.success(
        res.transfer.status === "completed"
          ? `رُحِّل التحويل ${res.transfer.number}`
          : `أُنشئ طلب التحويل ${res.transfer.number} بانتظار الاعتماد`,
      );
      onDone();
      onClose();
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const valid = fromId > 0 && toId > 0 && amount > 0 && reason.trim().length >= 3 && !short;

  return (
    <SupplierModal
      title="تحويل أموال بين الفروع"
      icon={ArrowLeftRight}
      busy={save.isPending}
      onClose={onClose}
      wide
    >
      <form
        className="grid grid-cols-2 gap-x-5 gap-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && online && !save.isPending) save.mutate();
        }}
      >
        <Field label="من صندوق">
          <select className={supplierInput} value={fromId} onChange={(e) => setFrom(e.target.value)}>
            {sources.map((a) => (
              <option key={a.id} value={a.id}>
                {a.branch_name} — {a.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="إلى صندوق">
          <select className={supplierInput} value={toId} onChange={(e) => setTo(e.target.value)}>
            {targets.map((a) => (
              <option key={a.id} value={a.id}>
                {a.branch_name} — {a.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="المبلغ (د.ع)">
          <MoneyInput label="مبلغ التحويل" value={amount} onChange={setAmount} className={supplierInput} />
        </Field>
        <div className="mt-7 text-[12px]">
          {source?.balance != null && (
            <p className={cn(short ? "font-semibold text-danger" : "text-ink-soft")}>
              المتاح في الصندوق المصدر <Money value={source.balance} />
              {short && " — المبلغ يتجاوز الرصيد"}
            </p>
          )}
        </div>
        <Field label="السبب">
          <input className={supplierInput} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <Field label="المرجع (اختياري)">
          <input
            dir="ltr"
            className={supplierInput}
            value={reference}
            onChange={(e) => setReference(e.target.value)}
          />
        </Field>
        {meta.data?.can_execute_now && (
          <label className="col-span-2 flex items-center gap-2 text-[13px] text-ink-soft">
            <input type="checkbox" checked={now} onChange={(e) => setNow(e.target.checked)} />
            تنفيذ مباشر (اعتماد وتأكيد استلام فوراً — للمدير العام)
          </label>
        )}
        <div className="col-span-2 flex justify-end gap-2">
          <button type="button" className={supplierSecondary} onClick={onClose}>
            إلغاء
          </button>
          <button type="submit" className={supplierPrimary} disabled={!valid || !online || save.isPending}>
            {save.isPending && <Loader2 size={16} className="animate-spin" />}
            {now ? "تحويل وترحيل" : "إرسال الطلب"}
          </button>
        </div>
      </form>
    </SupplierModal>
  );
}
