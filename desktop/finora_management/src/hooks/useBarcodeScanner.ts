import { useEffect, useRef } from "react";

const MAX_GAP_MS = 50;
const MIN_LENGTH = 6;

/** Physical key → character, independent of the active keyboard layout (scanners type on Arabic layouts too). */
export function scannerChar(event: Pick<KeyboardEvent, "code" | "shiftKey">): string | null {
  if (/^Digit\d$/.test(event.code)) return event.code.slice(5);
  if (/^Numpad\d$/.test(event.code)) return event.code.slice(6);
  if (/^Key[A-Z]$/.test(event.code)) {
    const letter = event.code.slice(3);
    return event.shiftKey ? letter : letter.toLowerCase();
  }
  if (event.code === "Minus" || event.code === "NumpadSubtract") return "-";
  return null;
}

/**
 * Detects keyboard-wedge barcode scanners: a burst of keys (≤ 50 ms apart)
 * ending with Enter. Typing in a text field is left alone — the field gets
 * the scan as normal input.
 */
export function useBarcodeScanner(
  onScan: (code: string) => void,
  enabled: boolean,
  /** Order numbers are printed as barcodes and can be short (e.g. 875). */
  minLength = MIN_LENGTH,
): void {
  const callback = useRef(onScan);
  callback.current = onScan;

  useEffect(() => {
    if (!enabled) return;
    let buffer = "";
    let last = 0;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      if (event.ctrlKey || event.altKey || event.metaKey) return;
      const now = performance.now();
      if (now - last > MAX_GAP_MS) buffer = "";
      last = now;
      if (event.key === "Enter") {
        if (buffer.length >= minLength) {
          event.preventDefault();
          callback.current(buffer);
        }
        buffer = "";
        return;
      }
      const char = scannerChar(event);
      if (char) buffer += char;
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled, minLength]);
}
