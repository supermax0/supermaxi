import { Eye, ListChecks, PowerOff, ScanBarcode } from "lucide-react";
import { useOrderPreferences, type OrderScanAction } from "@/features/orders/orderPreferences";
import { useCan } from "@/stores/session";
import { cn } from "@/utils/cn";
import { SectionCard, SettingRow, Switch } from "./primitives";

const segment = "flex h-9 items-center gap-1.5 rounded-[10px] px-3 text-sm font-semibold transition-colors";

const ACTIONS: Array<{ id: OrderScanAction; label: string; icon: typeof Eye }> = [
  { id: "shipping", label: "باركود شركة النقل", icon: ScanBarcode },
  { id: "details", label: "تفاصيل الطلب", icon: Eye },
  { id: "select", label: "تحديد الطلب", icon: ListChecks },
  { id: "off", label: "إيقاف", icon: PowerOff },
];

export function OrdersSettingsSection() {
  const prefs = useOrderPreferences();
  const canManage = useCan("manage_orders");
  return (
    <SectionCard title="مسح باركود الطلب" icon={ScanBarcode}>
      <SettingRow
        title="عند مسح باركود طلب"
        hint={
          canManage
            ? "في نافذة الطلبات: يفتح نافذة إدخال باركود شركة النقل، أو تفاصيل الطلب، أو يتجاهل الماسح."
            : "إدخال باركود شركة النقل يحتاج صلاحية إدارة الطلبات؛ سيُفتح تفاصيل الطلب بدلاً منه."
        }
      >
        <div
          role="radiogroup"
          aria-label="عند مسح باركود طلب"
          className="flex gap-1 rounded-control bg-surface-sunken p-1"
        >
          {ACTIONS.map((action) => {
            const Icon = action.icon;
            const selected = prefs.scanAction === action.id;
            return (
              <button
                key={action.id}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => prefs.update({ scanAction: action.id })}
                className={cn(
                  segment,
                  selected ? "bg-white text-violet-deep shadow-control" : "text-ink-soft hover:bg-white",
                )}
              >
                <Icon size={15} aria-hidden />
                {action.label}
              </button>
            );
          })}
        </div>
      </SettingRow>
      <SettingRow
        title="حفظ تلقائي بعد آخر قطعة"
        hint="عند مسح باركود آخر قطعة يُحفظ مباشرة وتُغلق النافذة لتمسح الطلب التالي. عند إيقافه تضغط «حفظ» بنفسك."
      >
        <Switch
          label="حفظ تلقائي بعد آخر قطعة"
          checked={prefs.autoSaveShipping}
          disabled={prefs.scanAction !== "shipping"}
          onChange={(on) => prefs.update({ autoSaveShipping: on })}
        />
      </SettingRow>
    </SectionCard>
  );
}
