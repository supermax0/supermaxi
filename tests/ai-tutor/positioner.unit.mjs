import test from "node:test";
import assert from "node:assert/strict";
import { computePlacement, intersectionArea, layoutMode, sheetEdge, toRect } from "../../static/ai-tutor/ui/positioner.js";
import { motionFor, tutorMotion } from "../../static/ai-tutor/motion/tokens.js";

const desktop = { width: 1440, height: 900 };
const card = { width: 360, height: 200 };
const safe = { top: 64, bottom: 0, left: 0, right: 0 };
const place = (target, extra = {}) => computePlacement({ target: toRect(...target), card, viewport: desktop, safe, ...extra });
const cardRect = (p) => toRect(p.x, p.y, card.width, card.height);
const insideViewport = (r) => r.left >= 0 && r.top >= 64 && r.right <= desktop.width && r.bottom <= desktop.height;

test("prefers left of a centred target and never covers it", () => {
  const t = [600, 400, 200, 40];
  const p = place(t);
  assert.equal(p.side, "left");
  assert.equal(p.connector, null);
  assert.equal(intersectionArea(cardRect(p), toRect(...t)), 0);
  assert.ok(insideViewport(cardRect(p)));
});

test("uses the right side when the left has no room", () => {
  const p = place([20, 400, 150, 40]);
  assert.equal(p.side, "right");
});

test("uses top for a wide bar at the bottom and bottom for a wide bar at the top", () => {
  assert.equal(place([100, 830, 1240, 50]).side, "top");
  assert.equal(place([100, 80, 1240, 50]).side, "bottom");
});

test("all four sides are reachable", () => {
  const sides = new Set([
    place([600, 400, 200, 40]).side, place([20, 400, 150, 40]).side,
    place([100, 830, 1240, 50]).side, place([100, 80, 1240, 50]).side,
  ]);
  assert.deepEqual([...sides].sort(), ["bottom", "left", "right", "top"]);
});

test("falls back to a safe spot with a connector when the target fills the screen", () => {
  const p = place([0, 0, 1440, 900]);
  assert.equal(p.side, "safe");
  assert.ok(p.connector);
});

test("keeps the card off a modal that contains the target and connects to it", () => {
  const container = toRect(600, 200, 500, 600);
  const t = [700, 500, 200, 40];
  const p = place(t, { container });
  assert.equal(intersectionArea(cardRect(p), container), 0);
  assert.ok(p.connector, "card sits beside the modal, so it needs a connector");
  assert.equal(intersectionArea(cardRect(p), toRect(...t)), 0);
});

test("avoids covering other important fields when an equal side is free", () => {
  const field = toRect(250, 380, 340, 80); // exactly where 'left' would land
  const p = place([600, 400, 200, 40], { avoid: [{ rect: field, weight: 1 }] });
  assert.notEqual(p.side, "left");
  assert.equal(intersectionArea(cardRect(p), field), 0);
});

test("sticky side prevents flapping between near-equal placements", () => {
  const p = place([600, 400, 200, 40], { stickySide: "right" });
  assert.equal(p.side, "right");
});

test("phones use a bottom sheet; layout modes", () => {
  const p = computePlacement({ target: toRect(10, 10, 50, 50), card, viewport: { width: 390, height: 800 }, safe });
  assert.equal(p.mode, "sheet");
  assert.equal(layoutMode({ width: 390 }), "phone");
  assert.equal(layoutMode({ width: 800 }), "tablet");
  assert.equal(layoutMode({ width: 1440 }), "desktop");
});

test("placement is always inside the safe viewport for random targets", () => {
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 300; i += 1) {
    const w = 40 + rnd() * 500;
    const h = 24 + rnd() * 200;
    const t = [rnd() * (desktop.width - w), 64 + rnd() * (desktop.height - 64 - h), w, h];
    const p = place(t);
    if (p.mode !== "floating") continue;
    const r = cardRect(p);
    assert.ok(insideViewport(r), JSON.stringify({ t, p }));
    if (p.side !== "safe") assert.equal(intersectionArea(r, toRect(...t)), 0, JSON.stringify({ t, p }));
  }
});

test("motion tokens: reduced motion zeroes movement and shortens fades", () => {
  const normal = motionFor({ matchMedia: () => ({ matches: false }) });
  const reduced = motionFor({ matchMedia: () => ({ matches: true }) });
  assert.equal(normal.ms("move"), 480);
  assert.equal(reduced.ms("move"), 0);
  assert.ok(reduced.ms("contentIn") <= tutorMotion.reducedFade);
  assert.throws(() => normal.ms("nope"), RangeError);
});

test("phone: the sheet docks to the bottom, unless the target sits under it and cannot scroll away (a fixed Save button)", () => {
  const phone = { width: 390, height: 800 };
  const sheetCard = { width: 390, height: 260 };
  const edge = (rect) => sheetEdge({ target: toRect(...rect), card: sheetCard, viewport: phone, safe: { top: 0 } });
  assert.equal(edge([20, 300, 350, 48]), "bottom"); // a field in the middle: the sheet stays at the bottom
  assert.equal(edge([20, 726, 120, 47]), "top"); // the modal's fixed footer button is under the bottom sheet
  const p = computePlacement({ target: toRect(20, 726, 120, 47), card: sheetCard, viewport: phone, safe: { top: 0 } });
  assert.equal(p.mode, "sheet");
  assert.equal(p.edge, "top");
  const q = computePlacement({ target: toRect(20, 300, 350, 48), card: sheetCard, viewport: phone, safe: { top: 0 } });
  assert.equal(q.edge, "bottom");
  assert.equal(edge([20, 478, 350, 90]), "bottom"); // a text area half under the sheet is still usable: no flip to the top
  // a target that is tall enough to touch both edges keeps the default
  assert.equal(edge([0, 20, 390, 760]), "bottom");
});
