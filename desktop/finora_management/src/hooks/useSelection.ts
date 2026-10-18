import { useCallback, useMemo, useState } from "react";
import type { Selection } from "@/components/DataTable";

export function useSelection(): Selection & { clear(): void; ids: number[] } {
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const toggle = useCallback((id: number) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const setMany = useCallback((ids: number[], on: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);
  const clear = useCallback(() => setSelected(new Set()), []);
  const ids = useMemo(() => [...selected], [selected]);
  return useMemo(() => ({ selected, toggle, setMany, clear, ids }), [selected, toggle, setMany, clear, ids]);
}
