/** Favorites and recently opened pages (per device, best-effort localStorage — the app works without it). */
import { create } from "zustand";

const STORAGE_KEY = "finora-management:navigation";
export const RECENT_LIMIT = 6;

interface Stored {
  favorites: string[];
  recent: string[];
}

function read(): Stored {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<Stored>;
      const ids = (v: unknown) =>
        Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
      return { favorites: ids(parsed.favorites), recent: ids(parsed.recent).slice(0, RECENT_LIMIT) };
    }
  } catch (error) {
    if (import.meta.env.DEV) console.debug("[navigation] prefs unavailable", error);
  }
  return { favorites: [], recent: [] };
}

function write(state: Stored): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    if (import.meta.env.DEV) console.debug("[navigation] prefs not persisted", error);
  }
}

interface NavigationPrefsState extends Stored {
  toggleFavorite(id: string): void;
  recordVisit(id: string): void;
}

export const useNavigationPrefs = create<NavigationPrefsState>()((set, get) => ({
  ...read(),
  toggleFavorite(id) {
    const { favorites, recent } = get();
    const next = favorites.includes(id) ? favorites.filter((f) => f !== id) : [...favorites, id];
    write({ favorites: next, recent });
    set({ favorites: next });
  },
  recordVisit(id) {
    const { favorites, recent } = get();
    const next = [id, ...recent.filter((r) => r !== id)].slice(0, RECENT_LIMIT);
    write({ favorites, recent: next });
    set({ recent: next });
  },
}));
