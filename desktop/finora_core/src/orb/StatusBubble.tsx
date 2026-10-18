import type { AgentState } from "../data/schemas";
import { cx } from "../ui/primitives";
import { isBusy } from "./orbMachine";

/**
 * Floating status above the orb. The label is keyed so each new status fades in via CSS (no exit choreography:
 * rapid agent state changes must never leave a stale label on screen).
 */
export function StatusBubble({
  state,
  text,
  reducedMotion,
}: {
  state: AgentState;
  text: string;
  reducedMotion: boolean;
}) {
  const busy = isBusy(state);
  return (
    <div className={cx("status-bubble", `is-${state}`)} role="status" aria-live="polite" aria-atomic="true">
      <span className={cx("sb-dots", busy && !reducedMotion && "is-animated")} aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span key={text} className="sb-text">
        {text}
        {busy && <span className="sb-ellipsis">...</span>}
      </span>
    </div>
  );
}
