import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Loader2, Wallet, X, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { finora, toFinoraError } from "@/api/finora";
import type { SupplierDetails, SupplierFields, SupplierRow } from "@/api/finora/suppliers";
import { Field } from "@/components/FilterPanel";
import { IconButton } from "@/components/IconButton";
import { MoneyInput } from "@/components/MoneyInput";
import { today } from "@/features/purchases/composer";
import { canMutate, useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { formatIqd } from "@/utils/money";
import { cn } from "@/utils/cn";

export const supplierInput =
  "h-11 w-full rounded-control border border-line bg-white/95 px-3 text-sm text-ink outline-none focus:border-violet/50 focus:ring-4 focus:ring-violet/10";
export const supplierPrimary =
  "inline-flex h-11 items-center justify-center gap-2 rounded-control bg-maroon px-5 text-sm font-semibold text-white shadow-control transition-colors hover:bg-maroon/90 disabled:opacity-45";
export const supplierSecondary =
  "inline-flex h-11 items-center justify-center gap-2 rounded-control border border-line bg-white/80 px-4 text-sm font-medium text-ink shadow-control hover:bg-violet-soft disabled:opacity-45";

export function SupplierModal({
  title,
  busy,
  onClose,
  children,
  wide = false,
  placement = "center",
  icon: Icon = Building2,
}: {
  title: string;
  icon?: LucideIcon;
  busy: boolean;
  onClose(): void;
  children: ReactNode;
  wide?: boolean;
  placement?: "center" | "right";
}) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const frame = requestAnimationFrame(() =>
      panel.current?.querySelector<HTMLInputElement>("input")?.focus(),
    );
    return () => {
      cancelAnimationFrame(frame);
      previous?.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const dialogs = document.querySelectorAll('[data-finora-modal="supplier"]');
      if (dialogs[dialogs.length - 1] !== panel.current) return;
      if (event.key === "Escape") {
        event.stopImmediatePropagation();
        event.preventDefault();
        if (!busy) close.current();
      } else if (event.key === "Tab") {
        const controls = panel.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)",
        );
        const first = controls?.[0];
        const last = controls?.[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [busy]);
  return createPortal(
    <div
      style={placement === "right" ? { direction: "ltr", justifyContent: "flex-end" } : undefined}
      className={cn(
        "no-drag fixed inset-0 z-[90] bg-ink/20 p-5",
        placement === "right" ? "flex flex-row-reverse items-stretch" : "grid place-items-center",
      )}
      onPointerDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={panel}
        data-finora-modal="supplier"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        dir="rtl"
        className={cn(
          "glass-solid max-h-[90vh] max-w-full overflow-y-auto rounded-panel p-6",
          placement === "right" ? "w-[680px]" : wide ? "w-[860px]" : "w-[500px]",
        )}
      >
        <header className="mb-5 flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-control bg-maroon-soft text-maroon">
            <Icon size={22} />
          </span>
          <h2 className="flex-1 text-lg font-bold text-ink">{title}</h2>
          <IconButton label="إغلاق النموذج" onClick={onClose} disabled={busy}>
            <X size={18} />
          </IconButton>
        </header>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function useRefreshSuppliers() {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["suppliers"] }),
      client.invalidateQueries({ queryKey: ["purchases"] }),
      client.invalidateQueries({ queryKey: ["reports"] }),
      client.invalidateQueries({ queryKey: ["pos", "bootstrap"] }),
    ]);
  };
}

export function SupplierEditor({
  supplier,
  onClose,
  onSaved,
}: {
  supplier?: SupplierRow;
  onClose(): void;
  onSaved(id: number): void;
}) {
  const [fields, setFields] = useState<SupplierFields>({
    name: supplier?.name ?? "",
    phone: supplier?.phone ?? "",
    phone2: supplier?.phone2 ?? "",
    address: supplier?.address ?? "",
    opening_balance: 0,
  });
  const online = useConnection((s) => s.status === "online");
  const refresh = useRefreshSuppliers();
  const save = useMutation({
    mutationFn: () => {
      if (!canMutate()) throw new Error("لا يمكن حفظ المورد بدون اتصال بـ FINORA.");
      const { opening_balance, ...contact } = fields;
      return finora.suppliers.save(supplier ? contact : { ...contact, opening_balance }, supplier?.id);
    },
    onSuccess: async (result) => {
      toast.success(result.message);
      await refresh();
      onSaved(result.id);
    },
  });
  const patch = (key: keyof SupplierFields, value: string | number) =>
    setFields((f) => ({ ...f, [key]: value }));
  return (
    <SupplierModal title={supplier ? "تعديل المورد" : "إضافة مورد"} busy={save.isPending} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!save.isPending && fields.name.trim()) save.mutate();
        }}
      >
        <fieldset disabled={save.isPending} className="grid grid-cols-2 gap-4 disabled:opacity-60">
          <Field label="اسم المورد" wide>
            <input
              required
              maxLength={150}
              value={fields.name}
              onChange={(e) => patch("name", e.target.value)}
              placeholder="اسم الشركة أو المورد"
              className={supplierInput}
            />
          </Field>
          <Field label="الهاتف">
            <input
              dir="ltr"
              type="tel"
              maxLength={50}
              value={fields.phone}
              onChange={(e) => patch("phone", e.target.value)}
              className={supplierInput}
            />
          </Field>
          <Field label="هاتف إضافي">
            <input
              dir="ltr"
              type="tel"
              maxLength={50}
              value={fields.phone2}
              onChange={(e) => patch("phone2", e.target.value)}
              className={supplierInput}
            />
          </Field>
          <Field label="العنوان" wide>
            <input
              maxLength={255}
              value={fields.address}
              onChange={(e) => patch("address", e.target.value)}
              placeholder="المحافظة، المنطقة، تفاصيل العنوان"
              className={supplierInput}
            />
          </Field>
          {!supplier && (
            <div className="col-span-2 rounded-control bg-violet-soft/60 p-4">
              <Field label="الرصيد الافتتاحي المستحق للمورد">
                <MoneyInput
                  label="الرصيد الافتتاحي"
                  value={fields.opening_balance ?? 0}
                  onChange={(v) => patch("opening_balance", v)}
                  className="h-11 w-full"
                />
              </Field>
              <p className="mt-2 text-xs leading-5 text-ink-soft">
                رصيد سابق بالدينار العراقي يُضاف إلى حساب المورد عند إنشائه.
              </p>
            </div>
          )}
        </fieldset>
        {save.error && (
          <p role="alert" className="mt-4 rounded-control bg-danger-soft p-3 text-sm text-danger">
            {toFinoraError(save.error).message}
          </p>
        )}
        <footer className="mt-6 flex justify-end gap-2 border-t border-line/70 pt-4">
          <button type="button" className={supplierSecondary} onClick={onClose} disabled={save.isPending}>
            إلغاء
          </button>
          <button
            type="submit"
            className={supplierPrimary}
            disabled={!online || !fields.name.trim() || save.isPending}
          >
            {save.isPending && <Loader2 size={16} className="animate-spin" />}حفظ المورد
          </button>
        </footer>
      </form>
    </SupplierModal>
  );
}

