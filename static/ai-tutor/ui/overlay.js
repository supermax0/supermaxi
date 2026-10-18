/*
 * TutorOverlay: root layer + spotlight (dim + hole + ring + pulse + click indicator) + connector.
 * Everything here is pointer-events:none, so the real page (and modal) stays fully clickable.
 */
import { animate, tutorMotion } from "../motion/tokens.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const SPOT_PAD = 10;

function el(doc, tag, className) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  return node;
}

export class TutorOverlay {
  constructor(doc = document) {
    this.doc = doc;
    this.root = el(doc, "div");
    this.root.id = "finora-tutor-root";
    this.root.dataset.tutorUi = "root";
    this.root.setAttribute("dir", "rtl");
    this.root.setAttribute("lang", "ar");
    doc.body.appendChild(this.root);
  }

  mount(node) {
    this.root.appendChild(node);
  }

  destroy() {
    this.root.remove();
  }
}

export class TutorSpotlight {
  constructor(overlay, motion, win = window) {
    this.win = win;
    this.motion = motion;
    const doc = overlay.doc;
    this.spot = el(doc, "div", "ft-spot");
    this.spot.dataset.tutorUi = "spotlight";
    this.spot.hidden = true;
    this.ring = el(doc, "div", "ft-ring");
    this.pulse = el(doc, "div", "ft-pulse");
    this.click = el(doc, "div", "ft-click");
    this.check = el(doc, "div", "ft-check");
    this.check.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
    this.spot.append(this.pulse, this.ring, this.click, this.check);
    overlay.mount(this.spot);

    this.target = null;
    this.box = null; // last applied {x,y,w,h,r}
    this.animating = false;
    this.frame = 0;
    this.onMove = null;
    this.token = 0; // a late fade-out must never hide a spotlight that was focused again
  }

  static radiusOf(target, win) {
    const parsed = parseFloat(win.getComputedStyle(target).borderTopLeftRadius);
    return (Number.isFinite(parsed) ? parsed : 0) + SPOT_PAD;
  }

  measure() {
    const rect = this.target.getBoundingClientRect();
    return {
      rect,
      box: {
        x: Math.round(rect.left - SPOT_PAD), y: Math.round(rect.top - SPOT_PAD),
        w: Math.round(rect.width + SPOT_PAD * 2), h: Math.round(rect.height + SPOT_PAD * 2),
        r: Math.round(TutorSpotlight.radiusOf(this.target, this.win)),
      },
    };
  }

  apply(box) {
    this.box = box;
    Object.assign(this.spot.style, {
      transform: `translate3d(${box.x}px, ${box.y}px, 0)`,
      width: `${box.w}px`, height: `${box.h}px`, borderRadius: `${box.r}px`,
    });
  }

  /** Morph (same page) or fade in (first target / new page) to `target`. */
  async focus(target, { mode = "info", morph = true } = {}) {
    this.target = target;
    this.token += 1;
    this.setMode(mode);
    const { rect, box } = this.measure();
    const previous = this.box;
    const wasVisible = !this.spot.hidden;
    this.spot.hidden = false;
    this.apply(box);
    this.animating = true;
    const move = this.motion.ms("move");
    try {
      if (wasVisible && previous && morph) {
        await animate(this.spot, [
          { transform: `translate3d(${previous.x}px, ${previous.y}px, 0)`, width: `${previous.w}px`, height: `${previous.h}px`, borderRadius: `${previous.r}px` },
          { transform: `translate3d(${box.x}px, ${box.y}px, 0)`, width: `${box.w}px`, height: `${box.h}px`, borderRadius: `${box.r}px` },
        ], move);
      } else {
        await animate(this.spot, [{ opacity: 0 }, { opacity: 1 }], this.motion.ms("normal"));
      }
    } finally {
      this.animating = false;
    }
    this.startFollow();
    return rect;
  }

  setMode(mode) {
    this.spot.dataset.mode = mode;
    this.spot.classList.remove("is-success");
  }

  startFollow() {
    cancelAnimationFrame(this.frame);
    const tick = () => {
      if (!this.target) return;
      if (!this.target.isConnected) {
        this.frame = requestAnimationFrame(tick);
        return;
      }
      if (!this.animating) {
        const { rect, box } = this.measure();
        const b = this.box;
        if (!b || Math.abs(box.x - b.x) > 0.5 || Math.abs(box.y - b.y) > 0.5 || box.w !== b.w || box.h !== b.h) {
          this.apply(box);
          this.onMove?.(rect);
        }
      }
      this.frame = requestAnimationFrame(tick);
    };
    this.frame = requestAnimationFrame(tick);
  }

  /** Brief success tick on the ring (only used for important operations). */
  async flashSuccess() {
    this.spot.classList.add("is-success");
    await animate(this.check, [{ opacity: 0, transform: "scale(.7) rotate(-8deg)" }, { opacity: 1, transform: "scale(1) rotate(0)" }], this.motion.ms("normal"));
  }

  async fadeOut() {
    cancelAnimationFrame(this.frame);
    this.target = null;
    const token = ++this.token;
    if (this.spot.hidden) return;
    await animate(this.spot, [{ opacity: 1 }, { opacity: 0 }], this.motion.ms("fast"));
    if (token !== this.token) return;
    this.spot.hidden = true;
    this.box = null;
  }

  clear() {
    cancelAnimationFrame(this.frame);
    this.target = null;
    this.box = null;
    this.spot.hidden = true;
  }
}

export class TutorPointer {
  constructor(overlay, motion) {
    this.motion = motion;
    const doc = overlay.doc;
    this.svg = doc.createElementNS(SVG_NS, "svg");
    this.svg.setAttribute("class", "ft-pointer");
    this.svg.dataset.tutorUi = "pointer";
    this.svg.setAttribute("aria-hidden", "true");
    this.line = doc.createElementNS(SVG_NS, "line");
    this.dot = doc.createElementNS(SVG_NS, "circle");
    this.dot.setAttribute("r", "4");
    this.svg.append(this.line, this.dot);
    this.svg.style.display = "none";
    overlay.mount(this.svg);
  }

  show(connector) {
    if (!connector) return this.hide();
    this.line.setAttribute("x1", connector.x1);
    this.line.setAttribute("y1", connector.y1);
    this.line.setAttribute("x2", connector.x2);
    this.line.setAttribute("y2", connector.y2);
    this.dot.setAttribute("cx", connector.x2);
    this.dot.setAttribute("cy", connector.y2);
    const wasHidden = this.svg.style.display === "none";
    this.svg.style.display = "";
    if (wasHidden) animate(this.svg, [{ opacity: 0 }, { opacity: 1 }], this.motion.ms("normal"));
    return undefined;
  }

  hide() {
    this.svg.style.display = "none";
  }
}

export { SPOT_PAD, tutorMotion };
