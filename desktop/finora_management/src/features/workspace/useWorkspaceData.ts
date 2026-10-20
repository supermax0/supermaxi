import { useQuery } from "@tanstack/react-query";
import { finora } from "@/api/finora";
import { workspaceApi } from "@/api/finora/workspace";
import { useSession } from "@/stores/session";
import { useOffline } from "@/stores/offline";
import { useWindowManager } from "@/stores/windowManager";
import { useHRAlerts } from "@/hooks/useHRNotifications";
import { useConnection } from "@/stores/connection";
import { sessionScope, useWorkspace } from "./state";

export function useWorkspaceData() {
  const session = useSession((s) => s.session);
  const scope = useWorkspace((s) => s.scope);
  const ready = useWorkspace((s) => s.ready);
  const active = useWindowManager((s) => s.active === null);
  const offline = useOffline((s) => s.status);
  const online = useConnection((s) => s.status === "online");
  const identity = `${scope}:${sessionScope(session)}`;
  const can = (permission: string) => session?.permissions.some((p) => p === permission) ?? false;
  const enabled = ready && active;
  const hr = useHRAlerts(enabled && can("hr.view"), false);
  const options = {
    staleTime: 60_000,
    placeholderData: undefined,
    refetchInterval: enabled && online ? 60_000 : (false as const),
  };
  const sales = useQuery({
    ...options,
    queryKey: ["workspace", "sales", identity],
    queryFn: workspaceApi.sales,
    enabled: enabled && can("view_reports"),
  });
  const orders = useQuery({
    ...options,
    queryKey: ["workspace", "orders", identity],
    queryFn: () => finora.orders.counts({}),
    enabled: enabled && can("can_see_orders"),
  });
  const stock = useQuery({
    ...options,
    queryKey: ["workspace", "stock", identity],
    queryFn: () => finora.products.list({ page: 1, pageSize: 1 }),
    enabled: enabled && can("can_manage_inventory"),
  });
  const receivables = useQuery({
    ...options,
    queryKey: ["workspace", "receivables", identity],
    queryFn: workspaceApi.receivables,
    enabled: enabled && can("manage_customers"),
  });
  const activity = useQuery({
    ...options,
    queryKey: ["workspace", "activity", identity, 0],
    queryFn: () => workspaceApi.activity(),
    enabled,
  });
  const counts = orders.data;
  const shipping = useQuery({
    ...options,
    queryKey: ["workspace", "shipping", identity],
    queryFn: workspaceApi.shipping,
    enabled: enabled && can("can_see_shipping"),
  });
  const ordered = counts?.ordered;
  const activeOrders = counts
    ? [counts.ordered, counts.packed, counts.shipping].some((value) => value !== undefined)
      ? [counts.ordered, counts.packed, counts.shipping].reduce<number>((sum, value) => sum + (value ?? 0), 0)
      : counts.all
    : undefined;
  const syncIssues = offline.conflicts || (offline.error ? 1 : 0);
  const hasTaskData =
    (!can("can_see_orders") || !!orders.data) &&
    (!can("can_manage_inventory") || !!stock.data) &&
    (!can("can_see_shipping") || !!shipping.data) &&
    (!can("hr.view") || !online || !!hr.data);
  const attention = hasTaskData
    ? (ordered ?? 0) +
      (stock.data?.stats.low ?? 0) +
      (stock.data?.stats.out ?? 0) +
      syncIssues +
      (shipping.data?.value.open_manifests ?? 0) +
      (can("hr.view") ? new Set(hr.data?.items.map((item) => item.key)).size : 0)
    : undefined;
  const refreshAttention = () =>
    Promise.all([
      ...(can("can_see_orders") ? [orders.refetch()] : []),
      ...(can("can_manage_inventory") ? [stock.refetch()] : []),
      ...(can("can_see_shipping") ? [shipping.refetch()] : []),
      ...(can("hr.view") && online ? [hr.refetch()] : []),
    ]);
  return {
    sales,
    orders,
    stock,
    receivables,
    activity,
    shipping,
    hr,
    ordered,
    activeOrders,
    attention,
    attentionError: orders.isError || stock.isError || shipping.isError || (can("hr.view") && hr.isError),
    syncIssues,
    can,
    identity,
    refreshAttention,
  };
}
