import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { cn } from "@/utils/cn";
import { Checkbox } from "./Checkbox";

export interface Column<T> {
  id: string;
  header: ReactNode;
  cell(row: T): ReactNode;
  /** CSS width, e.g. "120px" or "18%". */
  width?: string;
  align?: "start" | "center" | "end";
  /** Secondary columns hide when the table is narrower than this (px); details stay in the side panel. */
  minTableWidth?: number;
}

export interface Selection {
  selected: ReadonlySet<number>;
  toggle(id: number): void;
  setMany(ids: number[], on: boolean): void;
}

interface DataTableProps<T extends { id: number }> {
  label: string;
  columns: Column<T>[];
  rows: T[] | undefined;
  loading: boolean;
  fetching: boolean;
  error: string | null;
  onRetry(): void;
  emptyTitle: string;
  emptyHint?: string;
  selection?: Selection;
  activeId?: number | null;
  onOpen?(row: T): void;
  rowActions?(row: T): ReactNode;
}

const ALIGN = { start: "text-start", center: "text-center", end: "text-end" } as const;

interface RowProps<T extends { id: number }> {
  row: T;
  columns: Column<T>[];
  selected: boolean;
  active: boolean;
  focused: boolean;
  selectable: boolean;
  onToggle?(id: number): void;
  onOpen?(row: T): void;
  rowActions?(row: T): ReactNode;
}

function RowView<T extends { id: number }>({
  row,
  columns,
  selected,
  active,
  focused,
  selectable,
  onToggle,
  onOpen,
  rowActions,
}: RowProps<T>) {
  return (
    <tr
      data-row={row.id}
      aria-selected={selected}
      onClick={() => onOpen?.(row)}
      className={cn(
        "group h-[60px] cursor-default border-b border-line/70 transition-colors duration-150 last:border-0",
        selected ? "bg-violet-soft/70" : active ? "bg-azure-soft/50" : "hover:bg-white/80",
        focused && "outline outline-2 -outline-offset-2 outline-violet/35",
      )}
    >
      {selectable && (
        <td className="w-12 ps-4">
          <Checkbox checked={selected} label={`تحديد ${row.id}`} onChange={() => onToggle?.(row.id)} />
        </td>
      )}
      {columns.map((column) => (
        <td key={column.id} className={cn("px-3 text-[13.5px] text-ink", ALIGN[column.align ?? "start"])}>
          {column.cell(row)}
        </td>
      ))}
      {rowActions && (
        <td className="w-14 pe-3 text-center" onClick={(event) => event.stopPropagation()}>
          {rowActions(row)}
        </td>
      )}
    </tr>
  );
}

// Rows re-render only when their own data / state changes, not when a sibling does.
const Row = memo(RowView) as typeof RowView;

