import { Copy, Minus, Square, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { WindowState } from "@shared/ipc";
import { desktopBridge } from "@/services/bridge";
import { playSound, unlockSounds } from "@/services/sounds";
import { IconButton } from "./IconButton";

/** Native window controls (frameless Electron window) wired through the preload bridge. */
export function WindowControls() {
  const [state, setState] = useState<WindowState>({ maximized: false, focused: true });

  useEffect(() => {
    const bridge = desktopBridge();
    let alive = true;
    bridge.window
      .getState()
      .then((initial) => alive && setState(initial))
      .catch((error: unknown) => console.error("[window] state unavailable", error));
    const unsubscribe = bridge.window.onState(setState);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);

  const run =
    (action: () => Promise<unknown>, closing = false) =>
    () => {
      unlockSounds();
      if (closing) playSound("close");
      action().catch((error: unknown) => console.error("[window] control failed", error));
    };

  return (
    <div className="flex items-center gap-0.5" role="group" aria-label="التحكم بنافذة التطبيق">
      <IconButton label="تصغير" onClick={run(() => desktopBridge().window.minimize(), true)}>
        <Minus size={18} />
      </IconButton>
      <IconButton
        label={state.maximized ? "استعادة" : "تكبير"}
        onClick={run(() => desktopBridge().window.toggleMaximize().then(setState))}
      >
        {state.maximized ? <Copy size={15} className="-scale-x-100" /> : <Square size={15} />}
      </IconButton>
      <IconButton label="إغلاق" tone="danger" onClick={run(() => desktopBridge().window.close(), true)}>
        <X size={19} />
      </IconButton>
    </div>
  );
}
