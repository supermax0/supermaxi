/* First-login welcome card. Shown once, only on the dashboard, never over a running tutorial. */
import { animate } from "../motion/tokens.js";

const LATER_KEY = "finora.tutor.onboarding.later";

export async function maybeShowOnboarding({ api, engine, overlay, motion, doc = document, win = window }) {
  if (doc.querySelector("[data-finora-page]")?.dataset.finoraPage !== "dashboard") return;
  if (engine.state !== "IDLE") return;
  try {
    if (win.sessionStorage.getItem(LATER_KEY)) return;
  } catch (error) {
    console.warn("[tutor] sessionStorage unavailable", error);
  }
  let data;
  try {
    data = await api.request("/onboarding");
  } catch (error) {
    if (error.name !== "FeatureDisabledError") console.warn("[tutor] onboarding unavailable", error);
    return;
  }
  if (!data.show || engine.state !== "IDLE") return;

  const node = (tag, className, text) => {
    const n = doc.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const backdrop = node("div", "ft-welcome-backdrop");
  backdrop.dataset.tutorUi = "welcome-backdrop";
  const card = node("section", "ft-welcome");
  card.dataset.tutorUi = "welcome";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-label", "أهلاً بك في Finora Clinics");
  card.append(node("div", "ft-welcome__spark", "✦"), node("h2", "", "أهلاً بك في Finora Clinics"),
    node("p", "", "أقدر أعلمك النظام خطوة بخطوة أثناء استخدامه الحقيقي."), node("p", "ft-welcome__label", "البداية المقترحة:"));
  const list = node("ol", "ft-welcome__list");
  data.suggestions.forEach((s, i) => list.append(node("li", "", `${String(i + 1).padStart(2, "0")}  ${s.title_ar}`)));
  card.append(list);

  const forever = node("input");
  forever.type = "checkbox";
  forever.id = "ftWelcomeForever";
  const label = node("label", "ft-welcome__forever", "لا تظهر هذه الرسالة مرة أخرى");
  label.prepend(forever);
  const start = node("button", "ft-btn ft-btn--primary ft-welcome__start", "ابدأ الإعداد");
  start.type = "button";
  start.dataset.tutorAction = "welcome-start";
  const later = node("button", "ft-welcome__later", "لاحقاً");
  later.type = "button";
  later.dataset.tutorAction = "welcome-later";
  card.append(start, later, label);
  overlay.mount(backdrop);
  overlay.mount(card);

  await Promise.all([
    animate(backdrop, [{ opacity: 0 }, { opacity: 1 }], motion.ms("normal")),
    animate(card, [{ opacity: 0, transform: "translate(-50%, -50%) scale(.96)" }, { opacity: 1, transform: "translate(-50%, -50%) scale(1)" }], motion.ms("intro")),
  ]);

  const dismiss = async (keepForever) => {
    await Promise.all([
      animate(card, [{ opacity: 1 }, { opacity: 0 }], motion.ms("exit")),
      animate(backdrop, [{ opacity: 1 }, { opacity: 0 }], motion.ms("exit")),
    ]);
    card.remove();
    backdrop.remove();
    if (keepForever) {
      await api.request("/onboarding/dismiss", { method: "POST", body: { forever: true } });
    } else {
      try {
        win.sessionStorage.setItem(LATER_KEY, "1");
      } catch (error) {
        console.warn("[tutor] could not remember 'later'", error);
      }
    }
  };
  later.addEventListener("click", () => dismiss(forever.checked));
  start.addEventListener("click", async () => {
    await dismiss(true); // the user acted on it: do not show again
    await engine.startTutorial(data.suggestions[0].id);
  });
}
