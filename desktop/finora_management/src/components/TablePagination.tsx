import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";

export const PAGE_SIZES = [10, 25, 50, 100] as const;

interface TablePaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  noun: string;
  onPage(page: number): void;
  onPageSize(size: number): void;
}

/** 1 … 4 5 [6] 7 8 … 55 */
export function pageWindow(page: number, totalPages: number): Array<number | "gap"> {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
  const pages = new Set([1, totalPages, page - 1, page, page + 1]);
  if (page <= 3) [2, 3, 4].forEach((p) => pages.add(p));
  if (page >= totalPages - 2) [totalPages - 3, totalPages - 2, totalPages - 1].forEach((p) => pages.add(p));
  const sorted = [...pages].filter((p) => p >= 1 && p <= totalPages).sort((a, b) => a - b);
  const result: Array<number | "gap"> = [];
  sorted.forEach((p, index) => {
    const previous = sorted[index - 1];
    if (previous !== undefined && p - previous > 1) result.push("gap");
    result.push(p);
  });
  return result;
}

export function TablePagination({
  page,
  totalPages,
  total,
  pageSize,
  noun,
  onPage,
  onPageSize,
}: TablePaginationProps) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  const button = "grid h-9 min-w-9 place-items-center rounded-[10px] px-2 text-sm transition-colors";

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 pt-3">
      <div className="flex items-center gap-3 text-sm text-ink-soft">
        <label className="flex items-center gap-2">
          <span className="sr-only">عدد الصفوف</span>
          <select
            value={pageSize}
            onChange={(event) => onPageSize(Number(event.target.value))}
            className="ltr-isolate h-9 rounded-[10px] border border-line bg-white px-2 text-sm text-ink outline-none focus:border-violet/50"
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <span>
          عرض{" "}
          <span className="ltr-isolate">
            {formatNumber(from)}–{formatNumber(to)}
          </span>{" "}
          من <span className="ltr-isolate font-semibold text-ink">{formatNumber(total)}</span> {noun}
        </span>
      </div>
      <nav
        aria-label="الصفحات"
        className="flex items-center gap-1 rounded-control bg-white/80 p-1 shadow-control"
      >
        <button
          type="button"
          aria-label="الصفحة السابقة"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          className={cn(button, "text-ink-soft hover:bg-violet-soft disabled:opacity-35")}
        >
          <ChevronRight size={16} />
        </button>
        {pageWindow(page, totalPages).map((item, index) =>
          item === "gap" ? (
            <span key={`gap-${index}`} className="px-1 text-ink-faint">
              …
            </span>
          ) : (
            <button
              key={item}
              type="button"
              aria-current={item === page ? "page" : undefined}
              onClick={() => onPage(item)}
              className={cn(
                button,
                "ltr-isolate",
                item === page
                  ? "bg-gradient-to-b from-violet to-violet-deep font-semibold text-white shadow-control"
                  : "text-ink-soft hover:bg-violet-soft",
              )}
            >
              {item}
            </button>
          ),
        )}
        <button
          type="button"
          aria-label="الصفحة التالية"
          disabled={page >= totalPages}
          onClick={() => onPage(page + 1)}
          className={cn(button, "text-ink-soft hover:bg-violet-soft disabled:opacity-35")}
        >
          <ChevronLeft size={16} />
        </button>
      </nav>
    </div>
  );
}
