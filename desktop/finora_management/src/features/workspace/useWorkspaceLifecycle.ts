import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { finora } from "@/api/finora";
import { CONFIG_QUERY_KEY } from "@/features/auth/LoginScreen";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";
import { allowedWindow, sessionScope, useWorkspace } from "./state";
import { openWorkspaceTarget } from "./navigation";

export function useWorkspaceLifecycle(): void {
  const session = useSession((s) => s.session);
  const signature = sessionScope(session);
  const config = useQuery({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: () => finora.config.get(),
    staleTime: Infinity,
  });
  const client = useQueryClient();
  const started = useRef("");
  useEffect(() => {
    if (!session || !config.data?.serverUrl) {
      useWorkspace.getState().reset();
      return;
    }
    useWorkspace.getState().activate(config.data.serverUrl, session);
    const state = useWorkspace.getState();
    if (started.current !== state.identity) {
      started.current = state.identity;
      if (state.prefs.home !== "workspace" && allowedWindow(state.prefs.home, session))
        openWorkspaceTarget({ window: state.prefs.home });
    }
  }, [signature, session, config.data?.serverUrl]);
  useEffect(() => {
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => void client.invalidateQueries({ queryKey: ["workspace"] }), 120);
    };
    const unsubscribe = useWindowManager.subscribe((state, previous) => {
      if (!state.active || state.active === previous.active) return;
      const workspace = useWorkspace.getState();
      const saved = workspace.saved.find((row) => row.window === state.active);
      workspace.record(saved ?? { window: state.active }, true);
    });
    // Every successful existing mutation invalidates summaries once; GETs never trigger it.
    const mutations = client.getMutationCache().subscribe((event) => {
      if (
        event.type === "updated" &&
        event.action.type === "success" &&
        !(
          event.mutation.options.mutationKey?.[0] === "workspace" &&
          event.mutation.options.mutationKey?.[1] === "assistant-read"
        )
      )
        refresh();
    });
    // Several native financial forms use the existing transport directly, outside useMutation.
    document.addEventListener("finora:form-saved", refresh);
    return () => {
      unsubscribe();
      mutations();
      clearTimeout(refreshTimer);
      document.removeEventListener("finora:form-saved", refresh);
    };
  }, [client]);
}
