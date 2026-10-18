import { Bell, LayoutGrid, Search, Settings } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import { registerNavAnchor } from "@/animations/anchors";
import { useNotifications } from "@/stores/notifications";
import { useUi } from "@/stores/ui";
import { useAvailableWindows } from "@/hooks/useAvailableWindows";
import { useHRNotifications } from "@/hooks/useHRNotifications";
import { WINDOWS } from "@/windows/registry";
import { BranchScopeSwitcher } from "./BranchScopeSwitcher";
import { FinoraLogo } from "./FinoraLogo";
import { IconButton } from "./IconButton";
import { MoreMenu } from "./more/MoreMenu";
import { NavButton } from "./NavButton";
import { NotificationsPanel } from "./NotificationsPanel";
import { Popover } from "./Popover";
import { SettingsDialog } from "./settings/SettingsDialog";
import { WindowControls } from "./WindowControls";

/**
 * The only chrome of the app: logo · window shortcuts · tools · native controls.
 * Laid out LTR like a Windows title bar (close button at the far right) while
 * every label inside stays RTL.
 */
export function TopNavigation() {
  useHRNotifications();
  const panel = useUi((s) => s.panel);
  const togglePanel = useUi((s) => s.togglePanel);
  const closePanel = useUi((s) => s.closePanel);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const unread = useNotifications((s) => s.unread);
  const windows = useAvailableWindows();
  const markAllRead = useNotifications((s) => s.markAllRead);
  const bellRef = useRef<HTMLButtonElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const extra = windows.filter((id) => WINDOWS[id].moreOnly);
    extra.forEach((id) => registerNavAnchor(id, moreRef.current));
    return () => extra.forEach((id) => registerNavAnchor(id, null));
  }, [windows]);

  const closeNotifications = useCallback(() => {
    closePanel();
    markAllRead();
  }, [closePanel, markAllRead]);

  return (
    <header
      dir="ltr"
      className="drag-region relative z-30 grid h-[var(--nav-height)] shrink-0 grid-cols-[1fr_auto_1fr] items-center px-6"
    >
      <div className="justify-self-start">
        <FinoraLogo />
      </div>

      <nav
        dir="rtl"
        aria-label="النوافذ"
        className="glass no-drag flex items-center gap-1 rounded-panel p-1.5"
      >
        {windows
          .filter((id) => !WINDOWS[id].moreOnly)
          .map((id) => (
            <NavButton key={id} id={id} />
          ))}
      </nav>

      <div className="no-drag flex items-center gap-1 justify-self-end">
        <IconButton
          ref={moreRef}
          label="المزيد"
          className="more-trigger"
          aria-haspopup="dialog"
          aria-expanded={panel === "more"}
          onClick={() => togglePanel("more")}
        >
          <LayoutGrid size={19} />
        </IconButton>
        <MoreMenu open={panel === "more"} anchor={moreRef} onClose={closePanel} />
        <BranchScopeSwitcher />
        <IconButton label="بحث سريع (Ctrl+K)" onClick={() => setPaletteOpen(true)}>
          <Search size={19} />
        </IconButton>
        <div className="relative">
          <IconButton
            ref={bellRef}
            label="الإشعارات"
            aria-expanded={panel === "notifications"}
            onClick={() => (panel === "notifications" ? closeNotifications() : togglePanel("notifications"))}
          >
            <Bell size={19} />
          </IconButton>
          {unread > 0 && (
            <span className="ltr-isolate pointer-events-none absolute right-1.5 top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
          <Popover
            open={panel === "notifications"}
            onClose={closeNotifications}
            anchor={bellRef}
            label="الإشعارات"
            align="start"
          >
            <NotificationsPanel />
          </Popover>
        </div>
        <IconButton
          label="الإعدادات"
          aria-expanded={panel === "settings"}
          onClick={() => togglePanel("settings")}
        >
          <Settings size={19} />
        </IconButton>
        <SettingsDialog open={panel === "settings"} onClose={closePanel} />
        <span className="mx-2 h-7 w-px bg-line" aria-hidden />
        <WindowControls />
      </div>
    </header>
  );
}
