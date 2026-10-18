/** In-app notification center (connection and session events). */
import { create } from "zustand";

export type NotificationTone = "info" | "warning" | "success";

export interface AppNotification {
  id: number;
  tone: NotificationTone;
  title: string;
  body: string;
  at: number;
  read?: boolean;
  group?: "hr";
  key?: string;
  target?: { tab: string; person_id: number | null; date: string; month: string | null };
}

interface NotificationState {
  items: AppNotification[];
  unread: number;
  add(input: Omit<AppNotification, "id" | "at">): void;
  markAllRead(): void;
  clear(): void;
  replaceHR(items: Omit<AppNotification, "id">[]): void;
}

const MAX_ITEMS = 50;
let nextId = 1;

export const useNotifications = create<NotificationState>()((set, get) => ({
  items: [],
  unread: 0,
  add(input) {
    const item: AppNotification = { ...input, id: nextId++, at: Date.now() };
    const items = [item, ...get().items].slice(0, MAX_ITEMS);
    set({ items, unread: items.filter((i) => !i.read).length });
  },
  markAllRead() {
    if (get().unread) set({ unread: 0, items: get().items.map((i) => ({ ...i, read: true })) });
  },
  clear() {
    set({ items: [], unread: 0 });
  },
  replaceHR(items) {
    const old = get().items.filter((i) => i.group === "hr");
    const retained = items.map((i) => ({
      ...i,
      id: old.find((previous) => previous.key === i.key)?.id ?? nextId++,
      read: old.find((previous) => previous.key === i.key)?.read ?? false,
    }));
    const nextItems = [...retained, ...get().items.filter((i) => i.group !== "hr")].slice(0, MAX_ITEMS);
    set({ items: nextItems, unread: nextItems.filter((i) => !i.read).length });
  },
}));
