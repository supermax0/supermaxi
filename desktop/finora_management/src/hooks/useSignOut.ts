import { desktopBridge, hasDesktopBridge } from "@/services/bridge";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import { useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ["auth", "signout"],
    mutationFn: async () => {
      const lifecycle = hasDesktopBridge() ? desktopBridge().lifecycle : undefined;
      if (lifecycle && !(await lifecycle.confirmLeave())) return false;
      await finora.auth.signOut();
      return true;
    },
    onSuccess: (done) => {
      if (!done) return;
      useWindowManager.getState().reset();
      useSession.getState().signedOut("signed_out");
      queryClient.clear();
    },
    onError: (error) => toast.error(toFinoraError(error).message),
  });
}
