import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Plus, Trash2, RefreshCw } from "lucide-react";
import { finora, toFinoraError } from "@/api/finora";
import type {
  StockMeta,
  StockRow,
  StockTransferDetail,
  StockWriteOff,
  StockPayload,
} from "@/api/finora/stockOperations";
import { SidePanel } from "@/components/SidePanel";
import { ConfirmDialog } from "@/components/Dialog";
import { FeatureHelp } from "@/components/FeatureHelp";
import { ProductThumb } from "@/components/ProductThumb";
import { productImageUrl } from "@/api/finora/products";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";
export const fieldClass =
  "mt-2 w-full rounded-control border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none focus:border-violet disabled:opacity-50";
export const stockButton =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-control border border-line bg-white px-3 text-sm text-ink-soft transition-colors hover:bg-violet-soft disabled:opacity-40";
export const stockPrimary =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-control border border-violet bg-violet px-3 text-sm text-white transition-colors hover:bg-violet-deep disabled:opacity-40";
export const stockMoney = (amount: number | string | null | undefined) =>
  amount == null ? "—" : `${BigInt(amount).toLocaleString("en-US")} د.ع`;
export type StockForm =
  | { kind: "transfer" }
  | { kind: "writeoff"; row: StockRow }
  | { kind: "rule"; row: StockRow }
  | { kind: "warehouse" }
  | {
      kind: "phase";
      phase: "send" | "receive" | "cancel" | "approve" | "reject" | "receive_partial" | "resolve";
      row: StockTransferDetail;
    }
  | { kind: "reverse"; row: StockWriteOff };
