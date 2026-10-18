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
    const groups = config
      .map((group) => ({ ...group, items: group.items.filter(allowed) }))
      .filter((group) => group.items.length > 0);
    const items = groups.flatMap((group) => group.items);
    return { groups, items, byId: new Map(items.map((item) => [item.id, item])) };
  }, [config, permissions]);
}

/** Opens a navigation item through the app's existing navigation and remembers it as recently used. */
export function openNavItem(item: NavItem): void {
  useNavigationPrefs.getState().recordVisit(item.id);
  if (item.target.kind === "window") useWindowManager.getState().open(item.target.window);
  else item.target.run();
}
