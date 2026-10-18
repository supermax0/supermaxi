import { ChevronLeft, Star } from "lucide-react";
import { memo } from "react";
import type { NavItem } from "@/navigation/types";
import { cn } from "@/utils/cn";

interface NavItemRowProps {
  item: NavItem;
  /** Keyboard-order key of this row. */
  rowKey: string;
  /** DOM id used by aria-activedescendant on the search field. */
  rowId: string;
  highlighted: boolean;
  current: boolean;
  favorite: boolean;
  onOpen(item: NavItem): void;
  onToggleFavorite(id: string): void;
  onHover(rowKey: string): void;
}

/** One navigation entry: icon · name · optional description · favorite · arrow. Light, dense, no card chrome. */
export const NavItemRow = memo(function NavItemRow({
  item,
  rowKey,
  rowId,
  highlighted,
  current,
  favorite,
  onOpen,
  onToggleFavorite,
  onHover,
}: NavItemRowProps) {
  const Icon = item.icon;
  return (
    <div
      id={rowId}
      role="option"
      aria-selected={highlighted}
      aria-current={current ? "page" : undefined}
      data-highlighted={highlighted || undefined}
      className="more-row group relative"
      onPointerMove={() => onHover(rowKey)}
    >
      <button
        type="button"
        tabIndex={-1}
        onClick={() => onOpen(item)}
        className="flex h-[52px] w-full items-center gap-3 rounded-[12px] px-3 text-start"
      >
        <span className="more-row-icon grid h-8 w-8 shrink-0 place-items-center rounded-[10px]">
          <Icon size={17} strokeWidth={1.8} aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              "block truncate text-[14px] font-medium",
              current ? "text-violet-deep" : "text-ink",
            )}
          >
            {item.label}
          </span>
          {item.description && (
            <span className="block truncate text-[12px] leading-4 text-ink-faint">{item.description}</span>
          )}
        </span>
        <ChevronLeft size={16} className="more-row-arrow shrink-0 text-ink-faint" aria-hidden />
      </button>
      <button
        type="button"
        tabIndex={-1}
        aria-label={favorite ? `إزالة ${item.label} من المفضلة` : `إضافة ${item.label} إلى المفضلة`}
        aria-pressed={favorite}
        onClick={() => onToggleFavorite(item.id)}
        className={cn(
          "more-row-star absolute left-9 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-lg",
          favorite ? "is-on text-warning" : "text-ink-faint",
        )}
      >
        <Star size={14} strokeWidth={1.9} fill={favorite ? "currentColor" : "none"} aria-hidden />
      </button>
    </div>
  );
});
