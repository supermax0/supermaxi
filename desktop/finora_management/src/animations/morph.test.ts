import { collapsedFrame, expandedFrame, fallbackOrigin, BUTTON_RADIUS } from "./morph";

describe("collapsedFrame", () => {
  const target = { left: 20, top: 20, width: 1000, height: 600 };

  it("maps the shell onto the button: centers align and scale matches the button size", () => {
    const origin = { left: 700, top: -60, width: 100, height: 60 };
    const frame = collapsedFrame(origin, target);
    expect(frame.scaleX).toBeCloseTo(0.1);
    expect(frame.scaleY).toBeCloseTo(0.1);
    // button center (750, -30) minus window center (520, 320)
    expect(frame.x).toBeCloseTo(230);
    expect(frame.y).toBeCloseTo(-350);
  });

  it("pre-divides the radius by the scale so the shrunk shell keeps the button's corners", () => {
    const frame = collapsedFrame({ left: 0, top: 0, width: 100, height: 60 }, target);
    expect(frame.borderRadius).toBe(`${BUTTON_RADIUS / 0.1}px / ${BUTTON_RADIUS / 0.1}px`);
  });

  it("never produces a zero/negative scale for degenerate rects", () => {
    const frame = collapsedFrame(
      { left: 0, top: 0, width: 0, height: 0 },
      { left: 0, top: 0, width: 0, height: 0 },
    );
    expect(frame.scaleX).toBeGreaterThan(0);
    expect(frame.scaleY).toBeGreaterThan(0);
    expect(Number.isFinite(frame.x) && Number.isFinite(frame.y)).toBe(true);
  });

  it("expanded frame is the identity transform", () => {
    expect(expandedFrame).toMatchObject({ x: 0, y: 0, scaleX: 1, scaleY: 1 });
  });

  it("fallback origin sits centered above the window", () => {
    const origin = fallbackOrigin(target);
    expect(origin.left + origin.width / 2).toBe(target.left + target.width / 2);
    expect(origin.top + origin.height).toBe(target.top);
  });
});
