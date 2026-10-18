import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { finora } from "@/api/finora";
import { useSession } from "@/stores/session";
import { useConnection } from "@/stores/connection";
import { useNotifications } from "@/stores/notifications";
export function useHRNotifications() {
  const session = useSession((s) => s.session);
  const online = useConnection((s) => s.status === "online");
  const enabled = !!session?.permissions.some((p) => p === "hr.view" || p === "hr.self");
  const identity = JSON.stringify([
    session?.tenant.id,
    session?.user.id,
    session?.branch?.id,
    session?.permissions,
    session?.hr_scope_revision,
  ]);
  const alerts = useQuery({
    queryKey: ["hr", "notifications", identity],
    queryFn: finora.hr.notifications,
    enabled: enabled && online,
    refetchInterval: 60000,
  });
  useEffect(() => {
    useNotifications.getState().replaceHR([]);
    return () => useNotifications.getState().replaceHR([]);
  }, [identity]);
  useEffect(() => {
    if (alerts.data)
      useNotifications.getState().replaceHR(
        alerts.data.items.map((item) => ({
          group: "hr",
          key: item.key,
          tone: item.tone,
          title: item.title,
          body: item.body,
          at: Date.parse(item.date.length === 10 ? item.date + "T00:00:00+03:00" : item.date) || Date.now(),
          target: { tab: item.tab, person_id: item.person_id, date: item.date, month: item.month },
        })),
      );
  }, [alerts.data]);
}
