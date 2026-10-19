import { PanelsTopLeft } from "lucide-react";
import { WORKSPACE_PAGES, type WorkspacePageId } from "@shared/workspacePages";
import { useWorkspaceCapabilities, workspaceIdentity } from "@/hooks/useConnectedWorkspaces";
import { desktopBridge } from "@/services/bridge";
import { toast } from "@/stores/toasts";
import { createContext, useContext, useMemo } from "react";
import type { Permission } from "@/api/finora/schemas";
import { useNavigationPrefs } from "@/stores/navigationPrefs";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { WINDOWS } from "@/windows/registry";
import { NAV_GROUPS } from "./config";
import type { NavGroup, NavItem } from "./types";

/** The navigation data. Defaults to NAV_GROUPS; tests and previews may provide their own. */
export const NavigationConfigContext = createContext<readonly NavGroup[]>(NAV_GROUPS);

function requiredPermission(item: NavItem): Permission | undefined {
  return (
    item.permission ?? (item.target.kind === "window" ? WINDOWS[item.target.window].permission : undefined)
  );
}

export interface Navigation {
  /** Non-empty groups the user may see, with only the items they may open. */
  groups: NavGroup[];
  /** Every visible item, in display order (search input for the menu and the palette). */
  items: NavItem[];
  byId: Map<string, NavItem>;
}

/** Visible navigation for the signed-in user. Prepared in memory — no request is needed to open the menu. */
export function useNavigation(): Navigation {
  const config = useContext(NavigationConfigContext);
  const permissions = useSession((s) => s.session?.permissions);
  const session = useSession((s) => s.session);
  const capabilities = useWorkspaceCapabilities();
  return useMemo(() => {
    const allowed = (item: NavItem) => {
      if (
        item.target.kind === "window" &&
        item.target.window === "products" &&
        permissions?.includes("inventory.audit.view")
      )
        return true;
      const needed = requiredPermission(item);
      return !needed || (permissions?.includes(needed) ?? false);
    };
    const connected: NavGroup[] =
      config === NAV_GROUPS &&
      capabilities.identity === workspaceIdentity(session) &&
      capabilities.pages.length
        ? [
            {
              id: "connected-workspaces",
              title: "مساحات العمل",
              items: capabilities.pages
                .filter((id) => id in WORKSPACE_PAGES)
                .map((id) => ({
                  id: `workspace-${id}`,
                  label: WORKSPACE_PAGES[id as WorkspacePageId].title,
                  icon: PanelsTopLeft,
                  description: "صفحة متصلة بخادم FINORA",
                  target: {
                    kind: "run" as const,
                    run: () => {
                      void desktopBridge()
                        .pages?.open(id)
                        .catch((error: unknown) =>
                          toast.error(error instanceof Error ? error.message : "تعذّر فتح الصفحة"),
                        );
                    },
                  },
                })),
            },
          ]
        : [];
    const groups = [...config, ...connected]
      .map((group) => ({ ...group, items: group.items.filter(allowed) }))
      .filter((group) => group.items.length > 0);
    const items = groups.flatMap((group) => group.items);
    return { groups, items, byId: new Map(items.map((item) => [item.id, item])) };
  }, [config, permissions, capabilities, session]);
}

/** Opens a navigation item through the app's existing navigation and remembers it as recently used. */
export function openNavItem(item: NavItem): void {
  useNavigationPrefs.getState().recordVisit(item.id);
  if (item.target.kind === "window") useWindowManager.getState().open(item.target.window);
  else item.target.run();
}
