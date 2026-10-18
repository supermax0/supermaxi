import { getCurrentWindow } from "@tauri-apps/api/window";

/** True when running inside the Tauri shell (false in the browser / Playwright web shell). */
export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function report(action: string) {
  return (err: unknown) => console.error(`[finora-core] window ${action} failed`, err);
}

export const windowControls = {
  minimize: () => getCurrentWindow().minimize().catch(report("minimize")),
  toggleMaximize: () => getCurrentWindow().toggleMaximize().catch(report("maximize")),
  close: () => getCurrentWindow().close().catch(report("close")),
  /** Calls back with the maximized state on every resize. Returns an unsubscribe function. */
  onResized(cb: (maximized: boolean) => void): () => void {
    const w = getCurrentWindow();
    let disposed = false;
    let unlisten: (() => void) | null = null;
    const sync = () => w.isMaximized().then(cb).catch(report("state"));
    sync();
    w.onResized(sync)
      .then((u) => {
        if (disposed) u();
        else unlisten = u;
      })
      .catch(report("listen"));
    return () => {
      disposed = true;
      unlisten?.();
    };
  },
};
