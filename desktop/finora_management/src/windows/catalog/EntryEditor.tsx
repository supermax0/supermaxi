import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { productImageUrl } from "@/api/finora/products";
import { CONFIG_QUERY_KEY } from "@/features/auth/LoginScreen";
import {
  VERIFICATION,
  type CatalogEntryInput,
  type CatalogFile,
  type Verification,
} from "@/api/finora/catalog";
import { toast } from "@/stores/toasts";
import { Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";

const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;

function toLines(attrs: Record<string, string>): string {
  return Object.entries(attrs)
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
}
function fromLines(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf(":");
    if (at > 0) {
      const key = line.slice(0, at).trim();
      const value = line.slice(at + 1).trim();
      if (key && value) out[key] = value;
    }
  }
  return out;
}

/** One catalogue model: data with its sources, photos, publication and the explicit activation into stock. */
export function EntryEditor({
  id,
  prefill,
  onClose,
  onSaved,
}: {
  id: number | null;
  prefill: Partial<CatalogEntryInput> | null;
  onClose(): void;
  onSaved(id: number): void;
}) {
  const client = useQueryClient();
  const config = useQuery({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: () => finora.config.get(),
    staleTime: Infinity,
  });
  const serverUrl = config.data?.serverUrl ?? null;
  const detail = useQuery({
    queryKey: ["catalog", "entry", id],
    queryFn: () => finora.catalog.get(id as number),
    enabled: id !== null,
  });
  const entry = detail.data?.entry;
  const [form, setForm] = useState({
    canonical_name: "",
    brand: "",
    model_number: "",
    regional_version: "",
    category: "",
    description: "",
    barcodes: "",
    attributes: "",
    verification_status: "needs_review" as Verification,
  });
  const [price, setPrice] = useState("");
  const [posVisible, setPosVisible] = useState(false);

  useEffect(() => {
    const source = entry ?? prefill;
    if (!source) return;
    setForm({
      canonical_name: source.canonical_name ?? "",
      brand: source.brand ?? "",
      model_number: source.model_number ?? "",
      regional_version: source.regional_version ?? "",
      category: source.category ?? "",
      description: source.description ?? "",
      barcodes: (source.barcodes ?? []).join(", "),
      attributes: toLines(source.attributes ?? {}),
      verification_status: (source.verification_status as Verification) ?? "needs_review",
    });
  }, [entry, prefill]);

  const refresh = async (saved?: number) => {
    await client.invalidateQueries({ queryKey: ["catalog"] });
    if (saved) onSaved(saved);
  };
  const fail = (e: unknown) => toast.error(toFinoraError(e).message);
  const save = useMutation({
    mutationFn: () =>
      finora.catalog.save(id, {
        canonical_name: form.canonical_name,
        brand: form.brand,
        model_number: form.model_number,
        regional_version: form.regional_version,
        category: form.category,
        description: form.description,
        barcodes: form.barcodes.split(/[,\s]+/).filter(Boolean),
        attributes: fromLines(form.attributes),
        verification_status: form.verification_status,
      }),
    onSuccess: async (res) => {
      toast.success("حُفظ الموديل");
      await refresh(res.entry.id);
    },
    onError: fail,
  });
  const publish = useMutation({
    mutationFn: (on: boolean) => finora.catalog.listing(id as number, { publish: on, policy: "request" }),
    onSuccess: async (_r, on) => {
      toast.success(on ? "نُشر في المتجر بطلب التوفير" : "أُوقف النشر");
      await refresh();
    },
    onError: fail,
  });
  const activate = useMutation({
    mutationFn: () => finora.catalog.activate(id as number, Number(price), posVisible),
    onSuccess: async (res) => {
      toast.success(`فُعّل في المخزون (منتج رقم ${res.product_id}) بكمية 0`);
      await refresh();
    },
    onError: fail,
  });
  const upload = useMutation({
    mutationFn: (file: CatalogFile) => finora.catalog.uploadImage(id as number, file),
    onSuccess: async () => {
      toast.success("أُضيفت الصورة");
      await refresh();
    },
    onError: fail,
  });
  const media = useMutation({
    mutationFn: (v: { mediaId: number; action: "verify" | "unverify" | "remove" }) =>
      finora.catalog.mediaAction(id as number, v.mediaId, v.action),
    onSuccess: () => refresh(),
    onError: fail,
  });

  const pickImage = async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    if (!(IMAGE_TYPES as readonly string[]).includes(file.type)) {
      toast.error("الصيغ المقبولة: PNG أو JPG أو WebP");
      return;
    }
    upload.mutate({
      name: file.name,
      type: file.type as CatalogFile["type"],
      data: new Uint8Array(await file.arrayBuffer()),
    });
  };
  const field = (key: keyof typeof form, label: string, props: Record<string, unknown> = {}) => (
    <label className="grid gap-1 text-[12.5px] text-ink-soft">
      {label}
      <input
        className={supplierInput}
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        {...props}
      />
      {entry?.field_sources[key] && (
        <span className="text-[11px] text-ink-faint">
          المصدر: {entry.field_sources[key].source} · ثقة {entry.field_sources[key].confidence}%
        </span>
      )}
    </label>
  );

  return (
    <div className="space-y-4">
      <button type="button" className={supplierSecondary} onClick={onClose}>
        → رجوع للقائمة
      </button>
      <Panel title={id ? "تعديل موديل" : "موديل جديد"}>
        <div className="grid gap-3 md:grid-cols-2">
          {field("canonical_name", "الاسم")}
          {field("brand", "العلامة")}
          {field("model_number", "رقم الموديل", { dir: "ltr" })}
          {field("regional_version", "النسخة الإقليمية (إن اختلفت)")}
          {field("category", "القسم")}
          {field("barcodes", "الباركودات (افصل بفاصلة)", { dir: "ltr" })}
        </div>
        <label className="mt-3 grid gap-1 text-[12.5px] text-ink-soft">
          المواصفات (سطر لكل «خاصية: قيمة»)
          <textarea
            className={supplierInput}
            rows={5}
            value={form.attributes}
            onChange={(e) => setForm({ ...form, attributes: e.target.value })}
          />
        </label>
        <label className="mt-3 grid gap-1 text-[12.5px] text-ink-soft">
          الوصف
          <textarea
            className={supplierInput}
            rows={3}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </label>
        <label className="mt-3 grid gap-1 text-[12.5px] text-ink-soft">
          حالة البيانات
          <select
            className={supplierInput}
            value={form.verification_status}
            onChange={(e) => setForm({ ...form, verification_status: e.target.value as Verification })}
          >
            {Object.entries(VERIFICATION)
              .filter(([k]) => k !== "published")
              .map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
          </select>
        </label>
        <p className="mt-2 text-[12px] text-ink-faint">لا يُنشر موديل في المتجر قبل أن تكون حالته «موثّق».</p>
        <button
          type="button"
          className={`${supplierPrimary} mt-3`}
          disabled={save.isPending || form.canonical_name.trim().length < 3}
          onClick={() => save.mutate()}
        >
          حفظ
        </button>
      </Panel>

      {entry && (
        <>
          <Panel title="الصور">
            <div className="flex flex-wrap gap-3">
              {entry.media.map((m) => (
                <figure key={m.id} className="w-32 text-[11.5px]">
                  <img
                    src={productImageUrl(m.url, serverUrl) ?? undefined}
                    alt=""
                    className="h-32 w-32 rounded-lg bg-white object-contain ring-1 ring-line/60"
                  />
                  <figcaption className="mt-1 flex flex-wrap gap-1">
                    <span>{m.verified ? "مؤكدة" : "غير مؤكدة"}</span>
                    <button
                      type="button"
                      className="text-violet-deep underline"
                      onClick={() =>
                        media.mutate({ mediaId: m.id, action: m.verified ? "unverify" : "verify" })
                      }
                    >
                      {m.verified ? "إلغاء التأكيد" : "تأكيد"}
                    </button>
                    {!m.verified && (
                      <button
                        type="button"
                        className="text-danger underline"
                        onClick={() => media.mutate({ mediaId: m.id, action: "remove" })}
                      >
                        حذف
                      </button>
                    )}
                  </figcaption>
                </figure>
              ))}
            </div>
            <label className={`${supplierSecondary} mt-3 inline-flex cursor-pointer`}>
              رفع صورة (صورك أو صور يحق لك استخدامها)
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="sr-only"
                onChange={(e) => void pickImage(e.target.files)}
              />
            </label>
          </Panel>

          <Panel title="النشر والمخزون">
            <p className="mb-2 text-[13px]">
              {entry.listing?.is_published ? "منشور في المتجر" : "غير منشور"}
              {entry.listing?.inventory_product_id
                ? ` · مربوط بمنتج المخزون رقم ${entry.listing.inventory_product_id}`
                : " · غير موجود في المخزون"}
            </p>
            <div className="flex flex-wrap gap-2">
              {!entry.listing?.inventory_product_id && (
                <button
                  type="button"
                  className={supplierSecondary}
                  disabled={publish.isPending}
                  onClick={() => publish.mutate(!entry.listing?.is_published)}
                >
                  {entry.listing?.is_published ? "إيقاف النشر" : "نشر بطلب التوفير"}
                </button>
              )}
            </div>
            {!entry.listing?.inventory_product_id && (
              <div className="mt-4 grid gap-2 rounded-panel bg-white/70 p-3 ring-1 ring-line/60 md:grid-cols-[1fr_auto_auto] md:items-end">
                <label className="grid gap-1 text-[12.5px] text-ink-soft">
                  سعر البيع لتفعيله في المخزون
                  <input
                    className={supplierInput}
                    inputMode="numeric"
                    value={price}
                    onChange={(e) => setPrice(e.target.value.replace(/\D/g, ""))}
                  />
                </label>
                <label className="flex items-center gap-2 text-[13px]">
                  <input
                    type="checkbox"
                    checked={posVisible}
                    onChange={(e) => setPosVisible(e.target.checked)}
                  />{" "}
                  يظهر للكاشير
                </label>
                <button
                  type="button"
                  className={supplierPrimary}
                  disabled={!Number(price) || activate.isPending}
                  onClick={() => activate.mutate()}
                >
                  تفعيل في المخزون
                </button>
                <p className="text-[12px] text-ink-faint md:col-span-3">
                  ينشئ منتجاً بكمية 0 فقط — الكمية تأتي من فواتير الشراء والتحويلات كأي منتج.
                </p>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
