/*
 * Unified launcher. The existing Finora AI button (#finoraAiFab) stays the ONLY floating
 * button: while the tutor is enabled its click opens a small menu (Assistant / Learn the system).
 * "Assistant" replays the original click untouched, so the assistant keeps working exactly as before.
 * If that button does not exist on a page, a single fallback orb in the same spot is created.
 */
import { animate } from "../motion/tokens.js";

const FAB_ID = "finoraAiFab";
const PANEL_ID = "finoraAiPanel";

export class TutorLauncher {
  constructor({ overlay, home, engine, api, motion, doc = document, win = window }) {
    this.overlay = overlay;
    this.home = home;
    this.engine = engine;
    this.api = api;
    this.motion = motion;
    this.doc = doc;
    this.win = win;
    this.bypass = false;
    this.menuOpen = false;
    this.menuToken = 0; // a late close-animation must never hide a menu that was re-opened
    this.fab = doc.getElementById(FAB_ID);
    this.ownsButton = !this.fab;
    if (this.ownsButton) this.fab = this.createFallbackOrb();
    this.menu = this.buildMenu();
    this.badge = this.buildBadge();

    this.onFabClick = (event) => this.handleFabClick(event);
    this.fab.addEventListener("click", this.onFabClick, true);
    this.onOutside = (event) => {
      if (this.menuOpen && !this.menu.contains(event.target) && !this.fab.contains(event.target)) this.closeMenu();
    };
    this.onKey = (event) => {
      if (event.key === "Escape" && this.menuOpen) this.closeMenu();
    };
    doc.addEventListener("pointerdown", this.onOutside, true);
    doc.addEventListener("keydown", this.onKey, true);
    this.onLayout = () => {
      this.placeBadge();
      if (this.menuOpen) this.placeMenu();
    };
    win.addEventListener("finora:assistantlayout", this.onLayout);
    win.addEventListener("resize", this.onLayout);
    this.refreshBadge();
    engine.machine.subscribe(() => this.refreshBadge());
  }

  createFallbackOrb() {
    const button = this.doc.createElement("button");
    button.type = "button";
    button.className = "ft-orb-launcher";
    button.dataset.tutorUi = "launcher";
    button.setAttribute("aria-label", "Finora Tutor");
    button.setAttribute("aria-haspopup", "menu");
    button.textContent = "✦";
    this.overlay.mount(button);
    return button;
  }

  buildMenu() {
    const menu = this.doc.createElement("div");
    menu.className = "ft-menu";
    menu.dataset.tutorUi = "launcher-menu";
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    const item = (key, label, hint) => {
      const b = this.doc.createElement("button");
      b.type = "button";
      b.className = "ft-menu__item";
      b.setAttribute("role", "menuitem");
      b.dataset.tutorMenu = key;
      const strong = this.doc.createElement("strong");
      strong.textContent = label;
      const small = this.doc.createElement("small");
      small.textContent = hint;
      b.append(strong, small);
      return b;
    };
    if (!this.ownsButton) {
      const assistant = item("assistant", "المساعد", "اسأل Finora AI عن بياناتك");
      assistant.addEventListener("click", () => this.openAssistant());
      menu.append(assistant);
    }
    const learn = item("learn", "تعلّم النظام", "دروس تفاعلية خطوة بخطوة");
    learn.addEventListener("click", () => {
      this.closeMenu();
      this.home.open();
    });
    menu.append(learn);
    this.overlay.mount(menu);
    return menu;
  }

  buildBadge() {
    const badge = this.doc.createElement("span");
    badge.className = "ft-badge";
    badge.dataset.tutorUi = "badge";
    badge.hidden = true;
    badge.setAttribute("aria-label", "لديك درس متوقف");
    this.overlay.mount(badge);
    return badge;
  }

  async refreshBadge() {
    let paused = false;
    try {
      paused = (await this.api.list()).tutorials.some((t) => t.progress?.status === "paused");
    } catch (error) {
      if (error.name !== "FeatureDisabledError") console.warn("[tutor] badge refresh failed", error);
      return;
    }
    this.placeBadge();
    this.badge.hidden = !paused;
  }

  placeBadge() {
    const rect = this.fab.getBoundingClientRect();
    Object.assign(this.badge.style, { left: `${Math.round(rect.right - 12)}px`, top: `${Math.round(rect.top - 4)}px` });
  }

  handleFabClick(event) {
    if (this.bypass) {
      this.bypass = false;
      return;
    }
    // Closing an open assistant panel must keep working exactly as before.
    if (this.doc.getElementById(PANEL_ID)?.classList.contains("is-open")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    this.toggleMenu();
  }

  openAssistant() {
    this.closeMenu();
    this.bypass = true;
    this.fab.click();
  }

  placeMenu() {
    const rect = this.fab.getBoundingClientRect();
    Object.assign(this.menu.style, {
      left: `${Math.max(12, Math.round(rect.left))}px`,
      bottom: `${Math.round(this.win.innerHeight - rect.top + 10)}px`,
    });
  }

  async toggleMenu() {
    if (this.menuOpen) return this.closeMenu();
    this.home.close();
    this.menuOpen = true;
    this.menuToken += 1;
    this.fab.setAttribute("aria-expanded", "true");
    this.placeMenu();
    this.menu.hidden = false;
    await animate(this.menu, [{ opacity: 0, transform: "translateY(8px) scale(.97)" }, { opacity: 1, transform: "translateY(0) scale(1)" }], this.motion.ms("fast"));
    return undefined;
  }

  async closeMenu() {
    if (!this.menuOpen) return;
    this.menuOpen = false;
    const token = ++this.menuToken;
    this.fab.setAttribute("aria-expanded", "false");
    await animate(this.menu, [{ opacity: 1 }, { opacity: 0 }], this.motion.ms("fast"));
    if (token === this.menuToken) this.menu.hidden = true;
  }

  destroy() {
    this.fab.removeEventListener("click", this.onFabClick, true);
    this.doc.removeEventListener("pointerdown", this.onOutside, true);
    this.doc.removeEventListener("keydown", this.onKey, true);
    this.win.removeEventListener("finora:assistantlayout", this.onLayout);
    this.win.removeEventListener("resize", this.onLayout);
    this.fab.setAttribute("aria-expanded", "false");
    if (this.ownsButton) this.fab.remove();
    this.menu.remove();
    this.badge.remove();
  }
}
