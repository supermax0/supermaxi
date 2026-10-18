import { useMutation, useQueryClient } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import { useSession } from "@/stores/session";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => finora.auth.signOut(),
    onSuccess: () => {
      useWindowManager.getState().reset();
      useSession.getState().signedOut("signed_out");
      queryClient.clear();
    },
    onError: (error) => toast.error(toFinoraError(error).message),
  });
}
