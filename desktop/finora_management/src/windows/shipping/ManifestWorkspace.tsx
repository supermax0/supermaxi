import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCheck,
  ClipboardPaste,
  FileSpreadsheet,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Save,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { finora, toFinoraError } from "@/api/finora";
import { ROW_STATUSES, type Manifest, type ManifestRow, type RowStatus } from "@/api/finora/shipping";
import { ConfirmDialog } from "@/components/Dialog";
import { MoneyInput } from "@/components/MoneyInput";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";
import { MissingButton, MissingOrdersDialog } from "./Insights";
import { normalizeStatus } from "./shared";
import { KIND_LABEL, ManifestState, Money, STATUS_STYLE, codesFromCsv, money, splitCodes } from "./shared";

type Filter = "all" | "unclassified" | RowStatus;
type Draft = Record<string, RowStatus | "">;

const FILTERS: Array<{ id: Filter; label: string }> = [
  { id: "all", label: "الكل" },
  { id: "unclassified", label: "غير مصنف" },
  { id: "واصل", label: "واصل" },
  { id: "راجع", label: "راجع" },
  { id: "مؤجل", label: "مؤجل" },
  { id: "مشكلة", label: "مشكلة" },
];
const KEY_STATUS: Record<string, RowStatus> = { F2: "واصل", F3: "راجع", F4: "مؤجل" };

