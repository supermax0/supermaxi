import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  Banknote,
  CheckCircle2,
  Landmark,
  Loader2,
  Plus,
  Sparkles,
  SplitSquareHorizontal,
  Trash2,
  Truck,
  Wallet,
  Warehouse,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { finora, toFinoraError } from "@/api/finora";
import type { PaymentAccount } from "@/api/finora/pos";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { FeatureHelp } from "@/components/FeatureHelp";
import { MoneyInput } from "@/components/MoneyInput";
import {
  accountsForBranch,
  allocatedTotal,
  collectionDue,
  defaultAccount,
  MAX_ALLOCATIONS,
  nextAccount,
  paymentProblem,
  syncSingleAllocation,
  targetAmount,
  toAllocations,
  type AllocationDraft,
  type PaymentMode,
} from "@/features/orders/payment";
import { orderFailureMessage, useOrderDetails, usePayOrder } from "@/features/orders/useOrders";
import { cn } from "@/utils/cn";
import { formatIqd } from "@/utils/money";

interface PaymentDialogProps {
  orderId: number | null;
  onClose(): void;
  onPaid?(orderId: number): void;
}

let allocationKey = 0;
const newKey = () => ++allocationKey;

function AccountIcon({ account, size = 16 }: { account: PaymentAccount | undefined; size?: number }) {
  return account?.type === "bank" ? (
    <Landmark size={size} className="text-azure" aria-hidden />
  ) : (
    <Wallet size={size} className="text-success" aria-hidden />
  );
}

function SectionTitle({ icon: Icon, children }: { icon: typeof Wallet; children: string }) {
  return (
    <h3 className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-ink-soft">
      <Icon size={15} className="text-violet" aria-hidden />
      {children}
    </h3>
  );
}

/**
 * Order collection dialog — same flow as FINORA's web "تسديد": stock branch,
 * receiving accounts of that branch, optional split across up to 8 accounts,
 * and the internal delivery fee. FINORA validates and records everything.
 */
