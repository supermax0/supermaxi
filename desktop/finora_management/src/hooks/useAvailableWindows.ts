import { useMemo } from "react";
import { useSession } from "@/stores/session";
import { WINDOW_IDS, WINDOWS, type WindowId } from "@/windows/registry";

/** Windows this user may open (FINORA still enforces the permission on every call). */
export function useAvailableWindows(): WindowId[] {
  const permissions = useSession((s) => s.session?.permissions);
  return useMemo(
    () =>
      WINDOW_IDS.filter((id) => {
        const needed = WINDOWS[id].permission;
        if (id === "products" && permissions?.includes("inventory.audit.view")) return true;
        return !needed || (permissions?.includes(needed) ?? false);
      }),
    [permissions],
  );
}
