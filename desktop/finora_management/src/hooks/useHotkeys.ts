import { useEffect, useRef } from "react";

export interface HotkeyMap {
  /** Keys like "ctrl+k", "ctrl+1", "escape". */
  [combo: string]: (event: KeyboardEvent) => void;
}

function comboOf(event: KeyboardEvent): string {
  const parts: string[] = [];
  if (event.ctrlKey || event.metaKey) parts.push("ctrl");
  if (event.shiftKey) parts.push("shift");
  if (event.altKey) parts.push("alt");
  // `code` keeps shortcuts working with the Arabic keyboard layout.
  const key = event.code.startsWith("Digit")
    ? event.code.slice(5)
    : event.code.startsWith("Key")
      ? event.code.slice(3).toLowerCase()
      : event.key.toLowerCase();
  parts.push(key);
  return parts.join("+");
}

export function useHotkeys(map: HotkeyMap): void {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const handler = ref.current[comboOf(event)];
      if (!handler) return;
      event.preventDefault();
      handler(event);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
