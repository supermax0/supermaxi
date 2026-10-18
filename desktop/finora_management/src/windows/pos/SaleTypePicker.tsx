import { Check, ChevronDown, Landmark } from "lucide-react";
import { useRef, useState } from "react";
import { Popover } from "@/components/Popover";
import type { BankOption } from "@/features/pos/bankAccounts";
import type { SaleType } from "@/features/pos/cart";
import { SALE_TYPES } from "@/features/pos/saleTypes";
import { cn } from "@/utils/cn";

interface SaleTypePickerProps {
  value: SaleType;
  onChange(value: SaleType): void;
  canPay: boolean;
  bankAccounts: BankOption[];
  bankAccountId: number | null;
  onBankAccount(id: number): void;
  loadingAccounts: boolean;
  label?: string;
  hints?: Partial<Record<SaleType, string>>;
}

/** Coloured sale-type segments; بنك reveals a clean account picker (no native select). */
export function SaleTypePicker({
  value,
  onChange,
  canPay,
  bankAccounts,
  bankAccountId,
  onBankAccount,
  loadingAccounts,
  label = "نوع البيع",
  hints,
}: SaleTypePickerProps) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const chosen = bankAccounts.find((a) => a.id === bankAccountId) ?? null;

  return (
    <div className="flex items-center gap-1.5 rounded-panel bg-white/80 p-1.5 shadow-control">
      <span className="px-2 text-[13px] font-semibold text-ink-soft">{label}</span>
      <div role="radiogroup" aria-label={label} className="flex items-center gap-1">
        {SALE_TYPES.map((type) => {
          const disabled = type.id !== "credit" && !canPay;
          const selected = value === type.id;
          const Icon = type.icon;
          return (
            <button
              key={type.id}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              title={disabled ? "لا تملك صلاحية تسجيل الدفع" : (hints?.[type.id] ?? type.hint)}
              onClick={() => onChange(type.id)}
              className={cn(
                "flex h-10 min-w-[72px] items-center justify-center gap-1.5 rounded-[11px] px-3 text-sm font-semibold transition-[background-color,color,box-shadow] duration-200 disabled:opacity-40",
                selected ? cn("shadow-control ring-1", type.active) : "text-ink-soft hover:bg-white",
              )}
            >
              <Icon size={16} className={selected ? undefined : type.dot} aria-hidden />
              {type.label}
            </button>
          );
        })}
      </div>
      {value === "bank" && (
        <div className="relative">
          <button
            ref={anchor}
            type="button"
            aria-label="الحساب البنكي"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className={cn(
              "flex h-10 max-w-[200px] items-center gap-2 rounded-[11px] px-3 text-sm ring-1 transition-colors",
              chosen
                ? "bg-azure-soft/60 text-azure ring-azure/25"
                : "bg-warning-soft/70 text-warning ring-warning/30",
            )}
          >
            <Landmark size={15} aria-hidden />
            <span className="truncate">
              {chosen ? chosen.name : loadingAccounts ? "جارٍ التحميل…" : "اختر الحساب"}
            </span>
            <ChevronDown size={14} aria-hidden />
          </button>
          <Popover
            open={open}
            onClose={() => setOpen(false)}
            anchor={anchor}
            label="الحسابات البنكية"
            align="start"
            width={260}
          >
            {bankAccounts.length === 0 && !loadingAccounts && (
              <p className="px-3 py-4 text-sm text-ink-faint">لا يوجد حساب بنكي مفعّل لهذا الفرع في FINORA</p>
            )}
            <ul role="listbox" aria-label="الحسابات البنكية" className="max-h-[280px] overflow-y-auto">
              {bankAccounts.map((account) => (
                <li key={account.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={account.id === bankAccountId}
                    onClick={() => {
                      onBankAccount(account.id);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-start text-sm transition-colors",
                      account.id === bankAccountId
                        ? "bg-azure-soft text-azure"
                        : "text-ink hover:bg-surface-sunken",
                    )}
                  >
                    <Landmark size={16} className="shrink-0 text-azure" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{account.name}</span>
                      {account.branch && (
                        <span className="block truncate text-xs text-ink-faint">{account.branch}</span>
                      )}
                    </span>
                    {account.id === bankAccountId && <Check size={16} aria-hidden />}
                  </button>
                </li>
              ))}
            </ul>
          </Popover>
        </div>
      )}
    </div>
  );
}
