import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  Keyboard,
  Cloud,
  Power,
  LogOut,
  Palette,
  Volume2,
  ScanBarcode,
  ScanLine,
  Server,
  UserRound,
  Wifi,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { finora } from "@/api/finora";
import { CONFIG_QUERY_KEY } from "@/features/auth/LoginScreen";
import { useSignOut } from "@/hooks/useSignOut";
import { useConnection } from "@/stores/connection";
import { usePreferences } from "@/stores/preferences";
import { useCan, useSession } from "@/stores/session";
import { desktopBridge } from "@/services/bridge";
import { cn } from "@/utils/cn";
import { OrdersSettingsSection } from "./OrdersSettingsSection";
import { PosSettingsSection } from "./PosSettingsSection";
import { OfflineSettingsSection } from "./OfflineSettingsSection";
import { SectionCard, SettingRow, Switch } from "./primitives";
import { SoundSettingsSection } from "./SoundSettingsSection";

import { RecoverySettingsSection, UpdateSettingsSection } from "./RecoverySettingsSection";

type SectionId =
  "account" | "orders" | "pos" | "appearance" | "sounds" | "connection" | "offline" | "recovery" | "updates";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: LucideIcon;
}

function AccountSection() {
  const session = useSession((s) => s.session);
  const signOut = useSignOut();
  if (!session) return null;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 rounded-panel bg-gradient-to-l from-violet-soft to-white px-5 py-5 ring-1 ring-violet/10">
        <span className="grid h-14 w-14 place-items-center rounded-full bg-white text-xl font-bold text-violet-deep shadow-control">
          {session.user.name.slice(0, 1)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-lg font-bold text-ink">{session.user.name}</p>
          <p className="ltr-isolate text-sm text-ink-soft">@{session.user.username}</p>
        </div>
      </div>
      <SectionCard title="الشركة والصلاحيات" icon={UserRound}>
        <SettingRow title="الشركة">{session.tenant.name ?? session.tenant.slug}</SettingRow>
        <SettingRow title="الفرع">{session.branch?.name ?? "كل الفروع"}</SettingRow>
        <SettingRow title="الدور">{session.roles.join("، ") || "—"}</SettingRow>
        <SettingRow title="الصلاحيات المفعّلة" hint="تُحدَّث من FINORA تلقائياً">
          <span className="ltr-isolate rounded-full bg-violet-soft px-2.5 py-0.5 text-xs font-semibold text-violet-deep">
            {session.permissions.length}
          </span>
        </SettingRow>
      </SectionCard>
      <button
        type="button"
        disabled={signOut.isPending}
        onClick={() => signOut.mutate()}
        className="flex h-11 w-full items-center justify-center gap-2 rounded-control bg-danger-soft text-sm font-semibold text-danger transition-colors hover:bg-danger hover:text-white disabled:opacity-50"
      >
        <LogOut size={17} aria-hidden />
        {signOut.isPending ? "جارٍ تسجيل الخروج…" : "تسجيل الخروج"}
      </button>
    </div>
  );
}

function AppearanceSection() {
  const motionPref = usePreferences((s) => s.motion);
  const setMotion = usePreferences((s) => s.setMotion);
  return (
    <SectionCard title="الحركة" icon={Palette}>
      <SettingRow
        title="تقليل الحركة"
        hint="يلغي تحريك النوافذ ويُبقي التلاشي فقط. يتبع إعداد Windows تلقائياً عند إيقافه."
      >
        <Switch
          label="تقليل الحركة"
          checked={motionPref === "reduced"}
          onChange={(on) => setMotion(on ? "reduced" : "system")}
        />
      </SettingRow>
    </SectionCard>
  );
}

const AUTO_START_KEY = ["desktop", "auto-start"] as const;

/** Start FINORA Management when Windows starts (per-user login item, no admin rights needed). */
function StartupCard() {
  const queryClient = useQueryClient();
  const autoStart = useQuery({
    queryKey: AUTO_START_KEY,
    queryFn: () => desktopBridge().app.getAutoStart(),
    staleTime: Infinity,
  });
  const update = useMutation({
    mutationFn: (enabled: boolean) => desktopBridge().app.setAutoStart(enabled),
    onSuccess: (enabled) => queryClient.setQueryData(AUTO_START_KEY, enabled),
  });
  return (
    <SectionCard title="بدء التشغيل" icon={Power}>
      <SettingRow
        title="تشغيل النظام مع بدء Windows"
        hint={
          update.isError
            ? "تعذر تغيير الإعداد، حاول مرة أخرى."
            : "يفتح FINORA Management تلقائياً عند تشغيل الجهاز وتسجيل الدخول إلى Windows."
        }
      >
        <Switch
          label="تشغيل النظام مع بدء Windows"
          checked={autoStart.data ?? false}
          disabled={autoStart.isPending || update.isPending}
          onChange={(on) => update.mutate(on)}
        />
      </SettingRow>
    </SectionCard>
  );
}

