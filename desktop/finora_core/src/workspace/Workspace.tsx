import { AnimatePresence, motion } from "framer-motion";
import { useLayoutEffect, useRef } from "react";
import { reducedTransition, transitions } from "../design/motion";
import { useAgent } from "../state/agent";
import { useUi } from "../state/ui";
import { MiniOrb, cx } from "../ui/primitives";
import { ChatPanel } from "./ChatPanel";
import { ConversationList } from "./ConversationList";
import { CustomerPanel } from "./CustomerPanel";

const CLOSED_OPACITY = 0.001;
const WORKING = new Set(["message_received", "reading", "thinking", "searching", "replying", "executing"]);

/**
 * The open state of the orb.
 *
 * Performance design:
 * - The morph is carried by `.ws-shell`, an EMPTY glass surface sharing `layoutId="core-surface"` with the orb
 *   hit-area. Framer scales only that plain rounded rect, so no text or shadows are re-rasterized per frame.
 * - The content is mounted once at startup and stays mounted (hidden + inert while closed). Opening the
 *   workspace is therefore only opacity/translate on composited layers — no React mount during the animation.
 */
export function Workspace({ open, reducedMotion }: { open: boolean; reducedMotion: boolean }) {
  const panelOpen = useUi((s) => s.customerPanelOpen);
  const close = useUi((s) => s.closeWorkspace);
  const agentState = useAgent((s) => s.state);
  const ref = useRef<HTMLElement>(null);
  const morph = reducedMotion ? reducedTransition : transitions.morph;

  useLayoutEffect(() => {
    if (ref.current) ref.current.inert = !open;
  }, [open]);

  const col = (delay: number, x: number) => ({
    initial: false as const,
    animate: open ? { opacity: 1, x: 0 } : { opacity: CLOSED_OPACITY, x: reducedMotion ? 0 : x },
    transition: open
      ? reducedMotion
        ? reducedTransition
        : { ...transitions.slow, delay }
      : { duration: 0.12 },
  });

  return (
    <>
      <AnimatePresence>
        {open && (
          <motion.div
            key="shell"
            layoutId="core-surface"
            className="ws-shell"
            style={{ borderRadius: 28 }}
            transition={morph}
            aria-hidden="true"
          >
            <div className="ws-veil" />
          </motion.div>
        )}
      </AnimatePresence>

      <motion.section
        ref={ref}
        className={cx("workspace", !open && "is-closed")}
        aria-label="مساحة المحادثات"
        aria-hidden={!open}
        initial={false}
        // 0.001, not 0: Chrome skips rasterizing fully transparent subtrees, which would move a ~100ms GPU
        // raster of all the text into the first frames of the morph. Visually identical to 0.
        animate={{ opacity: open ? 1 : CLOSED_OPACITY }}
        transition={
          open
            ? { duration: reducedMotion ? 0.1 : 0.32, ease: "easeOut", delay: reducedMotion ? 0 : 0.18 }
            : { duration: 0.14 }
        }
      >
        <div className={cx("ws-grid", !panelOpen && "is-panel-closed")}>
          <motion.div className="ws-col ws-list" {...col(0.22, 24)}>
            <ConversationList />
            {!panelOpen && <CoreDock onClose={close} working={WORKING.has(agentState)} />}
          </motion.div>
          <motion.div className="ws-col ws-chat" {...col(0.18, 0)}>
            <ChatPanel />
          </motion.div>
          <AnimatePresence initial={false}>
            {panelOpen && (
              <motion.div
                key="cp"
                className="ws-col ws-profile"
                initial={{ opacity: 0, x: reducedMotion ? 0 : -24 }}
                animate={
                  open ? { opacity: 1, x: 0 } : { opacity: CLOSED_OPACITY, x: reducedMotion ? 0 : -24 }
                }
                exit={{ opacity: 0, transition: { duration: 0.12 } }}
                transition={
                  open
                    ? {
                        ...(reducedMotion ? reducedTransition : transitions.slow),
                        delay: reducedMotion ? 0 : 0.26,
                      }
                    : { duration: 0.12 }
                }
              >
                <CustomerPanel />
                <CoreDock onClose={close} working={WORKING.has(agentState)} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.section>
    </>
  );
}

function CoreDock({ onClose, working }: { onClose: () => void; working: boolean }) {
  return (
    <button type="button" className="core-dock" onClick={onClose} aria-label="العودة إلى FINORA CORE">
      <MiniOrb size={36} active={working} />
      <span className="core-dock-text">
        <strong>Finora Core</strong>
        <span>
          <i className="live-dot" /> مفعل الآن
        </span>
      </span>
      <span className="core-dock-hint">العودة للنواة</span>
    </button>
  );
}