export function PaymentDialog({ orderId, onClose, onPaid }: PaymentDialogProps) {
  const open = orderId !== null;
  const details = useOrderDetails(orderId);
  const accountsQuery = useQuery({
    queryKey: ["pos", "accounts"],
    queryFn: () => finora.pos.paymentAccounts(),
    enabled: open,
    staleTime: 60_000,
  });
  const branchesQuery = useQuery({
    queryKey: ["orders", "branches"],
    queryFn: () => finora.orders.branches(),
    enabled: open,
    staleTime: 5 * 60_000,
  });
  const pay = usePayOrder();

  const order = details.data?.order;
  const due = order ? collectionDue(order.total ?? 0, order.paid_amount ?? 0, order.payment ?? "") : 0;
  const stockDeducted = Boolean(order?.stock_is_deducted);

  const [mode, setMode] = useState<PaymentMode>("full");
  const [partial, setPartial] = useState(0);
  const [fee, setFee] = useState(0);
  const [branchId, setBranchId] = useState<number | null>(null);
  const [allocations, setAllocations] = useState<AllocationDraft[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [quoting, setQuoting] = useState(false);

  // fresh state for every order opened
  useEffect(() => {
    if (!open) return;
    setMode("full");
    setPartial(0);
    setFee(0);
    setBranchId(null);
    setAllocations([]);
    setError(null);
  }, [open, orderId]);

  // stock branch: fixed once stock was deducted, else FINORA's schedule, else the order's branch
  const branches = useMemo(() => branchesQuery.data?.branches ?? [], [branchesQuery.data]);
  useEffect(() => {
    if (!order || branchId !== null || branchesQuery.isLoading) return;
    const scheduled = branchesQuery.data?.scheduledBranchId ?? null;
    const chosen =
      (stockDeducted && order.branch_id) || scheduled || order.branch_id || branches[0]?.id || null;
    if (chosen) setBranchId(chosen);
  }, [order, branchId, branchesQuery.isLoading, branchesQuery.data, branches, stockDeducted]);

  const accounts = useMemo(
    () => accountsForBranch(accountsQuery.data ?? [], branchId),
    [accountsQuery.data, branchId],
  );
  const accountById = useMemo(() => new Map(accounts.map((a) => [a.id, a])), [accounts]);
  const target = targetAmount({ mode, due, amount: partial });
  const targetRef = useRef(target);
  targetRef.current = target;

  // (re)seed the receiving account whenever the branch's accounts change
  useEffect(() => {
    if (!open || !accountsQuery.data) return;
    const first = defaultAccount(accounts);
    setAllocations((rows) => {
      if (rows.length && rows.every((row) => accounts.some((account) => account.id === row.accountId)))
        return rows;
      return first ? [{ key: rows[0]?.key ?? newKey(), accountId: first.id, amount: targetRef.current }] : [];
    });
  }, [open, accountsQuery.data, accounts]);
  useEffect(() => setAllocations((rows) => syncSingleAllocation(rows, target)), [target]);

  const allocated = allocatedTotal(allocations);
  const remainder = target - allocated;
  const problem = order
    ? paymentProblem({ mode, due, amount: partial, deliveryFee: fee, allocations })
    : null;
  const loading = details.isLoading || accountsQuery.isLoading;
  const loadError = details.error ?? accountsQuery.error;
  const canSubmit = Boolean(order) && !problem && !pay.isPending && accounts.length > 0;

  const submit = useCallback(() => {
    if (!order || orderId === null || !canSubmit) return;
    setError(null);
    pay.mutate(
      {
        orderId,
        mode,
        amount: partial,
        deliveryFee: fee,
        branchId,
        allocations: toAllocations(allocations),
      },
      {
        onSuccess: () => {
          onPaid?.(orderId);
          onClose();
        },
        onError: (failure) => setError(orderFailureMessage(failure)),
      },
    );
  }, [order, orderId, canSubmit, pay, mode, partial, fee, branchId, allocations, onPaid, onClose]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (document.querySelector("[data-popover]")) return;
        event.stopPropagation();
        if (!pay.isPending) onClose();
      } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        submit();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose, submit, pay.isPending]);

  const suggestFee = async () => {
    if (!order?.city || !details.data) return;
    const items = details.data.items
      .filter((item) => item.product_id && (item.total ?? 0) >= 0)
      .map((item) => ({ product_id: item.product_id ?? 0, qty: Math.max(1, Math.round(item.qty)) }));
    if (items.length === 0) return;
    setQuoting(true);
    try {
      setFee(await finora.orders.quoteDeliveryFee(order.city, items));
    } catch (failure) {
      setError(toFinoraError(failure).message);
    } finally {
      setQuoting(false);
    }
  };

  const updateRow = (key: number, patch: Partial<AllocationDraft>) =>
    setAllocations((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  const addSplit = () => {
    const account = nextAccount(
      accounts,
      allocations.map((row) => row.accountId),
    );
    setAllocations((rows) => [
      ...rows,
      { key: newKey(), accountId: account?.id ?? null, amount: Math.max(0, target - allocatedTotal(rows)) },
    ]);
  };

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/20"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.14 } }}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget && !pay.isPending) onClose();
          }}
        >
          <motion.div
            role="dialog"
            aria-modal
            aria-label={`تسديد الطلب #${orderId}`}
            dir="rtl"
            className="glass-solid flex max-h-[min(760px,92vh)] w-[min(600px,94vw)] flex-col overflow-hidden rounded-panel bg-[#fbfaff]"
            initial={{ opacity: 0, y: 14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98, transition: { duration: 0.14 } }}
            transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
          >
            <header className="flex items-center gap-3 border-b border-line/70 px-5 py-4">
              <span className="grid h-11 w-11 place-items-center rounded-control bg-gradient-to-br from-success to-[#0f8a5f] text-white shadow-control">
                <Banknote size={21} aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="text-[17px] font-bold text-ink">
                  تسديد الطلب <span className="ltr-isolate">#{orderId}</span>
                </h2>
                <p className="truncate text-xs text-ink-faint">
                  {order ? `${order.customer ?? "—"} · ${order.city ?? ""}` : "جارٍ التحميل…"}
                </p>
              </div>
              <FeatureHelp
                label="شرح تسديد الطلب"
                text="الدفعة تخفض المتبقي على الطلب وتحدّث أقساطه إن وجدت. تقسيم المبلغ بين الصندوق والمصرف لا يضيف دفعة ثانية. لإنقاص تسديد مرتبط بسند حسابات، اعكس السند الأصلي من صفحة الحسابات حتى يبقى سجل الدفع محفوظاً."
              />
              <button
                type="button"
                aria-label="إغلاق"
                onClick={onClose}
                disabled={pay.isPending}
                className="grid h-9 w-9 place-items-center rounded-[10px] text-ink-soft hover:bg-surface-sunken"
              >
                <X size={18} />
              </button>
            </header>

            {loading ? (
              <div className="flex h-64 items-center justify-center text-sm text-ink-faint">
                <Loader2 size={20} className="me-2 animate-spin" aria-hidden /> جارٍ تحميل الطلب والحسابات من
                FINORA…
              </div>
            ) : loadError ? (
              <p role="alert" className="m-5 rounded-control bg-danger-soft px-4 py-3 text-sm text-danger">
                {toFinoraError(loadError).message}
              </p>
            ) : order ? (
              <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
                <div className="grid grid-cols-3 gap-2.5">
                  {[
                    { label: "إجمالي الطلب", value: order.total ?? 0, tone: "text-ink" },
                    { label: "المسدد سابقاً", value: (order.total ?? 0) - due, tone: "text-ink-soft" },
                    { label: "المستحق", value: due, tone: "text-violet-deep" },
                  ].map((card) => (
                    <div
                      key={card.label}
                      className="rounded-control bg-white px-3.5 py-3 ring-1 ring-line/70"
                    >
                      <p className="text-xs text-ink-faint">{card.label}</p>
                      <p className={cn("ltr-isolate mt-1 text-[17px] font-bold", card.tone)}>
                        <AnimatedNumber value={card.value} />
                      </p>
                    </div>
                  ))}
                </div>

                <div
                  role="radiogroup"
                  aria-label="نوع التسديد"
                  className="grid grid-cols-2 gap-1 rounded-control bg-surface-sunken p-1"
                >
                  {(
                    [
                      { id: "full", label: "تسديد كامل", hint: formatIqd(due) },
                      { id: "partial", label: "تسديد جزئي", hint: "دفعة من المبلغ" },
                    ] as const
                  ).map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      role="radio"
                      aria-checked={mode === option.id}
                      onClick={() => setMode(option.id)}
                      className={cn(
                        "relative flex h-12 flex-col items-center justify-center rounded-[11px] text-sm transition-[background-color,box-shadow] duration-200",
                        mode === option.id && "bg-white shadow-control",
                      )}
                    >
                      <span
                        className={cn(
                          "relative font-semibold",
                          mode === option.id ? "text-violet-deep" : "text-ink-soft",
                        )}
                      >
                        {option.label}
                      </span>
                      <span className="ltr-isolate relative text-[11px] text-ink-faint">{option.hint}</span>
                    </button>
                  ))}
                </div>

                <AnimatePresence initial={false}>
                  {mode === "partial" && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.2 }}
                      className="overflow-hidden"
                    >
                      <label className="flex items-center gap-3 rounded-control bg-white px-3.5 py-2.5 ring-1 ring-line/70">
                        <span className="text-sm font-medium text-ink">مبلغ الدفعة</span>
                        <MoneyInput
                          label="مبلغ التسديد الجزئي"
                          value={partial}
                          onChange={setPartial}
                          className="h-10 flex-1 text-base font-semibold"
                        />
                        <span className="ltr-isolate text-xs text-ink-faint">الحد {formatIqd(due)}</span>
                      </label>
                    </motion.div>
                  )}
                </AnimatePresence>

                {branches.length > 1 && (
                  <section>
                    <SectionTitle icon={Warehouse}>فرع خصم المخزون</SectionTitle>
                    <select
                      aria-label="فرع خصم المخزون"
                      value={branchId ?? ""}
                      disabled={stockDeducted}
                      onChange={(event) => setBranchId(Number(event.target.value) || null)}
                      className="h-11 w-full rounded-control border border-line bg-white px-3 text-sm text-ink outline-none focus:border-violet/45 disabled:bg-surface-sunken disabled:text-ink-soft"
                    >
                      {branches.map((branch) => (
                        <option key={branch.id} value={branch.id}>
                          {branch.name}
                          {branch.id === branchesQuery.data?.scheduledBranchId ? " — حسب جدول الوقت" : ""}
                        </option>
                      ))}
                    </select>
                    {stockDeducted && (
                      <p className="mt-1.5 text-xs text-ink-faint">
                        خُصم مخزون الطلب سابقاً؛ لا يمكن تغيير الفرع عند التسديد.
                      </p>
                    )}
                  </section>
                )}

                <section>
                  <div className="mb-2 flex items-center justify-between">
                    <SectionTitle icon={Wallet}>طريقة استلام المبلغ</SectionTitle>
                    <span
                      className={cn(
                        "ltr-isolate rounded-full px-2.5 py-0.5 text-xs font-semibold",
                        remainder === 0
                          ? "bg-success-soft text-success"
                          : remainder > 0
                            ? "bg-warning-soft text-warning"
                            : "bg-danger-soft text-danger",
                      )}
                    >
                      {remainder === 0
                        ? "مطابق ✓"
                        : remainder > 0
                          ? `متبقٍ ${formatIqd(remainder)}`
                          : `زيادة ${formatIqd(-remainder)}`}
                    </span>
                  </div>
                  {accounts.length === 0 ? (
                    <p className="rounded-control bg-warning-soft px-3.5 py-3 text-sm text-warning">
                      لا يوجد صندوق أو حساب بنكي مفعّل لهذا الفرع في FINORA.
                    </p>
                  ) : (
                    <ul className="space-y-2" aria-label="الدفعات">
                      <AnimatePresence initial={false}>
                        {allocations.map((row, index) => (
                          <motion.li
                            key={row.key}
                            layout
                            initial={{ opacity: 0, y: -6 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, x: 24, transition: { duration: 0.14 } }}
                            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                            className="flex items-center gap-2 rounded-control bg-white p-2 ring-1 ring-line/70"
                          >
                            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-surface-sunken">
                              <AccountIcon account={accountById.get(row.accountId ?? -1)} />
                            </span>
                            <select
                              aria-label={`حساب الدفعة ${index + 1}`}
                              value={row.accountId ?? ""}
                              onChange={(event) =>
                                updateRow(row.key, { accountId: Number(event.target.value) || null })
                              }
                              className="h-9 min-w-0 flex-1 rounded-[10px] border border-line bg-white px-2 text-sm text-ink outline-none focus:border-violet/45"
                            >
                              <option value="">اختر الحساب…</option>
                              {accounts.map((account) => (
                                <option key={account.id} value={account.id}>
                                  {account.type === "bank" ? "تحويل بنكي" : "نقدي"} — {account.name}
                                </option>
                              ))}
                            </select>
                            <MoneyInput
                              label={`مبلغ الدفعة ${index + 1}`}
                              value={row.amount}
                              onChange={(amount) => updateRow(row.key, { amount })}
                              className="w-32"
                            />
                            {allocations.length > 1 && (
                              <>
                                {remainder !== 0 && (
                                  <button
                                    type="button"
                                    onClick={() =>
                                      updateRow(row.key, { amount: Math.max(0, row.amount + remainder) })
                                    }
                                    className="h-9 shrink-0 rounded-[10px] bg-violet-soft px-2.5 text-xs font-semibold text-violet-deep hover:bg-violet hover:text-white"
                                  >
                                    الباقي
                                  </button>
                                )}
                                <button
                                  type="button"
                                  aria-label={`حذف الدفعة ${index + 1}`}
                                  onClick={() =>
                                    setAllocations((rows) => {
                                      const rest = rows.filter((r) => r.key !== row.key);
                                      return rest.length === 1 ? syncSingleAllocation(rest, target) : rest;
                                    })
                                  }
                                  className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] text-ink-faint hover:bg-danger-soft hover:text-danger"
                                >
                                  <Trash2 size={15} />
                                </button>
                              </>
                            )}
                          </motion.li>
                        ))}
                      </AnimatePresence>
                    </ul>
                  )}
                  {accounts.length > 0 && allocations.length < MAX_ALLOCATIONS && (
                    <button
                      type="button"
                      onClick={addSplit}
                      className="mt-2 flex h-9 items-center gap-1.5 rounded-[10px] px-3 text-sm font-semibold text-violet-deep hover:bg-violet-soft"
                    >
                      {allocations.length === 1 ? (
                        <SplitSquareHorizontal size={15} aria-hidden />
                      ) : (
                        <Plus size={15} aria-hidden />
                      )}
                      {allocations.length === 1 ? "تقسيم الدفعة على أكثر من حساب" : "إضافة دفعة"}
                    </button>
                  )}
                </section>

                <section>
                  <SectionTitle icon={Truck}>أجرة التوصيل</SectionTitle>
                  <div className="flex items-center gap-2 rounded-control bg-white p-2 ring-1 ring-line/70">
                    <MoneyInput
                      label="أجرة التوصيل"
                      value={fee}
                      onChange={setFee}
                      className="h-10 w-40 text-base"
                    />
                    <button
                      type="button"
                      disabled={quoting || !order.city}
                      onClick={() => void suggestFee()}
                      className="flex h-10 items-center gap-1.5 rounded-[10px] bg-azure-soft px-3 text-sm font-semibold text-azure transition-colors hover:bg-azure hover:text-white disabled:opacity-50"
                    >
                      {quoting ? (
                        <Loader2 size={15} className="animate-spin" aria-hidden />
                      ) : (
                        <Sparkles size={15} aria-hidden />
                      )}
                      المقترح
                    </button>
                    <div className="ms-auto text-end">
                      <p className="text-[11px] text-ink-faint">الصافي بعد الأجرة</p>
                      <p className="ltr-isolate text-sm font-bold text-ink">
                        {formatIqd(Math.max(0, (order.total ?? 0) - fee))}
                      </p>
                    </div>
                  </div>
                  <p className="mt-1.5 text-xs text-ink-faint">
                    تُسجَّل كأجرة توصيل داخلية للطلب ولا تُغيّر المبلغ المحصّل من الزبون.
                  </p>
                </section>
              </div>
            ) : null}

            <footer className="border-t border-line/70 bg-white/70 px-5 py-3.5">
              <AnimatePresence>
                {(error || (problem && order && due > 0 && allocations.length > 0)) && (
                  <motion.p
                    role="alert"
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className={cn(
                      "mb-2.5 rounded-control px-3.5 py-2 text-sm",
                      error ? "bg-danger-soft text-danger" : "bg-warning-soft text-warning",
                    )}
                  >
                    {error ?? problem}
                  </motion.p>
                )}
              </AnimatePresence>
              <div className="flex items-center gap-2.5">
                <p className="text-xs text-ink-faint">Ctrl+Enter للتأكيد</p>
                <button
                  type="button"
                  onClick={onClose}
                  disabled={pay.isPending}
                  className="ms-auto h-11 rounded-control px-4 text-sm text-ink-soft hover:bg-surface-sunken"
                >
                  إلغاء
                </button>
                <button
                  type="button"
                  disabled={!canSubmit}
                  onClick={submit}
                  className="flex h-11 items-center gap-2 rounded-control bg-gradient-to-l from-success to-[#0f8a5f] px-6 text-[15px] font-bold text-white shadow-float transition-opacity disabled:opacity-45"
                >
                  {pay.isPending ? (
                    <Loader2 size={17} className="animate-spin" aria-hidden />
                  ) : (
                    <CheckCircle2 size={17} aria-hidden />
                  )}
                  {pay.isPending ? "جارٍ التسديد…" : `تأكيد التسديد · ${formatIqd(target)}`}
                </button>
              </div>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
