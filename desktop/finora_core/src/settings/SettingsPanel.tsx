import {
  ArrowRight,
  BookOpen,
  BrainCircuit,
  Cable,
  ChevronLeft,
  LogOut,
  MessageSquareText,
  OctagonPause,
  Palette,
  Play,
  ShieldCheck,
  UserRound,
  Volume2,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { SoundSettings } from "../notifications/SoundSettings";
import { IntegrationSettings, type IntegrationSection } from "./IntegrationSettings";
import { useCan } from "../data/can";
import { HttpDataSource } from "../data/http";
import { useSetAutomationPaused, useSource, useStatus } from "../data/hooks";
import type { Connection } from "../data/schemas";
import { useUi, type AnimationQuality } from "../state/ui";
import { toast } from "../ui/toast";
import {
  Badge,
  ErrorState,
  FacebookIcon,
  FinoraButton,
  InstagramIcon,
  Skeleton,
  cx,
  errorText,
} from "../ui/primitives";

const CONN: Record<Connection, { label: string; tone: "green" | "red" | "amber" | "neutral" }> = {
  connected: { label: "متصل", tone: "green" },
  token_expired: { label: "انتهت صلاحية الرمز", tone: "red" },
  permission_missing: { label: "صلاحية ناقصة", tone: "amber" },
  webhook_invalid: { label: "Webhook غير صالح", tone: "red" },
  disconnected: { label: "غير متصل", tone: "red" },
  unknown: { label: "غير معروف", tone: "neutral" },
};

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { v: T; l: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.v}
          type="button"
          role="radio"
          aria-checked={value === o.v}
          className={cx(value === o.v && "is-active")}
          onClick={() => onChange(o.v)}
        >
          {o.l}
        </button>
      ))}
    </div>
  );
}

function KillSwitch({ paused }: { paused: boolean }) {
  const [reason, setReason] = useState("");
  const m = useSetAutomationPaused();
  const run = (next: boolean) =>
    m.mutate(
      { paused: next, reason },
      {
        onSuccess: () => {
          setReason("");
          toast.success(next ? "تم إيقاف كل الأتمتة" : "تم استئناف الأتمتة");
        },
        onError: (err) => toast.error(errorText(err)),
      },
    );
  return (
    <div className={cx("kill", paused && "is-paused")}>
      <p className="kill-text">
        {paused
          ? "الأتمتة متوقفة. الرسائل الواردة ما زالت تُجمع، لكن لا تُنفَّذ ردود أو إجراءات تلقائية."
          : "يوقف فوراً كل الردود والإجراءات التلقائية مع الاستمرار في استقبال الرسائل."}
      </p>
      {!paused && (
        <input
          className="input"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="سبب الإيقاف (مطلوب للسجل)"
          aria-label="سبب الإيقاف"
          maxLength={300}
        />
      )}
      {paused ? (
        <FinoraButton variant="primary" loading={m.isPending} onClick={() => run(false)}>
          <Play size={15} /> استئناف الأتمتة
        </FinoraButton>
      ) : (
        <FinoraButton
          variant="danger"
          loading={m.isPending}
          disabled={!reason.trim()}
          onClick={() => run(true)}
        >
          <OctagonPause size={16} /> إيقاف كل الأتمتة
        </FinoraButton>
      )}
    </div>
  );
}

const ROLE_LABEL = {
  super_admin: "Super Admin",
  admin: "Admin",
  sales: "مبيعات",
  support: "دعم",
  read_only: "عرض فقط",
} as const;

