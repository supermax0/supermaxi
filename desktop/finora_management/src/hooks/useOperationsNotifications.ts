import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { finora } from "@/api/finora";
import { useSession } from "@/stores/session";
import { useConnection } from "@/stores/connection";
import { useNotifications } from "@/stores/notifications";
import { desktopBridge, hasDesktopBridge } from "@/services/bridge";
import { sessionScope, useWorkspace } from "@/features/workspace/state";

export function useOperationsNotifications() {
  const session = useSession((s) => s.session),
    online = useConnection((s) => s.status === "online");
  const identity = JSON.stringify(session),
    latest = useRef<number | null>(null);
  const workspaceScope = useWorkspace((s) => s.scope);
  const workspaceIdentity = `${workspaceScope}:${sessionScope(session)}`;
  const enabled = hasDesktopBridge() && !!desktopBridge().lifecycle && online && !!session;
  const orders = useQuery({
    queryKey: ["desktop", "alerts", "orders", identity],
    enabled: enabled && !!session?.permissions.includes("can_see_orders"),
    queryFn: () =>
      finora.orders.list({ tab: "all", page: 1, pageSize: 1, sortField: "order_id", sortDir: "desc" }),
    refetchInterval: 30_000,
  });
  const stock = useQuery({
    queryKey: ["workspace", "stock", workspaceIdentity],
    enabled: enabled && !!workspaceScope && !!session?.permissions.includes("can_manage_inventory"),
    queryFn: () => finora.products.list({ page: 1, pageSize: 1 }),
    refetchInterval: 60_000,
  });
  useEffect(() => {
    latest.current = null;
    useNotifications.getState().clearOperations();
    return () => useNotifications.getState().clearOperations();
  }, [identity]);
  useEffect(() => {
    const id = orders.data?.rows[0]?.id;
    if (id === undefined) return;
    if (latest.current !== null && id > latest.current)
      useNotifications.getState().add({
        group: "operations",
        tone: "info",
        title: "وصل طلب جديد",
        body: `آخر طلب ظاهر لحسابك: #${id}؛ افتح الطلبات لمراجعته.`,
        windowTarget: "orders",
      });
    latest.current = id;
  }, [orders.data]);
  useEffect(() => {
    if (!stock.data) return;
    const stats = stock.data.stats;
    useNotifications.getState().replaceOperations(
      stats.low + stats.out > 0
        ? [
            {
              group: "operations",
              key: `stock:${stats.low}:${stats.out}`,
              tone: "warning",
              title: "تنبيه المخزون",
              body: `${stats.low} منتج منخفض المخزون و${stats.out} نافد ضمن نطاق حسابك.`,
              windowTarget: "products",
              at: Date.now(),
            },
          ]
        : [],
    );
  }, [stock.data]);
}
