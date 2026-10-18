/** Per-device POS preferences (Settings → نقطة البيع). Best-effort localStorage; defaults always work. */
import { create } from "zustand";
import type { SaleType } from "./cart";

export const POS_PAGE_SIZES = [12, 24, 48] as const;
export type PosPageSize = (typeof POS_PAGE_SIZES)[number];

export interface PosPreferences {
  autoPrint: boolean;
  showImages: boolean;
  defaultSaleType: SaleType;
  /** Bank account preselected when the sale type is بنك (treasury account id). */
  defaultBankAccountId: number | null;
  /** Scanning a barcode that matches exactly one product adds it straight to the cart. */
  scanAddsToCart: boolean;
  /** Short tone when a scan is recognised (or not). */
  scanSound: boolean;
  pageSize: PosPageSize;
  /** Ask for confirmation before executing sales above this total (0 = never). */
  confirmAbove: number;
}

const KEY = "finora-management:pos";
export const POS_DEFAULTS: PosPreferences = {
  autoPrint: true,
  showImages: true,
  defaultSaleType: "cash",
  defaultBankAccountId: null,
  scanAddsToCart: true,
  scanSound: true,
  pageSize: 24,
  confirmAbove: 0,
};

function pick<T>(value: unknown, valid: (v: unknown) => v is T, fallback: T): T {
  return valid(value) ? value : fallback;
}
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const isSaleType = (v: unknown): v is SaleType => v === "cash" || v === "credit" || v === "bank";
const isPageSize = (v: unknown): v is PosPageSize => POS_PAGE_SIZES.includes(v as PosPageSize);
const isAccount = (v: unknown): v is number | null =>
  v === null || (Number.isInteger(v) && (v as number) > 0);
const isAmount = (v: unknown): v is number => Number.isInteger(v) && (v as number) >= 0;

function read(): PosPreferences {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return POS_DEFAULTS;
    const p = JSON.parse(raw) as Record<string, unknown>;
    const d = POS_DEFAULTS;
    return {
      autoPrint: pick(p.autoPrint, isBool, d.autoPrint),
      showImages: pick(p.showImages, isBool, d.showImages),
      defaultSaleType: pick(p.defaultSaleType, isSaleType, d.defaultSaleType),
      defaultBankAccountId: pick(p.defaultBankAccountId, isAccount, d.defaultBankAccountId),
      scanAddsToCart: pick(p.scanAddsToCart, isBool, d.scanAddsToCart),
      scanSound: pick(p.scanSound, isBool, d.scanSound),
      pageSize: pick(p.pageSize, isPageSize, d.pageSize),
      confirmAbove: pick(p.confirmAbove, isAmount, d.confirmAbove),
    };
  } catch (error) {
    if (import.meta.env.DEV) console.debug("[pos] preferences unavailable", error);
    return POS_DEFAULTS;
  }
}

interface PosPreferencesState extends PosPreferences {
  update(patch: Partial<PosPreferences>): void;
  reset(): void;
}

function persist(state: PosPreferences): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch (error) {
    if (import.meta.env.DEV) console.debug("[pos] preferences not saved", error);
  }
}

function snapshot(state: PosPreferencesState): PosPreferences {
  return {
    autoPrint: state.autoPrint,
    showImages: state.showImages,
    defaultSaleType: state.defaultSaleType,
    defaultBankAccountId: state.defaultBankAccountId,
    scanAddsToCart: state.scanAddsToCart,
    scanSound: state.scanSound,
    pageSize: state.pageSize,
    confirmAbove: state.confirmAbove,
  };
}

export const usePosPreferences = create<PosPreferencesState>()((set, get) => ({
  ...read(),
  update(patch) {
    set(patch);
    persist(snapshot(get()));
  },
  reset() {
    set(POS_DEFAULTS);
    persist(POS_DEFAULTS);
  },
}));
