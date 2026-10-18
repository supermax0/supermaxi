import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { finora } from "@/api/finora";
import { onTransportOutcome } from "@/api/finora/transportEvents";
import { useConnection, type ConnectionStatus } from "@/stores/connection";
import { useNotifications } from "@/stores/notifications";
import { useSession } from "@/stores/session";
import { useWindowManager } from "@/stores/windowManager";

const PROBE_INTERVAL_MS = 8_000;

/**
 * App-wide reactions to the transport: session expiry → sign-in screen,
 * connection loss → banner + read-only, reconnect → refetch everything.
 */
export function useFinoraLifecycle(): void {
  const queryClient = useQueryClient();
  const status = useConnection((s) => s.status);

  useEffect(() => {
    let previous: ConnectionStatus = useConnection.getState().status;
    const unsubscribeConnection = useConnection.subscribe((state) => {
      if (state.status === previous) return;
      const notify = useNotifications.getState().add;
      if (state.status === "online") {
        notify({ tone: "success", title: "تمت استعادة الاتصال", body: "تم تحديث البيانات من FINORA." });
        void queryClient.invalidateQueries();
      } else if (previous === "online") {
        notify({
          tone: "warning",
          title: "انقطع الاتصال بـ FINORA",
          body: "تُعرض آخر البيانات المحفوظة؛ مسودات بيع المورد تنتظر تحقق السيرفر عند عودة الاتصال.",
        });
      }
      previous = state.status;
    });

    const unsubscribeTransport = onTransportOutcome((error) => {
      const connection = useConnection.getState();
      if (!error || !error.isConnectivity) {
        if (navigator.onLine !== false) connection.setStatus("online");
      } else {
        connection.setStatus(navigator.onLine === false ? "offline" : "unreachable");
      }
      if (error?.endsSession && useSession.getState().status === "signed_in") {
        useSession
          .getState()
          .signedOut(error.kind === "password_change_required" ? "password_change_required" : "expired");
        useWindowManager.getState().reset();
        queryClient.clear();
        useNotifications.getState().add({
          tone: "warning",
          title: "انتهت الجلسة",
          body: "سجّل الدخول من جديد للمتابعة.",
        });
      }
    });

    const goOffline = () => useConnection.getState().setStatus("offline");
    const goOnline = () => {
      // The OS says we are back; confirm FINORA itself answers before declaring online.
      useConnection.getState().setStatus("unreachable");
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    return () => {
      unsubscribeConnection();
      unsubscribeTransport();
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, [queryClient]);

  // While FINORA is unreachable, probe gently until it answers (any answer means reachable).
  useEffect(() => {
    if (status === "online") return;
    const timer = window.setInterval(() => {
      finora.auth.session().catch((error: unknown) => {
        if (import.meta.env.DEV) console.debug("[connection] probe", error);
      });
    }, PROBE_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [status]);
}
