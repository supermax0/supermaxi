import { BellOff, CheckCircle2, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import { useNotifications, type NotificationTone } from "@/stores/notifications";
import { cn } from "@/utils/cn";
import { formatTime } from "@/utils/format";
import { useHRNavigation } from "@/stores/hrNavigation";
import { useWindowManager } from "@/stores/windowManager";
import { useUi } from "@/stores/ui";

const TONE_ICON: Record<NotificationTone, { icon: LucideIcon; className: string }> = {
  info: { icon: Info, className: "text-azure" },
  warning: { icon: TriangleAlert, className: "text-warning" },
  success: { icon: CheckCircle2, className: "text-success" },
};

export function NotificationsPanel() {
  const items = useNotifications((s) => s.items);
  const clear = useNotifications((s) => s.clear);

  return (
    <div className="w-[340px]">
      <div className="flex items-center justify-between px-3 pb-2 pt-1.5">
        <h2 className="text-sm font-semibold text-ink">الإشعارات</h2>
        {items.length > 0 && (
          <button type="button" onClick={clear} className="text-xs text-violet-deep hover:underline">
            مسح الكل
          </button>
        )}
      </div>
      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-4 py-8 text-center text-sm text-ink-faint">
          <BellOff size={22} aria-hidden />
          لا توجد إشعارات
        </div>
      ) : (
        <ul className="max-h-[360px] space-y-1 overflow-y-auto">
          {items.map((item) => {
            const tone = TONE_ICON[item.tone];
            const Icon = tone.icon;
            return (
              <li key={item.id} className="flex gap-3 rounded-control px-3 py-2.5 hover:bg-white/70">
                <Icon size={18} className={cn("mt-0.5 shrink-0", tone.className)} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-sm font-medium text-ink">{item.title}</p>
                    <time className="ltr-isolate shrink-0 text-[11px] text-ink-faint">
                      {formatTime(item.at)}
                    </time>
                  </div>
                  <p className="mt-0.5 text-xs leading-5 text-ink-soft">{item.body}</p>
                  {item.windowTarget && (
                    <button
                      type="button"
                      className="mt-2 text-xs text-violet hover:underline"
                      onClick={() => {
                        if (item.windowTarget) useWindowManager.getState().open(item.windowTarget);
                        useUi.getState().closePanel();
                      }}
                    >
                      فتح الصفحة
                    </button>
                  )}
                  {item.target && (
                    <button
                      type="button"
                      className="mt-2 text-xs text-violet hover:underline"
                      onClick={() => {
                        useHRNavigation.getState().set(item.target ?? null);
                        useWindowManager.getState().open("employees");
                        useUi.getState().closePanel();
                      }}
                    >
                      فتح الإجراء
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
