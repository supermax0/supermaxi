import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { PriceBatch, PriceRule, PriceRuleInput } from "@/api/finora/pricing";
import { useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { ProductSearch } from "../productLinks/ProductLinksWindow";
import { Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";

type Tab = "rules" | "bulk" | "promotions" | "history";
const SCOPE: Record<PriceRule["scope"], string> = {
  default: "كل المنتجات",
  category: "قسم",
  brand: "علامة",
  product: "منتج",
};
const VERDICT: Record<string, string> = {
  up: "ارتفاع",
  down: "انخفاض",
  same: "بلا تغيير",
  below_minimum: "أقل من الحد الآمن — لن يُطبَّق",
  unmatched: "غير مطابق",
  invalid: "قيمة غير صحيحة",
};
const fail = (e: unknown) => toast.error(toFinoraError(e).message);

/** Selling prices: margin rules, bulk changes previewed then approved, dated promotions, full history. */
export function PricingWindow() {
  const active = useWindowManager((s) => s.active === "pricing");
  const [tab, setTab] = useState<Tab>("rules");
  return (
    <div className="flex h-full min-h-0 flex-col p-5" dir="rtl">
      <p className="mb-3 text-[12.5px] text-ink-soft">
        يغيّر أسعار البيع فقط. لا يمس كلفة الشراء المسجلة ولا قيمة المخزون ولا الفواتير السابقة، وكل تغيير
        يُسجَّل.
      </p>
      <div
        role="tablist"
        aria-label="أقسام التسعير"
        className="mb-4 flex gap-1 rounded-control bg-white/70 p-1 shadow-control"
      >
        {(
          [
            ["rules", "قواعد الهامش"],
            ["bulk", "تحديث جماعي"],
            ["promotions", "العروض"],
            ["history", "سجل الأسعار"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              "h-9 rounded-[11px] px-4 text-[13.5px] font-medium",
              tab === id ? "bg-violet-soft text-violet-deep" : "text-ink-soft hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "rules" && <RulesTab enabled={active} />}
        {tab === "bulk" && <BulkTab />}
        {tab === "promotions" && <PromotionsTab enabled={active} />}
        {tab === "history" && <HistoryTab enabled={active} />}
      </div>
    </div>
  );
}

const EMPTY: PriceRuleInput = {
  scope: "default",
  scope_value: "",
  target_margin_pct: 20,
  minimum_margin_pct: 8,
  extra_cost: 0,
  rounding_step: 1000,
  automatic: false,
  max_auto_change_pct: 10,
  approval_required: true,
  active: true,
};

function RulesTab({ enabled }: { enabled: boolean }) {
  const client = useQueryClient();
  const rules = useQuery({ queryKey: ["pricing", "rules"], queryFn: () => finora.pricing.rules(), enabled });
  const [editing, setEditing] = useState<{ id: number | null; form: PriceRuleInput } | null>(null);
  const save = useMutation({
    mutationFn: () => finora.pricing.saveRule(editing?.id ?? null, editing?.form ?? EMPTY),
    onSuccess: async () => {
      toast.success("حُفظت القاعدة");
      setEditing(null);
      await client.invalidateQueries({ queryKey: ["pricing"] });
    },
    onError: fail,
  });
  const f = editing?.form;
  const set = (patch: Partial<PriceRuleInput>) =>
    editing && setEditing({ ...editing, form: { ...editing.form, ...patch } });
  return (
    <div className="space-y-3">
      {rules.error && <p className="text-sm text-danger">{toFinoraError(rules.error).message}</p>}
      <ul className="space-y-1.5">
        {(rules.data?.rows ?? []).map((r) => (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => setEditing({ id: r.id, form: { ...r } })}
              className="flex w-full justify-between gap-2 rounded-panel bg-white/85 p-3 text-start ring-1 ring-line/60"
            >
              <span>
                {SCOPE[r.scope]}
                {r.scope_value ? `: ${r.scope_value}` : ""} — هامش {r.target_margin_pct}% (الأدنى{" "}
                {r.minimum_margin_pct}%)
              </span>
              <span className="text-[12px] text-ink-faint">
                {r.automatic ? `تلقائي حتى ${r.max_auto_change_pct}%` : "بالموافقة"}
                {r.active ? "" : " · متوقفة"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {!f && (
        <button
          type="button"
          className={supplierPrimary}
          onClick={() => setEditing({ id: null, form: { ...EMPTY } })}
        >
          قاعدة جديدة
        </button>
      )}
      {f && (
        <Panel title={editing?.id ? "تعديل قاعدة" : "قاعدة جديدة"}>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="grid gap-1 text-[12.5px]">
              النطاق
              <select
                className={supplierInput}
                value={f.scope}
                onChange={(e) => set({ scope: e.target.value as PriceRule["scope"] })}
              >
                {Object.entries(SCOPE).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            {f.scope !== "default" && (
              <label className="grid gap-1 text-[12.5px]">
                {f.scope === "product" ? "رقم المنتج" : SCOPE[f.scope]}
                <input
                  className={supplierInput}
                  value={f.scope_value}
                  onChange={(e) => set({ scope_value: e.target.value })}
                />
              </label>
            )}
            <label className="grid gap-1 text-[12.5px]">
              الهامش المستهدف %
              <input
                className={supplierInput}
                type="number"
                min={1}
                max={89}
                value={f.target_margin_pct}
                onChange={(e) => set({ target_margin_pct: Number(e.target.value) })}
              />
            </label>
            <label className="grid gap-1 text-[12.5px]">
              الهامش الأدنى % (الحد الآمن)
              <input
                className={supplierInput}
                type="number"
                min={0}
                value={f.minimum_margin_pct}
                onChange={(e) => set({ minimum_margin_pct: Number(e.target.value) })}
              />
            </label>
            <label className="grid gap-1 text-[12.5px]">
              مصاريف لكل قطعة (د.ع)
              <input
                className={supplierInput}
                type="number"
                min={0}
                value={f.extra_cost}
                onChange={(e) => set({ extra_cost: Number(e.target.value) })}
              />
            </label>
            <label className="grid gap-1 text-[12.5px]">
              التقريب
              <select
                className={supplierInput}
                value={f.rounding_step}
                onChange={(e) => set({ rounding_step: Number(e.target.value) })}
              >
                {[250, 500, 1000, 5000, 10000].map((s) => (
                  <option key={s} value={s}>
                    لأقرب {formatNumber(s)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-3 flex flex-wrap gap-4 text-[13px]">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={f.automatic}
                onChange={(e) => set({ automatic: e.target.checked })}
              />{" "}
              تحديث تلقائي
            </label>
            {f.automatic && (
              <>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={!f.approval_required}
                    onChange={(e) => set({ approval_required: !e.target.checked })}
                  />{" "}
                  بلا موافقة ضمن الحد
                </label>
                <label className="flex items-center gap-2">
                  أقصى تغيير تلقائي %{" "}
                  <input
                    className="h-9 w-20 rounded-control border border-line px-2"
                    type="number"
                    value={f.max_auto_change_pct}
                    onChange={(e) => set({ max_auto_change_pct: Number(e.target.value) })}
                  />
                </label>
              </>
            )}
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={f.active} onChange={(e) => set({ active: e.target.checked })} />{" "}
              فعّالة
            </label>
          </div>
          <p className="mt-2 text-[12px] text-ink-faint">
            سعر البيع = الكلفة ÷ (1 − الهامش)، ثم يُقرَّب للأعلى. مثال: كلفة 450,000 بهامش 20% ← 563,000.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className={supplierPrimary}
              disabled={save.isPending}
              onClick={() => save.mutate()}
            >
              حفظ
            </button>
            <button type="button" className={supplierSecondary} onClick={() => setEditing(null)}>
              إلغاء
            </button>
          </div>
        </Panel>
      )}
    </div>
  );
}

function BulkTab() {
  const client = useQueryClient();
  const canApprove = useSession((s) => s.session?.permissions.includes("pricing.approve") ?? false);
  const [batch, setBatch] = useState<PriceBatch | null>(null);
  const [supplier, setSupplier] = useState("");
  const show = (res: { batch: PriceBatch }) => setBatch(res.batch);
  const fromRules = useMutation({
    mutationFn: () => finora.pricing.fromRules(),
    onSuccess: show,
    onError: fail,
  });
  const fromFile = useMutation({
    mutationFn: async (file: File) => {
      const ext = file.name.toLowerCase().endsWith(".xlsx") ? "xlsx" : "csv";
      return finora.pricing.fromFile(
        {
          name: file.name,
          type:
            ext === "xlsx" ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "text/csv",
          data: new Uint8Array(await file.arrayBuffer()),
        },
        supplier,
      );
    },
    onSuccess: show,
    onError: fail,
  });
  const approve = useMutation({
    mutationFn: () => finora.pricing.approve((batch as PriceBatch).id),
    onSuccess: async (res) => {
      toast.success(
        `طُبّق ${res.result.applied} · تغيّر سعره منذ المعاينة ${res.result.stale} · تُرك ${res.result.skipped}`,
      );
      setBatch({ ...(batch as PriceBatch), status: "applied" });
      await client.invalidateQueries({ queryKey: ["pricing"] });
    },
    onError: fail,
  });
  const reject = useMutation({
    mutationFn: () => finora.pricing.reject((batch as PriceBatch).id),
    onSuccess: () => setBatch(null),
    onError: fail,
  });
  return (
    <div className="space-y-4">
      <Panel title="مصدر الاقتراحات">
        <div className="flex flex-wrap items-end gap-3">
          <button
            type="button"
            className={supplierPrimary}
            disabled={fromRules.isPending}
            onClick={() => fromRules.mutate()}
          >
            اقترح من قواعد الهامش
          </button>
          <label className="grid gap-1 text-[12.5px]">
            اسم المورد (لملف الكلف)
            <input className={supplierInput} value={supplier} onChange={(e) => setSupplier(e.target.value)} />
          </label>
          <label className={`${supplierSecondary} inline-flex cursor-pointer`}>
            رفع ملف أسعار أو كلف (Excel / CSV)
            <input
              type="file"
              accept=".xlsx,.csv"
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) fromFile.mutate(f);
              }}
            />
          </label>
        </div>
        <p className="mt-2 text-[12px] text-ink-faint">
          أعمدة الملف: الباركود أو الموديل، مع «سعر البيع» أو «سعر الشراء/الكلفة». لا يُطبَّق شيء قبل
          الموافقة.
        </p>
      </Panel>
      {batch && (
        <Panel title={`معاينة: ${batch.label}`}>
          <div className="mb-3 flex flex-wrap gap-2 text-[12.5px]">
            {Object.entries(batch.counts).map(([k, n]) => (
              <span key={k} className="rounded-full bg-white px-3 py-1 ring-1 ring-line/60">
                {VERDICT[k] ?? k}: {n}
              </span>
            ))}
            <span className="rounded-full bg-white px-3 py-1 ring-1 ring-line/60">
              صافي التغيير للقطعة: {formatNumber(batch.net_change_per_unit)} د.ع
            </span>
          </div>
          <div className="max-h-[360px] overflow-auto rounded-lg ring-1 ring-line/60">
            <table className="w-full text-[12.5px]">
              <thead className="sticky top-0 bg-white">
                <tr>
                  <th className="p-2 text-start">المنتج</th>
                  <th className="p-2 text-start">الحالي</th>
                  <th className="p-2 text-start">المقترح</th>
                  <th className="p-2 text-start">الحد الآمن</th>
                  <th className="p-2 text-start">الحكم</th>
                </tr>
              </thead>
              <tbody>
                {batch.rows.map((r) => (
                  <tr key={r.id} className="border-t border-line/50">
                    <td className="p-2">{r.name || r.ref}</td>
                    <td className="p-2">{r.old_price == null ? "—" : formatNumber(r.old_price)}</td>
                    <td className="p-2">{r.new_price == null ? "—" : formatNumber(r.new_price)}</td>
                    <td className="p-2">{r.minimum_price == null ? "—" : formatNumber(r.minimum_price)}</td>
                    <td
                      className={cn(
                        "p-2",
                        r.verdict === "below_minimum" || r.verdict === "invalid" ? "text-danger" : "",
                      )}
                    >
                      {VERDICT[r.verdict]}
                      {r.applied ? " · طُبّق" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {batch.status === "draft" ? (
            canApprove ? (
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  className={supplierPrimary}
                  disabled={approve.isPending}
                  onClick={() => approve.mutate()}
                >
                  اعتماد وتطبيق
                </button>
                <button
                  type="button"
                  className={supplierSecondary}
                  disabled={reject.isPending}
                  onClick={() => reject.mutate()}
                >
                  رفض
                </button>
              </div>
            ) : (
              <p className="mt-3 text-[13px] text-ink-soft">
                الدفعة محفوظة كمسودة؛ يعتمدها من يملك صلاحية «اعتماد تغييرات الأسعار».
              </p>
            )
          ) : (
            <p className="mt-3 text-[13px] text-ink-soft">
              {batch.status === "applied" ? "طُبّقت هذه الدفعة." : "رُفضت هذه الدفعة."}
            </p>
          )}
        </Panel>
      )}
    </div>
  );
}

function PromotionsTab({ enabled }: { enabled: boolean }) {
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["pricing", "promotions"],
    queryFn: () => finora.pricing.promotions(),
    enabled,
  });
  const [product, setProduct] = useState<{ id: number; name: string; price?: number } | null>(null);
  const [form, setForm] = useState({ promo_price: "", starts_at: "", ends_at: "" });
  const create = useMutation({
    mutationFn: () =>
      finora.pricing.createPromotion({
        product_id: product?.id ?? 0,
        promo_price: Number(form.promo_price),
        starts_at: new Date(form.starts_at).toISOString().slice(0, 19),
        ends_at: new Date(form.ends_at).toISOString().slice(0, 19),
      }),
    onSuccess: async () => {
      toast.success("أُنشئ العرض");
      setForm({ promo_price: "", starts_at: "", ends_at: "" });
      setProduct(null);
      await client.invalidateQueries({ queryKey: ["pricing"] });
    },
    onError: fail,
  });
  const cancel = useMutation({
    mutationFn: (id: number) => finora.pricing.cancelPromotion(id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["pricing"] }),
    onError: fail,
  });
  const STATUS: Record<string, string> = {
    scheduled: "مجدول",
    running: "جارٍ",
    ended: "انتهى",
    cancelled: "أُلغي",
    conflict: "تعارض: تغيّر السعر يدوياً أثناء العرض",
  };
  return (
    <div className="space-y-4">
      <Panel title="عرض جديد بتاريخ">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="grid gap-1 text-[12.5px]">
            المنتج
            <ProductSearch label="المنتج" value={product} onPick={setProduct} />
            {product?.price ? (
              <span className="text-ink-faint">السعر الحالي: {formatNumber(product.price)} د.ع</span>
            ) : null}
          </div>
          <label className="grid gap-1 text-[12.5px]">
            سعر العرض
            <input
              className={supplierInput}
              inputMode="numeric"
              value={form.promo_price}
              onChange={(e) => setForm({ ...form, promo_price: e.target.value.replace(/\D/g, "") })}
            />
          </label>
          <label className="grid gap-1 text-[12.5px]">
            يبدأ
            <input
              className={supplierInput}
              type="datetime-local"
              value={form.starts_at}
              onChange={(e) => setForm({ ...form, starts_at: e.target.value })}
            />
          </label>
          <label className="grid gap-1 text-[12.5px]">
            ينتهي
            <input
              className={supplierInput}
              type="datetime-local"
              value={form.ends_at}
              onChange={(e) => setForm({ ...form, ends_at: e.target.value })}
            />
          </label>
        </div>
        <p className="mt-2 text-[12px] text-ink-faint">
          يجب أن يكون أقل من السعر الحالي وفوق الحد الآمن. عند البدء يظهر السعر الأصلي مشطوباً (خصم حقيقي)،
          وعند الانتهاء يعود السعر الأصلي.
        </p>
        <button
          type="button"
          className={`${supplierPrimary} mt-3`}
          disabled={create.isPending || !product || !form.promo_price || !form.starts_at || !form.ends_at}
          onClick={() => create.mutate()}
        >
          إنشاء العرض
        </button>
      </Panel>
      <ul className="space-y-1.5 text-[13px]">
        {(list.data?.rows ?? []).map((p) => (
          <li
            key={p.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-panel bg-white/85 p-3 ring-1 ring-line/60"
          >
            <span>
              {p.product_name || `منتج #${p.product_id}`} — {formatNumber(p.promo_price)} د.ع
              {p.regular_price ? ` (بدل ${formatNumber(p.regular_price)})` : ""}
            </span>
            <span className="text-ink-faint">
              {p.starts_at.slice(0, 16).replace("T", " ")} ← {p.ends_at.slice(0, 16).replace("T", " ")} ·{" "}
              {STATUS[p.status]}
            </span>
            {(p.status === "scheduled" || p.status === "running") && (
              <button type="button" className={supplierSecondary} onClick={() => cancel.mutate(p.id)}>
                إلغاء
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function HistoryTab({ enabled }: { enabled: boolean }) {
  const rows = useQuery({
    queryKey: ["pricing", "history"],
    queryFn: () => finora.pricing.history(),
    enabled,
  });
  const SOURCE: Record<string, string> = {
    batch: "دفعة معتمدة",
    auto_rule: "قاعدة تلقائية",
    promotion_start: "بداية عرض",
    promotion_end: "نهاية عرض",
    manual: "يدوي",
  };
  return (
    <Panel title="آخر تغييرات الأسعار">
      <ul className="space-y-1.5 text-[13px]">
        {(rows.data?.rows ?? []).map((h) => (
          <li key={h.id} className="flex flex-wrap justify-between gap-2 border-b border-line/50 pb-1.5">
            <span>
              {h.product_name || `منتج #${h.product_id}`}: {formatNumber(h.old_price)} ←{" "}
              {formatNumber(h.new_price)}{" "}
              <span className="text-ink-faint">
                ({SOURCE[h.source] ?? h.source}
                {h.reason ? ` — ${h.reason}` : ""})
              </span>
            </span>
            <span className="text-ink-faint">{h.at.slice(0, 16).replace("T", " ")}</span>
          </li>
        ))}
        {rows.data && rows.data.rows.length === 0 && <li className="text-ink-faint">لا تغييرات بعد</li>}
      </ul>
    </Panel>
  );
}
