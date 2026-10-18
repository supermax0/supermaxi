/*
 * Smart card placement (pure geometry, unit-tested in node).
 *
 * Candidates are generated around the target (and around its modal container,
 * when it lives inside one), scored, and the cheapest valid one wins. A card
 * may never cover the target. When nothing fits the card docks to a safe spot
 * away from the target and a connector line points at it.
 */

export const SIDES = Object.freeze(["left", "right", "bottom", "top"]);
const PHONE_MAX = 640;
const TABLET_MAX = 1024;

const area = (r) => Math.max(0, r.width) * Math.max(0, r.height);

export function toRect(x, y, width, height) {
  return { x, y, left: x, top: y, width, height, right: x + width, bottom: y + height };
}

export function intersectionArea(a, b) {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return w > 0 && h > 0 ? w * h : 0;
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));

/** Closest point of `rect` to the point (px, py). */
function nearestPoint(rect, px, py) {
  return { x: clamp(px, rect.left, rect.right), y: clamp(py, rect.top, rect.bottom) };
}

function connectorBetween(card, target) {
  const cx = card.left + card.width / 2;
  const cy = card.top + card.height / 2;
  const to = nearestPoint(target, cx, cy);
  const from = nearestPoint(card, to.x, to.y);
  return { x1: Math.round(from.x), y1: Math.round(from.y), x2: Math.round(to.x), y2: Math.round(to.y) };
}

export function layoutMode(viewport) {
  if (viewport.width <= PHONE_MAX) return "phone";
  if (viewport.width <= TABLET_MAX) return "tablet";
  return "desktop";
}

function around(anchor, side, card, target, gap) {
  const tcx = target.left + target.width / 2;
  const tcy = target.top + target.height / 2;
  switch (side) {
    case "left": return { x: anchor.left - gap - card.width, y: tcy - card.height / 2 };
    case "right": return { x: anchor.right + gap, y: tcy - card.height / 2 };
    case "bottom": return { x: tcx - card.width / 2, y: anchor.bottom + gap };
    default: return { x: tcx - card.width / 2, y: anchor.top - gap - card.height };
  }
}

/**
 * Which edge a phone sheet docks to. Bottom is the default, but a control that lives under the bottom edge and cannot be
 * scrolled away (a modal's fixed footer: "Save") would be hidden by the sheet, so the sheet goes to the top instead.
 */
export function sheetEdge({ target, card, viewport, safe = {} }) {
  const height = Math.min(card.height, viewport.height * 0.42);
  const bottom = toRect(0, viewport.height - height, viewport.width, height);
  // Enough of the target stays visible above a bottom sheet (a tall text area peeking out is fine): keep the default.
  const visibleAbove = Math.max(0, Math.min(target.bottom, bottom.top) - Math.max(target.top, safe.top || 0));
  if (visibleAbove >= Math.min(target.height, 40)) return "bottom";
  const top = toRect(0, safe.top || 0, viewport.width, height);
  return intersectionArea(top, target) === 0 ? "top" : "bottom";
}

/**
 * @param {object} input
 * @param {DOMRect|object} input.target       target rect (viewport coordinates)
 * @param {{width:number,height:number}} input.card
 * @param {{width:number,height:number}} input.viewport
 * @param {{top:number,right:number,bottom:number,left:number}} [input.safe]  chrome insets (navbar, bottom bar)
 * @param {Array<{rect:object,weight:number}>} [input.avoid]  other important UI the card should not cover
 * @param {object|null} [input.container]     rect of the modal/panel containing the target
 * @param {string|null} [input.stickySide]    previous side; kept unless clearly worse (prevents flapping)
 */
