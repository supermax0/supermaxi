"""Responsive browser checks for the dentistry workspace on tablet widths."""
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "tests" / "_artifacts" / "dental_tablet_768.png"
DRAWER_ARTIFACT = ROOT / "tests" / "_artifacts" / "dental_tablet_drawer_768.png"


@pytest.fixture(scope="module")
def tablet_browser():
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="msedge", headless=True)
        yield browser
        browser.close()


def test_tablet_keeps_full_arch_and_focus_drawers(tablet_browser):
    chart_js = (ROOT / "static/clinics/dental-chart.js").read_text(encoding="utf-8")
    chart_css = (ROOT / "static/clinics/dental-chart.css").read_text(encoding="utf-8")
    clinics_css = (ROOT / "static/clinics/clinics.css").read_text(encoding="utf-8")
    context = tablet_browser.new_context(
        locale="ar-IQ", viewport={"width": 768, "height": 702}, has_touch=True
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_content("""
      <!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"></head>
      <body class="clinics-app-mode"><div class="cx-main">
        <main class="cx-shell"><div class="cx-ws is-dental-focus">
          <div class="cx-ws-grid">
            <aside class="cx-ws-queue"><div class="cx-ws-card">المريض الحالي</div></aside>
            <section class="cx-ws-main"><div id="chart"></div></section>
            <aside class="cx-ws-context"><div class="cx-ws-card">السجل السريري</div></aside>
          </div>
          <footer class="cx-ws-footer"><div class="cx-ws-footer__actions"><button class="cx-btn">مسودة</button></div><button class="cx-btn cx-btn--primary">إنهاء الزيارة</button></footer>
          <div class="cx-ws-focus-docks"><button class="cx-ws-focus-handle is-queue">المريض</button><button class="cx-ws-focus-handle is-context">السجل السريري</button><button class="cx-ws-focus-handle is-footer">الإجراءات</button></div>
          <div class="cx-ws-focus-scrim"></div>
        </div></main><nav class="cx-mobile-nav">تنقل</nav>
      </div></body></html>
    """)
    page.add_style_tag(content=clinics_css)
    page.add_style_tag(content=chart_css)
    page.add_script_tag(content=chart_js)
    page.evaluate("""async () => {
      const statuses = [
        ['healthy','طبيعي'],['caries','تسوس'],['filled','حشوة'],
        ['temporary_filling','حشوة مؤقتة'],['root_canal','علاج عصب'],
        ['crown','تاج'],['implant','زرعة'],['missing','مفقود'],
        ['extraction_planned','مقرر قلع'],['fracture','كسر'],['other','أخرى']
      ].map(([code, label_ar]) => ({code, label_ar}));
      const chart = {
        patient_id: 1, has_chart: true, dentition_mode: 'permanent',
        permissions: {can_edit: true}, teeth: [], history_summary: {},
        catalog: {statuses, surfaces: ['mesial','distal','occlusal','buccal','lingual','incisal']}
      };
      const api = async (url) => url.endsWith('/procedures') || url.includes('/services') ? [] : chart;
      await ClinicsDentalChart.mount(document.getElementById('chart'), {visitId: 1, patientId: 1, api});
    }""")

    expect(page.locator(".cx-dental__desktop")).to_be_visible()
    expect(page.locator(".cx-dental__desktop [data-tooth]")).to_have_count(32)
    expect(page.locator(".cx-dental__mobile")).to_have_count(0)
    expect(page.locator(".cx-ws-focus-handle.is-queue")).to_be_visible()
    expect(page.locator(".cx-ws-focus-handle.is-context")).to_be_visible()
    expect(page.locator(".cx-ws-footer")).to_be_visible()

    layout = page.evaluate("""() => {
      const box = selector => document.querySelector(selector).getBoundingClientRect();
      const legend = box('.cx-dental__legend');
      const canvas = box('.cx-dental__canvas');
      return {
        overflow: document.documentElement.scrollWidth - innerWidth,
        legendAboveCanvas: legend.bottom <= canvas.top + 1,
        canvasWidth: canvas.width,
        queueOpacity: getComputedStyle(document.querySelector('.cx-ws-queue')).opacity,
        contextOpacity: getComputedStyle(document.querySelector('.cx-ws-context')).opacity,
        mobileNav: getComputedStyle(document.querySelector('.cx-mobile-nav')).display,
        toothSvgWidth: box('.cx-dental__desktop [data-tooth="11"] svg').width,
      };
    }""")
    assert layout["overflow"] <= 2
    assert layout["legendAboveCanvas"] is True
    assert layout["canvasWidth"] >= 700
    assert layout["toothSvgWidth"] >= 35
    assert layout["queueOpacity"] == "0"
    assert layout["contextOpacity"] == "0"
    assert layout["mobileNav"] == "none"

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACT), full_page=True)

    page.locator(".cx-ws").evaluate("element => element.classList.add('is-queue-open')")
    expect(page.locator(".cx-ws-queue")).to_be_visible()
    expect(page.locator(".cx-ws-focus-scrim")).to_be_visible()
    expect(page.locator(".cx-ws-queue")).to_have_css("transform", "matrix(1, 0, 0, 1, 0, 0)")
    opened = page.locator(".cx-ws-queue").evaluate(
        "element => ({left: element.getBoundingClientRect().left, opacity: getComputedStyle(element).opacity})"
    )
    assert opened["left"] >= -1
    assert opened["opacity"] == "1"
    assert not errors, errors

    page.screenshot(path=str(DRAWER_ARTIFACT), full_page=True)
    context.close()
