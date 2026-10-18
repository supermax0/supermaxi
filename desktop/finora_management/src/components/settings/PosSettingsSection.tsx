import { useQuery } from "@tanstack/react-query";
import { Landmark, Printer, RotateCcw, ScanLine, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { finora } from "@/api/finora";
import { bankAccountsFor } from "@/features/pos/bankAccounts";
import { POS_PAGE_SIZES, usePosPreferences } from "@/features/pos/posPreferences";
import { posKeys } from "@/features/pos/queries";
import { SALE_TYPES } from "@/features/pos/saleTypes";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { SectionCard, SettingRow, Switch } from "./primitives";

const segment = "h-9 rounded-[10px] px-3 text-sm font-semibold transition-colors";

/** Settings → نقطة البيع. Stored per device; FINORA permissions still decide what is allowed. */
export function PosSettingsSection() {
  const prefs = usePosPreferences();
  const bootstrap = useQuery({
    queryKey: posKeys.bootstrap,
    queryFn: () => finora.pos.bootstrap(),
    staleTime: 5 * 60_000,
  });
  const canPay = bootstrap.data?.can_pay ?? false;
  const canPrint = bootstrap.data?.can_print ?? false;
  const accounts = useQuery({
    queryKey: ["pos", "accounts"],
    queryFn: () => finora.pos.paymentAccounts(),
    enabled: canPay,
    staleTime: 5 * 60_000,
  });
  const banks = useMemo(
    () => bankAccountsFor(accounts.data ?? [], bootstrap.data?.branch_id ?? null),
    [accounts.data, bootstrap.data?.branch_id],
  );
  const [limitText, setLimitText] = useState(prefs.confirmAbove ? String(prefs.confirmAbove) : "");

  return (
    <div className="space-y-4">
      <SectionCard title="البيع والدفع" icon={Landmark}>
        <SettingRow title="نوع البيع الافتراضي" hint="يُختار تلقائياً عند بدء فاتورة جديدة.">
          <div
            role="radiogroup"
            aria-label="نوع البيع الافتراضي"
            className="flex gap-1 rounded-control bg-surface-sunken p-1"
          >
            {SALE_TYPES.map((type) => {
              const disabled = type.id !== "credit" && !canPay;
              const Icon = type.icon;
              return (
                <button
                  key={type.id}
                  type="button"
                  role="radio"
                  aria-checked={prefs.defaultSaleType === type.id}
                  disabled={disabled}
                  onClick={() => prefs.update({ defaultSaleType: type.id })}
                  className={cn(
                    segment,
                    "flex items-center gap-1.5 disabled:opacity-40",
                    prefs.defaultSaleType === type.id
                      ? cn("shadow-control ring-1", type.active)
                      : "text-ink-soft hover:bg-white",
                  )}
                >
                  <Icon size={15} aria-hidden />
                  {type.label}
                </button>
              );
            })}
          </div>
        </SettingRow>
        <SettingRow
          title="الحساب البنكي الافتراضي"
          hint={
            canPay ? "يُستخدم عند اختيار «بنك» — حسابات فرعك فقط." : "يتطلب صلاحية تسجيل الدفع في FINORA."
          }
        >
          <select
            aria-label="الحساب البنكي الافتراضي"
            disabled={!canPay}
            value={prefs.defaultBankAccountId ?? ""}
            onChange={(event) => prefs.update({ defaultBankAccountId: Number(event.target.value) || null })}
            className="h-9 w-[220px] rounded-[10px] border border-line bg-white px-2 text-sm disabled:opacity-50"
          >
            <option value="">يُسأل عند البيع</option>
            {banks.map((account) => (
              <option key={account.id} value={account.id}>
                {account.branch ? `${account.name} — ${account.branch}` : account.name}
              </option>
            ))}
          </select>
        </SettingRow>
        <SettingRow
          title="تأكيد قبل تنفيذ الفواتير الكبيرة"
          hint="يُطلب تأكيد إذا تجاوز الإجمالي هذا المبلغ. اتركه فارغاً لإيقافه."
        >
          <div className="flex items-center gap-2">
            <input
              aria-label="حد التأكيد"
              dir="ltr"
              inputMode="numeric"
              value={limitText ? formatNumber(Number(limitText)) : ""}
              placeholder="بدون"
              onChange={(event) => {
                const digits = event.target.value.replace(/\D/g, "");
                setLimitText(digits);
                prefs.update({ confirmAbove: Number(digits) || 0 });
              }}
              className="ltr-isolate h-9 w-[150px] rounded-[10px] border border-line bg-white px-3 text-sm outline-none focus:border-violet/45"
            />
            <span className="text-xs text-ink-faint">د.ع</span>
          </div>
        </SettingRow>
      </SectionCard>

      <SectionCard title="الطباعة" icon={Printer}>
        <SettingRow
          title="الطباعة تلقائياً بعد التنفيذ"
          hint={canPrint ? "زر التنفيذ يصبح «تنفيذ و طباعة»." : "يتطلب صلاحية طباعة الفواتير."}
        >
          <Switch
            label="الطباعة تلقائياً بعد التنفيذ"
            checked={prefs.autoPrint && canPrint}
            disabled={!canPrint}
            onChange={(autoPrint) => prefs.update({ autoPrint })}
          />
        </SettingRow>
      </SectionCard>

      <SectionCard title="الباركود والمنتجات" icon={ScanLine}>
        <SettingRow
          title="الباركود يضيف المنتج للسلة مباشرة"
          hint="عند تطابق منتج واحد فقط؛ وإلا تُعرض النتائج."
        >
          <Switch
            label="الباركود يضيف المنتج للسلة مباشرة"
            checked={prefs.scanAddsToCart}
            onChange={(scanAddsToCart) => prefs.update({ scanAddsToCart })}
          />
        </SettingRow>
        <SettingRow
          title="صوت عند مسح الباركود"
          hint="نغمة قصيرة للنجاح، ونغمة مختلفة إذا لم يُعرف الباركود."
        >
          <Switch
            label="صوت عند مسح الباركود"
            checked={prefs.scanSound}
            onChange={(scanSound) => prefs.update({ scanSound })}
          />
        </SettingRow>
        <SettingRow title="إظهار صور المنتجات">
          <Switch
            label="إظهار صور المنتجات"
            checked={prefs.showImages}
            onChange={(showImages) => prefs.update({ showImages })}
          />
        </SettingRow>
        <SettingRow title="عدد المنتجات في الصفحة">
          <div
            role="radiogroup"
            aria-label="عدد المنتجات في الصفحة"
            className="flex gap-1 rounded-control bg-surface-sunken p-1"
          >
            {POS_PAGE_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                role="radio"
                aria-checked={prefs.pageSize === size}
                onClick={() => prefs.update({ pageSize: size })}
                className={cn(
                  segment,
                  "ltr-isolate",
                  prefs.pageSize === size
                    ? "bg-white text-violet-deep shadow-control"
                    : "text-ink-soft hover:bg-white",
                )}
              >
                {size}
              </button>
            ))}
          </div>
        </SettingRow>
      </SectionCard>

      <div className="flex items-center justify-between rounded-panel px-1">
        <p className="flex items-center gap-1.5 text-xs text-ink-faint">
          <ShieldCheck size={14} aria-hidden />
          تُحفظ على هذا الجهاز فقط. الأسعار والصلاحيات والمخزون يحددها FINORA.
        </p>
        <button
          type="button"
          onClick={() => {
            prefs.reset();
            setLimitText("");
          }}
          className="flex items-center gap-1.5 rounded-control px-3 py-2 text-sm text-ink-soft hover:bg-surface-sunken"
        >
          <RotateCcw size={14} aria-hidden />
          استعادة الافتراضي
        </button>
      </div>
    </div>
  );
}
