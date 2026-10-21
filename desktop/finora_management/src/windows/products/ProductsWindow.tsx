import { useQuery } from "@tanstack/react-query";
import {
  Ban,
  Boxes,
  ExternalLink,
  Eye,
  Layers,
  MoreHorizontal,
  PackagePlus,
  Pencil,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { productImageUrl, type ProductRow, type ProductsQuery, type StockState } from "@/api/finora/products";
import { DataTable, type Column } from "@/components/DataTable";
import { Field, FilterPanel, SelectInput } from "@/components/FilterPanel";
import { Menu } from "@/components/Menu";
import { ProductThumb } from "@/components/ProductThumb";
import { SearchBox } from "@/components/SearchBox";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { StatusTabs } from "@/components/StatusTabs";
import { TablePagination } from "@/components/TablePagination";
import { CONFIG_QUERY_KEY } from "@/features/auth/LoginScreen";
import { STOCK_STYLES } from "@/features/products/stock";
import { useBarcodeScanner } from "@/hooks/useBarcodeScanner";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { toast } from "@/stores/toasts";
import { useWindowManager } from "@/stores/windowManager";
import { useCan, useSession } from "@/stores/session";
import { formatNumber } from "@/utils/format";
import { useWorkspaceHistory, useWorkspaceRequest } from "@/features/workspace/navigation";
import { formatIqd } from "@/utils/money";
import { ProductDetailsPanel } from "./ProductDetailsPanel";
import { ProductEditor, type EditorTarget } from "./ProductEditor";
import { AuditWorkspace } from "./audit/AuditWorkspace";
import { StockActivity } from "./StockActivity";
import { StockOperations, type StockTarget } from "./stock/StockOperations";
import { useAssistantPageContext } from "@/features/assistant/pageContext";

export function ProductsWindow() {
  const active = useWindowManager((s) => s.active === "products");
  const [editor, setEditor] = useState<EditorTarget | null>(null);
  const catalogAllowed = useCan("can_manage_inventory");
  const [workspace, setWorkspace] = useState<"catalog" | "operations" | "activity" | "count" | "history">(
    catalogAllowed ? "catalog" : "count",
  );
  const [auditLocked, setAuditLocked] = useState(false);
  const [stockLocked, setStockLocked] = useState(false);
  const [stockTarget, setStockTarget] = useState<{ target: StockTarget; scope: string } | null>(null);
  const auditVisible = useCan("inventory.audit.view");
  const auditScope = useSession((s) =>
    JSON.stringify([
      s.session?.tenant.id,
      s.session?.tenant.slug,
      s.session?.user.id,
      s.session?.branch?.id,
      s.session?.branch_scope,
      s.session?.permissions.slice().sort(),
    ]),
  );

  // Ctrl+N: new product while this window is open (not while the editor is up).
  useEffect(() => {
    if (!active || workspace !== "catalog") return;
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.code === "KeyN") {
        event.preventDefault();
        setEditor((current) => current ?? { kind: "create" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, workspace]);
  const [searchText, setSearchText] = useState("");
  const [category, setCategory] = useState("");
  const [stock, setStock] = useState<StockState | "">("");
  const [draftStock, setDraftStock] = useState<StockState | "">("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [detailsId, setDetailsId] = useState<number | null>(null);
  const search = useDebouncedValue(searchText, 300);
  const searchInput = useRef<HTMLInputElement>(null);
  const config = useQuery({
    queryKey: CONFIG_QUERY_KEY,
    queryFn: () => finora.config.get(),
    staleTime: Infinity,
  });
  const serverUrl = config.data?.serverUrl ?? null;
  const stockScope = `${serverUrl}:${auditScope}`;
  const [activityProduct, setActivityProduct] = useState<{ id: number; scope: string } | null>(null);
  const [activityCard, setActivityCard] = useState<{ row: ProductRow; scope: string } | null>(null);
  const [auditTarget, setAuditTarget] = useState<{ id: number; scope: string } | null>(null);
  const auditInitialId = auditTarget?.scope === stockScope ? auditTarget.id : null;

  const query = useMemo<ProductsQuery>(
    () => ({ page, pageSize, search, category: category || undefined, stock: stock || undefined }),
    [page, pageSize, search, category, stock],
  );
  // Refreshed on focus and after stock-moving operations (order status, returns, purchase cancel).
  const list = useQuery({
    queryKey: ["products", "list", query],
    queryFn: () => finora.products.list(query),
    enabled: workspace === "catalog" && catalogAllowed,
  });

  useBarcodeScanner(
    useCallback((code: string) => {
      setSearchText(code);
      setPage(1);
      searchInput.current?.focus();
    }, []),
    active && workspace === "catalog" && editor === null,
  );

  const rows = list.data?.rows;
  useWorkspaceRequest("products", (target, action) => {
    if (action === "product") {
      setWorkspace("catalog");
      setEditor((current) => current ?? { kind: "create" });
      return;
    }
    if (action === "audit") {
      if (editor) {
        toast.info("أكمل نموذج المنتج المفتوح أو أغلقه قبل فتح الجرد");
        return;
      }
      if (auditVisible) setWorkspace("count");
      return;
    }
    if (target.tab === "low" || target.tab === "out" || target.tab === "available") {
      setWorkspace("catalog");
      setStock(target.tab);
      setDraftStock(target.tab);
      setPage(1);
    } else if (target.tab === "count" && auditVisible) setWorkspace("count");
    else if (
      target.tab &&
      ["catalog", "operations", "activity", "history"].includes(target.tab) &&
      catalogAllowed
    )
      setWorkspace(target.tab as "catalog" | "operations" | "activity" | "history");
    if (target.page) setPage(target.page);
    if (target.entityId) void openActivityProduct(target.entityId);
  });
  useWorkspaceHistory({
    window: "products",
    tab: workspace === "catalog" ? stock || "catalog" : workspace,
    page,
    ...(detailsId ? { entityId: detailsId } : {}),
  });
  const stats = list.data?.stats;
  const selectedRow =
    rows?.find((row) => row.id === detailsId) ??
    (activityCard?.scope === stockScope && activityCard.row.id === detailsId ? activityCard.row : null);
  const openActivityProduct = async (id: number) => {
    const actor = useSession.getState().session;
    try {
      const details = await finora.products.details(id);
      if (useSession.getState().session !== actor) return;
      setActivityCard({
        scope: stockScope,
        row: {
          id: details.id,
          name: details.name,
          sku: details.sku,
          barcode: details.barcode,
          category: details.category,
          brand: details.brand,
          image_url: details.image_url,
          buy_price: details.buy_price,
          sale_price: details.sale_price,
          quantity: details.current_stock,
          low_stock_threshold: details.low_stock_threshold,
          active: details.active,
          stock_state:
            details.current_stock <= 0
              ? "out"
              : details.current_stock <= details.low_stock_threshold
                ? "low"
                : "available",
        },
      });
      setDetailsId(id);
      setWorkspace("catalog");
    } catch (error) {
      toast.error(toFinoraError(error).message);
    }
  };

  const rowMenu = useCallback(
    (row: ProductRow) => (
      <Menu
        label={`إجراءات ${row.name}`}
        items={[
          {
            id: "edit",
            label: "تعديل",
            icon: Pencil,
            onSelect: () => setEditor({ kind: "edit", id: row.id }),
          },
          { id: "details", label: "عرض التفاصيل", icon: Eye, onSelect: () => setDetailsId(row.id) },
          {
            id: "edit",
            label: "فتح في FINORA",
            icon: ExternalLink,
            onSelect: () => {
              finora.products
                .openInFinora(row.id)
                .catch((error: unknown) => toast.error(toFinoraError(error).message));
            },
          },
        ]}
        trigger={(props) => (
          <button
            {...props}
            type="button"
            aria-label={`إجراءات ${row.name}`}
            className="grid h-9 w-9 place-items-center rounded-[10px] bg-white text-ink-soft shadow-control ring-1 ring-line/70 hover:text-violet-deep"
          >
            <MoreHorizontal size={17} />
          </button>
        )}
      />
    ),
    [],
  );

  const columns = useMemo<Column<ProductRow>[]>(
    () => [
      {
        id: "sku",
        header: "SKU",
        width: "150px",
        cell: (row) => (
          <span className="ltr-isolate block truncate text-ink-soft">{row.sku || row.barcode || "—"}</span>
        ),
      },
      {
        id: "name",
        header: "اسم المنتج",
        width: "24%",
        cell: (row) => <span className="line-clamp-2 font-semibold leading-snug">{row.name}</span>,
      },
      {
        id: "image",
        header: "الصورة",
        width: "92px",
        align: "center",
        minTableWidth: 980,
        cell: (row) => (
          <div className="flex justify-center">
            <ProductThumb src={productImageUrl(row.image_url, serverUrl)} />
          </div>
        ),
      },
      { id: "category", header: "الفئة", width: "11%", cell: (row) => row.category || "—" },
      {
        id: "brand",
        header: "الماركة",
        width: "9%",
        minTableWidth: 1150,
        cell: (row) => <span className="text-ink-soft">{row.brand || "—"}</span>,
      },
      {
        id: "buy",
        header: "سعر الشراء",
        width: "120px",
        minTableWidth: 1100,
        cell: (row) => <span className="ltr-isolate text-ink-soft">{formatIqd(row.buy_price)}</span>,
      },
      {
        id: "sale",
        header: "سعر البيع",
        width: "120px",
        cell: (row) => <span className="ltr-isolate font-semibold">{formatIqd(row.sale_price)}</span>,
      },
      {
        id: "qty",
        header: "الكمية المتوفرة",
        width: "110px",
        align: "center",
        cell: (row) => (
          <span
            className={`ltr-isolate text-[15px] font-bold ${
              row.stock_state === "out"
                ? "text-danger"
                : row.stock_state === "low"
                  ? "text-warning"
                  : "text-success"
            }`}
          >
            {formatNumber(row.quantity)}
          </span>
        ),
      },
      {
        id: "min",
        header: "أدنى مخزون",
        width: "96px",
        align: "center",
        minTableWidth: 1000,
        cell: (row) => (
          <span className="ltr-isolate text-ink-soft">{formatNumber(row.low_stock_threshold)}</span>
        ),
      },
      {
        id: "state",
        header: "الحالة",
        width: "124px",
        align: "center",
        cell: (row) => <StatusBadge {...STOCK_STYLES[row.stock_state]} />,
      },
    ],
    [serverUrl],
  );

  const pickStock = (next: StockState | "") => {
    setStock(next);
    setDraftStock(next);
    setPage(1);
  };

  useAssistantPageContext("products", {
    tab: workspace === "catalog" ? "" : workspace,
    search: searchText,
    filters: { category, stock },
    total: list.data?.total,
    ...(detailsId !== null
      ? { record: { id: detailsId, name: rows?.find((r) => r.id === detailsId)?.name ?? `#${detailsId}` } }
      : {}),
  });
  return (
    <div className="relative flex h-full flex-col gap-3">
      {(catalogAllowed || auditVisible) && (
        <div className="flex shrink-0 gap-2" aria-label="أقسام المنتجات والمخزون">
          {[
            ...(catalogAllowed ? (["catalog", "operations", "activity"] as const) : []),
            ...(auditVisible ? (["count", "history"] as const) : []),
          ].map((id) => (
            <button
              type="button"
              key={id}
              disabled={
                editor !== null || auditLocked || stockLocked || (id === "catalog" && !catalogAllowed)
              }
              aria-pressed={workspace === id}
              onClick={() => {
                setDetailsId(null);
                setStockTarget(null);
                setWorkspace(id);
              }}
              className={`min-h-10 rounded-control border px-4 text-sm ${workspace === id ? "border-violet/40 bg-violet-soft text-violet" : "border-line bg-white/80 text-ink-soft"}`}
            >
              {
                {
                  catalog: "المنتجات",
                  operations: "إدارة المخزون",
                  activity: "حركة المخزون",
                  count: "جرد المخزون",
                  history: "سجل الجرد",
                }[id]
              }
            </button>
          ))}
        </div>
      )}
      {!catalogAllowed && !auditVisible ? (
        <p role="alert" className="rounded-control border border-line bg-white p-4 text-sm text-ink-soft">
          تحتاج صلاحية عرض المنتجات أو الجرد لفتح هذه النافذة.
        </p>
      ) : workspace === "operations" && catalogAllowed ? (
        <StockOperations
          key={`${stockScope}:${stockTarget?.target.id ?? ""}:${stockTarget?.target.document ?? ""}`}
          scope={stockScope}
          active={active}
          serverUrl={serverUrl}
          onBusyChange={setStockLocked}
          initialTarget={stockTarget?.scope === stockScope ? stockTarget.target : undefined}
          onActivity={(id) => {
            setActivityProduct({ id, scope: stockScope });
            setWorkspace("activity");
          }}
        />
      ) : workspace === "activity" && catalogAllowed ? (
        <StockActivity
          key={stockScope}
          scope={stockScope}
          active={active}
          productId={activityProduct?.scope === stockScope ? activityProduct.id : undefined}
          onClearProduct={() => setActivityProduct(null)}
          onProduct={(id) => void openActivityProduct(id)}
          onStockDocument={(document, id) => {
            setStockTarget({ target: { kind: "branch", document, id }, scope: stockScope });
            setWorkspace("operations");
          }}
          onAudit={(id) => {
            setAuditTarget({ id, scope: stockScope });
            setWorkspace("count");
          }}
        />
      ) : (workspace !== "catalog" || !catalogAllowed) && auditVisible ? (
        <AuditWorkspace
          key={`${stockScope}:${workspace}:${auditInitialId ?? ""}`}
          serverUrl={serverUrl}
          scope={`${serverUrl}:${auditScope}`}
          initialView={workspace === "history" ? "history" : "count"}
          initialSessionId={auditInitialId}
          active={active}
          onBusyChange={setAuditLocked}
        />
      ) : (
        <>
          <div className="grid grid-cols-4 gap-3">
            <StatCard
              label="إجمالي المنتجات"
              value={formatNumber(stats?.total ?? 0)}
              unit="منتج"
              icon={Boxes}
              tone="violet"
              loading={!stats}
              active={stock === ""}
              onClick={() => pickStock("")}
            />
            <StatCard
              label="متوفر في المخزون"
              value={formatNumber(stats?.available ?? 0)}
              unit="منتج"
              icon={Layers}
              tone="success"
              loading={!stats}
              active={stock === "available"}
              onClick={() => pickStock("available")}
            />
            <StatCard
              label="منخفض المخزون"
              value={formatNumber(stats?.low ?? 0)}
              unit="منتج"
              icon={TriangleAlert}
              tone="warning"
              loading={!stats}
              active={stock === "low"}
              onClick={() => pickStock("low")}
            />
            <StatCard
              label="نفذ المخزون"
              value={formatNumber(stats?.out ?? 0)}
              unit="منتج"
              icon={Ban}
              tone="danger"
              loading={!stats}
              active={stock === "out"}
              onClick={() => pickStock("out")}
            />
          </div>

          <div className="flex items-center gap-3">
            {(list.data?.categories.length ?? 0) > 0 && (
              <div className="no-scrollbar max-w-[55%] overflow-x-auto">
                <StatusTabs
                  label="الفئات"
                  value={category}
                  onChange={(next) => {
                    setCategory(next);
                    setPage(1);
                  }}
                  tabs={[
                    { id: "", label: "الكل" },
                    ...(list.data?.categories ?? []).map((c) => ({ id: c, label: c })),
                  ]}
                />
              </div>
            )}
            <FilterPanel
              activeCount={stock ? 1 : 0}
              onApply={() => pickStock(draftStock)}
              onClear={() => pickStock("")}
            >
              <Field label="حالة المخزون" wide>
                <SelectInput
                  value={draftStock}
                  onChange={(value) => setDraftStock(value as StockState | "")}
                  placeholder="كل الحالات"
                  options={(Object.keys(STOCK_STYLES) as StockState[]).map((key) => ({
                    value: key,
                    label: STOCK_STYLES[key].label,
                  }))}
                />
              </Field>
            </FilterPanel>
            <SearchBox
              ref={searchInput}
              className="flex-1"
              scanner
              value={searchText}
              onChange={(value) => {
                setSearchText(value);
                setPage(1);
              }}
              busy={list.isFetching && search !== "" && searchText === search}
              placeholder="بحث عن اسم المنتج، SKU، باركود…"
            />
            <button
              type="button"
              onClick={() => setEditor({ kind: "create" })}
              title="Ctrl+N"
              className="flex h-11 shrink-0 items-center gap-2 rounded-control bg-gradient-to-l from-violet to-violet-deep px-5 text-sm font-bold text-white shadow-float transition-[transform,opacity] hover:opacity-95 active:scale-[0.98]"
            >
              <PackagePlus size={18} aria-hidden />
              منتج جديد
            </button>
          </div>

          <DataTable
            label="جدول المنتجات"
            columns={columns}
            rows={rows}
            loading={list.isLoading}
            fetching={list.isFetching}
            error={list.error ? toFinoraError(list.error).message : null}
            onRetry={() => void list.refetch()}
            emptyTitle={search || category || stock ? "لا توجد منتجات مطابقة" : "لا توجد منتجات"}
            activeId={detailsId}
            onOpen={(row) => setDetailsId(row.id)}
            rowActions={rowMenu}
          />

          {list.data && (
            <TablePagination
              page={list.data.page}
              totalPages={list.data.total_pages}
              total={list.data.total}
              pageSize={pageSize}
              noun="منتج"
              onPage={setPage}
              onPageSize={(size) => {
                setPageSize(size);
                setPage(1);
              }}
            />
          )}

          <ProductDetailsPanel
            product={selectedRow}
            imageSrc={selectedRow ? productImageUrl(selectedRow.image_url, serverUrl) : null}
            onClose={() => setDetailsId(null)}
            onViewActivity={(id) => {
              setActivityProduct({ id, scope: stockScope });
              setDetailsId(null);
              setWorkspace("activity");
            }}
            onEdit={(id) => {
              setDetailsId(null);
              setEditor({ kind: "edit", id });
            }}
          />
          <ProductEditor
            target={editor}
            categories={list.data?.categories ?? []}
            brands={list.data?.brands ?? []}
            serverUrl={serverUrl}
            onClose={() => setEditor(null)}
          />
        </>
      )}
    </div>
  );
}
