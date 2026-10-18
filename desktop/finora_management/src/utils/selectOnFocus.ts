/**
 * Select the field's text after React swaps the formatted value (1,250,000)
 * for the raw digits — but only if the user has not started typing yet, so a
 * fast first keystroke is never overwritten.
 */
export function selectAfterFormatSwap(input: HTMLInputElement, raw: string): void {
  requestAnimationFrame(() => {
    if (document.activeElement === input && input.value === raw) input.select();
  });
}
