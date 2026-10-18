import { useState } from "react";
import type { HRDetails } from "@/api/finora/hr";
import { useConnection } from "@/stores/connection";
import { MoneyInput } from "@/components/MoneyInput";
import { SupplierModal } from "../suppliers/SupplierDialogs";
import { hrInput, hrPrimary, hrSecondary, hrToday, useHRCommand } from "./shared";
import type { HRAction } from "./HRDialogs";

const kinds: Record<string, string> = {
  fixed: "مبلغ لكل فاتورة",
  sales: "نسبة من المبيعات",
  profit: "نسبة من الربح",
  product: "نسبة لمنتج محدد",
  target: "مكافأة تحقيق هدف شهري",
  tiered: "شرائح المبيعات الشهرية",
};

export function CommissionSettings({
  details,
  can,
  onAction,
}: {
  details: HRDetails;
  can(permission: string): boolean;
  onAction(action: HRAction): void;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <section className="space-y-3 rounded-panel border border-line/70 p-4">
      <h3 className="text-xs font-semibold">سياسات العمولات</h3>
      {details.commission_policies.map((p) => (
        <p key={p.id} className="flex justify-between text-xs">
          <span>{kinds[p.kind] ?? "سياسة سابقة"}</span>
          <span dir="ltr">{p.effective_from}</span>
        </p>
      ))}
      {!details.commission_policies.length && (
        <p className="text-xs text-ink-faint">لا توجد سياسة عمولة مسجلة</p>
      )}
      {can("hr.commission.manage") && (
        <div className="flex flex-wrap gap-2">
          <button className={hrSecondary} onClick={() => setEditing(true)}>
            إضافة سياسة
          </button>
          <button
            className={hrSecondary}
            onClick={() =>
              onAction({
                title: "ربط فاتورة بموظف المبيعات",
                action: "commission.assign",
                financial: true,
                payload: { person_id: details.person.id },
                fields: [
                  {
                    name: "invoice_id",
                    label: "رقم الفاتورة",
                    type: "number",
                    numeric: true,
                    required: true,
                  },
                ],
              })
            }
          >
            ربط فاتورة بيع
          </button>
        </div>
      )}
      {editing && <PolicyEditor personId={details.person.id} onClose={() => setEditing(false)} />}
    </section>
  );
}

function PolicyEditor({ personId, onClose }: { personId: number; onClose(): void }) {
  const [kind, setKind] = useState("fixed");
  const [effective, setEffective] = useState(hrToday());
  const [fixed, setFixed] = useState(0);
  const [target, setTarget] = useState(0);
  const [percent, setPercent] = useState("5");
  const [product, setProduct] = useState("");
  const [tiers, setTiers] = useState([{ up_to: 1000000, percent: "5" }]);
  const save = useHRCommand(onClose);
  const online = useConnection((s) => s.status === "online");
  return (
    <SupplierModal title="سياسة العمولة وتاريخ سريانها" onClose={onClose} busy={save.isPending}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({
            action: "commission.policy",
            payload: {
              person_id: personId,
              effective_from: effective,
              kind,
              fixed,
              target,
              basis_points: Math.round(Number(percent) * 100),
              ...(kind === "product" ? { product_id: Number(product) } : {}),
              ...(kind === "tiered"
                ? {
                    tiers: tiers.map((t) => ({
                      up_to: t.up_to,
                      basis_points: Math.round(Number(t.percent) * 100),
                    })),
                  }
                : {}),
            },
          });
        }}
      >
        <p className="rounded-control bg-violet-soft p-3 text-xs leading-6 text-ink-soft">
          تُحتسب العمولة عند استحقاق فاتورة البيع. المبيعات المتدرجة تُحتسب على الجزء الواقع داخل كل شريحة،
          ومكافأة الهدف مرة واحدة بالشهر. تغيير السياسة يحفظ تاريخ العمولات المعتمدة.
        </p>
        <label className="block space-y-1 text-xs">
          نوع العمولة
          <select className={hrInput} value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(kinds).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1 text-xs">
          يسري من
          <input
            className={hrInput}
            type="date"
            required
            value={effective}
            onChange={(e) => setEffective(e.target.value)}
          />
        </label>
        {["fixed", "target"].includes(kind) && (
          <label className="block space-y-1 text-xs">
            مبلغ العمولة أو المكافأة
            <MoneyInput label="مبلغ العمولة أو المكافأة" value={fixed} onChange={setFixed} />
          </label>
        )}
        {["sales", "profit", "product"].includes(kind) && (
          <label className="block space-y-1 text-xs">
            النسبة %
            <input
              className={hrInput}
              type="number"
              min="0"
              max="100"
              step="0.01"
              required
              value={percent}
              onChange={(e) => setPercent(e.target.value)}
            />
          </label>
        )}
        {kind === "product" && (
          <label className="block space-y-1 text-xs">
            رقم المنتج
            <input
              className={hrInput}
              type="number"
              min="1"
              required
              value={product}
              onChange={(e) => setProduct(e.target.value)}
            />
          </label>
        )}
        {kind === "target" && (
          <label className="block space-y-1 text-xs">
            هدف المبيعات بالشهر
            <MoneyInput label="هدف المبيعات بالشهر" value={target} onChange={setTarget} />
          </label>
        )}
        {kind === "tiered" && (
          <div className="space-y-2">
            {tiers.map((t, index) => (
              <div key={index} className="grid grid-cols-[1fr_90px_auto] gap-2">
                <label className="text-xs">
                  إلى إجمالي المبيعات
                  <MoneyInput
                    label="الحد الأعلى للشريحة"
                    value={t.up_to}
                    onChange={(v) =>
                      setTiers((old) => old.map((row, i) => (i === index ? { ...row, up_to: v } : row)))
                    }
                  />
                </label>
                <label className="text-xs">
                  النسبة %
                  <input
                    className={hrInput}
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    required
                    value={t.percent}
                    onChange={(e) =>
                      setTiers((old) =>
                        old.map((row, i) => (i === index ? { ...row, percent: e.target.value } : row)),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  className={hrSecondary + " mt-4"}
                  disabled={tiers.length === 1}
                  onClick={() => setTiers((old) => old.filter((_, i) => i !== index))}
                >
                  حذف
                </button>
              </div>
            ))}
            <button
              type="button"
              className={hrSecondary}
              disabled={tiers.length === 10}
              onClick={() =>
                setTiers((old) => [...old, { up_to: (old.at(-1)?.up_to ?? 0) + 1000000, percent: "5" }])
              }
            >
              إضافة شريحة
            </button>
            <p className="text-xs text-ink-faint">
              المبيعات التي تتجاوز آخر حد لا تحمل عمولة إضافية؛ أضف حداً يغطي خطتك.
            </p>
          </div>
        )}
        {!online && <p className="text-xs text-danger">اعتماد سياسة مالية يحتاج اتصالاً بالخادم.</p>}
        <button className={hrPrimary} disabled={!online || save.isPending}>
          حفظ السياسة
        </button>
      </form>
    </SupplierModal>
  );
}