function ConnectionSection() {
  const config = useQuery({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: () => finora.config.get(),
    staleTime: Infinity,
  });
  const status = useConnection((s) => s.status);
  const label = status === "online" ? "متصل" : status === "offline" ? "لا يوجد إنترنت" : "FINORA لا يستجيب";
  return (
    <SectionCard title="خادم FINORA" icon={Server}>
      <SettingRow title="العنوان" hint="لتغيير الخادم سجّل الخروج واختر «تغيير الخادم» في شاشة الدخول.">
        <span className="ltr-isolate text-sm text-ink">{config.data?.serverUrl ?? "—"}</span>
      </SettingRow>
      <SettingRow title="الحالة">
        <span
          className={cn(
            "flex items-center gap-1.5 text-sm font-medium",
            status === "online" ? "text-success" : "text-danger",
          )}
        >
          <Wifi size={15} aria-hidden />
          {label}
        </span>
      </SettingRow>
      <SettingRow title="إصدار التطبيق">
        <span className="ltr-isolate text-sm text-ink-soft">{config.data?.appVersion ?? "—"}</span>
      </SettingRow>
    </SectionCard>
  );
}

const SHORTCUTS: Array<[string, string]> = [
  ["Ctrl+K", "بحث سريع"],
  ["Ctrl+1 … 4", "فتح النوافذ"],
  ["Esc", "إغلاق النافذة / اللوحة"],
  ["F2", "نقطة البيع: بحث منتج"],
  ["F3", "نقطة البيع: بحث زبون"],
  ["F9 / Ctrl+Enter", "نقطة البيع: تنفيذ"],
];

function ShortcutsCard() {
  return (
    <SectionCard title="اختصارات لوحة المفاتيح" icon={Keyboard}>
      <ul className="grid grid-cols-2 gap-x-6 py-2">
        {SHORTCUTS.map(([keys, action]) => (
          <li
            key={keys}
            className="flex items-center justify-between gap-3 border-b border-line/50 py-2.5 text-sm last:border-0"
          >
            <span className="text-ink-soft">{action}</span>
            <kbd className="ltr-isolate rounded-md border border-line bg-white px-2 py-0.5 text-xs font-semibold text-ink">
              {keys}
            </kbd>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

export function SettingsDialog({ open, onClose }: { open: boolean; onClose(): void }) {
  const canPos = useCan("view_pos");
  const canOrders = useCan("can_see_orders");
  const sections: SectionDef[] = [
    { id: "account", label: "الحساب", icon: UserRound },
    ...(canOrders ? [{ id: "orders" as const, label: "الطلبات", icon: ScanBarcode }] : []),
    ...(canPos ? [{ id: "pos" as const, label: "نقطة البيع", icon: ScanLine }] : []),
    { id: "appearance", label: "المظهر والاختصارات", icon: Palette },
    { id: "sounds", label: "الأصوات", icon: Volume2 },
    { id: "connection", label: "الاتصال", icon: Server },
    { id: "recovery", label: "النسخ والاستعادة", icon: Cloud },
    { id: "updates", label: "تحديث التطبيق", icon: Server },
    { id: "offline", label: "الأوفلاين والمزامنة", icon: Cloud },
  ];
  const [section, setSection] = useState<SectionId>("account");

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector('[role="menu"]')) {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="no-drag fixed inset-0 z-[85] grid place-items-center bg-ink/15"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.14 } }}
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.div
            role="dialog"
            aria-modal
            aria-label="الإعدادات"
            dir="rtl"
            className="glass-solid flex h-[min(640px,86vh)] w-[min(880px,92vw)] overflow-hidden rounded-window"
            initial={{ opacity: 0, y: 12, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.99 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <nav
              aria-label="أقسام الإعدادات"
              className="settings-navigation flex w-[220px] shrink-0 flex-col gap-1 border-e border-line/70 bg-surface-sunken/60 p-4"
            >
              <h2 className="px-3 pb-3 pt-1 text-lg font-bold text-ink">الإعدادات</h2>
              {sections.map((item) => {
                const Icon = item.icon;
                const active = item.id === section;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => setSection(item.id)}
                    className={cn(
                      "relative flex h-11 items-center gap-3 rounded-control px-3 text-sm font-medium transition-[background-color,color,box-shadow] duration-200",
                      active
                        ? "bg-white text-violet-deep shadow-control ring-1 ring-violet/15"
                        : "text-ink-soft hover:bg-white/70 hover:text-ink",
                    )}
                  >
                    <Icon size={18} className="relative" aria-hidden />
                    <span className="relative">{item.label}</span>
                  </button>
                );
              })}
            </nav>
            <div className="relative min-w-0 flex-1 overflow-y-auto px-7 py-6">
              <button
                type="button"
                aria-label="إغلاق الإعدادات"
                onClick={onClose}
                className="absolute end-5 top-5 grid h-9 w-9 place-items-center rounded-control text-ink-soft hover:bg-surface-sunken hover:text-ink"
              >
                <X size={18} />
              </button>
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={section}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, transition: { duration: 0.08 } }}
                  transition={{ duration: 0.16 }}
                  className="space-y-4 pt-8"
                >
                  {section === "account" && <AccountSection />}
                  {section === "orders" && <OrdersSettingsSection />}
                  {section === "pos" && <PosSettingsSection />}
                  {section === "appearance" && (
                    <>
                      <StartupCard />
                      <AppearanceSection />
                      <ShortcutsCard />
                    </>
                  )}
                  {section === "connection" && <ConnectionSection />}
                  {section === "sounds" && <SoundSettingsSection />}
                  {section === "offline" && <OfflineSettingsSection />}
                  {section === "recovery" && <RecoverySettingsSection />}
                  {section === "updates" && <UpdateSettingsSection />}
                </motion.div>
              </AnimatePresence>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
