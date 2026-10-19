import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { useState } from "react";
import { Toaster } from "@/components/Toaster";
import { LoginScreen } from "@/features/auth/LoginScreen";
import { useFinoraLifecycle } from "@/hooks/useFinoraLifecycle";
import { useSessionProbe } from "@/hooks/useSessionProbe";
import { useOfflineStatus } from "@/hooks/useOfflineStatus";
import { useInterfaceSounds } from "@/hooks/useInterfaceSounds";
import { usePreferences } from "@/stores/preferences";
import { useSession } from "@/stores/session";
import { createQueryClient } from "./queryClient";
import { useExitProtection } from "@/hooks/useExitProtection";
import { Shell } from "./Shell";

function SessionGate() {
  useExitProtection();
  useSessionProbe();
  useFinoraLifecycle();
  useOfflineStatus();
  const status = useSession((s) => s.status);

  return (
    <AnimatePresence mode="wait" initial={false}>
      {status === "unknown" ? (
        <motion.div
          key="boot"
          className="grid h-full place-items-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1, transition: { delay: 0.3 } }}
          exit={{ opacity: 0 }}
          aria-busy
          aria-label="جارٍ الاتصال بـ FINORA"
        >
          <span className="h-1 w-24 overflow-hidden rounded-full bg-line">
            <span className="block h-full w-1/3 animate-[boot_1.1s_ease-in-out_infinite] rounded-full bg-violet" />
          </span>
        </motion.div>
      ) : status === "signed_in" ? (
        <motion.div
          key="shell"
          className="h-full"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <Shell />
        </motion.div>
      ) : (
        <motion.div
          key="login"
          className="h-full"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <LoginScreen />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function App({ queryClient }: { queryClient?: QueryClient }) {
  useInterfaceSounds();
  const [client] = useState(() => queryClient ?? createQueryClient());
  const motionPreference = usePreferences((s) => s.motion);

  return (
    <QueryClientProvider client={client}>
      <MotionConfig reducedMotion={motionPreference === "reduced" ? "always" : "user"}>
        <SessionGate />
        <Toaster />
      </MotionConfig>
    </QueryClientProvider>
  );
}
