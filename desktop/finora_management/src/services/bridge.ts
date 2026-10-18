import type { FinoraDesktopBridge } from "@shared/ipc";

export class BridgeUnavailableError extends Error {
  constructor() {
    super("FINORA desktop bridge is unavailable (renderer not running inside Electron)");
    this.name = "BridgeUnavailableError";
  }
}

export function desktopBridge(): FinoraDesktopBridge {
  const bridge = window.finoraDesktop;
  if (!bridge) throw new BridgeUnavailableError();
  return bridge;
}

export function hasDesktopBridge(): boolean {
  return window.finoraDesktop !== undefined;
}
