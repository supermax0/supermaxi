import { useQuery } from "@tanstack/react-query";
import { Boxes, ChevronLeft, ChevronRight, MapPin, Plus } from "lucide-react";
import { memo, useState } from "react";
import { finora, toFinoraError } from "@/api/finora";
import { productImageUrl } from "@/api/finora/products";
import type { PosProduct, PosProductsPage } from "@/api/finora/pos";
import { ProductThumb } from "@/components/ProductThumb";
import { StatusTabs } from "@/components/StatusTabs";
import { usePosPreferences } from "@/features/pos/posPreferences";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";

interface ProductsPanelProps {
  page: PosProductsPage | undefined;
  loading: boolean;
  error: string | null;
  category: string;
  serverUrl: string | null;
  onCategory(category: string): void;
  onPage(page: number): void;
  onAdd(product: PosProduct): void;
}

/** Where else the product is in stock — read-only; the server decides who may see other branches. */
function BranchAvailability({ product }: { product: PosProduct }) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["branches", "availability", product.id],
    queryFn: () => finora.branches.availability(product.id),
    enabled: open,
    staleTime: 15_000,
    retry: false,
  });
  const others = (query.data?.rows ?? []).filter((r) => !r.is_current);
  return (
    <div className="mt-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-azure"
      >
        <MapPin size={12} aria-hidden /> توفره بالفروع الأخرى
      </button>
      {open && (
        <div className="mt-1 rounded-control bg-white/80 p-2 text-[12px] ring-1 ring-line/60">
          {query.isLoading && <span className="text-ink-faint">جارٍ التحميل…</span>}
          {query.error && <span className="text-danger">{toFinoraError(query.error).message}</span>}
          {query.data && others.length === 0 && <span className="text-ink-faint">غير متوفر بفرع آخر</span>}
          {others.map((r) => (
            <div key={r.id} className="flex justify-between gap-3">
              <span>{r.name}</span>
              <span
                className={cn("ltr-isolate font-semibold", r.quantity > 0 ? "text-ink" : "text-ink-faint")}
              >
                {formatNumber(r.quantity)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const ProductCard = memo(function ProductCard({
  product,
  serverUrl,
  showImage,
  onAdd,
}: {
  product: PosProduct;
  serverUrl: string | null;
  showImage: boolean;
  onAdd(product: PosProduct): void;
}) {
  const out = product.quantity <= 0;
  return (
    <li className="group flex items-center gap-3 rounded-panel bg-white/85 p-3 ring-1 ring-line/60 transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-control">
      {showImage && <ProductThumb src={productImageUrl(product.image_url, serverUrl)} size={58} />}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-bold text-ink">{product.name}</p>
        <p className="ltr-isolate truncate text-xs text-ink-faint">
          {product.sku || product.barcode || product.category}
        </p>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="ltr-isolate text-[16px] font-bold text-ink">{formatNumber(product.price)}</span>
          <span className="text-xs text-ink-faint">د.ع</span>
          <span className={cn("ms-auto text-[11.5px]", out ? "text-danger" : "text-ink-faint")}>
            {out ? "نفذ" : `متوفر ${formatNumber(product.quantity)}`}
          </span>
        </div>
        {out && <BranchAvailability product={product} />}
      </div>
      <button
        type="button"
        aria-label={`إضافة ${product.name}`}
        onClick={() => onAdd(product)}
        className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-azure-soft text-azure transition-[transform,background-color,color] duration-150 hover:bg-azure hover:text-white active:scale-90"
      >
        <Plus size={20} />
      </button>
    </li>
  );
});

export function ProductsPanel({
  page,
  loading,
  error,
  category,
  serverUrl,
  onCategory,
  onPage,
  onAdd,
}: ProductsPanelProps) {
  const showImages = usePosPreferences((s) => s.showImages);
  return (
    <section aria-label="المنتجات" className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-2 px-4 pb-3 pt-4">
        <span className="grid h-9 w-9 place-items-center rounded-control bg-violet-soft text-violet-deep">
          <Boxes size={18} aria-hidden />
        </span>
        <h2 className="text-[17px] font-bold text-ink">المنتجات</h2>
        {page && (
          <span className="ltr-isolate ms-auto text-xs text-ink-faint">{formatNumber(page.total)}</span>
        )}
      </header>
      {(page?.categories.length ?? 0) > 0 && (
        <div className="no-scrollbar overflow-x-auto px-4 pb-3">
          <StatusTabs
            label="فئات نقطة البيع"
            value={category}
            onChange={onCategory}
            tabs={[{ id: "", label: "الكل" }, ...(page?.categories ?? []).map((c) => ({ id: c, label: c }))]}
          />
        </div>
      )}
      <ul className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-4 pb-3" aria-busy={loading}>
        {loading &&
          !page &&
          Array.from({ length: 5 }, (_, i) => (
            <li key={i} className="h-[84px] animate-pulse rounded-panel bg-white/70" />
          ))}
        {error && !page && <li className="py-8 text-center text-sm text-danger">{error}</li>}
        {page?.rows.length === 0 && (
          <li className="py-10 text-center text-sm text-ink-faint">لا توجد منتجات مطابقة</li>
        )}
        {page?.rows.map((product) => (
          <ProductCard
            key={product.id}
            product={product}
            serverUrl={serverUrl}
            showImage={showImages}
            onAdd={onAdd}
          />
        ))}
      </ul>
      {page && page.total_pages > 1 && (
        <nav
          aria-label="صفحات المنتجات"
          className="flex items-center justify-between px-4 pb-4 text-sm text-ink-soft"
        >
          <button
            type="button"
            aria-label="السابق"
            disabled={page.page <= 1}
            onClick={() => onPage(page.page - 1)}
            className="grid h-9 w-9 place-items-center rounded-[10px] bg-white shadow-control disabled:opacity-35"
          >
            <ChevronRight size={16} />
          </button>
          <span className="ltr-isolate">
            {page.page} / {page.total_pages}
          </span>
          <button
            type="button"
            aria-label="التالي"
            disabled={page.page >= page.total_pages}
            onClick={() => onPage(page.page + 1)}
            className="grid h-9 w-9 place-items-center rounded-[10px] bg-white shadow-control disabled:opacity-35"
          >
            <ChevronLeft size={16} />
          </button>
        </nav>
      )}
    </section>
  );
}
