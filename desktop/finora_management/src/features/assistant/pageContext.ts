import { useEffect } from "react";
import { create } from "zustand";
import type { WindowId } from "@/windows/registry";

/** What a window currently shows, so "this supplier" or "these orders" resolve without asking. */
export interface AssistantPageDetails {
  tab?: string;
  search?: string;
  filters?: Record<string, string | number | boolean>;
  /** The record opened in the details panel. */
  record?: { id: number; name: string };
  /** Rows the user ticked in the list. */
  checked?: { count: number; names: string[] };
  total?: number;
}
export const useAssistantPage = create<{ details: Partial<Record<WindowId, AssistantPageDetails>> }>()(
  () => ({ details: {} }),
);
const clean = (details: AssistantPageDetails): AssistantPageDetails => {
  const filters = Object.fromEntries(
    Object.entries(details.filters ?? {}).filter(([, v]) => v !== "" && v !== false && v !== 0),
  );
  return {
    ...(details.tab && details.tab !== "all" ? { tab: details.tab } : {}),
    ...(details.search?.trim() ? { search: details.search.trim().slice(0, 120) } : {}),
    ...(Object.keys(filters).length ? { filters } : {}),
    ...(details.record ? { record: { id: details.record.id, name: details.record.name.slice(0, 120) } } : {}),
    ...(details.checked?.count
      ? { checked: { count: details.checked.count, names: details.checked.names.slice(0, 5) } }
      : {}),
    ...(details.total !== undefined ? { total: details.total } : {}),
  };
};
/** Publishes a window's visible state while it is mounted; values stay in memory only. */
export function useAssistantPageContext(window: WindowId, details: AssistantPageDetails): void {
  const serialized = JSON.stringify(clean(details));
  useEffect(() => {
    useAssistantPage.setState((s) => ({
      details: { ...s.details, [window]: JSON.parse(serialized) as AssistantPageDetails },
    }));
  }, [window, serialized]);
  useEffect(
    () => () =>
      useAssistantPage.setState((s) => ({
        details: Object.fromEntries(Object.entries(s.details).filter(([id]) => id !== window)),
      })),
    [window],
  );
}
