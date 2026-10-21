import type { FinoraDesktopBridge } from "@shared/ipc";

declare global {
  /** package.json version, injected by Vite at build time. */
  const __APP_VERSION__: string;
  interface Window {
    /** Provided by the Electron preload; absent when the renderer runs outside Electron. */
    finoraDesktop?: FinoraDesktopBridge;
  }
}

export {};