export function SupplierPaymentDialog({ details, onClose }: { details: SupplierDetails; onClose(): void }) {
  const { supplier, treasury_accounts: accounts } = details;
  const [amount, setAmount] = useState(0);
  const [account, setAccount] = useState(
    String((accounts.find((a) => a.is_default) ?? accounts[0])?.id ?? ""),
  );
  const [date, setDate] = useState(today());
  const [documentNumber, setDocumentNumber] = useState("");
  const [note, setNote] = useState("");
  const online = useConnection((s) => s.status === "online");
  const refresh = useRefreshSuppliers();
  const pay = useMutation({
    mutationFn: () => {
      if (!canMutate()) throw new Error("لا يمكن تسجيل دفعة بدون اتصال بـ FINORA.");
      return finora.suppliers.pay(supplier.id, {
        amount,
        treasury_account_id: Number(account),
        payment_date: date,
        document_number: documentNumber,
        note,
      });
    },
    onSuccess: async (result) => {
      toast.success(result.message);
      await refresh();
      onClose();
    },
  });
  const valid = amount > 0 && amount <= supplier.remaining && account !== "" && date !== "";
  return (
    <SupplierModal title="تسجيل دفعة للمورد" busy={pay.isPending} onClose={onClose}>
      <div className="mb-5 flex items-center gap-3 rounded-control bg-violet-soft/60 p-4">
        <Wallet className="text-violet" size={22} />
        <div className="flex-1">
          <p className="font-bold">{supplier.name}</p>
          <p className="mt-1 text-xs text-ink-soft">
            المستحق حالياً:{" "}
            <span className="ltr-isolate font-semibold">{formatIqd(Math.max(supplier.remaining, 0))}</span>
          </p>
        </div>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && !pay.isPending) pay.mutate();
        }}
      >
        <fieldset disabled={pay.isPending} className="grid grid-cols-2 gap-4 disabled:opacity-60">
          <div className="col-span-2">
            <Field label="مبلغ الدفعة (د.ع)">
              <MoneyInput
                label="مبلغ الدفعة"
                value={amount}
                onChange={setAmount}
                className="h-12 w-full text-lg"
              />
            </Field>
            <button
              type="button"
              className="mt-2 text-xs font-semibold text-violet-deep"
              onClick={() => setAmount(Math.max(supplier.remaining, 0))}
            >
              تسديد كامل المستحق
            </button>
            {amount > supplier.remaining && (
              <p className="mt-2 text-xs text-danger">المبلغ أكبر من المستحق للمورد.</p>
            )}
          </div>
          <Field label="حساب الدفع" wide>
            <select
              required
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              className={supplierInput}
            >
              <option value="" disabled>
                اختر الحساب
              </option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="تاريخ الدفعة">
            <input
              type="date"
              required
              dir="ltr"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className={supplierInput}
            />
          </Field>
          <Field label="رقم السند">
            <input
              maxLength={100}
              value={documentNumber}
              onChange={(e) => setDocumentNumber(e.target.value)}
              className={supplierInput}
            />
          </Field>
          <Field label="ملاحظات" wide>
            <textarea
              maxLength={255}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className={`${supplierInput} h-20 resize-none py-3`}
            />
          </Field>
        </fieldset>
        {accounts.length === 0 && (
          <p className="mt-3 text-sm text-warning">أضف حساب خزينة قبل تسجيل الدفعة.</p>
        )}
        {pay.error && (
          <p role="alert" className="mt-4 rounded-control bg-danger-soft p-3 text-sm text-danger">
            {toFinoraError(pay.error).message}
          </p>
        )}
        <footer className="mt-6 flex justify-end gap-2 border-t border-line/70 pt-4">
          <button type="button" className={supplierSecondary} onClick={onClose} disabled={pay.isPending}>
            إلغاء
          </button>
          <button type="submit" className={supplierPrimary} disabled={!online || !valid || pay.isPending}>
            {pay.isPending && <Loader2 size={16} className="animate-spin" />}تأكيد الدفعة
          </button>
        </footer>
      </form>
    </SupplierModal>
  );
}