function Account({ src }: { src: HttpDataSource }) {
  const [busy, setBusy] = useState(false);
  const signOut = async () => {
    setBusy(true);
    try {
      await src.logout();
    } catch (err) {
      // The local session is cleared regardless; the server token expires on its own.
      console.warn("[finora-core] logout request failed", err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="set-section">
      <ul className="set-rows">
        <li>
          <span className="set-label">
            <strong dir="ltr">{src.operator.username}</strong>
          </span>
          <Badge tone="violet">{ROLE_LABEL[src.operator.role]}</Badge>
        </li>
        <li>
          <span className="set-label" dir="ltr">
            {new URL(src.baseUrl).host}
          </span>
          <FinoraButton size="sm" variant="ghost" loading={busy} onClick={() => void signOut()}>
            <LogOut size={14} /> تسجيل الخروج
          </FinoraButton>
        </li>
      </ul>
    </section>
  );
}

type SettingsSection = IntegrationSection | "account" | "appearance" | "system" | "sound";
const SECTIONS: Record<SettingsSection, { title: string; description: string; icon: LucideIcon }> = {
  account: { title: "الحساب", description: "بيانات الدخول والصلاحيات وتسجيل الخروج", icon: UserRound },
  sound: {
    title: "الصوت والإشعارات",
    description: "تنبيهات GPT Live والموافقات والأحداث المهمة",
    icon: Volume2,
  },
  meta: { title: "ربط Meta", description: "ربط Instagram وFacebook وفحص الاتصال", icon: Cable },
  telegram: { title: "بوت تلگرام", description: "ربط البوت واستقبال رسائل العملاء", icon: MessageSquareText },
  ai: {
    title: "الذكاء الاصطناعي",
    description: "النماذج المحلية والسحابية ومفاتيح الاتصال",
    icon: BrainCircuit,
  },
  replies: {
    title: "ردود العملاء",
    description: "طريقة الرد واللغة والنبرة وتجربة الردود",
    icon: MessageSquareText,
  },
  knowledge: {
    title: "معرفة النظام",
    description: "مميزات فينورا وأدلة الاستخدام التي يعتمدها المساعد",
    icon: BookOpen,
  },
  appearance: { title: "المظهر", description: "جودة الحركة وإعدادات العرض على جهازك", icon: Palette },
  system: {
    title: "النظام والأتمتة",
    description: "حالة الخادم والتحكم بالردود والإجراءات التلقائية",
    icon: ShieldCheck,
  },
};

export function SettingsPanel() {
  const status = useStatus();
  const src = useSource();
  const appearance = useUi((s) => s.appearance);
  const setAppearance = useUi((s) => s.setAppearance);
  const canManage = useCan("settings.manage");
  const [section, setSection] = useState<SettingsSection | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const connected = src instanceof HttpDataSource;
  const integrations = connected && canManage;
  const selected = section ? SECTIONS[section] : null;
  useEffect(() => {
    if (section) heading.current?.focus();
    root.current?.closest(".sheet-body")?.scrollTo({ top: 0 });
  }, [section]);
  const cards = (items: SettingsSection[]) => (
    <div className="settings-grid">
      {items.map((id) => {
        const item = SECTIONS[id];
        const Icon = item.icon;
        return (
          <button
            className="settings-card"
            type="button"
            key={id}
            onClick={() => setSection(id)}
            aria-label={item.title}
          >
            <span className="settings-card-icon">
              <Icon size={21} aria-hidden="true" />
            </span>
            <span className="settings-card-copy">
              <strong>{item.title}</strong>
              <span>{item.description}</span>
            </span>
            <ChevronLeft size={16} className="settings-card-arrow" aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="settings" ref={root}>
      {!section ? (
        <>
          <div className="settings-intro">
            <p>كل إعداد بمكانه</p>
            <span>اختَر القسم اللي تريد تضبطه.</span>
          </div>
          {integrations && (
            <section className="set-section">
              <h3>التواصل والذكاء</h3>
              {cards(["meta", "telegram", "ai", "replies", "knowledge"])}
            </section>
          )}
          <section className="set-section">
            <h3>التطبيق والتحكم</h3>
            {cards(
              connected ? ["account", "sound", "appearance", "system"] : ["sound", "appearance", "system"],
            )}
          </section>
        </>
      ) : (
        <div className="settings-section-head">
          <FinoraButton size="sm" variant="ghost" onClick={() => setSection(null)}>
            <ArrowRight size={15} /> كل الإعدادات
          </FinoraButton>
          <h3 ref={heading} tabIndex={-1}>
            {selected?.title}
          </h3>
          <p>{selected?.description}</p>
        </div>
      )}
      {section === "account" && src instanceof HttpDataSource && <Account src={src} />}
      {section === "sound" && <SoundSettings />}
      {section === "meta" && (
        <section className="set-section">
          <h3>حالة القنوات</h3>
          {status.isPending ? (
            <Skeleton w="100%" h={90} r={14} />
          ) : status.isError ? (
            <ErrorState error={status.error} onRetry={() => void status.refetch()} />
          ) : (
            <ul className="set-rows">
              <li>
                <span className="set-label">
                  <InstagramIcon size={18} /> Instagram
                </span>
                <Badge tone={CONN[status.data.channels.instagram].tone}>
                  {CONN[status.data.channels.instagram].label}
                </Badge>
              </li>
              <li>
                <span className="set-label">
                  <FacebookIcon size={18} /> Facebook
                </span>
                <Badge tone={CONN[status.data.channels.facebook].tone}>
                  {CONN[status.data.channels.facebook].label}
                </Badge>
              </li>
            </ul>
          )}
        </section>
      )}
      {integrations && src instanceof HttpDataSource && (
        <IntegrationSettings
          src={src}
          section={
            section === "ai" ||
            section === "replies" ||
            section === "meta" ||
            section === "telegram" ||
            section === "knowledge"
              ? section
              : null
          }
        />
      )}
      {section === "system" && (
        <>
          <section className="set-section">
            <h3>الأتمتة</h3>
            {status.isPending ? (
              <Skeleton w="100%" h={90} r={14} />
            ) : status.isError ? (
              <ErrorState error={status.error} onRetry={() => void status.refetch()} />
            ) : canManage ? (
              <KillSwitch paused={status.data.automationPaused} />
            ) : (
              <p className="kill-text">
                {status.data.automationPaused ? "الأتمتة متوقفة حالياً" : "الأتمتة تعمل"} — التغيير يتطلب
                صلاحية الإعدادات
              </p>
            )}
            {status.data?.devLoopback && (
              <p className="set-warn" role="note">
                وضع التطوير: الرسائل اليدوية لا تُرسل فعلياً إلى Meta (loopback)
              </p>
            )}
          </section>

          <section className="set-section">
            <h3>FINORA</h3>
            <ul className="set-rows">
              <li>
                <span className="set-label">مصدر البيانات</span>
                <Badge tone={src.kind === "development" ? "amber" : "green"}>
                  {src.kind === "development" ? "بيانات تطوير محلية" : "خادم FINORA"}
                </Badge>
              </li>
              <li>
                <span className="set-label">البيئة</span>
                <span dir="ltr">{status.data?.environment ?? "—"}</span>
              </li>
            </ul>
          </section>
        </>
      )}

      {section === "appearance" && (
        <section className="set-section settings-appearance">
          <div className="set-field">
            <span className="set-label">جودة الحركة</span>
            <Segmented<AnimationQuality>
              label="جودة الحركة"
              value={appearance.quality}
              onChange={(quality) => setAppearance({ quality })}
              options={[
                { v: "high", l: "عالية" },
                { v: "balanced", l: "متوازنة" },
                { v: "low", l: "منخفضة" },
              ]}
            />
          </div>
          <div className="set-field">
            <span className="set-label">تقليل الحركة</span>
            <Segmented
              label="تقليل الحركة"
              value={appearance.reducedMotion}
              onChange={(reducedMotion) => setAppearance({ reducedMotion })}
              options={[
                { v: "system", l: "حسب النظام" },
                { v: "on", l: "مفعل" },
                { v: "off", l: "متوقف" },
              ]}
            />
          </div>
        </section>
      )}
    </div>
  );
}
