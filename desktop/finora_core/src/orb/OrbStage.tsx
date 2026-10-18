import { AnimatePresence, motion } from "framer-motion";
import { BarChart3, Settings } from "lucide-react";
import { Component, lazy, Suspense, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApprovalBar } from "../approvals/ApprovalCard";
import { reducedTransition, transitions } from "../design/motion";
import { useCan } from "../data/can";
import { useActivity, useApprovals, useOnline, useStatus } from "../data/hooks";
import type { Connection } from "../data/schemas";
import { useAgent } from "../state/agent";
import { useUi } from "../state/ui";
import { FacebookIcon, InstagramIcon, TelegramIcon, cx } from "../ui/primitives";
import { orbLayout, type OrbLayout } from "./layout";
import { statusLabel } from "./orbMachine";
import { StatusBubble } from "./StatusBubble";

const OrbCanvas = lazy(() => import("./OrbCanvas"));

export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch (err) {
    console.warn("[finora-core] WebGL probe failed", err);
    return false;
  }
}

/** If the GPU context is lost or the shader fails, fall back to the static orb instead of a blank stage. */
class OrbBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  override componentDidCatch(err: unknown) {
    console.error("[finora-core] orb renderer failed, using static fallback", err);
  }
  override render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function useStageLayout(ref: React.RefObject<HTMLElement | null>): OrbLayout | null {
  const [layout, setLayout] = useState<OrbLayout | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) setLayout(orbLayout(r.width, r.height));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return layout;
}

/** The orb never pretends to monitor a channel it cannot reach (spec §86). */
const CHANNEL_PROBLEM: Record<Connection, string> = {
  connected: "متصل",
  token_expired: "انتهت صلاحية الرمز",
  permission_missing: "صلاحية ناقصة",
  webhook_invalid: "Webhook غير صالح",
  disconnected: "غير متصل",
  unknown: "غير متصل",
};

function ChannelChip({
  side,
  connection,
  children,
  label,
}: {
  side: "left" | "right" | "telegram";
  connection: Connection;
  children: ReactNode;
  label: string;
}) {
  const off = connection !== "connected";
  const text = `${label} ${CHANNEL_PROBLEM[connection]}`;
  return (
    <div className={cx("channel-chip", `is-${side}`, off && "is-off")} title={text}>
      <span className="cc-bubble">{children}</span>
      {off && <span className="cc-warn">{text}</span>}
    </div>
  );
}

