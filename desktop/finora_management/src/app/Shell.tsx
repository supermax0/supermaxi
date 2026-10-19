import { HomeDashboard } from "@/components/HomeDashboard";
import { useConnectedWorkspaces } from "@/hooks/useConnectedWorkspaces";
import { useOperationsNotifications } from "@/hooks/useOperationsNotifications";
import { LogOut, Maximize, Settings, type LucideIcon } from "lucide-react";
import { useMemo } from "react";
import { CommandPalette, type Command } from "@/components/CommandPalette";
import { OfflineBanner } from "@/components/OfflineBanner";
import { TopNavigation } from "@/components/TopNavigation";
import { useHotkeys } from "@/hooks/useHotkeys";
import { useSignOut } from "@/hooks/useSignOut";
import { desktopBridge } from "@/services/bridge";
import { overlayOpen, useUi } from "@/stores/ui";
import { useWindowManager } from "@/stores/windowManager";
import { WINDOWS } from "@/windows/registry";
import { useAvailableWindows } from "@/hooks/useAvailableWindows";
import { useIdlePrefetch } from "@/hooks/useIdlePrefetch";
import { openNavItem, useNavigation } from "@/navigation/useNavigation";
import { WindowTransitionManager } from "@/windows/WindowTransitionManager";

function windowCommand(icon: LucideIcon, id: string, label: string, run: () => void, hint?: string): Command {
  return { id, icon, label, run, hint };
}

export function Shell() {
  useConnectedWorkspaces();
  useOperationsNotifications();
  const paletteOpen = useUi((s) => s.paletteOpen);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const signOut = useSignOut();
  const { mutate: signOutMutate } = signOut;
  const windows = useAvailableWindows();
  const navigation = useNavigation();
  useIdlePrefetch(windows);

  const commands = useMemo<Command[]>(
    () => [
      ...windows
        .filter(
          (id) =>
            !WINDOWS[id].moreOnly &&
            !navigation.items.some((item) => item.target.kind === "window" && item.target.window === id),
        )
        .map((id) => {
          const definition = WINDOWS[id];
          return {
            ...windowCommand(
              definition.icon,
              `open-${id}`,
              `فتح ${definition.title}`,
              () => useWindowManager.getState().open(id),
              `Ctrl+${definition.shortcut}`,
            ),
            keywords: [definition.navLabel],
          };
        }),
      // Pages from the navigation config — one data source for «المزيد» and the palette.
      ...navigation.items.map((item): Command => ({
        id: `nav-${item.id}`,
        label: item.label,
        icon: item.icon,
        keywords: [...(item.keywords ?? []), ...(item.description ? [item.description] : [])],
        hint: item.target.kind === "window" ? `Ctrl+${WINDOWS[item.target.window].shortcut}` : undefined,
        run: () => openNavItem(item),
      })),
      windowCommand(Maximize, "toggle-maximize", "تكبير / استعادة نافذة التطبيق", () => {
        desktopBridge()
          .window.toggleMaximize()
          .catch((error: unknown) => console.error("[window] toggle failed", error));
      }),
      windowCommand(Settings, "settings", "الإعدادات", () => useUi.getState().togglePanel("settings")),
      windowCommand(LogOut, "sign-out", "تسجيل الخروج", () => signOutMutate()),
    ],
    [navigation.items, signOutMutate, windows],
  );

  useHotkeys({
    "ctrl+k": () => setPaletteOpen(!useUi.getState().paletteOpen),
    ...Object.fromEntries(
      windows.map((id) => [`ctrl+${WINDOWS[id].shortcut}`, () => useWindowManager.getState().toggle(id)]),
    ),
    escape: () => {
      if (!overlayOpen()) useWindowManager.getState().close();
    },
  });

  return (
    <div className="relative flex h-full flex-col">
      <TopNavigation />
      <OfflineBanner />
      <div className="relative flex min-h-0 flex-1 flex-col">
        <HomeDashboard />
        <WindowTransitionManager />
      </div>
      <CommandPalette open={paletteOpen} commands={commands} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
