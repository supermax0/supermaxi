import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { finora, FinoraApiError } from "@/api/finora";
import { useSession } from "@/stores/session";

export const SESSION_QUERY_KEY = ["finora", "session"] as const;
const REVALIDATE_MS = 5 * 60_000;

/** Startup check and periodic revalidation (picks up permission changes made in FINORA). */
export function useSessionProbe(): void {
  const status = useSession((s) => s.status);
  const query = useQuery({
    queryKey: SESSION_QUERY_KEY,
    queryFn: () => finora.auth.session(),
    retry: false,
    placeholderData: undefined,
    staleTime: 60_000,
    refetchInterval: status === "signed_in" ? REVALIDATE_MS : false,
    enabled: status !== "signed_out",
  });

  useEffect(() => {
    if (query.data) useSession.getState().signedIn(query.data);
  }, [query.data]);

  useEffect(() => {
    if (!query.error) return;
    const { status: current, signedOut } = useSession.getState();
    if (query.error instanceof FinoraApiError && query.error.endsSession) {
      signedOut(current === "signed_in" ? "expired" : null);
    } else if (current === "unknown") {
      // FINORA unreachable or not configured at startup: show sign-in (the banner explains the connection).
      signedOut(null);
    }
  }, [query.error]);
}
