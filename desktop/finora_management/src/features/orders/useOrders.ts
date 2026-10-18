import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { finora, toFinoraError } from "@/api/finora";
import type {
  OrderFilters,
  OrderPayment,
  OrdersPage,
  OrdersQuery,
  QuickOrderEdit,
} from "@/api/finora/orders";
import { canMutate } from "@/stores/connection";
import { toast } from "@/stores/toasts";
import { formatIqd } from "@/utils/money";
import { orderStatusStyle } from "./status";

const POLL_MS = 20_000;

export const ordersKeys = {
  all: ["orders"] as const,
  list: (query: OrdersQuery) => ["orders", "list", query] as const,
  counts: (filters: OrderFilters) => ["orders", "counts", filters] as const,
  lookups: ["orders", "lookups"] as const,
  details: (id: number) => ["orders", "details", id] as const,
};

/** Loads once the window is built (even hidden); smart polling only while it is open. */
export function useOrdersList(query: OrdersQuery, active: boolean) {
  return useQuery({
    queryKey: ordersKeys.list(query),
    queryFn: () => finora.orders.list(query),
    refetchInterval: active ? POLL_MS : false,
  });
}

export function useOrderCounts(filters: OrderFilters, active: boolean) {
  return useQuery({
    queryKey: ordersKeys.counts(filters),
    queryFn: () => finora.orders.counts(filters),
    refetchInterval: active ? POLL_MS : false,
  });
}

export function useOrderLookups() {
  return useQuery({
    queryKey: ordersKeys.lookups,
    queryFn: () => finora.orders.lookups(),
    staleTime: 5 * 60_000,
  });
}

export function useOrderDetails(id: number | null) {
  return useQuery({
    queryKey: ordersKeys.details(id ?? 0),
    queryFn: () => finora.orders.details(id ?? 0),
    enabled: id !== null,
    placeholderData: undefined,
  });
}

function assertOnline(): void {
  if (!canMutate()) throw new Error("offline");
}

function failureMessage(error: unknown): string {
  if (error instanceof Error && error.message === "offline") return "لا يمكن التعديل بدون اتصال بـ FINORA.";
  return toFinoraError(error).message;
}

/** Status change with optimistic rows; FINORA's answer (incl. stock refusals) is final. */
export function useChangeOrderStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, status }: { ids: number[]; status: string }) => {
      assertOnline();
      return finora.orders.changeStatus(ids, status);
    },
    onMutate: async ({ ids, status }) => {
      await queryClient.cancelQueries({ queryKey: ["orders", "list"] });
      const snapshot = queryClient.getQueriesData<OrdersPage>({ queryKey: ["orders", "list"] });
      const idSet = new Set(ids);
      queryClient.setQueriesData<OrdersPage>({ queryKey: ["orders", "list"] }, (page) =>
        page
          ? { ...page, rows: page.rows.map((row) => (idSet.has(row.id) ? { ...row, status } : row)) }
          : page,
      );
      return { snapshot };
    },
    onError: (error, _vars, context) => {
      context?.snapshot.forEach(([key, data]: [QueryKey, OrdersPage | undefined]) =>
        queryClient.setQueryData(key, data),
      );
      toast.error(failureMessage(error));
    },
    onSuccess: (result, { status }) => {
      const label = orderStatusStyle(status).label;
      toast.success(
        result.updated === 1
          ? `تم تغيير حالة الطلب إلى "${label}".`
          : `تم تغيير حالة ${result.updated} طلبات إلى "${label}".`,
      );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ordersKeys.all });
      // Status changes move stock in FINORA.
      void queryClient.invalidateQueries({ queryKey: ["products"] });
    },
  });
}

export function useReturnOrders() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, branchId }: { ids: number[]; branchId: number }) => {
      assertOnline();
      return finora.orders.markReturned(ids, branchId);
    },
    onError: (error) => toast.error(failureMessage(error)),
    onSuccess: (result) => {
      if (result.updated > 0)
        toast.success(
          result.updated === 1
            ? "تم إرجاع الطلب وتحديث المخزون والحسابات."
            : `تم إرجاع ${result.updated} طلبات وتحديث المخزون والحسابات.`,
        );
      if (result.skipped.length)
        toast.info(
          `طلبات راجعة مسبقاً، لم تتكرر العملية: ${result.skipped.map((row) => `#${row.id}`).join("، ")}`,
        );
      if (result.failed.length)
        toast.error(result.failed.map((row) => `#${row.id}: ${row.error}`).join("، "));
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ordersKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      for (const key of ["customers", "finance", "reports", "pos"])
        void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
}

