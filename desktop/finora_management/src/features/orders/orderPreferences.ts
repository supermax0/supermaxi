/** Per-device order preferences (Settings → الطلبات). Best-effort localStorage; defaults always work. */
import { create } from "zustand";

/** What scanning an order's barcode in the orders window does. */
export type OrderScanAction = "shipping" | "details" | "select" | "off";

export interface OrderPreferences {
  scanAction: OrderScanAction;
  /** Save the shipping barcodes as soon as the last piece is scanned (Enter). */
  autoSaveShipping: boolean;
}

const KEY = "finora-management:orders";
export const ORDER_DEFAULTS: OrderPreferences = { scanAction: "shipping", autoSaveShipping: true };

const isAction = (v: unknown): v is OrderScanAction =>
  v === "shipping" || v === "details" || v === "select" || v === "off";

function read(): OrderPreferences {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return ORDER_DEFAULTS;
    const p = JSON.parse(raw) as Record<string, unknown>;
    return {
      scanAction: isAction(p.scanAction) ? p.scanAction : ORDER_DEFAULTS.scanAction,
      autoSaveShipping:
        typeof p.autoSaveShipping === "boolean" ? p.autoSaveShipping : ORDER_DEFAULTS.autoSaveShipping,
    };
  } catch (error) {
    if (import.meta.env.DEV) console.debug("[orders] preferences unavailable", error);
    return ORDER_DEFAULTS;
  }
}

interface OrderPreferencesState extends OrderPreferences {
  update(patch: Partial<OrderPreferences>): void;
}

export const useOrderPreferences = create<OrderPreferencesState>()((set, get) => ({
  ...read(),
  update(patch) {
    set(patch);
    const { scanAction, autoSaveShipping } = get();
    try {
      window.localStorage.setItem(KEY, JSON.stringify({ scanAction, autoSaveShipping }));
    } catch (error) {
      if (import.meta.env.DEV) console.debug("[orders] preferences not saved", error);
    }
  },
}));
