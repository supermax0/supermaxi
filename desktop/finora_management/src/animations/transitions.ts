import type { WindowId } from "@/windows/registry";
import { anchorRect, windowRect } from "./anchors";
import { collapsedFrame } from "./morph";

export const STAGE_INSET = 22;
export const STAGE_INSET_EXPANDED = 8;

/** Live geometry, read when a transition starts (window resizes and the expand toggle stay correct). */
export interface MorphContext {
  id: WindowId;
  stage: HTMLElement | null;
  inset: () => number;
}

export const IDENTITY = "translate(0px, 0px) scale(1, 1)";

/** Transform that shrinks the window shell onto its navigation button. */
export function collapsedTransform(ctx: MorphContext): string {
  if (!ctx.stage) return "translate(0px, -40px) scale(0.1, 0.1)";
  const target = windowRect(ctx.stage, ctx.inset());
  const frame = collapsedFrame(anchorRect(ctx.id, ctx.stage, target), target);
  return `translate(${frame.x}px, ${frame.y}px) scale(${frame.scaleX}, ${frame.scaleY})`;
}
