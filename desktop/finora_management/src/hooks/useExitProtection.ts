import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { desktopBridge, hasDesktopBridge } from "@/services/bridge";

import { draftScope } from "@/utils/draftScope";
import { useCart } from "@/features/pos/cart";
const valueOf = (node: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement) =>
  node instanceof HTMLInputElement && ["checkbox", "radio"].includes(node.type)
    ? String(node.checked)
    : node.value;

/** Tracks user edits in forms/dialogs, independently of the route that owns them. */
export function useExitProtection() {
  const client = useQueryClient();
  useEffect(() => {
    const bridge = hasDesktopBridge() ? desktopBridge().lifecycle : undefined;
    if (!bridge) return;
    const fields = new Map<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, string>();
    const eligible = (node: EventTarget | null) => {
      if (!(
        node instanceof HTMLInputElement ||
        node instanceof HTMLSelectElement ||
        node instanceof HTMLTextAreaElement
      ))
        return null;
      if (
        !draftScope(node) ||
        node.closest('[aria-label="الإعدادات"], [role="search"]') ||
        (node instanceof HTMLInputElement && ["search", "password", "hidden"].includes(node.type))
      )
        return null;
      return node;
    };
    let timer: ReturnType<typeof setTimeout> | undefined;
    const publish = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        for (const node of fields.keys()) if (!node.isConnected) fields.delete(node);
        const dirty =
          useCart.getState().lines.length > 0 ||
          [...fields].some(([node, initial]) => valueOf(node) !== initial) ||
          document.querySelector('[data-unsaved="true"]') !== null;
        void bridge
          .activity({
            dirty,
            saving:
              client.isMutating({
                predicate: (mutation) => mutation.options.mutationKey?.[1] !== "signout",
              }) > 0,
          })
          .catch(() => console.error("[exit] protection unavailable"));
      }, 0);
    };
    const remember = (event: Event) => {
      const node = eligible(event.target);
      if (node && !fields.has(node)) fields.set(node, valueOf(node));
    };
    const saved = (event: Event) => {
      const scope = (event as CustomEvent<Element | null>).detail;
      if (scope) for (const node of fields.keys()) if (scope.contains(node)) fields.delete(node);
      publish();
    };
    const observer = new MutationObserver(publish);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["data-unsaved"],
    });
    const unsubscribe = client.getMutationCache().subscribe(publish);
    const unsubscribeCart = useCart.subscribe(publish);
    document.addEventListener("focusin", remember, true);
    document.addEventListener("beforeinput", remember, true);
    document.addEventListener("input", publish, true);
    document.addEventListener("change", publish, true);
    document.addEventListener("finora:form-saved", saved);
    publish();
    return () => {
      clearTimeout(timer);
      observer.disconnect();
      unsubscribe();
      unsubscribeCart();
      document.removeEventListener("focusin", remember, true);
      document.removeEventListener("beforeinput", remember, true);
      document.removeEventListener("input", publish, true);
      document.removeEventListener("change", publish, true);
      document.removeEventListener("finora:form-saved", saved);
    };
  }, [client]);
}
