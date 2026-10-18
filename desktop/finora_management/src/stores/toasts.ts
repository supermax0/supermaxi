import { create } from "zustand";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastState {
  toasts: Toast[];
  push(tone: ToastTone, message: string): number;
  dismiss(id: number): void;
}

const AUTO_DISMISS_MS = 4200;
const MAX_VISIBLE = 4;
let nextId = 1;

export const useToasts = create<ToastState>()((set, get) => ({
  toasts: [],
  push(tone, message) {
    const id = nextId++;
    set({ toasts: [...get().toasts, { id, tone, message }].slice(-MAX_VISIBLE) });
    window.setTimeout(() => get().dismiss(id), AUTO_DISMISS_MS);
    return id;
  },
  dismiss(id) {
    set({ toasts: get().toasts.filter((toast) => toast.id !== id) });
  },
}));

export const toast = {
  success: (message: string) => useToasts.getState().push("success", message),
  error: (message: string) => useToasts.getState().push("error", message),
  info: (message: string) => useToasts.getState().push("info", message),
};
