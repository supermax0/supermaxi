import { ArrowUpRight, ChevronLeft, RefreshCw, type LucideIcon } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { formatNumber } from "@/utils/format";
export function relative(at: number): string {
  const minutes = Math.max(0, Math.floor((Date.now() - at) / 60_000));
  return minutes < 1
    ? "الآن"
    : minutes < 60
      ? `قبل ${minutes} دقيقة`
      : minutes < 1440
        ? `قبل ${Math.floor(minutes / 60)} ساعة`
        : new Date(at).toLocaleDateString("ar-IQ");
}
export function Panel({
  title,
  icon: Icon,
  children,
  footer,
  count,
  className = "",
  style,
}: {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
  footer?: ReactNode;
  count?: number;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <section className={`workspace-panel ${className}`} style={style} aria-label={title}>
      <header>
        <h2>
          <Icon size={19} />
          {title}
        </h2>
        {count !== undefined && <span className="workspace-counter">{formatNumber(count)}</span>}
      </header>
      <div className="workspace-panel-body">{children}</div>
      {footer && <footer>{footer}</footer>}
    </section>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <p className="workspace-empty">{children}</p>;
}
export function Retry({
  retry,
  children = "تعذر تحميل البيانات",
}: {
  retry(): unknown;
  children?: ReactNode;
}) {
  return (
    <div className="workspace-error" role="alert">
      {children}
      <button onClick={() => void retry()}>
        <RefreshCw size={13} />
        إعادة المحاولة
      </button>
    </div>
  );
}
export function Skeleton() {
  return <span className="workspace-skeleton" aria-label="جارٍ التحميل" />;
}
export function Metric({
  title,
  icon: Icon,
  value,
  detail,
  change,
  tone,
  error,
  retry,
  onOpen,
}: {
  title: string;
  icon: LucideIcon;
  value: number | undefined;
  detail: ReactNode;
  change?: number | null;
  tone: string;
  error?: boolean;
  retry(): unknown;
  onOpen(): void;
}) {
  return (
    <section className={`workspace-metric tone-${tone}`} aria-label={title}>
      <button className="workspace-metric-open" onClick={onOpen} aria-label={`فتح ${title}`}>
        <span>
          <span className="workspace-metric-title">
            {title}
            <ChevronLeft size={15} />
          </span>
          <strong>
            {value === undefined ? error ? "—" : <Skeleton /> : formatNumber(value)}
            {value !== undefined && ["مبيعات اليوم", "المستحقات"].includes(title) && <small> د.ع</small>}
          </strong>
          <span className="workspace-metric-detail">{detail}</span>
        </span>
        <span className="workspace-metric-icon">
          <Icon size={29} strokeWidth={1.7} />
        </span>
      </button>
      {change != null && (
        <span dir="ltr" className={`workspace-change ${change < 0 ? "negative" : ""}`}>
          <ArrowUpRight size={13} />
          {change > 0 ? "+" : ""}
          {change}%
        </span>
      )}
      {error && <Retry retry={retry} />}
    </section>
  );
}
