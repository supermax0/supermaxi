import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Check, Loader2, Plus, Receipt, Repeat } from "lucide-react";
import { useMemo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import type { ExpenseInput, ExpensesMeta } from "@/api/finora/expenses";
import { Field } from "@/components/FilterPanel";
import { MoneyInput } from "@/components/MoneyInput";
import { today } from "@/features/purchases/composer";
import { useConnection } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { cn } from "@/utils/cn";
import { formatIqd } from "@/utils/money";
import {
  SupplierModal,
  supplierInput,
  supplierPrimary,
  supplierSecondary,
} from "../suppliers/SupplierDialogs";

/** Same look as the form inputs, without the full width (they sit inline in the repeat sentence). */
const inlineInput = supplierInput.replace("w-full", "").trim();

const UNITS: Array<{ value: ExpenseInput["repeat_unit"]; label: string }> = [
  { value: "days", label: "يوم" },
  { value: "weeks", label: "أسبوع" },
  { value: "months", label: "شهر" },
  { value: "years", label: "سنة" },
];

/** New expense (or a recurring series). FINORA decides what is posted now and what stays scheduled. */
export function ExpenseComposer({ meta, onClose }: { meta: ExpensesMeta; onClose(): void }) {
  const client = useQueryClient();
  const online = useConnection((s) => s.status === "online");
  const defaultAccount = meta.treasury_accounts.find((a) => a.is_default) ?? meta.treasury_accounts[0];
  const [form, setForm] = useState<ExpenseInput>({
    title: "",
    category: meta.categories[0]?.key ?? "other",
    amount: 0,
    expense_date: meta.today || today(),
    expense_time: "",
    treasury_account_id: defaultAccount?.id ?? null,
    note: "",
    repeat_enabled: false,
    repeat_interval: 1,
    repeat_unit: "months",
    repeat_count: 12,
  });
  const [categories, setCategories] = useState(meta.categories);
  const [newCategory, setNewCategory] = useState<string | null>(null);
  const patch = (next: Partial<ExpenseInput>) => setForm((f) => ({ ...f, ...next }));

  const save = useMutation({
    mutationFn: () => finora.expenses.create(form),
    onSuccess: async (result) => {
      toast.success(result.message);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["expenses"] }),
        client.invalidateQueries({ queryKey: ["finance"] }),
        client.invalidateQueries({ queryKey: ["reports"] }),
      ]);
      onClose();
    },
  });
  const addCategory = useMutation({
    mutationFn: (name: string) => finora.expenses.addCategory(name, ""),
    onSuccess: (result) => {
      setCategories((list) => [...list.filter((c) => c.key !== result.category.key), result.category]);
      patch({ category: result.category.key });
      setNewCategory(null);
      void client.invalidateQueries({ queryKey: ["expenses", "meta"] });
    },
    onError: (e: unknown) => toast.error(toFinoraError(e).message),
  });

  const count = form.repeat_enabled ? form.repeat_count : 1;
  const future = form.expense_date > (meta.today || today());
  const issues = useMemo(() => {
    const list: string[] = [];
    if (!form.title.trim()) list.push("اكتب عنوان المصروف");
    if (form.amount <= 0) list.push("أدخل مبلغ المصروف");
    if (!form.expense_date) list.push("اختر التاريخ");
    return list;
  }, [form]);
  const busy = save.isPending;
  const error = save.error ? toFinoraError(save.error).message : null;

  return (
    <SupplierModal title="إضافة مصروف" icon={Receipt} busy={busy} onClose={onClose} wide>
      <form
        className="grid grid-cols-2 gap-x-5 gap-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (issues.length === 0 && online && !busy) save.mutate();
        }}
      >
        <Field label="عنوان المصروف">
          <input
            data-autofocus
            className={supplierInput}
            value={form.title}
            maxLength={150}
            placeholder="مثال: إيجار المحل لشهر تشرين"
            onChange={(e) => patch({ title: e.target.value })}
          />
        </Field>
        <Field label="المبلغ (د.ع)">
          <MoneyInput
            label="مبلغ المصروف"
            value={form.amount}
            onChange={(amount) => patch({ amount })}
            className={cn(supplierInput, "text-lg font-semibold")}
          />
        </Field>

        <div className="col-span-2">
          <p className="mb-2 text-[13px] font-medium text-ink-soft">الفئة</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="فئة المصروف">
            {categories.map((c) => (
              <button
                key={c.key}
                type="button"
                role="radio"
                aria-checked={form.category === c.key}
                onClick={() => patch({ category: c.key })}
                className={cn(
                  "inline-flex h-10 items-center gap-2 rounded-control border px-3.5 text-sm transition-colors",
                  form.category === c.key
                    ? "border-violet/40 bg-violet-soft font-semibold text-violet-deep shadow-control"
                    : "border-line bg-white/80 text-ink-soft hover:border-violet/25 hover:bg-violet-soft/50",
                )}
              >
                {c.icon && <span aria-hidden>{c.icon}</span>}
                {c.label}
                {form.category === c.key && <Check size={14} aria-hidden />}
              </button>
            ))}
            {newCategory === null ? (
              <button
                type="button"
                onClick={() => setNewCategory("")}
                className="inline-flex h-10 items-center gap-1.5 rounded-control border border-dashed border-line px-3.5 text-sm text-ink-faint hover:border-violet/40 hover:text-violet-deep"
              >
                <Plus size={15} /> فئة جديدة
              </button>
            ) : (
              <span className="inline-flex items-center gap-1.5">
                <input
                  autoFocus
                  aria-label="اسم الفئة الجديدة"
                  className={cn(inlineInput, "h-10 w-44")}
                  value={newCategory}
                  maxLength={40}
                  placeholder="اسم الفئة"
                  onChange={(e) => setNewCategory(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      if (newCategory.trim()) addCategory.mutate(newCategory);
                    }
                  }}
                />
                <button
                  type="button"
                  className={cn(supplierSecondary, "h-10 px-3")}
                  disabled={!newCategory.trim() || addCategory.isPending}
                  onClick={() => addCategory.mutate(newCategory)}
                >
                  {addCategory.isPending ? <Loader2 size={15} className="animate-spin" /> : "إضافة"}
                </button>
              </span>
            )}
          </div>
        </div>

        <Field label="تاريخ المصروف">
          <input
            type="date"
            className={supplierInput}
            value={form.expense_date}
            onChange={(e) => patch({ expense_date: e.target.value })}
          />
        </Field>
        <Field label="ساعة الصرف (اختياري)">
          <input
            type="time"
            className={supplierInput}
            value={form.expense_time}
            onChange={(e) => patch({ expense_time: e.target.value })}
          />
        </Field>
        <Field label="الصرف من">
          <select
            aria-label="حساب الصرف"
            className={supplierInput}
            value={form.treasury_account_id ?? ""}
            onChange={(e) => patch({ treasury_account_id: e.target.value ? Number(e.target.value) : null })}
          >
            {meta.treasury_accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.type === "bank" ? " (مصرف)" : ""}
                {a.branch_name && a.branch_name !== "مشترك" ? ` — ${a.branch_name}` : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="ملاحظة (اختياري)">
          <input
            className={supplierInput}
            value={form.note}
            maxLength={200}
            placeholder="تفاصيل إضافية"
            onChange={(e) => patch({ note: e.target.value })}
          />
        </Field>

        <div className="col-span-2 rounded-panel border border-line/80 bg-surface-sunken/50 p-4">
          <label className="flex cursor-pointer items-center gap-3">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[rgb(var(--violet))]"
              checked={form.repeat_enabled}
              onChange={(e) => patch({ repeat_enabled: e.target.checked })}
            />
            <Repeat size={17} className="text-violet" aria-hidden />
            <span className="text-sm font-semibold text-ink">مصروف متكرر</span>
            <span className="text-xs text-ink-faint">مثل الإيجار والرواتب والاشتراكات</span>
          </label>
          {form.repeat_enabled && (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-ink-soft">
              كل
              <input
                type="number"
                min={1}
                max={365}
                aria-label="فترة التكرار"
                className={cn(inlineInput, "h-10 w-20 text-center")}
                value={form.repeat_interval}
                onChange={(e) =>
                  patch({ repeat_interval: Math.max(1, Math.min(365, Number(e.target.value) || 1)) })
                }
              />
              <select
                aria-label="وحدة التكرار"
                className={cn(inlineInput, "h-10 w-28")}
                value={form.repeat_unit}
                onChange={(e) => patch({ repeat_unit: e.target.value as ExpenseInput["repeat_unit"] })}
              >
                {UNITS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </select>
              لمدة
              <input
                type="number"
                min={2}
                max={366}
                aria-label="عدد التكرارات"
                className={cn(inlineInput, "h-10 w-20 text-center")}
                value={form.repeat_count}
                onChange={(e) =>
                  patch({ repeat_count: Math.max(2, Math.min(366, Number(e.target.value) || 2)) })
                }
              />
              مرة
            </div>
          )}
        </div>

        <div className="col-span-2 flex items-center gap-3 rounded-panel bg-gradient-to-l from-violet-soft/70 to-white px-4 py-3 text-sm">
          <CalendarClock size={18} className="shrink-0 text-violet" aria-hidden />
          <p className="flex-1 text-ink-soft">
            {count > 1 ? (
              <>
                سيُسجَّل <b className="ltr-isolate text-ink">{count}</b> مصروف بقيمة{" "}
                <b className="text-ink">{formatIqd(form.amount)}</b> لكل منها — المجموع{" "}
                <b className="text-ink">{formatIqd(form.amount * count)}</b>. يُخصم المستحق منها الآن ويبقى
                الباقي مجدولاً حتى موعده.
              </>
            ) : future || form.expense_time ? (
              <>يُجدول المصروف ولا يُخصم من الحساب قبل موعده.</>
            ) : (
              <>يُخصم المبلغ من الحساب المختار فور الحفظ.</>
            )}
          </p>
        </div>

        {error && (
          <p role="alert" className="col-span-2 rounded-control bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </p>
        )}

        <footer className="col-span-2 flex items-center justify-between gap-3 pt-1">
          <p className="text-xs text-ink-faint">{!online ? "لا يوجد اتصال بـ FINORA" : (issues[0] ?? "")}</p>
          <div className="flex gap-2">
            <button type="button" className={supplierSecondary} onClick={onClose} disabled={busy}>
              إلغاء
            </button>
            <button type="submit" className={supplierPrimary} disabled={busy || !online || issues.length > 0}>
              {busy ? <Loader2 size={17} className="animate-spin" /> : <Check size={17} />}
              حفظ المصروف
            </button>
          </div>
        </footer>
      </form>
    </SupplierModal>
  );
}
