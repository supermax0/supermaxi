import { QueryClient } from "@tanstack/react-query";
import { FinoraApiError } from "@/api/finora";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Keep showing the last data while refetching; never blank a table on refetch.
        placeholderData: (previous: unknown) => previous,
        staleTime: 15_000,
        gcTime: 10 * 60_000,
        refetchOnWindowFocus: true,
        networkMode: "always",
        retry: (failureCount, error) =>
          failureCount < 2 &&
          error instanceof FinoraApiError &&
          (error.kind === "timeout" || error.kind === "server"),
      },
      mutations: { networkMode: "always", retry: false },
    },
  });
}
