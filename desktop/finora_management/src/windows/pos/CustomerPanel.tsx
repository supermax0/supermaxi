import { useMutation } from "@tanstack/react-query";
import { MapPin, Phone, Save, UserPlus, UserRound, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { PosBootstrap } from "@/api/finora/pos";
import { IconButton } from "@/components/IconButton";
import { useCart } from "@/features/pos/cart";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";

const input =
  "h-11 w-full rounded-control border border-line bg-white/90 px-3.5 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-violet/45 focus:ring-4 focus:ring-violet/10";

interface CustomerPanelProps {
  bootstrap: PosBootstrap | undefined;
  adding: boolean;
  onAdding(adding: boolean): void;
}

function Label({ text, required }: { text: string; required?: boolean }) {
  return (
    <span className="mb-1.5 block text-[13px] font-medium text-ink-soft">
      {text}
      {required && <span className="ms-1 text-danger">*</span>}
    </span>
  );
}

/** Selected customer card, or FINORA's add-customer form (same validation as the web POS). */
export function CustomerPanel({ bootstrap, adding, onAdding }: CustomerPanelProps) {
  const customer = useCart((s) => s.customer);
  const setCustomer = useCart((s) => s.setCustomer);
  const [form, setForm] = useState({ name: "", phone: "", phone2: "", city: "", address: "" });
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => finora.pos.addCustomer(form, bootstrap?.branch_id ?? null),
    onSuccess: (saved) => {
      setCustomer(saved);
      setForm({ name: "", phone: "", phone2: "", city: "", address: "" });
      onAdding(false);
      toast.success(`تم حفظ الزبون ${saved.name}`);
    },
    onError: (failure) => setError(toFinoraError(failure).message),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const phone = form.phone.replace(/\D/g, "");
    if (!form.name.trim()) return setError("اسم الزبون مطلوب");
    if (phone.length !== 11) return setError("رقم الهاتف يجب أن يكون 11 رقم");
    if (form.phone2 && form.phone2.replace(/\D/g, "").length !== 11)
      return setError("الرقم الآخر يجب أن يكون 11 رقم");
    if (!form.city) return setError("اختر المحافظة");
    if (!form.address.trim()) return setError("العنوان مطلوب");
    save.mutate();
  };

  if (adding) {
    return (
      <form onSubmit={submit} aria-label="إضافة زبون جديد" className="flex h-full flex-col">
        <header className="flex items-center gap-2 border-b border-line/70 px-5 py-4">
          <UserPlus size={20} className="text-azure" aria-hidden />
          <h2 className="flex-1 text-[15px] font-semibold text-ink">إضافة زبون جديد</h2>
          <IconButton label="إغلاق" size="sm" onClick={() => onAdding(false)}>
            <X size={16} />
          </IconButton>
        </header>
        <div className="min-h-0 flex-1 space-y-3.5 overflow-y-auto px-5 py-4">
          <label className="block">
            <Label text="الاسم" required />
            <input
              className={input}
              value={form.name}
              placeholder="اسم الزبون الكامل"
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label className="block">
            <Label text="الرقم" required />
            <input
              dir="ltr"
              inputMode="tel"
              className={cn(input, "text-end")}
              value={form.phone}
              placeholder="07701234567"
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
          </label>
          <label className="block">
            <Label text="رقم آخر" />
            <input
              dir="ltr"
              inputMode="tel"
              className={cn(input, "text-end")}
              value={form.phone2}
              placeholder="اختياري"
              onChange={(e) => setForm({ ...form, phone2: e.target.value })}
            />
          </label>
          <label className="block">
            <Label text="المحافظة" required />
            <select
              className={input}
              value={form.city}
              onChange={(e) => setForm({ ...form, city: e.target.value })}
            >
              <option value="">اختر المحافظة</option>
              {(bootstrap?.provinces ?? []).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <Label text="العنوان" required />
            <textarea
              rows={3}
              className={cn(input, "h-auto resize-none py-2.5 leading-6")}
              value={form.address}
              placeholder="العنوان التفصيلي"
              onChange={(e) => setForm({ ...form, address: e.target.value })}
            />
          </label>
          {error && (
            <p role="alert" className="rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
        <div className="px-5 pb-5">
          <button
            type="submit"
            disabled={save.isPending}
            className="flex h-12 w-full items-center justify-center gap-2 rounded-control bg-gradient-to-l from-azure to-violet-deep text-[15px] font-semibold text-white shadow-float disabled:opacity-60"
          >
            <Save size={18} aria-hidden />
            {save.isPending ? "جارٍ الحفظ…" : "حفظ العميل"}
          </button>
        </div>
      </form>
    );
  }

  return (
    <section aria-label="الزبون" className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-line/70 px-5 py-4">
        <UserRound size={20} className="text-violet" aria-hidden />
        <h2 className="flex-1 text-[15px] font-semibold text-ink">الزبون</h2>
        {customer && (
          <button
            type="button"
            onClick={() => setCustomer(null)}
            className="text-xs text-violet-deep hover:underline"
          >
            تغيير
          </button>
        )}
      </header>
      {customer ? (
        <div className="space-y-3 px-5 py-5">
          <div className="flex items-center gap-3">
            <span className="grid h-12 w-12 place-items-center rounded-full bg-violet-soft text-lg font-bold text-violet-deep">
              {customer.name.slice(0, 1)}
            </span>
            <div className="min-w-0">
              <p className="truncate text-base font-semibold text-ink">{customer.name}</p>
              <p className="ltr-isolate text-sm text-ink-soft">{customer.phone}</p>
            </div>
          </div>
          {(customer.city || customer.address) && (
            <p className="flex items-start gap-2 rounded-control bg-surface-sunken/80 px-3 py-2.5 text-sm text-ink-soft">
              <MapPin size={16} className="mt-0.5 shrink-0" aria-hidden />
              {[customer.city, customer.address].filter(Boolean).join(" — ")}
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-full bg-surface-sunken text-ink-faint">
            <Phone size={22} aria-hidden />
          </span>
          <p className="text-sm text-ink-soft">
            ابحث عن الزبون بالاسم أو الرقم من الأعلى، أو أضف زبوناً جديداً.
          </p>
          <button
            type="button"
            onClick={() => onAdding(true)}
            className="flex items-center gap-2 rounded-control bg-azure-soft px-4 py-2 text-sm font-semibold text-azure"
          >
            <UserPlus size={16} aria-hidden />
            إضافة زبون
          </button>
        </div>
      )}
    </section>
  );
}
