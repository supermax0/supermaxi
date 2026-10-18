/**
 * DOM anchors for the window morph: each navigation button registers itself so
 * a window can grow out of (and shrink back into) the button that owns it.
 * All rects are expressed in the stage's coordinate space.
 */
import type { WindowId } from "@/windows/registry";
import { fallbackOrigin, toRect, type Rect } from "./morph";

const buttons = new Map<WindowId, HTMLElement>();

export function registerNavAnchor(id: WindowId, element: HTMLElement | null): void {
  if (element) buttons.set(id, element);
  else buttons.delete(id);
}

/** Where a window sits inside the stage for a given inset. */
export function windowRect(stage: HTMLElement, inset: number): Rect {
  return {
    left: inset,
    top: inset,
    width: Math.max(stage.clientWidth - inset * 2, 1),
    height: Math.max(stage.clientHeight - inset * 2, 1),
  };
}

/** The owning button's rect relative to the stage (falls back to the stage top center). */
export function anchorRect(id: WindowId, stage: HTMLElement, target: Rect): Rect {
  const button = buttons.get(id);
  if (!button || !button.isConnected) return fallbackOrigin(target);
  const box = toRect(button.getBoundingClientRect());
  if (box.width === 0 || box.height === 0) return fallbackOrigin(target);
  const origin = stage.getBoundingClientRect();
  return { ...box, left: box.left - origin.left, top: box.top - origin.top };
}
