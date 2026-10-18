import { useQuery } from "@tanstack/react-query";
import { ArrowDownLeft, ArrowUpRight, ExternalLink, Pencil } from "lucide-react";
import { finora, toFinoraError } from "@/api/finora";
import type { ProductMovement, ProductRow } from "@/api/finora/products";
import { IconButton } from "@/components/IconButton";
import { DetailRow, SidePanel } from "@/components/SidePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { STOCK_STYLES } from "@/features/products/stock";
import { toast } from "@/stores/toasts";
import { formatNumber } from "@/utils/format";
import { formatIqd } from "@/utils/money";
import { ProductThumb } from "@/components/ProductThumb";
import { FeatureHelp } from "@/components/FeatureHelp";

function movementDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("en-GB");
}

function MovementItem({ movement }: { movement: ProductMovement }) {
  const inbound = (movement.quantity_in ?? 0) > 0;
  const quantity = inbound ? (movement.quantity_in ?? 0) : (movement.quantity_out ?? 0);
  return (
    <li className="flex items-center gap-3 rounded-control bg-white/80 px-3 py-2.5 text-sm ring-1 ring-line/60">
      <span
        className={`grid h-8 w-8 shrink-0 place-items-center rounded-full ${inbound ? "bg-success-soft text-success" : "bg-danger-soft text-danger"}`}
      >
        {inbound ? <ArrowDownLeft size={15} aria-hidden /> : <ArrowUpRight size={15} aria-hidden />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{movement.type_ar || movement.type}</p>
        <p className="truncate text-xs text-ink-faint">{movement.description ?? ""}</p>
      </div>
      <div className="text-end">
        <p className={`ltr-isolate font-semibold ${inbound ? "text-success" : "text-danger"}`}>
          {inbound ? "+" : "−"}
          {formatNumber(quantity)}
        </p>
        <p className="ltr-isolate text-[11px] text-ink-faint">{movementDate(movement.date)}</p>
      </div>
    </li>
  );
}

export function ProductDetailsPanel({
  product,
  imageSrc,
  onClose,
  onEdit,
  onViewActivity,
}: {
  product: ProductRow | null;
  imageSrc: string | null;
  onClose(): void;
  onEdit(productId: number): void;
  onViewActivity?(productId: number): void;
}) {
  const movements = useQuery({
    queryKey: ["products", "movements", product?.id ?? 0],
    queryFn: () => finora.products.movements(product?.id ?? 0),
    enabled: product !== null,
    placeholderData: undefined,
  });
  const details = useQuery({
    queryKey: ["products", "details", product?.id ?? 0],
    queryFn: () => finora.products.details(product?.id ?? 0),
    enabled: product !== null,
  });

  return (
    <SidePanel
      open={product !== null}
      title={product?.name ?? ""}
      subtitle={product ? <span className="ltr-isolate">{product.sku || product.barcode}</span> : undefined}
      onClose={onClose}
      actions={
        product && (
          <>
            <button
              type="button"
              onClick={() => onEdit(product.id)}
              className="flex h-8 items-center gap-1.5 rounded-control bg-violet-soft px-3 text-xs font-semibold text-violet-deep transition-colors hover:bg-violet hover:text-white"
            >
              <Pencil size={13} aria-hidden />
              تعديل
            </button>
            <IconButton
              label="فتح في FINORA"
              size="sm"
              onClick={() => {
                finora.products
                  .openInFinora(product.id)
                  .catch((error: unknown) => toast.error(toFinoraError(error).message));
              }}
            >
              <ExternalLink size={15} />
            </IconButton>
          </>
        )
      }
    >
      {product && (
        <div className="space-y-5">
          <div className="flex justify-center rounded-panel bg-surface-sunken/70 p-4">
            <ProductThumb src={imageSrc} size={120} />
          </div>
          <div className="flex justify-center">
            <StatusBadge {...STOCK_STYLES[product.stock_state]} />
          </div>
          <section>
            <DetailRow label="SKU">
              <span className="ltr-isolate">{product.sku || "—"}</span>
            </DetailRow>
            <DetailRow label="الباركود">
              <span className="ltr-isolate">{product.barcode || "—"}</span>
            </DetailRow>
            <DetailRow label="الفئة">{product.category || "—"}</DetailRow>
            <DetailRow label="سعر الشراء">
              <span className="ltr-isolate">{formatIqd(product.buy_price)}</span>
            </DetailRow>
            <DetailRow label="سعر البيع">
              <span className="ltr-isolate font-semibold">{formatIqd(product.sale_price)}</span>
            </DetailRow>
            <DetailRow label="الكمية المتوفرة">
              <span className="ltr-isolate font-semibold">{formatNumber(product.quantity)}</span>
            </DetailRow>
            <DetailRow label="أدنى مخزون">
              <span className="ltr-isolate">{formatNumber(product.low_stock_threshold)}</span>
            </DetailRow>
          </section>
          {!!details.data?.colors.length && (
            <section className="space-y-2">
              <h3 className="flex items-center gap-2 text-xs font-semibold text-ink-faint">
                خيارات المنتج{" "}
                <FeatureHelp text="كل خيار له سعر ومخزون مستقل. الخيارات الموقوفة تبقى ظاهرة هنا لحماية سجل الفواتير، ويمكن تعديلها من نافذة المنتج." />
              </h3>
              {details.data.colors.map((option) => (
                <div key={option.name} className="rounded-control border border-line p-3 text-sm">
                  <p className="font-semibold">
                    {option.name}
                    {option.active === false ? " · موقوف" : ""}
                  </p>
                  <p className="mt-1 text-xs text-ink-soft">
                    {formatNumber(option.qty)} قطعة · بيع{" "}
                    {formatIqd(option.sale_price ?? details.data?.sale_price ?? 0)} · شراء{" "}
                    {formatIqd(option.buy_price ?? details.data?.buy_price ?? 0)}
                  </p>
                </div>
              ))}
            </section>
          )}
          <section>
            <h3 className="mb-2 text-xs font-semibold text-ink-faint">آخر حركات المخزون</h3>
            {onViewActivity && (
              <button
                type="button"
                onClick={() => onViewActivity(product.id)}
                className="mb-3 rounded-control border border-line bg-white px-3 py-2 text-sm text-violet hover:bg-violet-soft"
              >
                عرض سجل حركة الصنف
              </button>
            )}
            {movements.isLoading && <span className="block h-10 animate-pulse rounded-control bg-line/70" />}
            {movements.error && (
              <p className="text-sm text-danger">{toFinoraError(movements.error).message}</p>
            )}
            {movements.data?.length === 0 && <p className="text-sm text-ink-faint">لا توجد حركات مسجلة.</p>}
            <ul className="space-y-1.5">
              {movements.data?.slice(0, 15).map((movement, index) => (
                <MovementItem key={`${movement.type}-${index}`} movement={movement} />
              ))}
            </ul>
          </section>
        </div>
      )}
    </SidePanel>
  );
}
