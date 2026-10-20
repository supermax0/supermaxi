import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { finora } from "@/api/finora";
import { CONFIG_QUERY_KEY } from "@/features/auth/LoginScreen";
import { useSession } from "@/stores/session";
import { useDisplayTime } from "@/stores/displayTime";

export function useDisplayPreferences(sync = false) {
  const session = useSession((state) => state.session);
  const config = useQuery({ queryKey: CONFIG_QUERY_KEY, queryFn: finora.config.get, staleTime: Infinity });
  const key = [
    "display-preferences",
    config.data?.serverUrl,
    session?.tenant.slug,
    session?.user.id,
  ] as const;
  const query = useQuery({
    queryKey: key,
    queryFn: finora.displayPreferences.get,
    enabled: Boolean(session && config.data?.serverUrl),
    retry: false,
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
  });
  useEffect(() => {
    if (!sync || !query.data || !session) return;
    const format = query.data.time_format;
    useDisplayTime.getState().setFormat(format);
    if (format !== (session.display_time_format ?? "12")) {
      let current = true;
      void finora.auth
        .session()
        .then((fresh) => {
          if (
            current &&
            fresh.user.id === session.user.id &&
            fresh.tenant.slug === session.tenant.slug &&
            useSession.getState().session?.user.id === session.user.id &&
            useSession.getState().session?.tenant.slug === session.tenant.slug
          )
            useSession
              .getState()
              .signedIn({ ...fresh, display_time_format: fresh.display_time_format ?? format });
        })
        .catch(() => {
          /* Keep the current scope and last verified display setting while offline. */
        });
      return () => {
        current = false;
      };
    }
  }, [query.data, session, sync, config.data?.serverUrl]);
  return { ...query, queryKey: key };
}
