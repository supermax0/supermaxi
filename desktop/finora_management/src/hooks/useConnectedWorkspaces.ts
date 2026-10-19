import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { create } from "zustand";
import { z } from "zod";
import { finoraCall } from "@/api/finora/transport";
import { desktopBridge, hasDesktopBridge } from "@/services/bridge";
import { useSession } from "@/stores/session";

export const useWorkspaceCapabilities = create<{ identity: string; pages: string[] }>(() => ({
  identity: "",
  pages: [],
}));
export function workspaceIdentity(session: unknown) {
  return JSON.stringify(session);
}
export function useConnectedWorkspaces() {
  const session = useSession((s) => s.session);
  const identity = workspaceIdentity(session);
  const capabilities = useQuery({
    queryKey: ["desktop", "workspace", identity],
    enabled: !!session && hasDesktopBridge() && !!desktopBridge().pages,
    queryFn: () =>
      finoraCall(
        { method: "GET", path: "/api/v1/desktop/workspace" },
        z.object({ ok: z.literal(true), pages: z.array(z.string()) }),
      ),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
  useEffect(() => {
    useWorkspaceCapabilities.setState({ identity, pages: capabilities.data?.pages ?? [] });
    return () => {
      useWorkspaceCapabilities.setState({ identity: "", pages: [] });
    };
  }, [identity, capabilities.data]);
}
