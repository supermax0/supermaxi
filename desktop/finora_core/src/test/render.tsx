import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { DataSourceContext } from "../data/hooks";
import { DevDataSource } from "../data/devSource";
import type { DataSource } from "../data/source";

export const TEST_NOW = new Date("2026-10-03T19:44:00Z");

export function makeSource(): DevDataSource {
  return new DevDataSource({ simulate: false, now: TEST_NOW, latency: 0 });
}

export function renderWithSource(ui: ReactElement, source: DataSource = makeSource()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <DataSourceContext.Provider value={source}>{ui}</DataSourceContext.Provider>
    </QueryClientProvider>,
  );
  return { ...result, source, client };
}
