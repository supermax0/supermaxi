import { Clock3, LayoutGrid, Search, SearchX, Star } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { searchItems } from "@/navigation/search";
import type { NavItem } from "@/navigation/types";
import { openNavItem, useNavigation } from "@/navigation/useNavigation";
import { useNavigationPrefs } from "@/stores/navigationPrefs";
import { usePreferences } from "@/stores/preferences";
import { useWindowManager } from "@/stores/windowManager";
import { NavItemRow } from "./NavItemRow";

const CLOSE_MS = 150;
const SIDE_GUTTER = 24; // matches the top bar's px-6
const MAX_WIDTH = 800;
const MIN_COLUMN = 196;

interface MoreMenuProps {
  open: boolean;
  anchor: RefObject<HTMLElement>;
  onClose(): void;
}

interface Row {
  key: string;
  item: NavItem;
}

function panelWidth(): number {
  return Math.min(MAX_WIDTH, window.innerWidth - SIDE_GUTTER * 2);
}

/**
 * «المزيد» — a navigation hub that grows out of the top bar (morph, not a dropdown).
 * Data-driven (navigation/config.ts), permission-aware, fully keyboard operable; the search engine is shared with
 * the Ctrl+K palette. Animations are CSS transform/opacity only.
 */
export function MoreMenu({ open, anchor, onClose }: MoreMenuProps) {
  const [rendered, setRendered] = useState(open);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    if (open) {
      setRendered(true);
      setClosing(false);
      return;
    }
    if (!rendered) return;
    setClosing(true);
    const timer = window.setTimeout(() => {
      setRendered(false);
      setClosing(false);
    }, CLOSE_MS + 30);
    return () => window.clearTimeout(timer);
  }, [open, rendered]);

  if (!rendered) return null;
  return <MorePanel closing={closing} anchor={anchor} onClose={onClose} />;
}

