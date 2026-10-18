/** Suppress keyboard-wedge scans (three rapid keys, <=50ms apart).
 * No text, key values, or passwords are retained; existing input handling is untouched.
 */
export function createTypingFeedback(tick: () => void) {
  let pending: ReturnType<typeof setTimeout> | undefined;
  let count = 0;
  let last = -Infinity;
  let target: EventTarget | null = null;
  const clear = () => {
    clearTimeout(pending);
    count = 0;
    last = -Infinity;
    target = null;
  };
  const flush = () => {
    if (count < 3) for (let i = 0; i < count; i++) tick();
    count = 0;
  };
  return {
    clear,
    key(event: KeyboardEvent) {
      if (["Enter", "Tab", "Escape"].includes(event.key)) {
        clear();
        return;
      }
      if (event.repeat || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key.length !== 1 && event.key !== "Backspace" && event.key !== "Delete") return;
      if (!(event.target instanceof Element)) return;
      const field = event.target.closest('input,textarea,[contenteditable="true"]');
      if (!field || field.closest('[disabled],[readonly],[aria-disabled="true"],[data-sound="off"]')) return;
      if (
        field instanceof HTMLInputElement &&
        !["text", "search", "tel", "url", "email", "password", "number"].includes(field.type)
      )
        return;
      const now = performance.now();
      clearTimeout(pending);
      if (event.target !== target || now - last > 50) flush();
      target = event.target;
      last = now;
      count = Math.min(3, count + 1);
      pending = setTimeout(flush, 65);
    },
  };
}
