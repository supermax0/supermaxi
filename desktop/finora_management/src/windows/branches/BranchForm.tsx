import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Loader2 } from "lucide-react";
import { useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { Branch, BranchInput } from "@/api/finora/branches";
import { Field } from "@/components/FilterPanel";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import {
  SupplierModal,
  supplierInput,
  supplierPrimary,
  supplierSecondary,
} from "../suppliers/SupplierDialogs";

/** Create / edit a branch. A new branch starts empty: no stock, no balance, no movements. */
export function BranchForm({
  branch,
  types,
  onClose,
  onSaved,
}: {
  branch: Branch | null;
  types: Array<{ id: string; label: string }>;
  onClose(): void;
  onSaved(branch: Branch): void;
}) {
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const [form, setForm] = useState<Required<Omit<BranchInput, "is_default">> & { is_default: boolean }>({
    code: branch?.code ?? "",
    name: branch?.name ?? "",
    branch_type: branch?.branch_type ?? "sales",
    governorate: branch?.governorate ?? "",
    city: branch?.city ?? "",
    address: branch?.address ?? "",
    phone: branch?.phone ?? "",
    email: branch?.email ?? "",
    manager_name: branch?.manager_name ?? "",
    opened_on: branch?.opened_on ?? "",
    is_default: branch?.is_default ?? false,
  });
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));
  const save = useMutation({
    mutationFn: () => {
      const { is_default, ...rest } = form;
      const input: BranchInput = {
        ...rest,
        ...(branch && is_default && !branch.is_default ? { is_default } : {}),
      };
      return branch ? finora.branches.update(branch.id, input) : finora.branches.create(input);
    },
    onSuccess: async (res) => {
      toast.success(
        branch ? "حُفظت بيانات الفرع" : `أُضيف الفرع ${res.branch.name} فارغاً — بدون حركات أو أرصدة`,
      );
      await client.invalidateQueries({ queryKey: ["branches"] });
      onSaved(res.branch);
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });
  const valid = form.code.trim() !== "" && form.name.trim() !== "";

  return (
    <SupplierModal
      title={branch ? `تعديل الفرع ${branch.name}` : "فرع جديد"}
      icon={Building2}
      busy={save.isPending}
      onClose={onClose}
      wide
    >
      <form
        className="grid grid-cols-2 gap-x-5 gap-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && online && !save.isPending) save.mutate();
        }}
      >
        <Field label="اسم الفرع">
          <input
            data-autofocus
            className={supplierInput}
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </Field>
        <Field label="كود الفرع (فريد)">
          <input
            dir="ltr"
            className={supplierInput}
            value={form.code}
            onChange={(e) => set({ code: e.target.value.toUpperCase() })}
            placeholder="KRD"
          />
        </Field>
        <Field label="نوع الفرع">
          <select
            className={supplierInput}
            value={form.branch_type}
            onChange={(e) => set({ branch_type: e.target.value })}
          >
            {types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="مدير الفرع">
          <input
            className={supplierInput}
            value={form.manager_name}
            onChange={(e) => set({ manager_name: e.target.value })}
          />
        </Field>
        <Field label="المحافظة">
          <input
            className={supplierInput}
            value={form.governorate}
            onChange={(e) => set({ governorate: e.target.value })}
          />
        </Field>
        <Field label="المدينة / المنطقة">
          <input
            className={supplierInput}
            value={form.city}
            onChange={(e) => set({ city: e.target.value })}
          />
        </Field>
        <Field label="العنوان" wide>
          <input
            className={supplierInput}
            value={form.address}
            onChange={(e) => set({ address: e.target.value })}
          />
        </Field>
        <Field label="الهاتف">
          <input
            dir="ltr"
            className={supplierInput}
            value={form.phone}
            onChange={(e) => set({ phone: e.target.value })}
          />
        </Field>
        <Field label="البريد الإلكتروني">
          <input
            dir="ltr"
            className={supplierInput}
            value={form.email}
            onChange={(e) => set({ email: e.target.value })}
          />
        </Field>
        <Field label="تاريخ بدء التشغيل">
          <input
            type="date"
            dir="ltr"
            className={supplierInput}
            value={form.opened_on}
            onChange={(e) => set({ opened_on: e.target.value })}
          />
        </Field>
        {branch && !branch.is_default && branch.is_active ? (
          <label className="mt-7 flex items-center gap-2 text-[13px] text-ink-soft">
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(e) => set({ is_default: e.target.checked })}
            />
            جعله الفرع الأساسي للشركة
          </label>
        ) : (
          <span />
        )}
        {!branch && (
          <p className="col-span-2 rounded-control bg-violet-soft/60 p-3 text-[12px] leading-5 text-ink-soft">
            يُنشأ الفرع فارغاً مع صندوق نقدي برصيد صفر. لا يؤثر على أرباح الشركة أو أرصدتها. لنقل بضاعة أو
            أموال إليه استخدم التحويلات الرسمية.
          </p>
        )}
        <div className="col-span-2 flex justify-end gap-2">
          <button type="button" className={supplierSecondary} onClick={onClose}>
            إلغاء
          </button>
          <button type="submit" className={supplierPrimary} disabled={!valid || !online || save.isPending}>
            {save.isPending && <Loader2 size={16} className="animate-spin" />}
            {branch ? "حفظ التعديلات" : "إنشاء الفرع"}
          </button>
        </div>
      </form>
    </SupplierModal>
  );
}
