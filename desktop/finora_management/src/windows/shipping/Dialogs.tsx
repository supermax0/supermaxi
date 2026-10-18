import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, Loader2 } from "lucide-react";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { ShippingMeta } from "@/api/finora/shipping";
import { Field } from "@/components/FilterPanel";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import {
  SupplierModal,
  supplierInput,
  supplierPrimary,
  supplierSecondary,
} from "../suppliers/SupplierDialogs";

const today = () => new Date().toISOString().slice(0, 10);

export function NewSettlementDialog({
  carriers,
  agents = [],
  onClose,
  onCreated,
}: {
  carriers: ShippingMeta["carriers"];
  agents?: ShippingMeta["agents"];
  onClose(): void;
  onCreated(id: number): void;
}) {
  const [party, setParty] = useState<"carrier" | "agent">("carrier");
  const [agentId, setAgentId] = useState(agents[0] ? String(agents[0].id) : "");
  const [fromPortal, setFromPortal] = useState(true);
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const [carrierId, setCarrierId] = useState(carriers[0] ? String(carriers[0].id) : "");
  const [reference, setReference] = useState("");
  const [date, setDate] = useState(today());
  const create = useMutation({
    mutationFn: () =>
      finora.shipping.createSettlement(
        party === "agent"
          ? { agent_id: Number(agentId), from_portal: fromPortal, reference: reference.trim(), date }
          : { carrier_id: Number(carrierId), reference: reference.trim(), date },
      ),
    onSuccess: async (res) => {
      await client.invalidateQueries({ queryKey: ["shipping"] });
      toast.success(`أُنشئ الكشف ${res.manifest.number}`);
      onCreated(res.manifest.id);
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  return (
    <SupplierModal title="كشف تسوية جديد" icon={FilePlus2} busy={create.isPending} onClose={onClose}>
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if ((party === "agent" ? agentId : carrierId) && online) create.mutate();
        }}
      >
        <div
          className="flex gap-1 rounded-control bg-surface-sunken p-1"
          role="radiogroup"
          aria-label="جهة الكشف"
        >
          {(["carrier", "agent"] as const).map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={party === p}
              disabled={p === "agent" && agents.length === 0}
              onClick={() => setParty(p)}
              className={cn(
                "h-9 flex-1 rounded-[10px] text-[13px] font-medium",
                party === p ? "bg-white text-maroon shadow-control" : "text-ink-soft",
              )}
            >
              {p === "carrier" ? "شركة نقل" : "مندوب"}
            </button>
          ))}
        </div>
        {party === "agent" ? (
          <>
            <Field label="المندوب">
              <select className={supplierInput} value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </Field>
            <label className="flex items-center gap-2 text-[13px] text-ink-soft">
              <input type="checkbox" checked={fromPortal} onChange={(e) => setFromPortal(e.target.checked)} />
              استيراد ما أبلغ عنه المندوب في البوابة (يبقى تصنيفه للمقارنة)
            </label>
          </>
        ) : (
          <Field label="شركة النقل">
            <select
              className={supplierInput}
              value={carrierId}
              onChange={(e) => setCarrierId(e.target.value)}
            >
              {carriers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="grid grid-cols-2 gap-4">
          <Field label="رقم كشف الشركة (اختياري)">
            <input
              className={supplierInput}
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="مثل: 2026-1145"
            />
          </Field>
          <Field label="تاريخ الكشف">
            <input
              type="date"
              dir="ltr"
              className={supplierInput}
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </Field>
        </div>
        <p className="rounded-control bg-violet-soft/60 p-3 text-[12px] leading-5 text-ink-soft">
          يُنشأ الكشف كمسودة برقم تلقائي. أدخل الطلبات وصنّفها ثم اعتمده — لا يتغير أي طلب أو رصيد قبل
          الاعتماد.
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" className={supplierSecondary} onClick={onClose}>
            إلغاء
          </button>
          <button
            type="submit"
            className={supplierPrimary}
            disabled={!(party === "agent" ? agentId : carrierId) || !online || create.isPending}
          >
            {create.isPending && <Loader2 size={16} className="animate-spin" />} إنشاء وفتح الكشف
          </button>
        </div>
      </form>
    </SupplierModal>
  );
}
