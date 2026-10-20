import { startTransition, useEffect, useState, type ComponentType } from "react";
import { useAvailableWindows } from "@/hooks/useAvailableWindows";
import { useWindowManager } from "@/stores/windowManager";
import { FinoraWindow } from "./FinoraWindow";
import { OrdersWindow } from "./orders/OrdersWindow";
import { PosWindow } from "./pos/PosWindow";
import { ReportsWindow } from "./reports/ReportsWindow";
import { ProductsWindow } from "./products/ProductsWindow";
import { PurchasesWindow } from "./purchases/PurchasesWindow";
import { SuppliersWindow } from "./suppliers/SuppliersWindow";
import { EmployeesWindow } from "./employees/EmployeesWindow";
import { FinanceWindow } from "./finance/FinanceWindow";
import { CustomersWindow } from "./customers/CustomersWindow";
import { ExpensesWindow } from "./expenses/ExpensesWindow";
import { BranchesWindow } from "./branches/BranchesWindow";
import { PermissionsWindow } from "./permissions/PermissionsWindow";
import { CatalogWindow } from "./catalog/CatalogWindow";
import { PricingWindow } from "./pricing/PricingWindow";
import { StoreAnalyticsWindow } from "./storeAnalytics/StoreAnalyticsWindow";
import { ProductLinksWindow } from "./productLinks/ProductLinksWindow";
import { ShippingCenterWindow } from "./shipping/ShippingCenterWindow";
import { WINDOW_IDS, type WindowId } from "./registry";

const BODIES: Record<WindowId, ComponentType> = {
  orders: OrdersWindow,
  purchases: PurchasesWindow,
  products: ProductsWindow,
  pos: PosWindow,
  reports: ReportsWindow,
  suppliers: SuppliersWindow,
  employees: EmployeesWindow,
  finance: FinanceWindow,
  customers: CustomersWindow,
  expenses: ExpensesWindow,
  shipping: ShippingCenterWindow,
  branches: BranchesWindow,
  permissions: PermissionsWindow,
  catalog: CatalogWindow,
  pricing: PricingWindow,
  storeAnalytics: StoreAnalyticsWindow,
  productLinks: ProductLinksWindow,
};

const WARM_UP_DELAY_MS = 700;

function whenIdle(callback: () => void): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const handle = window.requestIdleCallback(callback);
    return () => window.cancelIdleCallback(handle);
  }
  const timer = window.setTimeout(callback, 50);
  return () => window.clearTimeout(timer);
}

/**
 * Owns the stage below the navigation bar. Windows stay mounted once built;
 * `active` only decides which one is open. After sign-in, the remaining
 * windows are built one by one in idle time (hidden, fetching nothing), so even
 * the first open of a window is a pure compositor morph with no React mount.
 * A switch is one state change: the old window morphs back into its button
 * while the new one grows out of its own — concurrently — and rapid clicks
 * retarget the running animations instead of stacking new ones.
 */
export function WindowTransitionManager() {
  const active = useWindowManager((s) => s.active);
  const available = useAvailableWindows();
  const [stage, setStage] = useState<HTMLElement | null>(null);
  const [mounted, setMounted] = useState<ReadonlySet<WindowId>>(() => new Set());

  if (active && !mounted.has(active)) setMounted(new Set(mounted).add(active));

  const next = available.find((id) => !mounted.has(id));
  useEffect(() => {
    if (!stage || !next) return;
    let cancelIdle: (() => void) | null = null;
    const timer = window.setTimeout(() => {
      cancelIdle = whenIdle(() =>
        // Transition render: React yields to clicks/keys while building the hidden window.
        startTransition(() => setMounted((current) => new Set(current).add(next))),
      );
    }, WARM_UP_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      cancelIdle?.();
    };
  }, [stage, next]);

  return (
    <div ref={setStage} className="pointer-events-none relative min-h-0 flex-1" data-testid="window-stage">
      {stage &&
        WINDOW_IDS.filter((id) => mounted.has(id)).map((id) => {
          const Body = BODIES[id];
          return (
            <FinoraWindow key={id} id={id} open={active === id} stage={stage}>
              <Body />
            </FinoraWindow>
          );
        })}
    </div>
  );
}
