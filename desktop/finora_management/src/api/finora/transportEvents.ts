/** Lets app-level stores observe connectivity/session outcomes without the API layer importing them. */
import type { FinoraApiError } from "./errors";

type Listener = (error: FinoraApiError | null) => void;
const listeners = new Set<Listener>();

export function onTransportOutcome(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function reportTransportOutcome(error: FinoraApiError | null): void {
  for (const listener of listeners) listener(error);
}
