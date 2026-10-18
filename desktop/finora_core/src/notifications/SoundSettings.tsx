import { Volume2 } from "lucide-react";
import { FinoraButton } from "../ui/primitives";
import { useSound, type VoiceStatus } from "./preferences";
import { testNotificationSound } from "./useNotifications";

const STATUS: Record<VoiceStatus, string> = {
  ready: "الصوت جاهز",
  locked: "اضغط تجربة الصوت لتفعيل السماع",
  connecting: "جاري الاتصال بـ GPT Live…",
  speaking: "GPT Live يحچي الآن",
  unavailable: "GPT Live غير متاح حالياً؛ تبقى نغمة التنبيه شغالة",
};
export function SoundSettings() {
  const { preferences: p, status, update } = useSound();
  return (
    <section className="set-section sound-settings">
      <p className="kill-text">
        تنبيه قصير عند طلب موافقة أو مشكلة تحتاج انتباهك. صوت GPT Live مولّد بالذكاء الاصطناعي.
      </p>
      <ul className="set-rows">
        <li>
          <label htmlFor="notice-enabled">تنبيهات مسموعة</label>
          <input
            id="notice-enabled"
            type="checkbox"
            role="switch"
            checked={p.enabled}
            onChange={(e) => update({ enabled: e.target.checked })}
          />
        </li>
        <li>
          <label htmlFor="notice-mode">طريقة التنبيه</label>
          <select
            className="input"
            id="notice-mode"
            value={p.mode}
            disabled={!p.enabled}
            onChange={(e) => update({ mode: e.target.value === "live" ? "live" : "chime" })}
          >
            <option value="live">GPT Live يحچي</option>
            <option value="chime">نغمة فقط</option>
          </select>
        </li>
        <li>
          <label htmlFor="notice-volume">مستوى الصوت · {Math.round(p.volume * 100)}٪</label>
          <input
            id="notice-volume"
            type="range"
            min="0"
            max="100"
            value={Math.round(p.volume * 100)}
            disabled={!p.enabled}
            onChange={(e) => update({ volume: Number(e.target.value) / 100 })}
          />
        </li>
        <li>
          <label htmlFor="notice-approvals">طلبات الموافقة</label>
          <input
            id="notice-approvals"
            type="checkbox"
            role="switch"
            checked={p.approvals}
            disabled={!p.enabled}
            onChange={(e) => update({ approvals: e.target.checked })}
          />
        </li>
        <li>
          <label htmlFor="notice-important">الأحداث المهمة ومشاكل الإرسال</label>
          <input
            id="notice-important"
            type="checkbox"
            role="switch"
            checked={p.important}
            disabled={!p.enabled}
            onChange={(e) => update({ important: e.target.checked })}
          />
        </li>
      </ul>
      <p className="kill-text" role="status" aria-live="polite">
        {p.enabled
          ? p.mode === "chime"
            ? "نغمة التنبيه مفعّلة"
            : STATUS[status]
          : "التنبيهات الصوتية مكتومة"}
      </p>
      <FinoraButton
        disabled={!p.enabled || p.volume === 0 || status === "connecting" || status === "speaking"}
        onClick={testNotificationSound}
      >
        <Volume2 size={16} /> تجربة الصوت
      </FinoraButton>
      <p className="kill-text">
        التفضيلات محفوظة على جهازك. تشغيل GPT Live يحتاج اتصالاً بالخادم وإتاحة النموذج للمفتاح السحابي.
      </p>
    </section>
  );
}
