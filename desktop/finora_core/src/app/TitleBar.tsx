import { Bell, Copy, Minus, Settings, Square, Volume2, VolumeX, X } from "lucide-react";
import { useSound } from "../notifications/preferences";
import { useEffect, useState } from "react";
import { useApprovals, useOnline, useStatus } from "../data/hooks";
import { useUi } from "../state/ui";
import { useSupportIssues } from "../data/accountHooks";
import { FinoraMark, IconButton, cx } from "../ui/primitives";
import { isTauri, windowControls } from "./native";

export function TitleBar({ devData }: { devData: boolean }) {
  const status = useStatus();
  const approvals = useApprovals();
  const issues = useSupportIssues();
  const online = useOnline();
  const setOverlay = useUi((s) => s.setOverlay);
  const overlay = useUi((s) => s.overlay);
  const sound = useSound((s) => s.preferences.enabled);
  const updateSound = useSound((s) => s.update);

  const paused = status.data?.automationPaused ?? false;
  const shadow = status.data?.shadowMode ?? false;
  const live = online && !status.isError;
  const label = !online
    ? "Offline"
    : status.isError
      ? "غير متصل"
      : paused
        ? "Paused"
        : shadow
          ? "Shadow"
          : "Live";
  const pending = (approvals.data?.length ?? 0) + (issues.data?.length ?? 0);
  const env = status.data?.environment;

  return (
    <header className="titlebar" data-tauri-drag-region>
      <div className="tb-brand" data-tauri-drag-region>
        <FinoraMark size={30} />
        <div className="tb-wordmark" data-tauri-drag-region>
          <span className="tb-name">FINORA</span>
          <span className="tb-sub">SUPER ADMIN</span>
        </div>
        {env && env !== "production" && (
          <span className="env-chip" title="بيئة غير إنتاجية">
            {devData ? "DEV DATA" : env.toUpperCase()}
          </span>
        )}
      </div>

      <div className="tb-actions">
        <button
          type="button"
          className={cx(
            "live-pill",
            !live && "is-off",
            paused && "is-paused",
            shadow && !paused && "is-shadow",
          )}
          title={shadow ? "وضع الظل: FINORA CORE يقترح فقط ولا يرسل أو ينفذ" : undefined}
          onClick={() => setOverlay(overlay === "settings" ? "none" : "settings")}
          aria-label={`حالة النظام: ${label}`}
        >
          <span className="live-dot" />
          {label}
        </button>
        <span className="tb-sep" />
        <IconButton
          label={sound ? "كتم صوت التنبيهات" : "تشغيل صوت التنبيهات"}
          className="tb-icon"
          onClick={() => updateSound({ enabled: !sound })}
        >
          {sound ? <Volume2 size={19} /> : <VolumeX size={19} />}
        </IconButton>
        <IconButton
          label={pending ? `${pending} إشعار ومراجعة` : "الإشعارات"}
          className="tb-icon"
          onClick={() => setOverlay(overlay === "activity" ? "none" : "activity")}
        >
          <Bell size={19} />
          {pending > 0 && <span className="tb-count">{pending}</span>}
        </IconButton>
        <IconButton
          label="الإعدادات"
          className="tb-icon"
          onClick={() => setOverlay(overlay === "settings" ? "none" : "settings")}
        >
          <Settings size={19} />
        </IconButton>
        {isTauri() && (
          <>
            <span className="tb-sep" />
            <WindowControls />
          </>
        )}
      </div>
    </header>
  );
}

/** Native window buttons for the frameless Tauri window (renders nothing in the browser). */
export function WindowControls() {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!isTauri()) return;
    return windowControls.onResized(setMaximized);
  }, []);
  if (!isTauri()) return null;
  return (
    <div className="win-controls">
      <IconButton label="تصغير" className="win-btn" onClick={() => void windowControls.minimize()}>
        <Minus size={17} />
      </IconButton>
      <IconButton
        label={maximized ? "استعادة" : "تكبير"}
        className="win-btn"
        onClick={() => void windowControls.toggleMaximize()}
      >
        {maximized ? <Copy size={14} /> : <Square size={14} />}
      </IconButton>
      <IconButton label="إغلاق" className="win-btn is-close" onClick={() => void windowControls.close()}>
        <X size={18} />
      </IconButton>
    </div>
  );
}
