import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type {
  Bundle,
  BundleInput,
  ProductRelation,
  RelationInput,
  RelationType,
} from "@/api/finora/recommendations";
import { RELATION_TYPES } from "@/api/finora/recommendations";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";

type Tab = "relations" | "bundles" | "preview";
type Picked = { id: number; name: string; price?: number } | null;

const TYPE_LABEL: Record<RelationType, string> = {
  accessory: "ملحق",
  compatible: "متوافق مع",
  upgrade: "ترقية",
  service: "خدمة",
};
const fail = (e: unknown) => toast.error(toFinoraError(e).message);

/** What the store suggests next to a product: staff-confirmed relations, bundles, and a preview of the shopper's view. */
export function ProductLinksWindow() {
  const active = useWindowManager((s) => s.active === "productLinks");
  const [tab, setTab] = useState<Tab>("relations");
  return (
    <div className="flex h-full min-h-0 flex-col p-5" dir="rtl">
      <p className="mb-3 text-[12.5px] text-ink-soft">
        المتجر لا يخمّن التوافق: «الملحقات المتوافقة» لا تظهر للزبون إلا إذا أكّدها موظف. الباقات تُحسب
        بالأسعار الحالية بلا خصم وهمي.
      </p>
      <div
        role="tablist"
        aria-label="أقسام التوصيات"
        className="mb-4 flex gap-1 rounded-control bg-white/70 p-1 shadow-control"
      >
        {(
          [
            ["relations", "علاقات المنتجات"],
            ["bundles", "الباقات"],
            ["preview", "ما يراه الزبون"],
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
        {tab === "relations" && <RelationsTab enabled={active} />}
        {tab === "bundles" && <BundlesTab enabled={active} />}
        {tab === "preview" && <PreviewTab />}
      </div>
    </div>
  );
}

/** Search a product by name, model or barcode and pick it. */
export function ProductSearch({
  label,
  value,
  onPick,
}: {
  label: string;
  value: Picked;
  onPick: (p: Picked) => void;
}) {
  const [text, setText] = useState("");
  const q = text.trim();
  const results = useQuery({
    queryKey: ["productLinks", "search", q],
    queryFn: () => finora.products.list({ page: 1, pageSize: 8, search: q }),
    enabled: q.length >= 2 && !value,
  });
  if (value) {
    return (
      <div className="flex items-center gap-2 text-[13px]">
        <span className="text-ink-faint">{label}:</span>
        <b className="truncate">{value.name}</b>
        <button type="button" className="text-violet-deep underline" onClick={() => onPick(null)}>
          تغيير
        </button>
      </div>
    );
  }
  return (
    <div className="relative">
      <input
        aria-label={label}
        placeholder={`${label} — اكتب الاسم أو الموديل`}
        className={cn(supplierInput, "w-full")}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {q.length >= 2 && results.data && results.data.rows.length > 0 && (
        <ul
          role="listbox"
          aria-label={`نتائج ${label}`}
          className="absolute z-10 mt-1 w-full rounded-control bg-white shadow-control ring-1 ring-line/60"
        >
          {results.data.rows.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                className="block w-full px-3 py-2 text-start text-[13px] hover:bg-violet-soft"
                onClick={() => {
                  onPick({ id: p.id, name: p.name, price: p.sale_price });
                  setText("");
                }}
              >
                {p.name}
                {p.sku ? <span className="text-ink-faint"> · {p.sku}</span> : null}
                <span className="text-ink-faint"> · {p.sale_price.toLocaleString("en-US")} د.ع</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const EMPTY_RELATION = { type: "accessory" as RelationType, note: "", priority: 50, verified: true };

function RelationsTab({ enabled }: { enabled: boolean }) {
  const client = useQueryClient();
  const [filter, setFilter] = useState<Picked>(null);
  const [source, setSource] = useState<Picked>(null);
  const [target, setTarget] = useState<Picked>(null);
  const [form, setForm] = useState(EMPTY_RELATION);
  const rows = useQuery({
    queryKey: ["productLinks", "relations", filter?.id ?? 0],
    queryFn: () => finora.recommendations.relations(filter?.id),
    enabled,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["productLinks", "relations"] });
  const save = useMutation({
    mutationFn: (input: RelationInput) => finora.recommendations.saveRelation(input),
    onSuccess: async () => {
      toast.success("حُفظت العلاقة");
      setTarget(null);
      setForm({ ...EMPTY_RELATION, type: form.type });
      await refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: number) => finora.recommendations.deleteRelation(id),
    onSuccess: async () => {
      toast.success("حُذفت العلاقة");
      await refresh();
    },
    onError: fail,
  });
  const toggle = (r: ProductRelation) =>
    save.mutate({
      source_product_id: r.source_product_id,
      target_product_id: r.target_product_id,
      relation_type: r.relation_type,
      compatibility_note: r.compatibility_note,
      priority: r.priority,
      verified: !r.verified,
    });
  return (
    <div className="space-y-4">
      <Panel title="إضافة علاقة">
        <div className="grid gap-3 md:grid-cols-2">
          <ProductSearch label="المنتج الأساسي" value={source} onPick={setSource} />
          <ProductSearch label="المنتج المقترح" value={target} onPick={setTarget} />
          <label className="flex items-center gap-2 text-[13px]">
            النوع
            <select
              aria-label="نوع العلاقة"
              className={cn(supplierInput, "w-36")}
              value={form.type}
              onChange={(e) => setForm({ ...form, type: e.target.value as RelationType })}
            >
              {RELATION_TYPES.map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABEL[t]}
                </option>
              ))}
            </select>
          </label>
          <input
            aria-label="ملاحظة التوافق"
            placeholder="ملاحظة التوافق (مثلاً: VESA 400)"
            className={cn(supplierInput, "w-full")}
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
          <label className="flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={form.verified}
              onChange={(e) => setForm({ ...form, verified: e.target.checked })}
            />
            تأكدت من التوافق (يظهر للزبون)
          </label>
          <button
            type="button"
            className={supplierPrimary}
            disabled={!source || !target || save.isPending}
            onClick={() =>
              source &&
              target &&
              save.mutate({
                source_product_id: source.id,
                target_product_id: target.id,
                relation_type: form.type,
                compatibility_note: form.note,
                priority: form.priority,
                verified: form.verified,
              })
            }
          >
            حفظ العلاقة
          </button>
        </div>
      </Panel>
      <Panel
        title="العلاقات المسجلة"
        actions={
          <div className="w-72">
            <ProductSearch label="تصفية بمنتج" value={filter} onPick={setFilter} />
          </div>
        }
      >
        {rows.error && <p className="text-sm text-danger">{toFinoraError(rows.error).message}</p>}
        <ul className="space-y-1.5">
          {(rows.data?.rows ?? []).map((r) => (
            <li
              key={r.id}
              className="flex flex-wrap items-center gap-2 rounded-panel bg-white/85 p-3 text-[13px] ring-1 ring-line/60"
            >
              <span className="flex-1">
                <b>{r.source_name}</b> ← {TYPE_LABEL[r.relation_type]}: <b>{r.target_name}</b>
                {r.compatibility_note ? (
                  <span className="text-ink-faint"> ({r.compatibility_note})</span>
                ) : null}
              </span>
              <span className={r.verified ? "text-success" : "text-warning"}>
                {r.verified ? "مؤكدة — تظهر للزبون" : "غير مؤكدة — مخفية"}
              </span>
              <button
                type="button"
                className={supplierSecondary}
                onClick={() => toggle(r)}
                disabled={save.isPending}
              >
                {r.verified ? "إلغاء التأكيد" : "تأكيد"}
              </button>
              <button
                type="button"
                className={supplierSecondary}
                aria-label={`حذف علاقة ${r.target_name}`}
                onClick={() => remove.mutate(r.id)}
                disabled={remove.isPending}
              >
                حذف
              </button>
            </li>
          ))}
          {rows.data && !rows.data.rows.length && (
            <li className="text-[13px] text-ink-faint">لا علاقات بعد.</li>
          )}
        </ul>
      </Panel>
    </div>
  );
}

function BundlesTab({ enabled }: { enabled: boolean }) {
  const client = useQueryClient();
  const bundles = useQuery({
    queryKey: ["productLinks", "bundles"],
    queryFn: () => finora.recommendations.bundles(),
    enabled,
  });
  const [editing, setEditing] = useState<{
    id: number | null;
    title: string;
    description: string;
    active: boolean;
    items: { id: number; name: string }[];
  } | null>(null);
  const save = useMutation({
    mutationFn: (b: NonNullable<typeof editing>) =>
      finora.recommendations.saveBundle(b.id, {
        title: b.title,
        description: b.description,
        active: b.active,
        product_ids: b.items.map((i) => i.id),
      } satisfies BundleInput),
    onSuccess: async () => {
      toast.success("حُفظت الباقة");
      setEditing(null);
      await client.invalidateQueries({ queryKey: ["productLinks", "bundles"] });
    },
    onError: fail,
  });
  const open = (b: Bundle | null) =>
    setEditing(
      b
        ? { id: b.id, title: b.title, description: b.description, active: b.active, items: b.products }
        : { id: null, title: "", description: "", active: true, items: [] },
    );
  return (
    <div className="space-y-4">
      {!editing && (
        <button type="button" className={supplierPrimary} onClick={() => open(null)}>
          باقة جديدة
        </button>
      )}
      {editing && (
        <Panel title={editing.id ? "تعديل الباقة" : "باقة جديدة"}>
          <div className="space-y-3">
            <input
              aria-label="عنوان الباقة"
              placeholder="عنوان الباقة (مثلاً: جهّز صالتك)"
              className={cn(supplierInput, "w-full")}
              value={editing.title}
              onChange={(e) => setEditing({ ...editing, title: e.target.value })}
            />
            <input
              aria-label="وصف الباقة"
              placeholder="وصف قصير (اختياري)"
              className={cn(supplierInput, "w-full")}
              value={editing.description}
              onChange={(e) => setEditing({ ...editing, description: e.target.value })}
            />
            <ul className="space-y-1 text-[13px]" aria-label="منتجات الباقة">
              {editing.items.map((i) => (
                <li key={i.id} className="flex items-center gap-2">
                  <span className="flex-1">{i.name}</span>
                  <button
                    type="button"
                    className="text-danger underline"
                    onClick={() =>
                      setEditing({ ...editing, items: editing.items.filter((x) => x.id !== i.id) })
                    }
                  >
                    إزالة
                  </button>
                </li>
              ))}
            </ul>
            {editing.items.length < 12 && (
              <ProductSearch
                label="أضف منتجاً للباقة"
                value={null}
                onPick={(p) =>
                  p &&
                  !editing.items.some((x) => x.id === p.id) &&
                  setEditing({ ...editing, items: [...editing.items, p] })
                }
              />
            )}
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={editing.active}
                onChange={(e) => setEditing({ ...editing, active: e.target.checked })}
              />
              مفعّلة في المتجر
            </label>
            <p className="text-[12px] text-ink-faint">من 2 إلى 12 منتجاً. السعر = مجموع الأسعار الحالية.</p>
            <div className="flex gap-2">
              <button
                type="button"
                className={supplierPrimary}
                disabled={save.isPending || editing.items.length < 2 || !editing.title.trim()}
                onClick={() => save.mutate(editing)}
              >
                حفظ الباقة
              </button>
              <button type="button" className={supplierSecondary} onClick={() => setEditing(null)}>
                إلغاء
              </button>
            </div>
          </div>
        </Panel>
      )}
      {bundles.error && <p className="text-sm text-danger">{toFinoraError(bundles.error).message}</p>}
      <ul className="space-y-1.5">
        {(bundles.data?.rows ?? []).map((b) => (
          <li key={b.id}>
            <button
              type="button"
              onClick={() => open(b)}
              className="flex w-full justify-between gap-2 rounded-panel bg-white/85 p-3 text-start text-[13px] ring-1 ring-line/60"
            >
              <span>
                <b>{b.title}</b> — {b.products.length} منتجات
              </span>
              <span className={b.active ? "text-success" : "text-ink-faint"}>
                {b.active ? "مفعّلة" : "متوقفة"}
              </span>
            </button>
          </li>
        ))}
        {bundles.data && !bundles.data.rows.length && (
          <li className="text-[13px] text-ink-faint">لا باقات بعد.</li>
        )}
      </ul>
    </div>
  );
}

function PreviewTab() {
  const [product, setProduct] = useState<Picked>(null);
  const preview = useQuery({
    queryKey: ["productLinks", "preview", product?.id ?? 0],
    queryFn: () => finora.recommendations.preview(product?.id ?? 0),
    enabled: !!product,
  });
  const d = preview.data;
  const name = (id: number) => d?.names[String(id)] ?? `#${id}`;
  const Section = ({ title, items }: { title: string; items: { id: number; extra?: string }[] }) => (
    <section>
      <h4 className="mb-1 text-[13px] font-bold">{title}</h4>
      {items.length ? (
        <ul className="mb-3 space-y-1 text-[13px]">
          {items.map((i) => (
            <li key={i.id}>
              {name(i.id)}
              {i.extra ? <span className="text-ink-faint"> — {i.extra}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-3 text-[12.5px] text-ink-faint">لا شيء — القسم لا يظهر للزبون.</p>
      )}
    </section>
  );
  return (
    <Panel title="معاينة صفحة المنتج كما يراها الزبون">
      <ProductSearch label="المنتج" value={product} onPick={setProduct} />
      {preview.error && <p className="mt-2 text-sm text-danger">{toFinoraError(preview.error).message}</p>}
      {d && (
        <div className="mt-4">
          <Section
            title="ملحقات متوافقة"
            items={d.accessories.map((a) => ({ id: a.id, extra: String(a.note ?? "") }))}
          />
          <Section title="يُشترى عادة معه" items={d.bought_together.map((id) => ({ id }))} />
          <Section
            title="خيار أفضل"
            items={d.upgrades.map((u) => ({ id: u.id, extra: (u.benefits ?? []).join("، ") }))}
          />
          <Section title="منتجات مشابهة" items={d.similar.map((id) => ({ id }))} />
        </div>
      )}
    </Panel>
  );
}
