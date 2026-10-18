import { getDevSource } from "./devSource";
import type { DataSource } from "./source";

/**
 * Resolves the backend for this build.
 * - Development (vite dev, or VITE_FINORA_DEV_DATA=1 for E2E builds): in-memory development data.
 * - Otherwise: the HTTP source (Phase 6). Until it is configured, `null` → the app shows the setup state.
 *   There is no silent fallback to development data in production.
 */
export function resolveDataSource(): DataSource | null {
  // VITE_FINORA_SOURCE=http runs the dev server against a real backend (login + HTTP source).
  if (import.meta.env.VITE_FINORA_SOURCE === "http") return null;
  const devData = import.meta.env.DEV || import.meta.env.VITE_FINORA_DEV_DATA === "1";
  if (!devData) return null;
  const params = new URLSearchParams(window.location.search);
  const frozen = params.get("frozen");
  return getDevSource({
    simulate: params.get("sim") !== "0",
    now: frozen ? new Date(frozen) : undefined,
    latency: params.has("latency") ? Number(params.get("latency")) : undefined,
    firstCycle: params.has("cycle") ? Number(params.get("cycle")) : undefined,
    firstCycleDelay: params.has("cycleDelay") ? Number(params.get("cycleDelay")) : undefined,
  });
}
