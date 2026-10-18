"""Browser regression for the shared AI/Tutor launcher and mobile composers.

Uses the real app styles, widget markup, and Tutor components with local API stubs.
No model calls or tenant writes are needed for these layout checks.
"""
from pathlib import Path
import threading

import pytest
from flask import Flask, render_template_string, session
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "tests/_artifacts/assistant-layout"


@pytest.fixture(scope="module")
def assistant_workspace():
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    widget_start = base.index('<button class="finora-ai-fab"')
    widget = base[widget_start:base.index("</aside>", widget_start) + len("</aside>")]
    base_style = base[base.index("<style>"):base.index("</style>") + len("</style>")]
    workspace = (ROOT / "templates/clinics/workspace.html").read_text(encoding="utf-8")
    nav_start = workspace.index('<nav class="cx-mobile-nav"')
    nav = workspace[nav_start:workspace.index("</nav>", nav_start) + len("</nav>")]
    app = Flask(__name__, static_folder=str(ROOT / "static"))
    app.secret_key = "assistant-layout-tests"

    @app.get("/")
    def home():
        session["role"] = "admin"
        return render_template_string("""<!doctype html><html lang="ar" dir="rtl" data-theme="light"><head>
          <meta name="viewport" content="width=device-width,initial-scale=1">
          {{ base_style|safe }}
          <link rel="stylesheet" href="/static/css/finora-ai.css">
          <link rel="stylesheet" href="/static/css/assistant-layout.css">
          <link rel="stylesheet" href="/static/clinics/clinics.css">
          <link rel="stylesheet" href="/static/clinics/theme.css">
          <link rel="stylesheet" href="/static/ai-tutor/ui/tutor.css">
          <script src="/static/js/assistant-layout.js" defer></script>
          </head><body class="clinics-app-mode"><main class="page-main"><h1>لوحة العيادة</h1></main>
          {{ nav|safe }}{{ widget|safe }}<script src="/static/js/finora-ai.js" defer></script>
          </body></html>""", base_style=base_style, nav=render_template_string(nav, clinics_page="dashboard"), widget=render_template_string(widget))

    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except Exception:
            browser = runtime.chromium.launch(channel="msedge", headless=True)
        yield browser, f"http://127.0.0.1:{server.server_port}"
        browser.close()
    server.shutdown()


def _mount_tutor(page):
    page.evaluate("""async () => {
      const { TutorOverlay } = await import('/static/ai-tutor/ui/overlay.js');
      const { TutorHome } = await import('/static/ai-tutor/ui/home.js');
      const { TutorLauncher } = await import('/static/ai-tutor/ui/launcher.js');
      const { motionFor } = await import('/static/ai-tutor/motion/tokens.js');
      const api = {
        list: async () => ({tutorials:[{id:'patient.create',title_ar:'إضافة مريض',progress:{status:'paused'}}]}),
        knowledge: async () => ({quick_actions:[{tutorial_id:'patient.create',label:'إضافة مريض'}],plan:{groups:[]},suggested_prompts:['شلون أضيف مريض؟']})
      };
      const engine = {machine:{subscribe(){}},isBusy:() => false};
      const overlay = new TutorOverlay();
      const motion = motionFor(window);
      const home = new TutorHome({overlay,engine,api,motion});
      const launcher = new TutorLauncher({overlay,home,engine,api,motion});
      window.testTutor = {home,launcher};
    }""")


def _clickable(page, selector):
    assert page.locator(selector).evaluate("""el => {
      const r=el.getBoundingClientRect();
      const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
      return hit===el || el.contains(hit);
    }""")


