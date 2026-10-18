import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { desktopBridge } from "@/services/bridge";
import { EMPTY_OFFLINE, useOffline } from "@/stores/offline";
import { useSession } from "@/stores/session";

export function useOfflineStatus(): void {
  const client = useQueryClient();
  const completed = useRef<string | null>(null);
  const session = useSession((s) => s.session);
  const signedIn = useSession((s) => s.status === "signed_in");
  const query = useQuery({
    queryKey: ["offline", session?.tenant.slug, session?.user.id, session?.branch?.id, session?.branch_scope],
    queryFn: () => desktopBridge().offline?.status() ?? Promise.resolve(EMPTY_OFFLINE),
    enabled: signedIn,
    refetchInterval: 2000,
    networkMode: "always",
    retry: false,
    placeholderData: undefined,
  });
  useEffect(() => {
    useOffline.getState().set(signedIn && query.data ? query.data : EMPTY_OFFLINE);
    if (!signedIn || !query.data) {
      completed.current = null;
      return;
    }
    const next =
      query.data.operations
        .filter((o) => o.status === "done")
        .map((o) => o.id)
        .sort()
        .join(",") +
      ":" +
      String(query.data.snapshot?.capturedAt ?? "") +
      ":" +
      String(query.data.hr?.savedAt ?? "");
    if (completed.current !== null && completed.current !== next) void client.invalidateQueries();
    completed.current = next;
  }, [signedIn, query.data, client]);
}