/** Settlement manifest workspace: enter / paste / import order numbers, classify fast, analyze, approve. */
export function ManifestWorkspace({
  manifestId,
  canApprove,
  canManage,
  treasuryAccounts,
  onBack,
}: {
  manifestId: number;
  canApprove: boolean;
  canManage: boolean;
  treasuryAccounts: Array<{ id: number; name: string; is_default: boolean }>;
  onBack(): void;
}) {
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const key = useMemo(() => ["shipping", "manifest", manifestId] as const, [manifestId]);
  const query = useQuery({ queryKey: key, queryFn: () => finora.shipping.manifest(manifestId) });
  const manifest = query.data?.manifest;
  const editable = !!manifest && manifest.kind === "settlement" && !manifest.executed && canManage;

  const [draft, setDraft] = useState<Draft>({});
  const [dirty, setDirty] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [focused, setFocused] = useState(0);
  const [entry, setEntry] = useState("");
  const [panelOpen, setPanelOpen] = useState(true);
  const [received, setReceived] = useState(0);
  const [accountId, setAccountId] = useState<number | null>(
    treasuryAccounts.find((a) => a.is_default)?.id ?? treasuryAccounts[0]?.id ?? null,
  );
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [partial, setPartial] = useState(false);
  const [alloc, setAlloc] = useState<Record<string, number>>({});
  const [method, setMethod] = useState<"cash" | "bank">("cash");
  const [missingOpen, setMissingOpen] = useState(false);
  const [detail, setDetail] = useState<ManifestRow | null>(null);
  const [lastAdd, setLastAdd] = useState<{ missing: string[]; duplicates: string[] } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const tableRef = useRef<HTMLDivElement>(null);

  // Server selections are the source of truth whenever nothing local is pending.
  useEffect(() => {
    if (manifest && !dirty) setDraft({ ...(manifest.selections as Draft) });
  }, [manifest, dirty]);

  const setManifest = useCallback(
    (m: Manifest) => client.setQueryData(key, { ok: true as const, manifest: m }),
    [client, key],
  );

  const save = useMutation({
    mutationFn: (d: Draft) => finora.shipping.saveSelections(manifestId, d),
    onSuccess: (res) => {
      setManifest(res.manifest);
      setDirty(false);
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const add = useMutation({
    mutationFn: (codes: string[]) => finora.shipping.addRows(manifestId, codes),
    onSuccess: (res) => {
      setManifest(res.manifest);
      setLastAdd(
        res.missing.length || res.duplicates.length
          ? { missing: res.missing, duplicates: res.duplicates }
          : null,
      );
      if (res.added.length > 1) toast.success(`أُضيف ${formatNumber(res.added.length)} طلب إلى الكشف`);
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const remove = useMutation({
    mutationFn: (orderId: number) => finora.shipping.removeRow(manifestId, orderId),
    onSuccess: (res) => setManifest(res.manifest),
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const approve = useMutation({
    mutationFn: () =>
      finora.shipping.approve(manifestId, {
        received_amount: received,
        treasury_account_id: accountId,
        payment_method: method,
        ...(partial ? { allocations: allocationsFor(rows, statusOf, alloc) } : {}),
      }),
    onSuccess: async (res) => {
      setManifest(res.manifest);
      setConfirmApprove(false);
      toast.success(`تم اعتماد الكشف ${res.manifest.number} وترحيل التسوية`);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["shipping"] }),
        client.invalidateQueries({ queryKey: ["orders"] }),
        client.invalidateQueries({ queryKey: ["products"] }),
        client.invalidateQueries({ queryKey: ["finance"] }),
        client.invalidateQueries({ queryKey: ["reports"] }),
      ]);
    },
    onError: (e: unknown) => {
      setConfirmApprove(false);
      toast.error(toFinoraError(e).message);
    },
  });

  // Autosave the classification draft (Ctrl+S saves immediately).
  useEffect(() => {
    if (!dirty || !editable) return;
    const timer = window.setTimeout(() => save.mutate(draft), 900);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, dirty, editable]);

  const rows = useMemo(() => manifest?.rows ?? [], [manifest]);
  const issuesByOrder = useMemo(() => {
    const map = new Map<number, { severity: "error" | "warning"; messages: string[] }>();
    for (const issue of manifest?.issues ?? []) {
      if (issue.order_id == null) continue;
      const current = map.get(issue.order_id) ?? { severity: issue.severity, messages: [] };
      current.messages.push(issue.message);
      if (issue.severity === "error") current.severity = "error";
      map.set(issue.order_id, current);
    }
    return map;
  }, [manifest]);
  const statusOf = useCallback((row: ManifestRow) => normalizeStatus(draft[String(row.id)]), [draft]);
  const visible = useMemo(
    () =>
      rows.filter((r) =>
        filter === "all" ? true : filter === "unclassified" ? !statusOf(r) : statusOf(r) === filter,
      ),
    [rows, filter, statusOf],
  );
  const counts = useMemo(() => {
    const c: Record<Filter, number> = {
      all: rows.length,
      unclassified: 0,
      واصل: 0,
      راجع: 0,
      مؤجل: 0,
      مشكلة: 0,
    };
    for (const r of rows) {
      const s = statusOf(r);
      if (s) c[s] += 1;
      else c.unclassified += 1;
    }
    return c;
  }, [rows, statusOf]);
  // Live summary from the local draft (the server re-checks everything on approval).
  const returnFeeEach = manifest?.return_fee_each ?? 0;
  const live = useMemo(() => {
    let collected = 0;
    let fees = 0;
    let owed = 0;
    let returns = 0;
    for (const r of rows) {
      const s = statusOf(r);
      if (s === "واصل") {
        const amount = partial ? Math.min(alloc[String(r.id)] ?? r.remaining, r.remaining) : r.remaining;
        collected += amount;
        owed += r.remaining - amount;
        if (amount > 0) fees += r.fee_due;
      } else if (s === "راجع") returns += returnFeeEach;
    }
    return { collected, fees, returns, owed, net: collected - fees - returns };
  }, [rows, statusOf, partial, alloc, returnFeeEach]);
  const difference = received - live.net;

  const setStatus = useCallback(
    (ids: number[], status: RowStatus | "") => {
      if (!editable || ids.length === 0) return;
      setDraft((d) => {
        const next = { ...d };
        for (const id of ids) next[String(id)] = status;
        return next;
      });
      setDirty(true);
    },
    [editable],
  );

  const submitEntry = (text: string) => {
    const codes = splitCodes(text);
    if (codes.length === 0 || !editable) return;
    add.mutate(codes);
    setEntry("");
    input.current?.focus();
  };

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    if (!/\.(csv|txt)$/i.test(f.name)) {
      toast.error("احفظ الكشف من Excel بصيغة CSV ثم استورده، أو انسخ عمود الأرقام والصقه مباشرة.");
      return;
    }
    const codes = codesFromCsv(await f.text());
    if (codes.length === 0) toast.error("لم يُعثر على أرقام طلبات في العمود الأول من الملف");
    else add.mutate(codes);
  };

  // Keyboard: ↑ ↓ move · F2/F3/F4 classify then move · F5 details · Space select · Ctrl+S save. Scoped to this screen.
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const inEntry = target === input.current;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (editable) save.mutate(draft);
      return;
    }
    if (visible.length === 0) return;
    const row = visible[Math.min(focused, visible.length - 1)];
    if (!row) return;
    const status = KEY_STATUS[event.key];
    if (status) {
      event.preventDefault();
      setStatus([row.id], status);
      setFocused((i) => Math.min(i + 1, visible.length - 1));
    } else if (event.key === "F5") {
      event.preventDefault();
      setDetail(row);
    } else if (!inEntry && event.key === "ArrowDown") {
      event.preventDefault();
      setFocused((i) => Math.min(i + 1, visible.length - 1));
    } else if (!inEntry && event.key === "ArrowUp") {
      event.preventDefault();
      setFocused((i) => Math.max(i - 1, 0));
    } else if (!inEntry && event.key === " ") {
      event.preventDefault();
      toggle(row.id);
    }
  };
  useEffect(() => {
    tableRef.current?.querySelector(`[data-row-index="${focused}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [focused]);

  const toggle = (id: number) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selectedIds = [...selected];
  const allVisibleSelected = visible.length > 0 && visible.every((r) => selected.has(r.id));

  if (query.isPending) {
    return (
      <div className="grid h-full place-items-center text-ink-faint">
        <Loader2 className="animate-spin" />
      </div>
    );
  }
  if (!manifest) {
    return (
      <div className="grid h-full place-items-center text-center">
        <div>
          <p className="font-semibold text-ink">
            {query.error ? toFinoraError(query.error).message : "الكشف غير موجود"}
          </p>
          <button type="button" className={cn(supplierSecondary, "mt-4")} onClick={onBack}>
            رجوع إلى الكشوف
          </button>
        </div>
      </div>
    );
  }

  const meta = manifest.meta as {
    reference?: string;
    date?: string;
    received_amount?: number;
    approved_by?: string;
    approved_at?: string;
  };
  const readyToApprove = manifest.ready && !dirty && difference === 0 && (received > 0 || live.net === 0);
  const ledger = (manifest.meta as { ledger?: { receipt_number?: string; outstanding?: number } }).ledger;
  const showAllocation = (editable && partial) || (manifest.executed && !!ledger);
  /** Oldest rows first: each order is paid in full (minus its fee) until the money received runs out. */
  const autoDistribute = () => {
    let budget = received + live.returns;
    const next: Record<string, number> = {};
    for (const r of rows) {
      if (statusOf(r) !== "واصل") continue;
      const capacity = r.remaining - r.fee_due;
      if (budget <= 0) next[String(r.id)] = 0;
      else if (budget >= capacity) {
        next[String(r.id)] = r.remaining;
        budget -= capacity;
      } else {
        next[String(r.id)] = budget + r.fee_due;
        budget = 0;
      }
    }
    setAlloc(next);
  };

  return (
    <div
      className="flex h-full min-h-0 flex-col"
      onKeyDown={onKeyDown}
      role="region"
      aria-label={`كشف ${manifest.number}`}
    >
      <div className="flex min-h-0 flex-1 gap-3">
        {/* right: manifest info */}
        <aside className="glass flex w-[230px] shrink-0 flex-col gap-3 rounded-panel p-4 text-[13px]">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1.5 text-xs text-ink-soft hover:text-maroon"
          >
            <ArrowRight size={14} /> كل الكشوف
          </button>
          <div>
            <p className="text-[11px] text-ink-faint">كشف {KIND_LABEL[manifest.kind]}</p>
            <p className="ltr-isolate text-right text-base font-bold text-ink">{manifest.number}</p>
          </div>
          <ManifestState executed={manifest.executed} partial={manifest.settlement_state === "partial"} />
          <dl className="space-y-2.5">
            <Info label="الشركة" value={manifest.carrier || manifest.agent || "—"} />
            <Info label="رقم كشف الشركة" value={meta.reference || "—"} />
            <Info label="التاريخ" value={meta.date || manifest.created_at.slice(0, 10)} />
            <Info label="أنشأه" value={manifest.created_by || "—"} />
            {manifest.executed && meta.received_amount != null && (
              <>
                <Info label="المبلغ المستلم" value={money(Number(meta.received_amount))} />
                {ledger?.receipt_number && <Info label="سند القبض" value={ledger.receipt_number} />}
                {!!ledger?.outstanding && (
                  <Info label="متبقٍ بذمة الجهة" value={money(Number(ledger.outstanding))} />
                )}
                <Info
                  label="اعتمده"
                  value={`${meta.approved_by ?? ""} ${meta.approved_at ?? ""}`.trim() || "—"}
                />
              </>
            )}
          </dl>
          {!manifest.executed && manifest.kind === "settlement" && (
            <p className="mt-auto rounded-control bg-violet-soft/60 p-3 text-[11px] leading-5 text-ink-soft">
              التصنيف يُحفظ كمسودة تلقائياً ولا يغيّر أي طلب أو حساب حتى الاعتماد.
            </p>
          )}
        </aside>

        {/* center: entry + table */}
        <main className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
          {editable && (
            <div className="glass flex items-center gap-2 rounded-panel p-2.5">
              <ScanLine size={22} className="mx-2 shrink-0 text-maroon" aria-hidden />
              <input
                ref={input}
                autoFocus
                value={entry}
                onChange={(e) => setEntry(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    submitEntry(entry);
                  }
                }}
                onPaste={(e) => {
                  const text = e.clipboardData.getData("text");
                  if (splitCodes(text).length > 1) {
                    e.preventDefault();
                    submitEntry(text);
                  }
                }}
                aria-label="رقم الطلب أو البوليصة"
                placeholder="اكتب رقم الطلب أو امسح البوليصة ثم Enter — أو الصق عموداً كاملاً من الكشف"
                className="h-12 min-w-0 flex-1 bg-transparent text-[16px] font-semibold text-ink outline-none placeholder:text-[14px] placeholder:font-normal placeholder:text-ink-faint"
              />
              {add.isPending && <Loader2 size={18} className="animate-spin text-ink-faint" />}
              <button
                type="button"
                className={cn(supplierSecondary, "h-10")}
                onClick={() => {
                  navigator.clipboard
                    .readText()
                    .then(submitEntry)
                    .catch(() => toast.error("تعذر قراءة الحافظة — الصق داخل الحقل مباشرة (Ctrl+V)"));
                }}
              >
                <ClipboardPaste size={16} /> لصق مجموعة
              </button>
              <button
                type="button"
                className={cn(supplierSecondary, "h-10")}
                onClick={() => file.current?.click()}
              >
                <FileSpreadsheet size={16} /> استيراد CSV
              </button>
              <input
                ref={file}
                type="file"
                accept=".csv,.txt"
                hidden
                onChange={(e) => {
                  void onFile(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </div>
          )}
          {lastAdd && (
            <div
              className="flex items-start gap-2 rounded-control bg-warning-soft px-3 py-2 text-xs text-warning"
              role="status"
            >
              <div className="flex-1">
                {lastAdd.missing.length > 0 && (
                  <p>
                    لم يُعثر على: <span className="ltr-isolate">{lastAdd.missing.join("، ")}</span>
                  </p>
                )}
                {lastAdd.duplicates.length > 0 && (
                  <p>
                    موجودة مسبقاً بالكشف: <span className="ltr-isolate">{lastAdd.duplicates.join("، ")}</span>
                  </p>
                )}
              </div>
              <button type="button" aria-label="إخفاء" onClick={() => setLastAdd(null)}>
                <X size={14} />
              </button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <div
              className="flex gap-1 rounded-control bg-white/70 p-1 shadow-control"
              role="tablist"
              aria-label="تصفية الصفوف"
            >
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  role="tab"
                  aria-selected={filter === f.id}
                  onClick={() => {
                    setFilter(f.id);
                    setFocused(0);
                  }}
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 text-xs font-medium",
                    filter === f.id ? "bg-maroon text-white" : "text-ink-soft hover:bg-surface-sunken",
                  )}
                >
                  {f.label}
                  <span className="ltr-isolate opacity-70">{formatNumber(counts[f.id])}</span>
                </button>
              ))}
            </div>
            {editable && selected.size > 0 && (
              <div className="flex flex-wrap items-center gap-1.5" aria-label="إجراءات جماعية">
                <span className="text-xs text-ink-soft">
                  <span className="ltr-isolate font-bold">{formatNumber(selected.size)}</span> محدد:
                </span>
                {ROW_STATUSES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={cn("h-8 rounded-[10px] px-3 text-xs font-semibold", STATUS_STYLE[s].tone)}
                    onClick={() => {
                      setStatus(selectedIds, s);
                      setSelected(new Set());
                    }}
                  >
                    تحديد كـ{s}
                  </button>
                ))}
                <button
                  type="button"
                  className="h-8 rounded-[10px] bg-success px-3 text-xs font-semibold text-white"
                  onClick={() => {
                    setStatus(
                      rows.filter((r) => !selected.has(r.id)).map((r) => r.id),
                      "واصل",
                    );
                    setSelected(new Set());
                  }}
                >
                  <CheckCheck size={13} className="inline" /> الكل واصل عدا المحدد
                </button>
                <button
                  type="button"
                  className="h-8 rounded-[10px] px-2 text-xs text-ink-faint hover:text-ink"
                  onClick={() => setSelected(new Set())}
                >
                  إلغاء التحديد
                </button>
              </div>
            )}
          </div>

          <div
            ref={tableRef}
            className="glass min-h-0 flex-1 overflow-auto rounded-panel"
            role="grid"
            aria-label="طلبات الكشف"
          >
            <table className="w-full border-separate border-spacing-0 text-[13px]">
              <thead className="sticky top-0 z-10 bg-white shadow-[0_1px_0_rgb(0_0_0/0.06)] text-[11px] text-ink-faint">
                <tr>
                  <th className="w-10 px-3 py-2.5">
                    <input
                      type="checkbox"
                      aria-label="تحديد الكل"
                      checked={allVisibleSelected}
                      onChange={() =>
                        setSelected(allVisibleSelected ? new Set() : new Set(visible.map((r) => r.id)))
                      }
                    />
                  </th>
                  <th className="px-2 py-2.5 text-start font-medium">رقم الطلب</th>
                  <th className="px-2 py-2.5 text-start font-medium">العميل</th>
                  <th className="px-2 py-2.5 text-start font-medium">مبلغ التحصيل</th>
                  <th className="px-2 py-2.5 text-start font-medium">أجرة النقل</th>
                  {showAllocation && <th className="px-2 py-2.5 text-start font-medium">المبلغ المسدد</th>}
                  <th className="px-2 py-2.5 text-start font-medium">حالة الطلب</th>
                  <th className="px-2 py-2.5 text-start font-medium">التصنيف</th>
                  <th className="w-10" />
                </tr>
              </thead>
              <tbody>
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={showAllocation ? 9 : 8} className="py-16 text-center text-ink-faint">
                      {rows.length === 0
                        ? "ابدأ بإدخال أرقام الطلبات أو مسح البوليصات في الحقل بالأعلى"
                        : "لا توجد طلبات بهذا التصنيف"}
                    </td>
                  </tr>
                )}
                {visible.map((row, index) => {
                  const status = statusOf(row);
                  const issue = issuesByOrder.get(row.id);
                  const isFocused = index === Math.min(focused, visible.length - 1);
                  return (
                    <tr
                      key={row.id}
                      data-row-index={index}
                      aria-selected={selected.has(row.id)}
                      onClick={() => setFocused(index)}
                      className={cn(
                        "transition-colors",
                        isFocused ? "bg-violet-soft/60" : "hover:bg-surface-sunken/50",
                        selected.has(row.id) && "bg-maroon-soft/40",
                      )}
                    >
                      <td className="border-b border-line/60 px-3 py-2">
                        <input
                          type="checkbox"
                          aria-label={`تحديد ${row.id}`}
                          checked={selected.has(row.id)}
                          onChange={() => toggle(row.id)}
                        />
                      </td>
                      <td className="border-b border-line/60 px-2 py-2">
                        <div className="flex items-center gap-1.5">
                          {issue && (
                            <span
                              title={issue.messages.join("\n")}
                              aria-label={issue.messages.join("، ")}
                              className={cn(
                                "h-2 w-2 shrink-0 rounded-full",
                                issue.severity === "error" ? "bg-danger" : "bg-warning",
                              )}
                            />
                          )}
                          <span className="ltr-isolate font-bold text-ink">#{row.id}</span>
                        </div>
                        {row.waybills[0] && (
                          <p className="ltr-isolate text-right text-[10px] text-ink-faint">
                            {row.waybills.join(" · ")}
                          </p>
                        )}
                      </td>
                      <td className="border-b border-line/60 px-2 py-2">
                        <p className="max-w-[200px] truncate font-medium">{row.customer_name || "—"}</p>
                        <p className="text-[11px] text-ink-faint">{row.customer_city}</p>
                      </td>
                      <td className="border-b border-line/60 px-2 py-2 font-bold">
                        <Money value={row.remaining} />
                      </td>
                      <td className="border-b border-line/60 px-2 py-2 text-ink-soft">
                        {row.fee ? (
                          <span title={row.fee_due ? undefined : "خُصمت سابقاً — لا تُخصم مرة ثانية"}>
                            <Money value={row.fee} className={row.fee_due ? "" : "line-through opacity-60"} />
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      {showAllocation && (
                        <td className="border-b border-line/60 px-2 py-2">
                          {status !== "واصل" ? (
                            <span className="text-ink-faint">—</span>
                          ) : manifest.executed ? (
                            <Money value={row.allocated ?? 0} className="font-semibold" />
                          ) : (
                            <MoneyInput
                              label={`المبلغ المسدد للطلب ${row.id}`}
                              value={Math.min(alloc[String(row.id)] ?? row.remaining, row.remaining)}
                              onChange={(v) =>
                                setAlloc((a) => ({ ...a, [String(row.id)]: Math.min(v, row.remaining) }))
                              }
                              className={cn(supplierInput.replace("w-full", ""), "h-8 w-[120px] text-[13px]")}
                            />
                          )}
                        </td>
                      )}
                      <td className="border-b border-line/60 px-2 py-2 text-[12px] text-ink-soft">
                        {row.status}
                      </td>
                      <td className="border-b border-line/60 px-2 py-2">
                        {editable ? (
                          <div className="flex gap-1" role="radiogroup" aria-label={`تصنيف ${row.id}`}>
                            {ROW_STATUSES.map((s) => (
                              <button
                                key={s}
                                type="button"
                                role="radio"
                                aria-checked={status === s}
                                title={STATUS_STYLE[s].key ? `${s} (${STATUS_STYLE[s].key})` : s}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setStatus([row.id], status === s ? "" : s);
                                }}
                                className={cn(
                                  "h-7 rounded-[8px] px-2.5 text-[11px] font-semibold transition-colors",
                                  status === s
                                    ? STATUS_STYLE[s].tone + " ring-1 ring-current/30"
                                    : "bg-white text-ink-faint ring-1 ring-line hover:text-ink",
                                )}
                              >
                                {s}
                              </button>
                            ))}
                          </div>
                        ) : status ? (
                          <span
                            className={cn(
                              "rounded-full px-2.5 py-1 text-[11px] font-semibold",
                              STATUS_STYLE[status].tone,
                            )}
                          >
                            {status}
                          </span>
                        ) : (
                          <span className="text-ink-faint">—</span>
                        )}
                      </td>
                      <td className="border-b border-line/60 px-2 py-2">
                        {editable && (
                          <button
                            type="button"
                            aria-label={`إزالة ${row.id} من الكشف`}
                            className="grid h-7 w-7 place-items-center rounded-[8px] text-ink-faint hover:bg-danger-soft hover:text-danger"
                            onClick={(e) => {
                              e.stopPropagation();
                              remove.mutate(row.id);
                            }}
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {editable && (
            <p className="text-[11px] text-ink-faint">
              اختصارات: <kbd>F2</kbd> واصل · <kbd>F3</kbd> راجع · <kbd>F4</kbd> مؤجل · <kbd>F5</kbd> التفاصيل
              · <kbd>↑ ↓</kbd> تنقل · <kbd>مسافة</kbd> تحديد · <kbd>Ctrl+S</kbd> حفظ
            </p>
          )}
        </main>

        {/* left: analysis */}
        {panelOpen ? (
          <aside
            className="glass flex w-[290px] shrink-0 flex-col gap-3 overflow-y-auto rounded-panel p-4"
            aria-label="لوحة التحليل"
          >
            <header className="flex items-center gap-2">
              <Sparkles size={16} className="text-maroon" />
              <h3 className="flex-1 text-sm font-bold">تحليل الكشف</h3>
              <button
                type="button"
                aria-label="تصغير لوحة التحليل"
                onClick={() => setPanelOpen(false)}
                className="text-ink-faint hover:text-ink"
              >
                <PanelLeftClose size={16} />
              </button>
            </header>
            <dl className="space-y-1.5 text-[13px]">
              <Line label="إجمالي الطلبات" value={formatNumber(rows.length)} />
              <Line label={`واصل (${formatNumber(counts["واصل"])})`} value={money(live.collected)} />
              <Line label={`راجع (${formatNumber(counts["راجع"])})`} value={formatNumber(counts["راجع"])} />
              <Line label={`مؤجل (${formatNumber(counts["مؤجل"])})`} value={formatNumber(counts["مؤجل"])} />
              <Line label="أجور النقل المخصومة" value={`− ${money(live.fees)}`} />
              {live.returns > 0 && <Line label="أجور المرتجعات" value={`− ${money(live.returns)}`} />}
              <div className="my-2 h-px bg-line" />
              <Line label="الصافي المتوقع استلامه" value={money(live.net)} strong />
              {live.owed > 0 && <Line label="يبقى بذمة الجهة" value={money(live.owed)} />}
            </dl>

            {editable && (
              <>
                <label className="text-[12px] font-medium text-ink-soft">
                  المبلغ المستلم فعلياً
                  <MoneyInput
                    label="المبلغ المستلم فعلياً"
                    value={received}
                    onChange={setReceived}
                    className={cn(supplierInput, "mt-1 text-lg font-bold")}
                  />
                </label>
                {received > 0 && (
                  <p
                    role="status"
                    className={cn(
                      "rounded-control px-3 py-2 text-[12px] font-semibold",
                      difference === 0 ? "bg-success-soft text-success" : "bg-warning-soft text-warning",
                    )}
                  >
                    {difference === 0
                      ? "✅ التسوية متطابقة"
                      : `⚠️ فرق ${money(Math.abs(difference))} ${difference > 0 ? "زيادة" : "نقص"} — يحتاج معالجة`}
                  </p>
                )}
                <label className="flex items-center gap-2 text-[12px] font-medium text-ink-soft">
                  <input
                    type="checkbox"
                    checked={partial}
                    onChange={(e) => {
                      setPartial(e.target.checked);
                      setAlloc({});
                    }}
                  />
                  تسديد جزئي — توزيع المبلغ على طلبات محددة
                </label>
                {partial && (
                  <button
                    type="button"
                    className={cn(supplierSecondary, "h-9 text-[12px]")}
                    disabled={received <= 0}
                    onClick={autoDistribute}
                  >
                    توزيع تلقائي على الأقدم
                  </button>
                )}
                <label className="text-[12px] font-medium text-ink-soft">
                  طريقة القبض
                  <select
                    className={cn(supplierInput, "mt-1")}
                    value={method}
                    onChange={(e) => setMethod(e.target.value === "bank" ? "bank" : "cash")}
                  >
                    <option value="cash">نقداً</option>
                    <option value="bank">تحويل مصرفي</option>
                  </select>
                </label>
                <label className="text-[12px] font-medium text-ink-soft">
                  الإيداع في
                  <select
                    className={cn(supplierInput, "mt-1")}
                    value={accountId ?? ""}
                    onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
                  >
                    {treasuryAccounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}

            {editable && (
              <MissingButton
                manifestId={manifestId}
                rowsCount={rows.length}
                onOpen={() => setMissingOpen(true)}
              />
            )}

            <div className="mt-1">
              <p className="mb-2 text-[12px] font-bold text-ink">ملاحظات المحلل</p>
              {dirty ? (
                <p className="text-[12px] text-ink-faint">احفظ التصنيف ليُعاد التحليل…</p>
              ) : manifest.issues.length === 0 && manifest.blocking.length === 0 ? (
                <p className="rounded-control bg-success-soft px-3 py-2 text-[12px] text-success">
                  🟢 لا توجد فروقات — جاهز للاعتماد بعد إدخال المبلغ
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {[...manifest.blocking.filter((b) => b.order_id == null), ...manifest.issues]
                    .slice(0, 30)
                    .map((issue, i) => (
                      <li
                        key={i}
                        className={cn(
                          "rounded-control px-3 py-2 text-[12px] leading-5",
                          issue.severity === "error"
                            ? "bg-danger-soft text-danger"
                            : "bg-warning-soft text-warning",
                        )}
                      >
                        {issue.message}
                      </li>
                    ))}
                </ul>
              )}
            </div>
          </aside>
        ) : (
          <button
            type="button"
            aria-label="إظهار لوحة التحليل"
            onClick={() => setPanelOpen(true)}
            className="glass grid w-10 shrink-0 place-items-center rounded-panel text-ink-soft"
          >
            <PanelLeftOpen size={18} />
          </button>
        )}
      </div>

      {/* fixed bottom bar */}
      <footer className="glass mt-3 flex shrink-0 flex-wrap items-center gap-x-6 gap-y-2 rounded-panel px-5 py-3 text-[12px]">
        <Stat label="الطلبات" value={formatNumber(rows.length)} />
        <Stat label="واصل" value={formatNumber(counts["واصل"])} tone="text-success" />
        <Stat label="راجع" value={formatNumber(counts["راجع"])} tone="text-danger" />
        <Stat label="مؤجل" value={formatNumber(counts["مؤجل"])} tone="text-warning" />
        <Stat label="التحصيل المتوقع" value={money(live.collected)} />
        <Stat label="الصافي" value={money(live.net)} tone="text-maroon" />
        <div className="ms-auto flex gap-2">
          {editable && (
            <>
              <button
                type="button"
                className={supplierSecondary}
                disabled={!dirty || save.isPending || !online}
                onClick={() => save.mutate(draft)}
              >
                {save.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                {dirty ? "حفظ مسودة" : "محفوظ"}
              </button>
              <button
                type="button"
                className={supplierSecondary}
                disabled={query.isFetching}
                onClick={() => void query.refetch()}
              >
                <Sparkles size={16} /> تحليل الكشف
              </button>
              {canApprove && (
                <button
                  type="button"
                  className={supplierPrimary}
                  disabled={!readyToApprove || !online}
                  title={
                    !readyToApprove
                      ? "يتطلب: حفظ التصنيف، لا مشاكل مانعة، ومبلغ مستلم مطابق للصافي"
                      : undefined
                  }
                  onClick={() => setConfirmApprove(true)}
                >
                  <ShieldCheck size={17} /> اعتماد التسوية
                </button>
              )}
            </>
          )}
        </div>
      </footer>

      {missingOpen && (
        <MissingOrdersDialog
          manifestId={manifestId}
          busy={add.isPending}
          onAdd={(ids) => {
            add.mutate(ids.map(String), { onSuccess: () => setMissingOpen(false) });
          }}
          onClose={() => setMissingOpen(false)}
        />
      )}
      <ConfirmDialog
        open={confirmApprove}
        title="اعتماد كشف التسوية"
        busy={approve.isPending}
        message={
          <>
            سيُرحَّل الكشف <strong>{manifest.number}</strong> عبر FINORA: يُودع{" "}
            <strong className="ltr-isolate">{money(received)}</strong> في الحساب بسند قبض، وتُسدَّد الطلبات
            الواصلة بالمبالغ الموزعة
            {live.owed > 0 && (
              <>
                {" "}
                ويبقى <strong className="ltr-isolate">{money(live.owed)}</strong> بذمة الجهة
              </>
            )}
            . الطلبات الراجعة تُسجَّل «بانتظار الاستلام» ولا تعود للمخزن إلا بعد فحصها. الطلبات المؤجلة ترجع
            إلى «تم الطلب» وتُعاد بضاعتها للمخزون مرة واحدة. لا يمكن تعديل الكشف بعد الاعتماد.
          </>
        }
        confirmLabel="اعتماد وترحيل"
        onClose={() => setConfirmApprove(false)}
        onConfirm={() => approve.mutate()}
      />
      <ConfirmDialog
        open={detail !== null}
        title={`الطلب #${detail?.id ?? ""}`}
        message={
          detail && (
            <dl className="grid grid-cols-2 gap-2 text-[13px]">
              <Info label="العميل" value={detail.customer_name} />
              <Info label="الهاتف" value={detail.customer_phone || "—"} />
              <Info label="المدينة" value={detail.customer_city || "—"} />
              <Info label="العنوان" value={detail.customer_address || "—"} />
              <Info label="الإجمالي" value={money(detail.total)} />
              <Info label="المدفوع" value={money(detail.paid_amount)} />
              <Info label="الباقي للتحصيل" value={money(detail.remaining)} />
              <Info label="أجرة النقل" value={money(detail.fee)} />
              <Info label="حالة الطلب" value={detail.status} />
              <Info label="حالة الدفع" value={detail.payment_status || "—"} />
              <Info label="البوليصة" value={detail.waybills.join("، ") || "—"} />
              <Info label="شركة النقل" value={detail.shipping_company || "—"} />
            </dl>
          )
        }
        confirmLabel="إغلاق"
        onClose={() => setDetail(null)}
        onConfirm={() => setDetail(null)}
      />
    </div>
  );
}

function allocationsFor(
  rows: ManifestRow[],
  statusOf: (row: ManifestRow) => RowStatus | "",
  alloc: Record<string, number>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of rows) {
    if (statusOf(r) === "واصل") out[String(r.id)] = Math.min(alloc[String(r.id)] ?? r.remaining, r.remaining);
  }
  return out;
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-ink-faint">{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-ink-soft">{label}</dt>
      <dd
        className={cn("ltr-isolate", strong ? "text-[15px] font-bold text-maroon" : "font-semibold text-ink")}
      >
        {value}
      </dd>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-ink-faint">{label}</span>
      <span className={cn("ltr-isolate text-[14px] font-bold text-ink", tone)}>{value}</span>
    </span>
  );
}
