import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { CalendarClock, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { finora, toFinoraError } from "@/api/finora";
import type { CustomerSchedule, SchedulePartition, OpeningDebt } from "@/api/finora/customers";
import { ConfirmDialog } from "@/components/Dialog";
import { FeatureHelp } from "@/components/FeatureHelp";
import { MoneyInput } from "@/components/MoneyInput";
import { useConnection } from "@/stores/connection";
import { useCan } from "@/stores/session";
import { useFinanceNavigation } from "@/stores/financeNavigation";
import { useWindowManager } from "@/stores/windowManager";
import { toast } from "@/stores/toasts";
import { formatIqd } from "@/utils/money";

type Props = {
  customerId: number;
  invoiceId?: number;
  planId?: number;
  openingDebt?: boolean;
  onClose(): void;
  onSaved(data: CustomerSchedule): void;
};
type Source = {
  total: number;
  paid: number;
  revision: string;
  blocked: string;
  fixed: CustomerSchedule["installments"];
  historical?: boolean;
  vouchers?: { id: number; number: string; date: string; amount: number; reversed: boolean }[];
};
const field =
  "h-10 w-full rounded-control border border-line bg-white px-3 text-sm focus:border-violet outline-none disabled:bg-surface-sunken";
const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Baghdad" }).format(new Date());
export function partitionPreview(
  total: number,
  count: number,
  first: string,
  interval: "monthly" | "weekly",
) {
  if (
    !Number.isInteger(count) ||
    count < 1 ||
    count > 240 ||
    total < count ||
    !/^\d{4}-\d{2}-\d{2}$/.test(first)
  )
    return [];
  const year = Number(first.slice(0, 4)),
    month = Number(first.slice(5, 7)),
    day = Number(first.slice(8, 10));
  const utc = (y: number, m: number, d: number) => {
    const value = new Date(0);
    value.setUTCFullYear(y, m, d);
    return value;
  };
  const origin = utc(year, month - 1, day);
  if (year < 1 || !Number.isFinite(origin.getTime())) return [];
  if (origin.toISOString().slice(0, 10) !== first) return [];
  const result = Array.from({ length: count }, (_, index) => {
    const due =
      interval === "weekly"
        ? new Date(origin.getTime() + index * 7 * 86400000)
        : utc(year, month - 1 + index, Math.min(day, utc(year, month + index, 0).getUTCDate()));
    return {
      date: due.toISOString().slice(0, 10),
      total: Math.floor(total / count) + (index === count - 1 ? total % count : 0),
    };
  });
  return result.every((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date)) ? result : [];
}

export function CustomerPlanBuilder(props: Props) {
  const { onClose } = props;
  const [generation, setGeneration] = useState(0);
  const panel = useRef<HTMLDivElement>(null);
  const query = useQuery({
    queryKey: [
      "customers",
      "plan-builder",
      props.customerId,
      props.invoiceId,
      props.planId,
      props.openingDebt,
    ],
    refetchOnWindowFocus: false,
    queryFn: async (): Promise<Source> => {
      if (props.openingDebt) {
        const data = await finora.customers.debtDraft(props.customerId);
        return { ...data, blocked: data.blocked_reason, fixed: [] };
      }
      if (props.invoiceId) {
        const data = await finora.customers.planDraft(props.customerId, props.invoiceId);
        return {
          ...data,
          blocked: data.blocked_reason,
          historical: !!data.historical,
          vouchers: data.historical?.vouchers ?? [],
          fixed: data.historical
            ? [
                {
                  id: props.invoiceId,
                  number: 1,
                  date: data.historical.date,
                  total: data.historical.paid,
                  paid: data.historical.paid,
                },
              ]
            : [],
        };
      }
      if (!props.planId) throw Error("مصدر الجدولة غير محدد");
      const data = await finora.customers.schedule(props.customerId, props.planId);
      const fixed = data.installments.filter((row) => row.paid > 0 || data.protected_ids?.includes(row.id));
      const free = data.total - fixed.reduce((sum, row) => sum + row.total, 0);
      return {
        ...data,
        fixed,
        blocked: free <= 0 ? "كل الأقساط مرتبطة بدفعات أو مسددة؛ يمكن تعديل المواعيد من الجدول الحالي" : "",
      };
    },
  });
  useEffect(() => {
    if (query.data) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onClose();
      }
      if (event.key === "Tab") {
        const controls = panel.current?.querySelectorAll<HTMLButtonElement>("button");
        const first = controls?.[0],
          last = controls?.[controls.length - 1];
        if (
          (event.shiftKey && document.activeElement === first) ||
          (!event.shiftKey && document.activeElement === last)
        ) {
          event.preventDefault();
          (event.shiftKey ? last : first)?.focus();
        }
      }
    };
    window.addEventListener("keydown", handle, true);
    return () => {
      window.removeEventListener("keydown", handle, true);
      previous?.focus({ preventScroll: true });
    };
  }, [query.data, onClose]);
  if (query.data)
    return (
      <BuilderForm
        key={generation}
        {...props}
        initial={query.data}
        onReload={async () => {
          const result = await query.refetch();
          if (!result.error && result.data) setGeneration((value) => value + 1);
          else if (result.error) toast.error(toFinoraError(result.error).message);
        }}
      />
    );
  return createPortal(
    <div className="no-drag fixed inset-0 z-[90] grid place-items-center bg-ink/20 p-5">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label="تقسيم الأقساط"
        className="glass-solid w-[520px] max-w-[calc(100vw-2.5rem)] rounded-panel p-6"
      >
        <h2 className="font-bold">تقسيم الأقساط</h2>
        <p role={query.isError ? "alert" : "status"} className="my-4">
          {query.isError ? toFinoraError(query.error).message : "جارٍ مراجعة مصدر الدين…"}
        </p>
        {query.isError && (
          <button className={field} onClick={() => void query.refetch()}>
            إعادة المحاولة
          </button>
        )}
        <button className="mt-4 text-violet-deep" onClick={props.onClose}>
          إغلاق
        </button>
      </div>
    </div>,
    document.body,
  );
}

