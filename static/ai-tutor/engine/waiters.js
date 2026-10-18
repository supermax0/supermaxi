/* Passive observers for user actions and real backend results. Nothing here mutates the page. */
import { conditionMet, requestMatches, selectorFor } from "./core.js";
import { resolve } from "./targets.js";

function onceAborted(signal, fn) {
  signal?.addEventListener("abort", fn, { once: true });
}

/** Resolves when the user clicks the target (document-level capture survives re-renders). */
export function waitClick(ref, { signal, root = document } = {}) {
  const selector = selectorFor(ref);
  return new Promise((resolveClick, reject) => {
    const handler = (event) => {
      if (event.target instanceof Element && event.target.closest(selector)) {
        cleanup();
        resolveClick(event);
      }
    };
    const cleanup = () => root.removeEventListener("click", handler, true);
    root.addEventListener("click", handler, true);
    onceAborted(signal, () => {
      cleanup();
      reject(new DOMException("aborted", "AbortError"));
    });
  });
}

function snapshot(targetRef, watchRef, root) {
  const target = resolve(targetRef, root);
  const watched = watchRef ? [...root.querySelectorAll(selectorFor(watchRef))] : [];
  return {
    value: target && "value" in target ? target.value : "",
    checked: watched.filter((el) => el.checked).length,
  };
}

/**
 * Calls onChange(boolean) whenever the input/select condition flips. The step
 * itself completes when the user presses "next" (so they stay in control).
 */
export function watchCondition({ target, watch, condition, onChange, signal, root = document }) {
  let last = null;
  const evaluate = () => {
    const ok = conditionMet(condition, snapshot(target, watch, root));
    if (ok !== last) {
      last = ok;
      onChange(ok);
    }
  };
  const events = ["input", "change", "click"];
  events.forEach((name) => root.addEventListener(name, evaluate, true));
  const observer = new MutationObserver(evaluate);
  observer.observe(root.documentElement, { childList: true, subtree: true });
  evaluate();
  const stop = () => {
    events.forEach((name) => root.removeEventListener(name, evaluate, true));
    observer.disconnect();
  };
  onceAborted(signal, stop);
  return stop;
}

/** Observes window.fetch traffic without altering requests or responses. */
export class FetchObserver {
  constructor(win = window) {
    this.win = win;
    this.listeners = new Set();
    this.original = null;
    this.wrapper = null;
  }

  install() {
    if (this.original) return;
    this.original = this.win.fetch.bind(this.win);
    this.wrapper = (input, init) => {
      const request = this.describe(input, init);
      const promise = this.original(input, init);
      promise.then((response) => this.report(request, response.clone()), () => undefined);
      return promise;
    };
    this.win.fetch = this.wrapper;
  }

  uninstall() {
    if (this.original && this.win.fetch === this.wrapper) this.win.fetch = this.original;
    this.listeners.clear();
    this.original = this.wrapper = null;
  }

  describe(input, init) {
    const raw = typeof input === "string" ? input : input?.url || String(input);
    const url = new URL(raw, this.win.location.href);
    return { method: (init?.method || input?.method || "GET").toUpperCase(), pathname: url.pathname + url.search };
  }

  async report(request, response) {
    const body = await response.json().catch(() => null);
    const event = { ...request, status: response.status, ok: response.ok && body?.ok !== false, error: body?.error || null };
    this.listeners.forEach((listener) => listener(event));
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

/**
 * Resolves on the first matching request that succeeded (HTTP ok AND body.ok !== false).
 * Failed matching requests are reported through onFailure and the wait continues.
 */
export function waitApiSuccess(observer, match, { onFailure, signal } = {}) {
  return new Promise((resolveApi, reject) => {
    const unsubscribe = observer.subscribe((event) => {
      if (!requestMatches(match, event.method, event.pathname.split("?")[0])) return;
      if (event.ok) {
        unsubscribe();
        resolveApi(event);
      } else {
        onFailure?.(event);
      }
    });
    onceAborted(signal, () => {
      unsubscribe();
      reject(new DOMException("aborted", "AbortError"));
    });
  });
}

/** Polls a server-side validator until it confirms the real state. */
export async function waitState(check, { intervalMs = 700, timeoutMs = 15000, signal } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (signal?.aborted) throw new DOMException("aborted", "AbortError");
    if (await check()) return true;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}
