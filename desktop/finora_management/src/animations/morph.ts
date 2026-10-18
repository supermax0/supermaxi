/**
 * Geometry for the button ⇄ window morph.
 *
 * The window shell is laid out at its final rect and only transformed
 * (translate + scale), which keeps the animation on the compositor. The
 * border radius is pre-divided by the scale so the shrunken shell visually
 * matches the button's rounded corners.
 */
export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface MorphFrame {
  x: number;
  y: number;
  scaleX: number;
  scaleY: number;
  borderRadius: string;
}

export const WINDOW_RADIUS = 26;
export const BUTTON_RADIUS = 16;

const MIN_SCALE = 0.02;

export function toRect(rect: DOMRect | Rect): Rect {
  return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

/** Transform that makes a shell laid out at `target` cover `origin` instead. */
export function collapsedFrame(origin: Rect, target: Rect, originRadius = BUTTON_RADIUS): MorphFrame {
  const width = Math.max(target.width, 1);
  const height = Math.max(target.height, 1);
  const scaleX = Math.max(origin.width / width, MIN_SCALE);
  const scaleY = Math.max(origin.height / height, MIN_SCALE);
  const x = origin.left + origin.width / 2 - (target.left + width / 2);
  const y = origin.top + origin.height / 2 - (target.top + height / 2);
  return {
    x,
    y,
    scaleX,
    scaleY,
    borderRadius: `${round(originRadius / scaleX)}px / ${round(originRadius / scaleY)}px`,
  };
}

export const expandedFrame: MorphFrame = {
  x: 0,
  y: 0,
  scaleX: 1,
  scaleY: 1,
  borderRadius: `${WINDOW_RADIUS}px / ${WINDOW_RADIUS}px`,
};

/** Fallback when the button is not measurable (e.g. first paint): grow from the stage top center. */
export function fallbackOrigin(target: Rect): Rect {
  const width = 120;
  const height = 56;
  return { left: target.left + target.width / 2 - width / 2, top: target.top - height, width, height };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