const phaseTitles = {
  send: "إرسال التحويل",
  receive: "استلام التحويل",
  cancel: "إلغاء التحويل",
  approve: "اعتماد التحويل",
  reject: "رفض الاستلام وإعادة البضاعة",
  receive_partial: "استلام جزئي للتحويل",
  resolve: "معالجة الكمية المتبقية",
};
const phaseHints: Record<string, string> = {
  send: "ينقص رصيد المصدر وتبقى الكمية قيد النقل إلى الاستلام.",
  receive: "يضاف الرصيد إلى الوجهة مرة واحدة بنفس كلفة القطع المرسلة.",
  cancel: "المسودة تُلغى دون تغيير الرصيد. إذا أُرسلت، ترجع القطع والكلفة إلى المصدر.",
  approve: "يُعتمد التحويل ليصبح قابلاً للإرسال. لا يتغير أي رصيد.",
  reject: "ترجع كل الكمية المرسلة إلى المصدر بنفس دفعاتها وكلفتها، ويُغلق التحويل كمرفوض.",
  receive_partial:
    "تُضاف إلى الوجهة الكميات التي وصلت فعلاً بكلفتها الأصلية. الباقي يبقى بالطريق ملكاً للمرسل حتى تحدّد مصيره.",
  resolve:
    "لكل كمية متبقية: وصلت متأخرة (تُضاف للوجهة) · تُعاد للمصدر · فاقد/تالف (يُسجَّل بسند تلف وقيد خسارة مخزون).",
};
export function StockForms({
  mode,
  meta,
  location,
  scope,
  active,
  serverUrl,
  onClose,
  onSaved,
}: {
  mode: StockForm;
  meta: StockMeta;
  location: string;
  scope: string;
  active: boolean;
  serverUrl: string | null;
  onClose(): void;
  onSaved(result: { id: number; type: string; ledger_kind: "branch" | "warehouse"; status: string }): void;
}) {
  const client = useQueryClient();
  const [key] = useState(() => crypto.randomUUID());
  const [dirty, setDirty] = useState(false),
    [discard, setDiscard] = useState(false);
  const [received, setReceived] = useState<Record<number, string>>({}),
    [fate, setFate] = useState<Record<number, string>>({});
  const [reason, setReason] = useState(""),
    [quantity, setQuantity] = useState("1"),
    [on, setOn] = useState(meta.today);
  const [from, setFrom] = useState(location),
    [to, setTo] = useState(meta.locations.find((row) => row.key !== location)?.key ?? "");
  const [search, setSearch] = useState(""),
    [lines, setLines] = useState<{ row: StockRow; quantity: number }[]>([]);
  const [current, setCurrent] = useState(
    "row" in mode && (mode.kind === "writeoff" || mode.kind === "rule") ? mode.row : null,
  );
  const [minimum, setMinimum] = useState(current ? String(current.minimum) : "5"),
    [target, setTarget] = useState(current ? String(current.target) : "10");
  const [name, setName] = useState(""),
    [code, setCode] = useState(""),
    [warehouseKind, setWarehouseKind] = useState("main"),
    [branch, setBranch] = useState(String(meta.branches[0]?.branch_id ?? ""));
  const [savedAttempt, setSavedAttempt] = useState<StockPayload | null>(null);
  const pending = useQuery({
    queryKey: ["stock-recovery", scope],
    queryFn: () => finora.stockOperations.pending(),
    enabled: active,
  });
  const protectedAttempt = !!pending.data?.items.some((row) => row.key === key);
  const query = useDebouncedValue(search, 200),
    count = useDebouncedValue(Number(quantity), 150);
  const catalog = useQuery({
    queryKey: ["stock-operations", scope, "picker", meta.kind, from, query],
    queryFn: () => finora.stockOperations.stocks(meta.kind, from, query),
    enabled: active && mode.kind === "transfer" && !!from,
  });
  const preview = useQuery({
    queryKey: [
      "stock-operations",
      scope,
      "valuation",
      current?.product_id,
      current?.variant_name,
      location,
      count,
    ],
    queryFn: () => {
      if (!current) throw Error("اختر الصنف");
      return finora.stockOperations.valuation(
        meta.kind,
        location,
        current.product_id,
        current.variant_name,
        count,
      );
    },
    enabled: active && mode.kind === "writeoff" && !!current && Number.isInteger(count) && count > 0,
  });
  const load = useMutation({
    mutationFn: () => {
      if (!current) throw Error("اختر الصنف");
      return finora.stockOperations.item(meta.kind, location, current.product_id, current.variant_name);
    },
    onSuccess: (row) => setCurrent(row),
    onError: (error) => toast.error(toFinoraError(error).message),
  });
  const title =
    mode.kind === "transfer"
      ? "تحويل مخزون جديد"
      : mode.kind === "writeoff"
        ? "تسجيل تلف مخزون"
        : mode.kind === "rule"
          ? "حد إعادة الطلب"
          : mode.kind === "warehouse"
            ? "إضافة مخزن"
            : mode.kind === "reverse"
              ? "عكس سند التلف"
              : phaseTitles[mode.phase];
  const change = <T,>(setter: (value: T) => void, value: T) => {
    setter(value);
    setDirty(true);
  };
  function body(): StockPayload {
    const base = { operation_id: key, reason };
    if (mode.kind === "transfer")
      return {
        ...base,
        from_location: from,
        to_location: to,
        lines: lines.map((entry) => ({
          product_id: entry.row.product_id,
          variant_name: entry.row.variant_name,
          quantity: entry.quantity,
        })),
      };
    if (mode.kind === "writeoff" && current)
      return {
        ...base,
        location_key: location,
        product_id: current.product_id,
        variant_name: current.variant_name,
        quantity: Number(quantity),
        stock_revision: current.revision,
        business_date: on,
      };
    if (mode.kind === "rule" && current)
      return {
        ...base,
        location_key: location,
        product_id: current.product_id,
        variant_name: current.variant_name,
        minimum: Number(minimum),
        target: Number(target),
        rule_version: current.rule_version,
      };
    if (mode.kind === "warehouse")
      return { ...base, name, code, branch_id: Number(branch), warehouse_kind: warehouseKind };
    if (mode.kind === "phase") {
      const withRevision = { ...base, revision: mode.row.revision };
      if (mode.phase === "receive_partial")
        return {
          ...withRevision,
          lines: mode.row.lines.map((line) => ({
            line_id: line.id,
            received: Number(received[line.id] ?? line.quantity),
          })),
        };
      if (mode.phase === "resolve")
        return {
          ...withRevision,
          lines: mode.row.lines
            .filter((line) => (line.residual ?? 0) > 0)
            .map((line) => ({ line_id: line.id, action: fate[line.id] ?? "late" })),
        };
      return withRevision;
    }
    if (mode.kind === "reverse")
      return { ...base, location_key: mode.row.location_key, revision: mode.row.revision, business_date: on };
    throw Error("اختر صنفاً قبل الحفظ");
  }
  const save = useMutation({
    mutationFn: async () => {
      const payload = protectedAttempt && savedAttempt ? savedAttempt : body();
      setSavedAttempt(payload);
      if (mode.kind === "transfer") return finora.stockOperations.createTransfer(meta.kind, payload);
      if (mode.kind === "writeoff") return finora.stockOperations.createWriteoff(meta.kind, payload);
      if (mode.kind === "rule") return finora.stockOperations.rule(meta.kind, payload);
      if (mode.kind === "warehouse") return finora.stockOperations.createWarehouse(payload);
      if (mode.kind === "phase")
        return finora.stockOperations.transferPhase(mode.row.ledger_kind, mode.row.id, mode.phase, payload);
      return finora.stockOperations.reverseWriteoff(mode.row.id, payload);
    },
    onSuccess: (result) => {
      toast.success("تم حفظ العملية وتحديث المخزون");
      onSaved(result);
    },
    onError: () => void client.invalidateQueries({ queryKey: ["stock-recovery", scope] }),
  });
  const frozen = save.isPending || protectedAttempt;
  const stale =
    mode.kind === "writeoff" &&
    !!current &&
    !!preview.data &&
    preview.data.stock_revision !== current.revision;
  const close = () => {
    if (save.isPending) return;
    if (dirty && !protectedAttempt) setDiscard(true);
    else onClose();
  };
  return (
    <>
      <SidePanel
        open={active}
        title={title}
        onClose={close}
        layer={45}
        footer={
          <div className="flex gap-2">
            <button
              type="submit"
              form="stock-operation-form"
              disabled={
                save.isPending ||
                load.isPending ||
                (!protectedAttempt &&
                  (stale ||
                    (mode.kind === "transfer" && !lines.length) ||
                    (mode.kind === "writeoff" && (!preview.data?.eligible || preview.isFetching))))
              }
              className={stockPrimary}
            >
              {save.isPending
                ? "جارٍ حفظ العملية…"
                : protectedAttempt
                  ? "إعادة نفس الطلب"
                  : mode.kind === "transfer"
                    ? "حفظ المسودة"
                    : mode.kind === "writeoff"
                      ? "ترحيل التلف"
                      : "تأكيد وحفظ"}
            </button>
            <button type="button" onClick={close} disabled={save.isPending} className={stockButton}>
              إغلاق النموذج
            </button>
          </div>
        }
      >
        <form
          id="stock-operation-form"
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <div className="flex items-center justify-between gap-3 rounded-control bg-violet-soft p-3 text-xs text-ink-soft">
            <span>
              {mode.kind === "transfer"
                ? "المسودة ما تغيّر الرصيد؛ الإرسال والاستلام بخطوتين واضحتين."
                : mode.kind === "writeoff"
                  ? "التلف يخصم القطع ويسجّل خسارتها؛ الصندوق يبقى كما هو."
                  : mode.kind === "reverse"
                    ? "العكس يرجّع الكمية وكلفتها ويلغي خسارة السند الأصلي."
                    : mode.kind === "rule"
                      ? "حد خاص بهذا الموقع وخيار الصنف؛ ما يغيّر الكمية."
                      : mode.kind === "warehouse"
                        ? "مخزن جديد برصيد فارغ، مرتبط بفرعه."
                        : "تأكد من انتقال القطع فعلياً قبل التأكيد."}
            </span>
            <FeatureHelp
              label="شرح العملية المخزنية"
              text="الحفظ يحتاج اتصالاً. يحتفظ FINORA بطلبك مشفراً قبل الإرسال. إذا انقطع الرد راجع عمليات المخزون المحفوظة وأعد نفس الطلب؛ لا تنشئ طلباً جديداً لنفس العملية. الكلفة تؤخذ من سجل المخزون، والتصحيح يبقى موثقاً."
            />
          </div>
          {protectedAttempt && (
            <p role="status" className="rounded-control bg-warning-soft p-3 text-sm">
              طلبك محفوظ للمراجعة. إعادة المحاولة ترسل بياناته الأصلية، حتى إذا تغيرت الشاشة.
            </p>
          )}
          {mode.kind === "transfer" && (
            <>
              <label className="block text-sm">
                من الموقع
                <select
                  aria-label="مصدر التحويل"
                  className={fieldClass}
                  value={from}
                  disabled={frozen}
                  onChange={(event) => {
                    change(setFrom, event.target.value);
                    setLines([]);
                  }}
                >
                  {meta.locations.map((place) => (
                    <option key={place.key} value={place.key}>
                      {place.name} · {place.branch_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                إلى الموقع
                <select
                  required
                  aria-label="وجهة التحويل"
                  className={fieldClass}
                  value={to}
                  disabled={frozen}
                  onChange={(event) => change(setTo, event.target.value)}
                >
                  <option value="">اختر الوجهة</option>
                  {meta.locations
                    .filter((place) => place.key !== from)
                    .map((place) => (
                      <option key={place.key} value={place.key}>
                        {place.name} · {place.branch_name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="block text-sm">
                أضف الأصناف
                <input
                  aria-label="بحث أصناف التحويل"
                  className={fieldClass}
                  value={search}
                  disabled={frozen}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="اسم، مقاس، لون، SKU أو باركود…"
                />
              </label>
              {catalog.error && (
                <p role="alert" className="text-danger">
                  {toFinoraError(catalog.error).message}
                </p>
              )}
              <div className="max-h-52 space-y-2 overflow-auto rounded-control border border-line p-2">
                {catalog.isPending ? (
                  <p role="status">تحميل الأصناف…</p>
                ) : (
                  catalog.data?.items.map((row) => (
                    <div key={row.id} className="flex items-center gap-2 rounded-control bg-white p-2">
                      <ProductThumb src={productImageUrl(row.image_url, serverUrl)} />
                      <div className="min-w-0 flex-1">
                        <strong className="block text-xs">{row.name}</strong>
                        <span className="text-xs text-ink-faint">
                          {row.variant_name || row.sku} · متاح {formatNumber(row.available)}
                        </span>
                        {!row.valuation_ready && (
                          <span className="block text-xs text-warning">تحتاج مراجعة كلفة المخزون</span>
                        )}
                      </div>
                      <button
                        type="button"
                        aria-label={`إضافة ${row.name} ${row.variant_name}`}
                        className={stockButton}
                        disabled={
                          frozen || row.available < 1 || lines.some((entry) => entry.row.id === row.id)
                        }
                        onClick={() => {
                          change(setLines, [...lines, { row, quantity: 1 }]);
                          setSearch("");
                        }}
                      >
                        <Plus size={15} />
                      </button>
                    </div>
                  ))
                )}
              </div>
              {lines.map((entry) => (
                <div key={entry.row.id} className="rounded-control border border-line p-3">
                  <div className="flex items-center justify-between gap-3">
                    <strong className="text-sm">
                      {entry.row.name} · {entry.row.variant_name || "بدون خيار"}
                    </strong>
                    <button
                      type="button"
                      className={stockButton}
                      aria-label={`حذف ${entry.row.name}`}
                      disabled={frozen}
                      onClick={() =>
                        change(
                          setLines,
                          lines.filter((line) => line.row.id !== entry.row.id),
                        )
                      }
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  <label className="mt-2 block text-xs">
                    الكمية · المتاح {formatNumber(entry.row.available)}
                    <input
                      required
                      aria-label={`كمية ${entry.row.name} ${entry.row.variant_name}`}
                      className={fieldClass}
                      type="number"
                      min="1"
                      max={entry.row.available}
                      step="1"
                      dir="ltr"
                      disabled={frozen}
                      value={entry.quantity || ""}
                      onChange={(event) =>
                        change(
                          setLines,
                          lines.map((line) =>
                            line.row.id === entry.row.id
                              ? { ...line, quantity: Number(event.target.value) }
                              : line,
                          ),
                        )
                      }
                    />
                  </label>
                </div>
              ))}
            </>
          )}
          {(mode.kind === "writeoff" || mode.kind === "rule") && current && (
            <div className="rounded-control border border-line p-3">
              <strong>{current.name}</strong>
              <p className="mt-1 text-sm text-ink-soft">
                {current.variant_name || current.sku} · {current.location_name}
              </p>
              <p className="mt-2 text-sm">
                الموجود {formatNumber(current.quantity)} · المتاح {formatNumber(current.available)}
              </p>
            </div>
          )}
          {mode.kind === "writeoff" && (
            <>
              <label className="block text-sm">
                الكمية التالفة
                <input
                  required
                  aria-label="الكمية التالفة"
                  className={fieldClass}
                  type="number"
                  min="1"
                  max={current?.available}
                  step="1"
                  dir="ltr"
                  disabled={frozen}
                  value={quantity}
                  onChange={(event) => change(setQuantity, event.target.value)}
                />
              </label>
              <label className="block text-sm">
                تاريخ التلف
                <input
                  required
                  aria-label="تاريخ التلف"
                  className={fieldClass}
                  type="date"
                  max={meta.today}
                  disabled={frozen}
                  value={on}
                  onChange={(event) => change(setOn, event.target.value)}
                />
              </label>
              <div className="rounded-control bg-danger-soft p-3">
                <span className="text-xs text-ink-soft">الكلفة الفعلية للتلف</span>
                <strong className="mt-2 block text-xl ltr-isolate">
                  {preview.isFetching ? "…" : stockMoney(preview.data?.cost)}
                </strong>
                <p className="mt-2 text-xs text-ink-soft">تُحتسب من دفعات القطع الأقدم. ماكو سحب نقدي.</p>
              </div>
              {(stale || preview.data?.blocked_reason || preview.error) && (
                <p role="alert" className="text-sm text-danger">
                  {stale
                    ? "المخزون تغيّر منذ فتح النموذج؛ حدّث الرصيد قبل التأكيد."
                    : preview.data?.blocked_reason || toFinoraError(preview.error).message}
                </p>
              )}
              <button
                type="button"
                className={stockButton}
                disabled={frozen || load.isPending}
                onClick={() => load.mutate()}
              >
                <RefreshCw size={14} />
                تحديث الرصيد
              </button>
            </>
          )}
          {mode.kind === "rule" && (
            <>
              <label className="block text-sm">
                حد إعادة الطلب
                <input
                  required
                  aria-label="حد إعادة الطلب"
                  className={fieldClass}
                  type="number"
                  min="0"
                  step="1"
                  disabled={frozen}
                  value={minimum}
                  onChange={(event) => change(setMinimum, event.target.value)}
                />
              </label>
              <label className="block text-sm">
                الرصيد المستهدف
                <input
                  required
                  aria-label="الرصيد المستهدف"
                  className={fieldClass}
                  type="number"
                  min={minimum || 0}
                  step="1"
                  disabled={frozen}
                  value={target}
                  onChange={(event) => change(setTarget, event.target.value)}
                />
              </label>
              <FeatureHelp
                label="شرح حد الطلب"
                text="يظهر الصنف عند وصول المتاح إلى الحد أو أقل. المقترح يكمل الرصيد المستهدف بعد طرح القطع قيد النقل. الصفر في الحد يعني التنبيه عند نفاد المتاح. الحد يخص هذا الموقع والخيار؛ بقية المواقع تستخدم حد المنتج الافتراضي حتى تعدله هنا."
              />
            </>
          )}
          {mode.kind === "warehouse" && (
            <>
              <label className="block text-sm">
                اسم المخزن
                <input
                  required
                  aria-label="اسم المخزن"
                  className={fieldClass}
                  maxLength={150}
                  disabled={frozen}
                  value={name}
                  onChange={(event) => change(setName, event.target.value)}
                />
              </label>
              <label className="block text-sm">
                رمز المخزن
                <input
                  required
                  aria-label="رمز المخزن"
                  className={fieldClass}
                  maxLength={60}
                  disabled={frozen}
                  value={code}
                  onChange={(event) => change(setCode, event.target.value)}
                />
              </label>
              <label className="block text-sm">
                الفرع
                <select
                  aria-label="فرع المخزن"
                  className={fieldClass}
                  disabled={frozen}
                  value={branch}
                  onChange={(event) => change(setBranch, event.target.value)}
                >
                  {meta.branches.map((place) => (
                    <option key={place.key} value={place.branch_id}>
                      {place.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                نوع المخزن
                <select
                  aria-label="نوع المخزن"
                  className={fieldClass}
                  disabled={frozen}
                  value={warehouseKind}
                  onChange={(event) => change(setWarehouseKind, event.target.value)}
                >
                  <option value="main">مخزن رئيسي</option>
                  <option value="damaged">مخزن تالف</option>
                  <option value="returns">مخزن مرتجعات</option>
                </select>
              </label>
            </>
          )}
          {mode.kind === "phase" && (
            <div className="rounded-control border border-line p-3">
              <strong>{mode.row.number}</strong>
              <p className="mt-2 text-sm">
                {mode.row.from_name} ← {mode.row.to_name}
              </p>
              <p className="mt-2 text-sm">{formatNumber(mode.row.quantity)} قطعة</p>
              <p className="mt-2 text-xs text-ink-soft">{phaseHints[mode.phase]}</p>
              {mode.phase === "receive_partial" && (
                <ul className="mt-3 space-y-2" aria-label="الكميات المستلمة">
                  {mode.row.lines.map((line) => (
                    <li key={line.id} className="flex items-center gap-3 text-sm">
                      <span className="min-w-0 flex-1 truncate">
                        {line.name}
                        {line.variant_name ? ` · ${line.variant_name}` : ""}
                        <span className="text-ink-faint"> (أُرسل {formatNumber(line.quantity)})</span>
                      </span>
                      <input
                        type="number"
                        min={0}
                        max={line.quantity}
                        aria-label={`الكمية المستلمة من ${line.name}`}
                        className={`${fieldClass} !mt-0 w-24`}
                        disabled={frozen}
                        value={received[line.id] ?? String(line.quantity)}
                        onChange={(event) => {
                          setReceived((current) => ({ ...current, [line.id]: event.target.value }));
                          setDirty(true);
                        }}
                      />
                    </li>
                  ))}
                </ul>
              )}
              {mode.phase === "resolve" && (
                <ul className="mt-3 space-y-2" aria-label="مصير الكميات المتبقية">
                  {mode.row.lines
                    .filter((line) => (line.residual ?? 0) > 0)
                    .map((line) => (
                      <li key={line.id} className="flex items-center gap-3 text-sm">
                        <span className="min-w-0 flex-1 truncate">
                          {line.name}
                          <span className="text-ink-faint"> · متبقٍ {formatNumber(line.residual ?? 0)}</span>
                        </span>
                        <select
                          aria-label={`مصير المتبقي من ${line.name}`}
                          className={`${fieldClass} !mt-0 w-44`}
                          disabled={frozen}
                          value={fate[line.id] ?? "late"}
                          onChange={(event) => {
                            setFate((current) => ({ ...current, [line.id]: event.target.value }));
                            setDirty(true);
                          }}
                        >
                          <option value="late">وصلت متأخرة</option>
                          <option value="return">تُعاد للمصدر</option>
                          <option value="loss">فاقد / تالف</option>
                        </select>
                      </li>
                    ))}
                </ul>
              )}
            </div>
          )}
          {mode.kind === "reverse" && (
            <div className="rounded-control border border-line p-3">
              <strong>{mode.row.number}</strong>
              <p>
                {mode.row.product_name} · {mode.row.variant_name}
              </p>
              <p className="mt-2">
                {formatNumber(mode.row.quantity)} قطعة · {stockMoney(mode.row.cost)}
              </p>
              <p className="mt-2 text-xs text-ink-soft">
                أكد أن التلف سُجل بالخطأ وأن القطع موجودة فعلياً. يُحفظ السند الأصلي وسند العكس معاً.
              </p>
            </div>
          )}
          <label className="block text-sm">
            السبب / الملاحظة
            <textarea
              required
              minLength={3}
              maxLength={1000}
              aria-label="سبب العملية المخزنية"
              className={fieldClass}
              rows={3}
              disabled={frozen}
              value={reason}
              onChange={(event) => change(setReason, event.target.value)}
            />
          </label>
          {save.error && (
            <p role="alert" className="rounded-control bg-danger-soft p-3 text-sm text-danger">
              {toFinoraError(save.error).message}
            </p>
          )}
        </form>
      </SidePanel>
      <ConfirmDialog
        open={active && discard}
        title="تعديلات غير محفوظة"
        message="إغلاق النموذج يلغي الإدخال الذي لم ترسله. الطلبات المرسلة محفوظة للمراجعة."
        confirmLabel="إغلاق النموذج"
        onClose={() => setDiscard(false)}
        onConfirm={() => {
          setDiscard(false);
          onClose();
        }}
      />
    </>
  );
}
