import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { finora } from "@/api/finora";
import { usePosPreferences } from "@/features/pos/posPreferences";
import { posKeys } from "@/features/pos/queries";
import type { WindowId } from "@/windows/registry";

const PREFETCH_DELAY_MS = 1500;

/**
 * After sign-in, quietly loads what each window shows first (POS catalogue
 * page 1 + settings, order filter options) so opening a window renders real
 * content immediately. Live data is still refetched when the window opens.
 */
export function useIdlePrefetch(available: WindowId[]): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const jobs: Array<Promise<unknown>> = [];
      if (available.includes("pos")) {
        const firstPage = { page: 1, pageSize: usePosPreferences.getState().pageSize, search: "" };
        jobs.push(
          queryClient.prefetchQuery({ queryKey: posKeys.bootstrap, queryFn: () => finora.pos.bootstrap() }),
          queryClient.prefetchQuery({
            queryKey: posKeys.products(firstPage),
            queryFn: () => finora.pos.products(firstPage),
          }),
        );
      }
      if (available.includes("orders")) {
        jobs.push(
          queryClient.prefetchQuery({
            queryKey: ["orders", "lookups"],
            queryFn: () => finora.orders.lookups(),
          }),
        );
      }
      // prefetchQuery never throws; failures simply leave the window to load normally.
      void Promise.all(jobs);
    }, PREFETCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [available, queryClient]);
}
