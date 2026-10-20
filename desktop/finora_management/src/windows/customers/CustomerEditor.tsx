import { useAssistantDraftFields } from "@/features/assistant/draftQueue";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { CustomerFields, CustomerRow } from "@/api/finora/customers";
import { FeatureHelp } from "@/components/FeatureHelp";
import { SidePanel } from "@/components/SidePanel";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";

const input =
  "h-11 w-full rounded-control border border-line bg-white px-3 text-sm text-ink outline-none focus:border-violet/50 focus:ring-4 focus:ring-violet/10 disabled:opacity-60";
const fields: {
  key: keyof CustomerFields;
  label: string;
  limit: number;
  required?: boolean;
  phone?: boolean;
}[] = [
  { key: "name", label: "اسم العميل", limit: 150, required: true },
  { key: "phone", label: "رقم الهاتف", limit: 20, required: true, phone: true },
  { key: "phone2", label: "هاتف إضافي", limit: 20, phone: true },
  { key: "city", label: "المحافظة / المدينة", limit: 100 },
  { key: "address", label: "العنوان", limit: 255 },
];

export function CustomerEditor({
  row,
  onClose,
  onSaved,
}: {
  row?: CustomerRow;
  onClose(): void;
  onSaved(row: CustomerRow): void;
}) {
  const client = useQueryClient();
  const online = useConnection((state) => state.status === "online");
  const formId = useId();
  const [key] = useState(() => crypto.randomUUID());
  const [uncertain, setUncertain] = useState(false);
  const [data, setData] = useState<CustomerFields>(() => ({
    name: row?.name ?? "",
    phone: row?.phone ?? "",
    phone2: row?.phone2 ?? "",
    city: row?.city ?? "",
    address: row?.address ?? "",
    notes: row?.notes ?? "",
  }));
  useAssistantDraftFields("customer", !row, (fields) => {
    const { note, ...customer } = fields;
    setData((current) => ({
      ...current,
      ...customer,
      notes: typeof note === "string" ? note : current.notes,
    }));
  });
  const save = useMutation({
    mutationFn: () => finora.customers.save(data, key, row),
    onSuccess: (saved) => {
      void client.invalidateQueries({ queryKey: ["customers"] });
      void client.invalidateQueries({ queryKey: ["pos"] });
      toast.success(row ? "تم تعديل ملف العميل" : "تمت إضافة العميل");
      onSaved(saved);
    },
    onError: (error) => {
      const failure = toFinoraError(error);
      setUncertain(["network", "timeout", "server", "invalid_response"].includes(failure.kind));
    },
  });
  const locked = save.isPending || uncertain;
  return (
    <SidePanel
      open
      title={row ? "تعديل ملف العميل" : "إضافة عميل"}
      onClose={() => {
        if (!save.isPending) onClose();
      }}
      footer={
        <button
          type="submit"
          form={formId}
          disabled={save.isPending || !online}
          className="h-11 w-full rounded-control bg-gradient-to-l from-violet to-violet-deep px-5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {save.isPending ? "جارٍ الحفظ…" : uncertain ? "إعادة محاولة نفس الحفظ" : "حفظ العميل"}
        </button>
      }
    >
      <form
        id={formId}
        onSubmit={(event) => {
          event.preventDefault();
          if (online && !save.isPending) save.mutate();
        }}
        className="space-y-4"
      >
        <div className="flex items-center gap-2 rounded-control bg-violet-soft px-3 py-3 text-sm text-ink-soft">
          بيانات العميل
          <FeatureHelp text="تعديل الاسم أو الهاتف يحدّث ملف العميل؛ فواتيره ودفعاته تبقى محفوظة. الدين يتغيّر من الفواتير والتحصيل، وليس من هذا النموذج." />
        </div>
        {!online && (
          <p role="status" className="text-warning">
            يلزم الاتصال لحفظ ملف العميل.
          </p>
        )}
        {save.error && (
          <p role="alert" className="rounded-control bg-danger-soft p-3 text-sm text-danger">
            {toFinoraError(save.error).message}
            {uncertain &&
              " لم يتأكد وصول نتيجة الحفظ؛ أعد نفس المحاولة. بعد إعادة تشغيل البرنامج راجع طلبات الحفظ المحفوظة في صفحة العملاء."}
          </p>
        )}
        {fields.map((field) => (
          <label key={field.key} className="block">
            <span className="mb-2 block text-sm font-medium text-ink-soft">
              {field.label}
              {field.required && (
                <span aria-hidden="true" className="ms-1 text-danger">
                  *
                </span>
              )}
            </span>
            <input
              autoFocus={field.key === "name"}
              className={input}
              value={data[field.key]}
              disabled={locked}
              required={field.required}
              maxLength={field.limit}
              type={field.phone ? "tel" : "text"}
              inputMode={field.phone ? "numeric" : "text"}
              pattern={field.phone ? "[0-9]{7,20}" : undefined}
              onChange={(event) => setData({ ...data, [field.key]: event.target.value })}
            />
          </label>
        ))}
        <label className="block">
          <span className="mb-2 block text-sm font-medium text-ink-soft">ملاحظات</span>
          <textarea
            className={`${input} h-24 py-3`}
            maxLength={2000}
            disabled={locked}
            value={data.notes}
            onChange={(event) => setData({ ...data, notes: event.target.value })}
          />
        </label>
      </form>
    </SidePanel>
  );
}