function SkeletonRows({ columns }: { columns: number }) {
  return (
    <>
      {Array.from({ length: 8 }, (_, index) => (
        <tr key={index} className="h-[60px] border-b border-line/60">
          {Array.from({ length: columns }, (__, cell) => (
            <td key={cell} className="px-3">
              <span
                className="block h-3.5 animate-pulse rounded-full bg-gradient-to-l from-line/60 via-line to-line/60"
                style={{
                  width: `${45 + ((index * 7 + cell * 13) % 45)}%`,
                  animationDelay: `${index * 60}ms`,
                }}
              />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

/**
 * Server-paged data table: memoised rows, skeleton on first load only (old rows
 * stay visible while refetching), keyboard navigation (↑ ↓ Enter Space).
 */
export function DataTable<T extends { id: number }>({
  label,
  columns,
  rows,
  loading,
  fetching,
  error,
  onRetry,
  emptyTitle,
  emptyHint,
  selection,
  activeId = null,
  onOpen,
  rowActions,
}: DataTableProps<T>) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1200);
  const [focusIndex, setFocusIndex] = useState(-1);

  useEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => setFocusIndex(-1), [rows]);

  const visible = useMemo(
    () => columns.filter((column) => !column.minTableWidth || width >= column.minTableWidth),
    [columns, width],
  );
  const ids = rows?.map((row) => row.id) ?? [];
  const selectedOnPage = selection ? ids.filter((id) => selection.selected.has(id)).length : 0;
  const toggle = selection?.toggle;

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (!rows?.length) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setFocusIndex((index) => {
          const next = event.key === "ArrowDown" ? index + 1 : index - 1;
          const clamped = Math.max(0, Math.min(rows.length - 1, next));
          container.current
            ?.querySelector(`[data-row="${rows[clamped]?.id}"]`)
            ?.scrollIntoView({ block: "nearest" });
          return clamped;
        });
      } else if (event.key === "Enter" && focusIndex >= 0) {
        const row = rows[focusIndex];
        if (row) onOpen?.(row);
      } else if (event.key === " " && focusIndex >= 0 && toggle) {
        event.preventDefault();
        const row = rows[focusIndex];
        if (row) toggle(row.id);
      }
    },
    [rows, focusIndex, onOpen, toggle],
  );

  const columnCount = visible.length + (selection ? 1 : 0) + (rowActions ? 1 : 0);
  const showSkeleton = loading && !rows;
  const showError = Boolean(error) && !rows;
  const showEmpty = !showSkeleton && !showError && rows?.length === 0;

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-panel bg-white/75 shadow-control ring-1 ring-line/60">
      <div
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 z-20 h-0.5 overflow-hidden transition-opacity duration-200",
          fetching && rows ? "opacity-100" : "opacity-0",
        )}
        aria-hidden
      >
        <span className="block h-full w-1/3 animate-[boot_1.1s_ease-in-out_infinite] bg-violet/70" />
      </div>
      <div
        ref={container}
        tabIndex={0}
        role="region"
        aria-label={label}
        aria-busy={fetching}
        onKeyDown={onKeyDown}
        className="min-h-0 flex-1 overflow-auto overscroll-contain outline-none [contain:content]"
      >
        <table className="w-full table-fixed border-collapse">
          <thead className="sticky top-0 z-10 bg-[#f8f7fd]/95">
            <tr className="h-12 border-b border-line text-[12.5px] font-semibold text-ink-soft">
              {selection && (
                <th className="w-12 ps-4 text-start">
                  <Checkbox
                    label="تحديد كل الصفحة"
                    checked={ids.length > 0 && selectedOnPage === ids.length}
                    indeterminate={selectedOnPage > 0 && selectedOnPage < ids.length}
                    onChange={(on) => selection.setMany(ids, on)}
                  />
                </th>
              )}
              {visible.map((column) => (
                <th
                  key={column.id}
                  scope="col"
                  style={{ width: column.width }}
                  className={cn("px-3 font-semibold", ALIGN[column.align ?? "start"])}
                >
                  {column.header}
                </th>
              ))}
              {rowActions && (
                <th className="w-14 pe-3 text-center" scope="col">
                  <span className="sr-only">إجراءات</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {showSkeleton && <SkeletonRows columns={columnCount} />}
            {rows?.map((row, index) => (
              <Row
                key={row.id}
                row={row}
                columns={visible}
                selected={selection?.selected.has(row.id) ?? false}
                active={row.id === activeId}
                focused={index === focusIndex}
                selectable={Boolean(selection)}
                onToggle={toggle}
                onOpen={onOpen}
                rowActions={rowActions}
              />
            ))}
          </tbody>
        </table>
        {showEmpty && (
          <div className="flex flex-col items-center gap-2 py-16 text-center">
            <Inbox size={28} className="text-ink-faint" aria-hidden />
            <p className="text-sm font-medium text-ink">{emptyTitle}</p>
            {emptyHint && <p className="text-xs text-ink-faint">{emptyHint}</p>}
          </div>
        )}
        {showError && (
          <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
            <AlertTriangle size={28} className="text-warning" aria-hidden />
            <p className="text-sm text-ink">{error}</p>
            <button
              type="button"
              onClick={onRetry}
              className="flex items-center gap-1.5 rounded-control bg-violet-soft px-3 py-1.5 text-sm text-violet-deep hover:bg-violet/15"
            >
              <RefreshCw size={14} aria-hidden />
              إعادة المحاولة
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