export function OrbStage({ reducedMotion, webgl }: { reducedMotion: boolean; webgl: boolean }) {
  const stageRef = useRef<HTMLElement>(null);
  const layout = useStageLayout(stageRef);
  const view = useUi((s) => s.view);
  const openWorkspace = useUi((s) => s.openWorkspace);
  const setOverlay = useUi((s) => s.setOverlay);
  const quality = useUi((s) => s.appearance.quality);
  const agent = useAgent();
  const status = useStatus();
  const approvals = useApprovals();
  const activity = useActivity("errors", useCan("audit.view"));
  const online = useOnline();
  const [docVisible, setDocVisible] = useState(() => document.visibilityState === "visible");

  useLayoutEffect(() => {
    const on = () => setDocVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);

  const visible = view === "orb";
  useLayoutEffect(() => {
    if (stageRef.current) stageRef.current.inert = !visible;
  }, [visible]);
  const effectiveState = !online || status.isError ? "offline" : agent.state;
  const text = useMemo(
    () =>
      statusLabel(effectiveState, {
        channel: agent.channel,
        serverLabel: agent.label,
        hasConversations: (status.data?.conversationCount ?? 0) > 0,
      }),
    [effectiveState, agent.channel, agent.label, status.data?.conversationCount],
  );
  const pending = approvals.data ?? [];
  const channels = status.data?.channels ?? {
    instagram: "unknown" as const,
    facebook: "unknown" as const,
    telegram: "unknown" as const,
  };
  const hasErrors = (activity.data?.length ?? 0) > 0;
  const t = reducedMotion ? reducedTransition : transitions.slow;

  const style = layout
    ? ({ "--orb-d": `${layout.diameter}px`, "--orb-oy": `${layout.offsetY}px` } as React.CSSProperties)
    : undefined;

  const fallback = <div className={cx("orb-fallback", `is-${effectiveState}`)} aria-hidden="true" />;

  return (
    <section
      ref={stageRef}
      className={cx("stage", !visible && "is-hidden")}
      style={style}
      aria-hidden={!visible}
    >
      <motion.div
        className="stage-canvas"
        initial={false}
        animate={visible ? { opacity: 1, scale: 1 } : { opacity: 0, scale: reducedMotion ? 1 : 1.18 }}
        transition={visible ? { ...t, delay: reducedMotion ? 0 : 0.12 } : { ...t, duration: 0.42 }}
      >
        {layout &&
          (webgl ? (
            <OrbBoundary fallback={fallback}>
              <Suspense fallback={fallback}>
                <OrbCanvas
                  state={effectiveState}
                  layout={layout}
                  quality={quality}
                  running={visible && docVisible}
                  reducedMotion={reducedMotion}
                />
              </Suspense>
            </OrbBoundary>
          ) : (
            fallback
          ))}
        <div className="stage-floor" aria-hidden="true" />
      </motion.div>

      {layout && (
        <>
          <motion.div
            className="sb-anchor"
            initial={false}
            animate={visible ? { opacity: 1, y: 0 } : { opacity: 0, y: reducedMotion ? 0 : -12 }}
            transition={t}
          >
            <StatusBubble state={effectiveState} text={text} reducedMotion={reducedMotion} />
          </motion.div>

          <AnimatePresence>
            {visible && (
              <motion.button
                key="orb-hit"
                type="button"
                layoutId="core-surface"
                className="orb-hit"
                style={{ borderRadius: 9999 }}
                transition={reducedMotion ? reducedTransition : transitions.morph}
                onClick={() => openWorkspace()}
                aria-label="فتح مساحة المحادثات — FINORA CORE"
              >
                <motion.span
                  className="orb-wordmark"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1, transition: { ...t, delay: 0.2 } }}
                  exit={{ opacity: 0, transition: { duration: 0.12 } }}
                >
                  <span className="ow-name">FINORA</span>
                  <span className="ow-core">CORE</span>
                </motion.span>
              </motion.button>
            )}
          </AnimatePresence>

          <motion.div
            className="stage-chrome"
            initial={false}
            animate={visible ? { opacity: 1 } : { opacity: 0 }}
            transition={visible ? { ...t, delay: reducedMotion ? 0 : 0.25 } : { duration: 0.18 }}
          >
            <ChannelChip side="left" connection={channels.instagram} label="Instagram">
              <InstagramIcon size={34} />
            </ChannelChip>
            <ChannelChip side="right" connection={channels.facebook} label="Facebook">
              <FacebookIcon size={34} />
            </ChannelChip>
            <ChannelChip side="telegram" connection={channels.telegram} label="Telegram">
              <TelegramIcon size={34} />
            </ChannelChip>

            {pending[0] && (
              <div className="stage-approval">
                <ApprovalBar approval={pending[0]} onDetails={() => setOverlay("activity")} />
              </div>
            )}

            <button type="button" className="stage-btn is-left" onClick={() => setOverlay("activity")}>
              <BarChart3 size={20} />
              <span>Activity</span>
              {(hasErrors || pending.length > 0) && (
                <span className="stage-dot" aria-label="يوجد عناصر تحتاج انتباهك" />
              )}
            </button>
            <button type="button" className="stage-btn is-right" onClick={() => setOverlay("settings")}>
              <Settings size={20} />
              <span>Settings</span>
            </button>
          </motion.div>
        </>
      )}
    </section>
  );
}