type AssignKind = "shipping" | "agent";

/** FINORA updates shipping company / agent one order at a time; report partial failures honestly. */
export function useAssignOrders() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      kind,
      ids,
      targetId,
    }: {
      kind: AssignKind;
      ids: number[];
      targetId: number | null;
    }) => {
      assertOnline();
      const failed: number[] = [];
      for (const id of ids) {
        try {
          if (kind === "shipping") await finora.orders.setShippingCompany(id, targetId);
          else await finora.orders.setDeliveryAgent(id, targetId);
        } catch (error) {
          if (import.meta.env.DEV) console.debug("[orders] assign failed", id, error);
          failed.push(id);
        }
      }
      return { done: ids.length - failed.length, failed };
    },
    onError: (error) => toast.error(failureMessage(error)),
    onSuccess: ({ done, failed }, { kind }) => {
      const what = kind === "shipping" ? "شركة النقل" : "المندوب";
      if (done > 0) toast.success(done === 1 ? `تم تحديث ${what}.` : `تم تحديث ${what} لـ ${done} طلبات.`);
      if (failed.length > 0)
        toast.error(`تعذّر تحديث ${what} للطلبات: ${failed.map((id) => `#${id}`).join("، ")}`);
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ordersKeys.all }),
  });
}

/** Collect an order through FINORA (full or partial, split across treasury accounts). */
export function usePayOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payment: OrderPayment) => {
      assertOnline();
      return finora.orders.pay(payment);
    },
    onSuccess: (result, payment) => {
      const left = result.order?.remaining ?? 0;
      toast.success(
        left > 0
          ? `تم تسديد جزء من الطلب #${payment.orderId} — المتبقي ${formatIqd(left)}`
          : `تم تسديد الطلب #${payment.orderId} بالكامل.`,
      );
    },
    onSettled: () => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ordersKeys.all }),
        queryClient.invalidateQueries({ queryKey: ["customers"] }),
        queryClient.invalidateQueries({ queryKey: ["finance"] }),
        queryClient.invalidateQueries({ queryKey: ["reports"] }),
        queryClient.invalidateQueries({ queryKey: ["products"] }),
        queryClient.invalidateQueries({ queryKey: ["pos"] }),
      ]);
    },
  });
}

/** Cancel a "تم الطلب" order; FINORA restores stock and reverses its payments. */
export function useCancelOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => {
      assertOnline();
      return finora.orders.cancel(id);
    },
    onError: (error) => toast.error(failureMessage(error)),
    onSuccess: (_result, id) => toast.success(`تم إلغاء الطلب #${id}.`),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ordersKeys.all }),
  });
}

export function useOrderHistory(id: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["orders", "history", id ?? 0],
    queryFn: () => finora.orders.history(id ?? 0),
    enabled: id !== null && enabled,
  });
}

export { failureMessage as orderFailureMessage };

export function useQuickEditOrder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: QuickOrderEdit }) => {
      assertOnline();
      return finora.orders.quickEdit(id, input);
    },
    onSuccess: async (result, { id }) => {
      if (result.stock_locked)
        toast.error(result.stock_lock_reason || `تم حفظ الطلب #${id}، وهو مقفل بسبب نقص المخزون.`);
      else toast.success(`تم حفظ تعديلات الطلب #${id}.`);
      await Promise.all([
        client.invalidateQueries({ queryKey: ordersKeys.all }),
        client.invalidateQueries({ queryKey: ["products"] }),
        client.invalidateQueries({ queryKey: ["pos"] }),
        client.invalidateQueries({ queryKey: ["reports"] }),
      ]);
    },
  });
}

/** Save shipping-company barcodes; FINORA may move the order to "جاري الشحن". */
export function useSaveShippingBarcodes() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, companyId, barcodes }: { id: number; companyId: number; barcodes: string[] }) => {
      assertOnline();
      return finora.orders.setShippingBarcodes(id, companyId, barcodes);
    },
    onSuccess: (result, { id }) =>
      toast.success(
        result.status_changed
          ? `الطلب #${id}: تم حفظ وصل شركة النقل وتحويله إلى جاري الشحن.`
          : `الطلب #${id}: تم حفظ وصل شركة النقل.`,
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ordersKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      void queryClient.invalidateQueries({ queryKey: ["pos"] });
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}
