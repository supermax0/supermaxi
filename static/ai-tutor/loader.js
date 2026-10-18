/*
 * Entry point. The server emits this <script> only when the tenant has the AI Tutor feature,
 * and it re-checks the backend before building any UI. Every later API call also shuts the
 * tutor down (and gives the assistant button back its original behaviour) if the server
 * reports FEATURE_NOT_ENABLED.
 */
import { TutorApi } from "./engine/api.js";
import { TutorEngine } from "./engine/engine.js";
import { motionFor } from "./motion/tokens.js";
import { TutorHome } from "./ui/home.js";
import { ShowMe } from "./ui/showme.js";
import { TutorLauncher } from "./ui/launcher.js?v=20261003-layout";
import { maybeShowOnboarding } from "./ui/onboarding.js";
import { createPresenter } from "./ui/presenter.js";

const STATUS_POLL_MS = 30000;

async function start() {
  let engine = null;
  let launcher = null;
  let poll = null;
  const onDisabled = () => {
    clearInterval(poll);
    launcher?.destroy();
    engine?.shutdown();
  };
  const api = new TutorApi({ onDisabled });

  let status;
  try {
    status = await api.status();
  } catch (error) {
    return; // feature off, logged out, or server error: render nothing
  }

  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./ui/tutor.css?v=20261003-layout", import.meta.url).href;
  document.head.appendChild(link);

  const motion = motionFor(window);
  const presenter = createPresenter({ win: window });
  engine = new TutorEngine({ api, presenter });
  const showMe = new ShowMe({ presenter, engine, overlay: presenter.overlay, motion });
  const home = new TutorHome({ overlay: presenter.overlay, engine, api, motion, showMe });
  launcher = new TutorLauncher({ overlay: presenter.overlay, home, engine, api, motion });
  window.FinoraTutor = { engine, home, launcher, showMe };

  // Switching the feature off must remove the tutor without a reload.
  poll = setInterval(() => api.status().catch(() => undefined), STATUS_POLL_MS);

  const continuing = presenter.resumeFromNavigation();
  let resumed = false;
  try {
    resumed = await engine.boot();
  } catch (error) {
    if (!engine.disabled) console.warn("[tutor] could not resume tutorial", error);
  }
  if (continuing && !resumed) presenter.hide();
  if (!resumed && status.configuration?.show_on_first_login) {
    await maybeShowOnboarding({ api, engine, overlay: presenter.overlay, motion });
  }
}

start();
