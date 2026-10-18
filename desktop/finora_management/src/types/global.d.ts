import type { FinoraDesktopBridge } from "@shared/ipc";

declare global {
  interface Window {
    /** Provided by the Electron preload; absent when the renderer runs outside Electron. */
    finoraDesktop?: FinoraDesktopBridge;
  }
}

export {};
