import { useTimeFormat } from "@/stores/displayTime";
import { formatDateTime } from "@/utils/format";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { CatalogEntryInput } from "@/api/finora/catalog";
import { useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { cn } from "@/utils/cn";
import { Panel } from "../shipping/shared";
import { supplierInput, supplierPrimary, supplierSecondary } from "../suppliers/SupplierDialogs";
import { EntryEditor } from "./EntryEditor";
import { ImportTab } from "./ImportTab";
import { SmartAdd } from "./SmartAdd";

type Tab = "entries" | "smart" | "import" | "requests";

/** Master catalogue: models, photos and specs — separate from stock. Nothing here creates quantities or prices. */
export function CatalogWindow() {
  useTimeFormat();
  const active = useWindowManager((s) => s.active === "catalog");
  const isAdmin = useSession((s) => s.session?.user.role === "admin");
  const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("entries");
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [prefill, setPrefill] = useState<Partial<CatalogEntryInput> | null>(null);

  const settings = useQuery({
    queryKey: ["catalog", "settings"],
    queryFn: () => finora.catalog.settings(),
    enabled: active && isAdmin,
    retry: false,
  });
  const enable = useMutation({
    mutationFn: () => finora.catalog.saveSettings({ catalog_layer: true }),
    onSuccess: async () => {
      toast.success("فُعّل الكتالوج الرئيسي لهذه الشركة");
      await client.invalidateQueries({ queryKey: ["catalog"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const disabled = isAdmin && settings.data && !settings.data.catalog_layer;
  const openEditor = (id: number | "new", data: Partial<CatalogEntryInput> | null = null) => {
    setPrefill(data);
    setEditing(id);
    setTab("entries");
  };

  return (
    <div className="flex h-full min-h-0 flex-col p-5" dir="rtl">
      {disabled && (
        <Panel title="الكتالوج الرئيسي غير مفعّل">
          <p className="mb-3 text-[13px] text-ink-soft">
            الكتالوج يحفظ موديلات الأجهزة ومواصفاتها وصورها منفصلة عن المخزون: لا ينشئ كميات ولا أسعاراً، ولا
            يظهر في نقطة البيع. يمكن نشر موديل في المتجر «بطلب التوفير» قبل شرائه.
          </p>
          <button
            type="button"
            className={supplierPrimary}
            disabled={enable.isPending}
            onClick={() => enable.mutate()}
          >
            تفعيل الكتالوج لهذه الشركة
          </button>
        </Panel>
      )}
      {!disabled && (
        <>
          <div
            role="tablist"
            aria-label="أقسام الكتالوج"
            className="mb-4 flex gap-1 rounded-control bg-white/70 p-1 shadow-control"
          >
            {(
              [
                ["entries", "الموديلات"],
                ["smart", "إضافة ذكية"],
                ["import", "استيراد ملف"],
                ["requests", "طلبات التوفير"],
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
            {tab === "entries" &&
              (editing !== null ? (
                <EntryEditor
                  id={editing === "new" ? null : editing}
                  prefill={prefill}
                  onClose={() => setEditing(null)}
                  onSaved={(id) => setEditing(id)}
                />
              ) : (
                <EntriesList
                  enabled={active}
                  onOpen={(id) => openEditor(id)}
                  onNew={() => openEditor("new")}
                />
              ))}
            {tab === "smart" && (
              <SmartAdd onCreate={(data) => openEditor("new", data)} onOpen={(id) => openEditor(id)} />
            )}
            {tab === "import" && <ImportTab onOpen={(id) => openEditor(id)} />}
            {tab === "requests" && <RequestsTab enabled={active} />}
          </div>
        </>
      )}
    </div>
  );
}

function EntriesList({
  enabled,
  onOpen,
  onNew,
}: {
  enabled: boolean;
  onOpen(id: number): void;
  onNew(): void;
}) {
  useTimeFormat();
  const [q, setQ] = useState("");
  const list = useQuery({
    queryKey: ["catalog", "entries", q],
    queryFn: () => finora.catalog.list(q),
    enabled,
  });
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input
          aria-label="بحث في الكتالوج"
          className={supplierInput}
          placeholder="اسم، علامة، موديل أو باركود"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button type="button" className={supplierPrimary} onClick={onNew}>
          موديل جديد
        </button>
      </div>
      {list.error && <p className="text-sm text-danger">{toFinoraError(list.error).message}</p>}
      <ul className="space-y-1.5">
        {(list.data?.rows ?? []).map((e) => (
          <li key={e.id}>
            <button
              type="button"
              onClick={() => onOpen(e.id)}
              className="flex w-full items-center justify-between gap-3 rounded-panel bg-white/85 p-3 text-start ring-1 ring-line/60"
            >
              <span className="min-w-0">
                <strong className="block truncate text-[14px]">{e.canonical_name}</strong>
                <span className="text-[12px] text-ink-faint" dir="ltr">
                  {[e.brand, e.model_number].filter(Boolean).join(" · ")}
                </span>
              </span>
              <span className="shrink-0 text-[12px]">
                {e.listing?.is_published
                  ? "منشور"
                  : (({ needs_review: "يحتاج مراجعة", verified: "موثّق" } as Record<string, string>)[
                      e.verification_status
                    ] ?? e.verification_status)}
                {e.listing?.inventory_product_id ? " · في المخزون" : ""}
              </span>
            </button>
          </li>
        ))}
        {list.data && list.data.rows.length === 0 && (
          <li className="text-sm text-ink-faint">لا موديلات بعد</li>
        )}
      </ul>
      {list.data && list.data.total > list.data.rows.length && (
        <p className="text-[12px] text-ink-faint">
          يُعرض أحدث {list.data.rows.length} من {list.data.total} — ابحث لتضييق النتائج.
        </p>
      )}
    </div>
  );
}

function RequestsTab({ enabled }: { enabled: boolean }) {
  useTimeFormat();
  const rows = useQuery({
    queryKey: ["catalog", "requests"],
    queryFn: () => finora.catalog.requests(),
    enabled,
  });
  return (
    <Panel title="طلبات توفير من الزبائن">
      <p className="mb-2 text-[12.5px] text-ink-soft">
        ليست طلبات شراء: زبون طلب موديلاً غير متوفر ليُتصل به بالسعر والموعد.
      </p>
      <ul className="space-y-1.5 text-[13px]">
        {(rows.data?.rows ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap justify-between gap-2 border-b border-line/50 pb-1.5">
            <span>
              <strong>{r.product}</strong> — {r.customer_name} <span dir="ltr">{r.phone}</span>
              {r.city ? ` · ${r.city}` : ""}
            </span>
            <span className="text-ink-faint">{formatDateTime(r.created_at)}</span>
            {r.note && <span className="w-full text-ink-soft">{r.note}</span>}
          </li>
        ))}
        {rows.data && rows.data.rows.length === 0 && <li className="text-ink-faint">لا طلبات بعد</li>}
      </ul>
      <button type="button" className={cn(supplierSecondary, "mt-3")} onClick={() => void rows.refetch()}>
        تحديث
      </button>
    </Panel>
  );
}
