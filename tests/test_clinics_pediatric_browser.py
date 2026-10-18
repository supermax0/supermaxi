"""Browser fixture for pediatric tools panel (mocked APIs)."""
import json
from pathlib import Path
from urllib.parse import quote

import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope="module")
def ped_browser():
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="msedge", headless=True)
        yield browser
        browser.close()


def test_pediatric_panel_vaccination_and_growth_readable(ped_browser):
    root = Path(__file__).resolve().parents[1]
    js = (root / "static/clinics/pediatric-tools.js").read_text(encoding="utf-8")
    css = (root / "static/clinics/pediatric-tools.css").read_text(encoding="utf-8")
    state = {
        "patient_id": 1,
        "pediatric_profile": {
            "exists": True,
            "current_age": {"age_label": "2س 3ش"},
            "feeding_label_ar": "مختلط",
            "delivery_label_ar": "طبيعي",
            "gestational_age_weeks": 38,
            "birth_weight": 3.1,
        },
        "latest_growth": {"weight_kg": 12.2, "height_cm": 86, "bmi": 16.5, "head_circumference_cm": 48},
        "growth_history": [
            {
                "recorded_at": "2026-09-04T10:00:00",
                "age_label": "2س 3ش",
                "weight_kg": 12.2,
                "height_cm": 86,
                "bmi": 16.5,
                "head_circumference_cm": 48,
            }
        ],
        "growth_series": [
            {"weight_kg": 11, "height_cm": 84, "head_circumference_cm": 47},
            {"weight_kg": 12.2, "height_cm": 86, "head_circumference_cm": 48},
        ],
        "vaccinations": [],
        "development_history": [],
        "percentile_available": False,
        "permissions": {"can_edit": True},
        "catalog": {
            "delivery_types": [{"code": "vaginal", "label_ar": "طبيعي"}],
            "feeding_types": [{"code": "mixed", "label_ar": "مختلط"}],
            "vax_statuses": [{"code": "recorded", "label_ar": "مسجّل"}],
            "vax_sources": [{"code": "clinic", "label_ar": "العيادة"}],
            "dev_domains": [{"code": "language", "label_ar": "اللغة"}],
            "dev_statuses": [{"code": "documented", "label_ar": "موثّق"}],
        },
    }
    bootstrap = quote(json.dumps(state))
    html = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/clinics/pediatric-tools.css">
<style>.cx-btn{{padding:6px 10px;border:1px solid #ccc;cursor:pointer}}.cx-btn--primary{{background:#0f766e;color:#fff}}
.cx-input,.cx-select,.cx-textarea{{width:100%;padding:8px}}.cx-modal-backdrop{{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center}}
.cx-modal{{background:#fff;padding:16px;width:min(420px,92vw);border-radius:12px}}</style></head><body>
<div id="root"></div><div id="modalHost"></div>
<script src="/static/clinics/pediatric-tools.js"></script>
<script>
window.__ctx = JSON.parse(decodeURIComponent('{bootstrap}'));
function openModal(title, body, onSave){{
  const host=document.getElementById('modalHost');
  host.innerHTML=`<div class="cx-modal-backdrop"><div class="cx-modal" dir="rtl"><h3>${{title}}</h3><div>${{body}}</div>
  <button class="cx-btn cx-btn--primary" id="modalSave">حفظ</button></div></div>`;
  host.querySelector('#modalSave').onclick=async()=>{{await onSave(); host.innerHTML='';}};
}}
async function api(url, opts={{}}){{
  const method=(opts.method||'GET').toUpperCase();
  const body=opts.body?JSON.parse(opts.body):null;
  if(url.includes('pediatric-context')) return JSON.parse(JSON.stringify(window.__ctx));
  if(url.includes('vaccinations') && method==='POST'){{
    window.__ctx.vaccinations.push({{id:1, vaccine_name:body.vaccine_name, dose_label:body.dose_label||'', administered_date:body.administered_date||'', source_label_ar:'العيادة', status_label_ar:'مسجّل', source:'clinic', status:'recorded', notes:''}});
    return {{items: window.__ctx.vaccinations}};
  }}
  if(url.includes('pediatric-profile') && method==='PUT') return window.__ctx.pediatric_profile;
  if(url.includes('development') && method==='POST'){{
    window.__ctx.development_history.unshift({{recorded_at:'2026-09-04', doctor_name:'د', domains:{{language:{{label_ar:'اللغة', status_label_ar:'موثّق'}}}}, notes:body.notes||''}});
    return {{items: window.__ctx.development_history}};
  }}
  return {{}};
}}
ClinicsPediatricTools.mount(document.getElementById('root'), {{patientId:1, visitId:1, doctorId:1, api, showNotice:()=>{{}}, openModal}});
</script></body></html>"""

    context = ped_browser.new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def route(request):
        url = request.request.url
        if url.endswith("pediatric-tools.js"):
            request.fulfill(content_type="application/javascript", body=js)
        elif url.endswith("pediatric-tools.css"):
            request.fulfill(content_type="text/css", body=css)
        elif "clinics.test" in url:
            request.fulfill(content_type="text/html", body=html)
        else:
            request.abort()

    page.route("**/*", route)
    page.goto("http://clinics.test/ped")
    expect(page.locator(".cx-ped__note")).to_contain_text("WHO/CDC")
    expect(page.locator(".cx-ped__summary")).to_contain_text("12.2")
    page.locator("[data-add-vax]").click()
    page.locator("#vaxName").fill("BCG")
    page.locator("#vaxDate").fill("2026-01-10")
    page.locator("#modalSave").click()
    expect(page.locator(".cx-ped-card").get_by_text("BCG")).to_be_visible()
    assert not errors, errors
    for width in (768, 390, 375):
        page.set_viewport_size({"width": width, "height": 800})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
    context.close()