export function computePlacement({
  target, card, viewport, safe = {}, avoid = [], container = null, stickySide = null,
  gap = 16, margin = 16, preferred = SIDES,
}) {
  const mode = layoutMode(viewport);
  if (mode === "phone") return { mode: "sheet", side: "sheet", edge: sheetEdge({ target, card, viewport, safe }), x: 0, y: 0, connector: null, score: 0 };

  const bounds = {
    left: margin + (safe.left || 0),
    top: margin + (safe.top || 0),
    right: viewport.width - margin - (safe.right || 0),
    bottom: viewport.height - margin - (safe.bottom || 0),
  };
  bounds.width = bounds.right - bounds.left;
  bounds.height = bounds.bottom - bounds.top;

  const order = stickySide && preferred.includes(stickySide) ? [stickySide, ...preferred.filter((s) => s !== stickySide)] : [...preferred];
  const anchors = [{ rect: target, kind: "target" }];
  if (container && area(container) > area(target) * 1.2) anchors.push({ rect: container, kind: "container" });

  const evaluate = (x0, y0, side, orderIndex, kind) => {
    const x = clamp(x0, bounds.left, bounds.right - card.width);
    const y = clamp(y0, bounds.top, bounds.bottom - card.height);
    const rect = toRect(x, y, card.width, card.height);
    if (intersectionArea(rect, target) > 0) return null; // never cover the target
    const shift = Math.abs(x - x0) + Math.abs(y - y0);
    let score = orderIndex * 12 + shift * 0.6 + (kind === "container" ? 28 : 0);
    if (stickySide && side === stickySide) score -= 20;
    const cardArea = area(rect);
    if (container && kind === "target") score += (intersectionArea(rect, container) / cardArea) * 400; // would cover the form
    for (const item of avoid) score += (intersectionArea(rect, item.rect) / cardArea) * 100 * (item.weight ?? 1);
    return { x, y, rect, side, kind, score };
  };

  let best = null;
  for (const anchor of anchors) {
    order.forEach((side, index) => {
      const { x, y } = around(anchor.rect, side, card, target, gap);
      const found = evaluate(x, y, side, index, anchor.kind);
      if (found && (!best || found.score < best.score)) best = found;
    });
  }

  if (!best) best = safeSpot({ target, card, bounds, avoid, container });

  const direct = best.kind === "target" && best.side !== "safe";
  const connector = direct ? null : connectorBetween(best.rect, target);
  const result = {
    mode: "floating", side: best.side, x: Math.round(best.x), y: Math.round(best.y),
    connector, score: Math.round(best.score), layout: mode,
  };

  // Tablet: a docked card whose connector is long is worse than a bottom sheet.
  if (mode === "tablet" && result.score > 140) {
    return { mode: "sheet", side: "sheet", edge: sheetEdge({ target, card, viewport, safe }), x: 0, y: 0, connector: null, score: result.score };
  }
  return result;
}

/** No clean side: pick the viewport corner/edge spot farthest from the target that avoids it. */
function safeSpot({ target, card, bounds, avoid, container }) {
  const xs = [bounds.left, (bounds.left + bounds.right - card.width) / 2, bounds.right - card.width];
  const ys = [bounds.top, (bounds.top + bounds.bottom - card.height) / 2, bounds.bottom - card.height];
  let best = null;
  const tcx = target.left + target.width / 2;
  const tcy = target.top + target.height / 2;
  for (const x of xs) {
    for (const y of ys) {
      const rect = toRect(x, y, card.width, card.height);
      if (intersectionArea(rect, target) > 0) continue;
      let score = 200 - Math.hypot(rect.left + card.width / 2 - tcx, rect.top + card.height / 2 - tcy) * 0.05;
      const cardArea = area(rect);
      if (container) score += (intersectionArea(rect, container) / cardArea) * 60;
      for (const item of avoid) score += (intersectionArea(rect, item.rect) / cardArea) * 100 * (item.weight ?? 1);
      if (!best || score < best.score) best = { x, y, rect, side: "safe", kind: "safe", score };
    }
  }
  // Degenerate (target covers everything): dock bottom-left; the connector still shows what to use.
  return best || { x: bounds.left, y: bounds.bottom - card.height, rect: toRect(bounds.left, bounds.bottom - card.height, card.width, card.height), side: "safe", kind: "safe", score: 999 };
}