@pytest.mark.parametrize("width", [390, 768, 1440])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_assistant_and_learning_panels(assistant_workspace, width, theme):
    browser, base = assistant_workspace
    context = browser.new_context(viewport={"width": width, "height": 840}, reduced_motion="reduce")
    context.route("**/finora-ai/api/**", lambda route: route.fulfill(json={"notice":"قراءة آمنة · حسب صلاحيات حسابك", "language_model":False}))
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base, wait_until="networkidle")
    page.evaluate("theme => document.documentElement.dataset.theme=theme", theme)
    await_fab = page.locator("#finoraAiFab")
    if width <= 1024:
        page.wait_for_function("document.querySelector('#finoraAiFab').getBoundingClientRect().bottom <= document.querySelector('.cx-mobile-nav').getBoundingClientRect().top - 12")
        # The position must respond to navigation resizing rather than a fixed guessed height.
        page.locator(".cx-mobile-nav").evaluate("el => el.style.paddingTop='30px'")
        page.wait_for_function("document.querySelector('#finoraAiFab').getBoundingClientRect().bottom <= document.querySelector('.cx-mobile-nav').getBoundingClientRect().top - 12")
    _clickable(page, "#finoraAiFab")
    await_fab.click()
    expect(await_fab).to_be_hidden()
    expect(page.locator("#finoraAiPanel")).to_be_visible()
    _clickable(page, "#finoraAiSend")
    expect(page.locator("#finoraAiPanel")).to_have_css("color", "rgb(232, 240, 246)" if theme == "dark" else "rgb(23, 43, 58)")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(SHOTS / f"ai-{theme}-{width}.png"))
    if width == 390:
        page.set_viewport_size({"width":width,"height":460})
        page.wait_for_function("document.querySelector('#finoraAiForm').getBoundingClientRect().bottom <= innerHeight")
        _clickable(page, "#finoraAiSend")
        page.screenshot(path=str(SHOTS / f"ai-short-{theme}.png"))
        page.set_viewport_size({"width":width,"height":840})
    page.locator("#finoraAiClose").click()
    expect(await_fab).to_be_visible()
    _mount_tutor(page)
    await_fab.click()
    page.locator('[data-tutor-menu="learn"]').click()
    expect(page.locator(".ft-home")).to_be_visible()
    expect(await_fab).to_be_hidden()
    expect(page.locator(".ft-badge")).to_be_hidden()
    _clickable(page, ".ft-chat__send")
    page.screenshot(path=str(SHOTS / f"learn-{theme}-{width}.png"))
    if width == 390:
        page.set_viewport_size({"width":width,"height":460})
        page.wait_for_function("document.querySelector('.ft-chat__form').getBoundingClientRect().bottom <= innerHeight")
        _clickable(page, ".ft-chat__send")
    page.locator(".ft-home__close").click()
    expect(await_fab).to_be_visible()
    assert not errors, errors
    context.close()


def test_fallback_launcher_and_badge_move_with_navigation(assistant_workspace):
    browser, base = assistant_workspace
    context = browser.new_context(viewport={"width":390,"height":840})
    page = context.new_page()
    page.goto(base, wait_until="networkidle")
    page.locator("#finoraAiFab").evaluate("el => el.remove()")
    _mount_tutor(page)
    page.wait_for_function("document.querySelector('.ft-orb-launcher').getBoundingClientRect().bottom <= document.querySelector('.cx-mobile-nav').getBoundingClientRect().top - 12")
    expect(page.locator(".ft-badge")).to_be_visible()
    page.locator(".cx-mobile-nav").evaluate("el => el.style.paddingTop='30px'")
    page.wait_for_function("Math.abs(document.querySelector('.ft-badge').getBoundingClientRect().top - document.querySelector('.ft-orb-launcher').getBoundingClientRect().top + 4) < 1")
    page.locator(".ft-orb-launcher").click()
    page.locator('[data-tutor-menu="learn"]').click()
    expect(page.locator(".ft-orb-launcher")).to_be_hidden()
    page.locator(".ft-home__close").click()
    expect(page.locator(".ft-orb-launcher")).to_be_visible()
    context.close()


def test_visual_keyboard_without_layout_viewport_resize(assistant_workspace):
    browser, base = assistant_workspace
    context = browser.new_context(viewport={"width":390,"height":840}, reduced_motion="reduce")
    context.add_init_script("""const vp=new EventTarget();vp.height=840;vp.offsetTop=0;
      Object.defineProperty(window,'visualViewport',{get:()=>vp});window.testViewport=vp;""")
    context.route("**/finora-ai/api/**", lambda route: route.fulfill(json={"notice":"قراءة آمنة", "language_model":False}))
    page = context.new_page()
    page.goto(base, wait_until="networkidle")
    page.locator("#finoraAiFab").click()
    page.evaluate("testViewport.height=460;testViewport.dispatchEvent(new Event('resize'))")
    page.wait_for_function("document.querySelector('#finoraAiForm').getBoundingClientRect().bottom <= 460")
    assert page.evaluate("innerHeight") == 840
    _clickable(page, "#finoraAiSend")
    page.locator("#finoraAiClose").click()
    _mount_tutor(page)
    page.locator("#finoraAiFab").click()
    page.locator('[data-tutor-menu="learn"]').click()
    page.wait_for_function("document.querySelector('.ft-chat__form').getBoundingClientRect().bottom <= 460")
    _clickable(page, ".ft-chat__send")
    page.evaluate("testViewport.offsetTop=120;testViewport.dispatchEvent(new Event('scroll'))")
    page.wait_for_function("document.querySelector('.ft-chat__form').getBoundingClientRect().bottom <= 580 && document.querySelector('.ft-home').getBoundingClientRect().top >= 120")
    _clickable(page, ".ft-chat__send")
    context.close()