function BuilderForm({
  initial,
  onReload,
  ...props
}: Props & { initial: Source; onReload(): Promise<void> }) {
  const cache = useQueryClient();
  const [count, setCount] = useState(3);
  const [first, setFirst] = useState(today);
  const [interval, setInterval] = useState<"monthly" | "weekly">("monthly");
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState(0);
  const [reference, setReference] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [discard, setDiscard] = useState<"close" | "reload" | "voucher" | null>(null);
  const voucherTarget = useRef<number | null>(null);
  const canFinance = useCan("finance.view");
  const compact = props.openingDebt || !!initial.vouchers?.length;
  const [refreshing, setRefreshing] = useState(false);
  const panel = useRef<HTMLFormElement>(null);
  const key = useRef(crypto.randomUUID());
  const sent = useRef<SchedulePartition | OpeningDebt | null>(null);
  const online = useConnection((state) => state.status === "online");
  const principal = props.openingDebt ? amount : initial.total;
  const free = principal - initial.fixed.reduce((sum, row) => sum + row.total, 0);
  const rows = partitionPreview(free, count, first, interval);
  const valid =
    !initial.blocked &&
    rows.length > 0 &&
    count + initial.fixed.length <= 240 &&
    reason.trim().length >= 3 &&
    (!props.openingDebt ||
      (Number.isSafeInteger(amount) &&
        amount <= 2147483647 &&
        reference.trim().length >= 3 &&
        reference.trim().length <= 80 &&
        reason.trim().length <= 120));
  const dirty =
    count !== 3 ||
    first !== today() ||
    interval !== "monthly" ||
    reason.length > 0 ||
    amount !== 0 ||
    reference.length > 0;
  const save = useMutation({
    mutationFn: () => {
      sent.current ??= { revision: initial.revision, count, first_due_date: first, interval, reason };
      if (props.openingDebt) {
        if (!("amount" in sent.current))
          sent.current = { ...sent.current, amount, source_type: "opening", source_reference: reference };
        return finora.customers.createDebt(props.customerId, sent.current as OpeningDebt, key.current);
      }
      return finora.customers.buildPlan(
        props.customerId,
        props.invoiceId ?? props.planId ?? 0,
        !!props.invoiceId,
        sent.current,
        key.current,
      );
    },
    onSuccess: (data) => {
      cache.setQueryData(["customers", "schedule", props.customerId, data.id], data);
      void Promise.all(
        ["customers", "finance", "reports", "orders"].map((name) =>
          cache.invalidateQueries({ queryKey: [name] }),
        ),
      );
      toast.success(
        props.openingDebt
          ? "تم تسجيل الدين وربطه بالذمم والرصيد الافتتاحي"
          : "تم حفظ جدول الأقساط دون تغيير الدين أو النقد",
      );
      props.onSaved(data);
    },
    onError: (error) => {
      const kind = toFinoraError(error).kind;
      const unknown = ["network", "timeout", "server", "invalid_response"].includes(kind);
      setUncertain(unknown);
      if (!unknown) sent.current = null;
    },
  });
  const locked = uncertain || save.isPending || refreshing;
  const openVoucher = () => {
    if (!canFinance || locked || !online || voucherTarget.current === null) return;
    useFinanceNavigation.getState().showVoucher(voucherTarget.current);
    props.onClose();
    useWindowManager.getState().open("finance");
  };
  const closeRef = useRef(() => {}),
    discardRef = useRef(discard);
  closeRef.current = () => {
    if (!locked) {
      if (dirty) setDiscard("close");
      else props.onClose();
    }
  };
  discardRef.current = discard;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLButtonElement>("button")?.focus();
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
          "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled)",
        );
        const firstControl = controls?.[0],
          last = controls?.[controls.length - 1];
        if (
          (event.shiftKey && document.activeElement === firstControl) ||
          (!event.shiftKey && document.activeElement === last)
        ) {
          event.preventDefault();
          (event.shiftKey ? last : firstControl)?.focus();
        }
      }
    };
    window.addEventListener("keydown", handle, true);
    return () => {
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
          aria-label={
            props.openingDebt
              ? "تسجيل دين افتتاحي"
              : props.invoiceId
                ? "إنشاء جدول أقساط"
                : "تقسيم الأقساط المتاحة"
          }
          dir="rtl"
          initial={{ y: 12, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className={`glass-solid flex ${compact ? "h-[92vh]" : "h-[88vh]"} max-h-[92vh] w-[1040px] min-w-0 max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-panel shadow-panel`}
          onSubmit={(event) => {
            event.preventDefault();
            if (online && !save.isPending && !refreshing && (valid || uncertain)) save.mutate();
          }}
        >
          <header
            className={`flex items-center gap-3 border-b border-line/70 px-5 ${compact ? "py-3" : "py-4"}`}
          >
            <span className="grid h-11 w-11 place-items-center rounded-control bg-violet-soft text-violet-deep">
              <CalendarClock size={22} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="font-bold text-ink">
                {props.openingDebt
                  ? "تسجيل دين افتتاحي"
                  : props.invoiceId
                    ? "إنشاء جدول أقساط"
                    : "تقسيم الأقساط المتاحة"}
              </h2>
              <p className="text-xs text-ink-faint">
                {props.openingDebt
                  ? `عميل #${props.customerId} · ذمم مقابل رصيد افتتاحي`
                  : props.invoiceId
                    ? `فاتورة #${props.invoiceId}`
                    : `خطة #${props.planId}`}{" "}
                · معاينة قبل الحفظ
              </p>
            </div>
            <FeatureHelp
              label="شرح تقسيم الأقساط"
              text={
                props.openingDebt
                  ? "سجل المبلغ المتبقي من دين سابق خارج فواتير FINORA بعد مراجعة الأرصدة الافتتاحية. يرحّل إلى الذمم مقابل تسوية الافتتاحي بتاريخ التسجيل، وتبقى حركة الصندوق والأرباح والمخزون كما هي. أدخل مرجعاً فريداً لهذا العميل ووصف المصدر؛ لا تسجل دين فاتورة موجودة أو مبلغاً مسدداً. يلزم صلاحية إعدادات الحسابات. العدد 1 يجعل الدين مستحقاً بدفعة واحدة. يظهر بعدها في كشف العميل والتحصيل والأقساط والتقارير، وتوثق العملية والموظف."
                  : "الجدولة تنظم استحقاق دين موجود ولا تنشئ بيعاً أو قبضاً جديداً. يُحفظ التحصيل السابق بصف ملخص بتاريخ الفاتورة وتبقى الدفعات الأصلية وتواريخها محفوظة؛ هذا التاريخ ليس استحقاقاً جديداً. سندات الحسابات تُربط تلقائياً بحصتها من هذه الفاتورة، وعكس السند الأصلي يعكس الحصة نفسها حتى بعد تغيير عدد الأقساط. السند المعكوس سابقاً يبقى ضمن التاريخ، وقد يكون صافي التحصيل صفراً. عند اختلاف المصادر تتوقف الجدولة للمراجعة. الرصيد القديم غير المفصل يبقى موضحاً دون اختراع وسيلة دفع. يُقسّم المتبقي فقط، والعدد يخص الأقساط الجديدة. الأقساط المرتبطة بدفعات تبقى بهويتها حتى بعد العكس. الشهري يحافظ على يوم الاستحقاق ويستعمل آخر يوم بالشهر الأقصر. السبب والجدول قبل وبعد محفوظان."
              }
            />
            <button
              type="button"
              aria-label="إغلاق تقسيم الأقساط"
              disabled={locked}
              onClick={() => closeRef.current()}
              className="rounded-control p-2 text-ink-soft hover:bg-violet-soft disabled:opacity-40"
            >
              <X size={19} />
            </button>
          </header>
          <div className={`flex min-h-0 min-w-0 flex-1 flex-col ${compact ? "gap-2 p-3" : "gap-3 p-5"}`}>
            <div className="grid grid-cols-3 gap-3">
              {[
                ["أصل الدين", principal],
                ["المدفوع المحفوظ", initial.paid],
                ["المبلغ القابل للتقسيم", free],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className={`rounded-control border border-line bg-white ${compact ? "p-2" : "p-3"}`}
                >
                  <p className="text-xs text-ink-faint">{label}</p>
                  <p className="ltr-isolate mt-1 font-bold text-ink">{formatIqd(Number(value))}</p>
                </div>
              ))}
            </div>
            {!!initial.vouchers?.length && (
              <div
                role="region"
                aria-label="سندات التحصيل السابقة"
                className="flex shrink-0 items-center gap-2 overflow-x-auto rounded-control border border-line bg-violet-soft/40 px-3 py-2 text-xs"
              >
                <span className="shrink-0 text-ink-soft">سندات التحصيل · حصة هذه الفاتورة</span>
                {initial.vouchers.map((voucher) => (
                  <div
                    key={voucher.id}
                    className="flex shrink-0 items-center gap-2 rounded-control border border-line bg-white px-3 py-2"
                  >
                    {canFinance ? (
                      <button
                        type="button"
                        disabled={locked || !online}
                        className="text-violet-deep hover:underline disabled:opacity-40"
                        aria-label={`فتح السند ${voucher.number}`}
                        onClick={() => {
                          voucherTarget.current = voucher.id;
                          if (dirty) setDiscard("voucher");
                          else openVoucher();
                        }}
                      >
                        {voucher.number}
                      </button>
                    ) : (
                      <span>{voucher.number}</span>
                    )}
                    <span className="ltr-isolate text-ink-soft">{voucher.date}</span>
                    <span className="ltr-isolate font-semibold">{formatIqd(voucher.amount)}</span>
                    <span className={voucher.reversed ? "text-ink-faint" : "text-success"}>
                      {voucher.reversed ? "معكوس" : "مرحّل"}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {initial.blocked ? (
              <p role="alert" className="rounded-control bg-warning-soft p-3 text-sm text-warning">
                {initial.blocked}
              </p>
            ) : (
              <>
                {props.openingDebt && (
                  <fieldset disabled={locked} className="grid grid-cols-3 gap-3 text-sm font-semibold">
                    <label>
                      المبلغ المتبقي بالدينار
                      <MoneyInput
                        label="مبلغ الدين الافتتاحي"
                        value={amount}
                        onChange={setAmount}
                        className={`${field} mt-2`}
                      />
                    </label>
                    <label>
                      مرجع المصدر
                      <input
                        aria-label="مرجع مصدر الدين"
                        required
                        minLength={3}
                        maxLength={80}
                        value={reference}
                        onChange={(event) => setReference(event.target.value)}
                        placeholder="رقم كشف أو مستند خارجي"
                        className={`${field} mt-2`}
                      />
                    </label>
                    <div className="rounded-control bg-violet-soft p-3 text-xs font-normal text-ink-soft">
                      دين سابق خارج فواتير FINORA · رصيد افتتاحي
                      <br />
                      يُرحّل بتاريخ التسجيل. راجع المصدر قبل الحفظ.
                    </div>
                  </fieldset>
                )}
                <fieldset disabled={locked} className="grid grid-cols-4 gap-3 text-sm font-semibold">
                  <label>
                    عدد الأقساط المتاحة
                    <input
                      aria-label="عدد الأقساط المتاحة"
                      type="number"
                      min={1}
                      max={240 - initial.fixed.length}
                      value={count}
                      onChange={(event) => setCount(Number(event.target.value))}
                      className={`${field} mt-2`}
                    />
                  </label>
                  <label>
                    أول استحقاق جديد
                    <input
                      aria-label="أول استحقاق جديد"
                      type="date"
                      value={first}
                      onChange={(event) => setFirst(event.target.value)}
                      className={`${field} mt-2`}
                    />
                  </label>
                  <label>
                    تكرار الاستحقاق
                    <select
                      aria-label="تكرار الاستحقاق"
                      value={interval}
                      onChange={(event) =>
                        setInterval(event.target.value === "weekly" ? "weekly" : "monthly")
                      }
                      className={`${field} mt-2`}
                    >
                      <option value="monthly">شهري</option>
                      <option value="weekly">أسبوعي</option>
                    </select>
                  </label>
                  <label>
                    {props.openingDebt ? "وصف الدين" : "سبب الجدولة"}
                    <input
                      aria-label={props.openingDebt ? "وصف الدين الافتتاحي" : "سبب تقسيم الأقساط"}
                      required
                      minLength={3}
                      maxLength={props.openingDebt ? 120 : 500}
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder={props.openingDebt ? "منشأ الدين المتبقي" : "سبب التقسيم"}
                      className={`${field} mt-2`}
                    />
                  </label>
                </fieldset>
                <p className="text-xs text-ink-soft">
                  {initial.historical &&
                    "صف التحصيل السابق ملخص محفوظ بتاريخ الفاتورة؛ ليس قبضاً أو استحقاقاً جديداً. "}
                  {initial.fixed.length} قسط محفوظ مرتبط بدفعات · {rows.length} قسط متاح · الإجمالي{" "}
                  {initial.fixed.length + rows.length} قسط
                </p>
                {(rows.length === 0 || count + initial.fixed.length > 240) && (
                  <p role="alert" className="text-sm text-danger">
                    راجع العدد والتاريخ؛ كل قسط لا يقل عن دينار واحد، والجدول كله حتى 240 قسطاً.
                  </p>
                )}
                {props.openingDebt && amount > 2147483647 && (
                  <p role="alert" className="text-sm text-danger">
                    المبلغ يتجاوز الحد: 2,147,483,647 دينار.
                  </p>
                )}
                <div
                  role="region"
                  aria-label="معاينة تقسيم الأقساط"
                  className="min-h-0 min-w-0 flex-1 overflow-auto rounded-panel border border-line bg-white"
                >
                  <table className="w-full min-w-[650px] text-sm">
                    <thead className="sticky top-0 bg-surface-sunken text-ink-soft">
                      <tr>
                        {["القسط", "الاستحقاق", "القيمة", "المدفوع", "الحالة"].map((label) => (
                          <th key={label} className="px-3 py-3 text-start">
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {initial.fixed.map((row) => (
                        <tr key={row.id} className="border-t border-line/60">
                          <td className="px-3 py-3">
                            {initial.historical ? "تحصيل سابق" : `#${row.number}`}
                          </td>
                          <td className="px-3 py-3">{row.date}</td>
                          <td className="ltr-isolate px-3 py-3">{formatIqd(row.total)}</td>
                          <td className="ltr-isolate px-3 py-3">{formatIqd(row.paid)}</td>
                          <td className="px-3 py-3 text-ink-faint">
                            {initial.historical ? "محفوظ — تحصيل سابق" : "محفوظ — مرتبط بدفعات"}
                          </td>
                        </tr>
                      ))}
                      {rows.map((row, index) => (
                        <tr key={index} className="border-t border-line/60">
                          <td className="px-3 py-3">
                            #{Math.max(0, ...initial.fixed.map((item) => item.number)) + index + 1}
                          </td>
                          <td className="px-3 py-3">{row.date}</td>
                          <td className="ltr-isolate px-3 py-3 font-semibold text-violet-deep">
                            {formatIqd(row.total)}
                          </td>
                          <td className="px-3 py-3">0</td>
                          <td className="px-3 py-3">متاح للجدولة</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {save.isError && (
              <p role="alert" className="rounded-control bg-danger-soft p-3 text-sm text-danger">
                {toFinoraError(save.error).message}
              </p>
            )}
            {uncertain && (
              <p className="text-sm text-warning">
                نتيجة الحفظ غير مؤكدة؛ أعد نفس الحفظ. بعد إعادة تشغيل البرنامج راجع طلبات الحفظ المحفوظة في
                صفحة العملاء.
              </p>
            )}
          </div>
          <footer
            className={`flex items-center justify-between gap-3 border-t border-line/70 bg-white/70 px-5 ${props.openingDebt ? "py-3" : "py-4"}`}
          >
            <button
              type="submit"
              disabled={!online || save.isPending || refreshing || (!valid && !uncertain)}
              className="h-11 rounded-control bg-gradient-to-l from-violet to-violet-deep px-5 font-semibold text-white disabled:opacity-45"
            >
              {save.isPending
                ? "جارٍ الحفظ…"
                : uncertain
                  ? "إعادة محاولة نفس الحفظ"
                  : props.openingDebt
                    ? "تسجيل الدين وترحيله"
                    : "حفظ تقسيم الأقساط"}
            </button>
            <button
              type="button"
              disabled={locked || !online}
              onClick={() => (dirty ? setDiscard("reload") : void reload())}
              className="flex h-10 items-center gap-2 rounded-control px-3 text-sm text-violet-deep hover:bg-violet-soft disabled:opacity-40"
            >
              <RefreshCw size={16} />
              تحميل أحدث مصدر
            </button>
          </footer>
        </motion.form>
      </motion.div>
      <ConfirmDialog
        open={discard !== null}
        title="تعديلات غير محفوظة"
        message={
          discard === "reload"
            ? "تحميل المصدر الأحدث يلغي تقسيمك غير المحفوظ."
            : discard === "voucher"
              ? "فتح السند الأصلي يغلق الجدولة ويلغي التقسيم غير المحفوظ."
              : "إغلاق النافذة يلغي التقسيم غير المحفوظ."
        }
        confirmLabel={
          discard === "reload"
            ? "تحميل المصدر"
            : discard === "voucher"
              ? "فتح السند دون حفظ"
              : "إغلاق دون حفظ"
        }
        onClose={() => setDiscard(null)}
        onConfirm={() => {
          const action = discard;
          setDiscard(null);
          if (action === "reload") void reload();
          else if (action === "voucher") openVoucher();
          else props.onClose();
        }}
      />
    </>,
    document.body,
  );
}