function MorePanel({
  closing,
  anchor,
  onClose,
}: {
  closing: boolean;
  anchor: RefObject<HTMLElement>;
  onClose(): void;
}) {
  const { groups, items, byId } = useNavigation();
  const favorites = useNavigationPrefs((s) => s.favorites);
  const recent = useNavigationPrefs((s) => s.recent);
  const toggleFavorite = useNavigationPrefs((s) => s.toggleFavorite);
  const activeWindow = useWindowManager((s) => s.active);
  const reduced = usePreferences((s) => s.motion) === "reduced";
  const panel = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [width, setWidth] = useState(panelWidth);
  const [notch, setNotch] = useState<number | null>(null);

  // Anchor the notch under the «المزيد» button and grow the panel from that point.
  useLayoutEffect(() => {
    const measure = () => {
      setWidth(panelWidth());
      const rect = anchor.current?.getBoundingClientRect();
      if (rect) setNotch(window.innerWidth - SIDE_GUTTER - (rect.left + rect.width / 2));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [anchor]);

  // Focus the search on open; give focus back to the button when the menu closes from inside.
  useEffect(() => {
    const frame = requestAnimationFrame(() => input.current?.focus());
    const button = anchor.current;
    const node = panel.current;
    return () => {
      cancelAnimationFrame(frame);
      const focused = document.activeElement;
      if (button && (!focused || focused === document.body || node?.contains(focused))) button.focus();
    };
  }, [anchor]);

  // Click outside closes (the button toggles itself).
  useEffect(() => {
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panel.current?.contains(target) || anchor.current?.contains(target)) return;
      onClose();
    };
    document.addEventListener("pointerdown", onPointer, true);
    return () => document.removeEventListener("pointerdown", onPointer, true);
  }, [anchor, onClose]);

  const results = useMemo(() => searchItems(items, query), [items, query]);
  const searching = query.trim().length > 0;
  const favoriteItems = useMemo(
    () => favorites.map((id) => byId.get(id)).filter((x): x is NavItem => x !== undefined),
    [byId, favorites],
  );
  const recentItems = useMemo(
    () => recent.map((id) => byId.get(id)).filter((x): x is NavItem => x !== undefined),
    [byId, recent],
  );
  const favoriteSet = useMemo(() => new Set(favorites), [favorites]);

  // Keyboard order = visual order of the rows on screen.
  const rows = useMemo<Row[]>(() => {
    if (searching) return results.map((item) => ({ key: `r:${item.id}`, item }));
    return [
      ...favoriteItems.map((item) => ({ key: `f:${item.id}`, item })),
      ...groups.flatMap((group) => group.items.map((item) => ({ key: `g:${group.id}:${item.id}`, item }))),
    ];
  }, [favoriteItems, groups, results, searching]);

  const highlighted = cursor && rows.some((r) => r.key === cursor) ? cursor : (rows[0]?.key ?? null);

  const choose = useCallback(
    (item: NavItem) => {
      onClose();
      openNavItem(item);
    },
    [onClose],
  );

  const onKeyDown = (event: KeyboardEvent) => {
    const at = rows.findIndex((r) => r.key === highlighted);
    const move = (to: number) => {
      const row = rows[Math.max(0, Math.min(rows.length - 1, to))];
      if (!row) return;
      setCursor(row.key);
      document.getElementById(rowDomId(row.key))?.scrollIntoView?.({ block: "nearest" });
    };
    if (event.key === "ArrowDown") {
      event.preventDefault();
      move(at + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(at - 1);
    } else if (event.key === "Home" && !searching) {
      event.preventDefault();
      move(0);
    } else if (event.key === "End" && !searching) {
      event.preventDefault();
      move(rows.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const row = rows[at];
      if (row) choose(row.item);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    }
  };

  const columns = Math.max(1, Math.min(4, groups.length, Math.floor(width / MIN_COLUMN)));
  const style = {
    width,
    "--more-notch": notch === null ? "40px" : `${notch}px`,
    "--more-cols": columns,
  } as CSSProperties;

  const renderRow = (row: Row) => (
    <NavItemRow
      key={row.key}
      item={row.item}
      rowKey={row.key}
      rowId={rowDomId(row.key)}
      highlighted={row.key === highlighted}
      current={row.item.target.kind === "window" && row.item.target.window === activeWindow}
      favorite={favoriteSet.has(row.item.id)}
      onOpen={choose}
      onToggleFavorite={toggleFavorite}
      onHover={setCursor}
    />
  );

  return (
    <div
      ref={panel}
      role="dialog"
      aria-label="المزيد"
      dir="rtl"
      data-state={closing ? "closing" : "open"}
      data-reduced={reduced || undefined}
      className="more-panel no-drag fixed z-40"
      style={style}
      onKeyDown={onKeyDown}
    >
      <span className="more-notch" aria-hidden />
      <div className="more-content" data-more-content>
        <label className="more-search">
          <Search size={18} className="shrink-0 text-ink-faint" aria-hidden />
          <input
            ref={input}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(null);
            }}
            placeholder="ابحث عن صفحة أو وظيفة..."
            aria-label="ابحث عن صفحة أو وظيفة"
            role="combobox"
            aria-expanded
            aria-controls="more-list"
            aria-activedescendant={highlighted ? rowDomId(highlighted) : undefined}
            autoComplete="off"
            spellCheck={false}
            className="h-full min-w-0 flex-1 bg-transparent text-[14.5px] text-ink outline-none placeholder:text-ink-faint"
          />
          <kbd className="ltr-isolate rounded-md border border-line bg-white px-1.5 py-0.5 text-[11px] text-ink-faint">
            Ctrl + K
          </kbd>
        </label>

        <div id="more-list" role="listbox" aria-label="الصفحات" className="more-body">
          {searching ? (
            results.length > 0 ? (
              <section className="more-section">
                <h3 className="more-heading">النتائج</h3>
                <div className="flex flex-col gap-0.5">{rows.map(renderRow)}</div>
              </section>
            ) : (
              <Empty
                icon={<SearchX size={22} />}
                title={`لا توجد نتائج لـ «${query.trim()}»`}
                hint="جرّب اسماً آخر أو جزءاً من الكلمة"
              />
            )
          ) : items.length === 0 ? (
            <Empty
              icon={<LayoutGrid size={22} />}
              title="لا توجد صفحات بعد"
              hint="ستظهر الصفحات هنا فور إضافتها إلى قائمة التنقّل"
            />
          ) : (
            <>
              {favoriteItems.length > 0 && (
                <section className="more-section" aria-label="المفضلة">
                  <h3 className="more-heading">
                    <Star size={13} aria-hidden /> المفضلة
                  </h3>
                  <div className="more-fav-grid">
                    {rows.filter((r) => r.key.startsWith("f:")).map(renderRow)}
                  </div>
                </section>
              )}
              {recentItems.length > 0 && (
                <section className="more-section" aria-label="آخر استخدام">
                  <h3 className="more-heading">
                    <Clock3 size={13} aria-hidden /> آخر استخدام
                  </h3>
                  <div className="no-scrollbar flex gap-2 overflow-x-auto">
                    {recentItems.map((item) => {
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          tabIndex={-1}
                          className="more-chip"
                          onClick={() => choose(item)}
                        >
                          <Icon size={14} strokeWidth={1.9} aria-hidden />
                          <span className="truncate">{item.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              )}
              <div className="more-grid">
                {groups.map((group) => {
                  const GroupIcon = group.icon;
                  return (
                    <section key={group.id} className="more-section" aria-label={group.title}>
                      <h3 className="more-heading">
                        {GroupIcon && <GroupIcon size={13} aria-hidden />} {group.title}
                      </h3>
                      <div className="flex flex-col gap-0.5">
                        {rows.filter((r) => r.key.startsWith(`g:${group.id}:`)).map(renderRow)}
                      </div>
                    </section>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function rowDomId(key: string): string {
  return `more-row-${key.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

function Empty({ icon, title, hint }: { icon: ReactNode; title: string; hint: string }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center" role="status">
      <span className="grid h-11 w-11 place-items-center rounded-2xl bg-violet-soft text-violet-deep">
        {icon}
      </span>
      <p className="text-[14px] font-medium text-ink">{title}</p>
      <p className="text-[12.5px] text-ink-faint">{hint}</p>
    </div>
  );
}
