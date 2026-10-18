import { useEffect } from "react";
import { playSound, unlockSounds } from "@/services/sounds";
import { createTypingFeedback } from "@/services/typingFeedback";
import { useWindowManager } from "@/stores/windowManager";
import { useToasts } from "@/stores/toasts";
import { useNotifications } from "@/stores/notifications";
const CONTROLS =
  'button,a[href],input:not([type="hidden"]),textarea,select,[contenteditable="true"],[role="button"],[role="tab"],[role="option"],[role="checkbox"],[role="menuitem"],[role="menuitemcheckbox"],[role="menuitemradio"],[role="radio"],[role="switch"],tr[tabindex]';
export function useInterfaceSounds() {
  useEffect(() => {
    const typing = createTypingFeedback(() => playSound("typing"));
    const arm = () => unlockSounds();
    const click = (event: MouseEvent) => {
      if (!(event.target instanceof Element)) return;
      const control = event.target.closest(CONTROLS);
      if (!control || control.closest('[disabled],[aria-disabled="true"],[data-sound="off"]')) return;
      playSound(
        control.matches(
          '[role="switch"],[role="radio"],[role="checkbox"],input[type="checkbox"],input[type="radio"]',
        )
          ? "toggle"
          : "click",
      );
    };
    const change = (event: Event) => {
      const input = event.target;
      if (
        (input instanceof HTMLSelectElement ||
          (input instanceof HTMLInputElement &&
            ["date", "time", "datetime-local", "color", "file", "range"].includes(input.type))) &&
        !input.disabled
      )
        playSound("toggle");
    };
    const submit = () => playSound("click");
    const invalid = () => playSound("warning");
    const key = (event: KeyboardEvent) => {
      unlockSounds();
      typing.key(event);
      if (event.repeat) return;
      if (
        event.key === "Escape" &&
        document.querySelector('[aria-modal="true"],[role="menu"],[role="complementary"]')
      )
        playSound("close");
      else if ((event.ctrlKey || event.metaKey) && ["k", "n", "s", "Enter"].includes(event.key))
        playSound("click");
      else if (["F2", "F3", "F9"].includes(event.key)) playSound("click");
    };
    const removeWindow = useWindowManager.subscribe((next, before) => {
      if (next.active !== before.active) playSound(next.active ? "open" : "close");
      else if (next.expanded !== before.expanded) playSound("open");
    });
    const removeToast = useToasts.subscribe((next, before) => {
      const added = next.toasts.find((row) => !before.toasts.some((old) => old.id === row.id));
      if (added) playSound(added.tone === "info" ? "notify" : added.tone);
    });
    const removeNotification = useNotifications.subscribe((next, before) => {
      const added = next.items.find((row) => !row.read && !before.items.some((old) => old.id === row.id));
      if (added) playSound(added.tone === "warning" ? "warning" : "notify");
    });
    const panels = () =>
      new Set(
        Array.from(
          document.querySelectorAll('[aria-modal="true"],[role="complementary"],[role="menu"]'),
        ).filter((node) => !node.closest('[aria-hidden="true"]') && node.getClientRects().length > 0),
      );
    let previous = panels();
    const alerts = new WeakSet<Element>(document.querySelectorAll('[role="alert"]'));
    const observer = new MutationObserver(() => {
      const next = panels();
      if ([...next].some((node) => !previous.has(node))) playSound("open");
      else if ([...previous].some((node) => !next.has(node))) playSound("close");
      previous = next;
      for (const alert of document.querySelectorAll('[role="alert"]')) {
        if (alerts.has(alert)) continue;
        alerts.add(alert);
        if (!alert.closest('[aria-live="polite"],[aria-hidden="true"]') && alert.getClientRects().length > 0)
          playSound("error");
      }
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-hidden"],
    });
    document.addEventListener("pointerdown", arm, true);
    document.addEventListener("click", click, true);
    document.addEventListener("change", change, true);
    document.addEventListener("submit", submit, true);
    document.addEventListener("invalid", invalid, true);
    window.addEventListener("keydown", key, true);
    window.addEventListener("blur", typing.clear);
    document.addEventListener("focusout", typing.clear, true);
    return () => {
      document.removeEventListener("pointerdown", arm, true);
      document.removeEventListener("click", click, true);
      document.removeEventListener("change", change, true);
      document.removeEventListener("submit", submit, true);
      document.removeEventListener("invalid", invalid, true);
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("blur", typing.clear);
      document.removeEventListener("focusout", typing.clear, true);
      typing.clear();
      removeWindow();
      removeToast();
      removeNotification();
      observer.disconnect();
    };
  }, []);
}
