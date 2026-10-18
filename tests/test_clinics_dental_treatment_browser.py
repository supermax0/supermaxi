"""Browser fixture E2E for dental treatment plan panel (mocked APIs)."""
import json
from pathlib import Path
from urllib.parse import quote

import pytest
from playwright.sync_api import sync_playwright, expect


@pytest.fixture(scope="module")
def dtp_browser():
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel="msedge", headless=True)
        yield browser
        browser.close()


def test_treatment_plan_panel_create_item_persists_in_session(dtp_browser):
    root = Path(__file__).resolve().parents[1]
    js = (root / "static/clinics/dental-treatment-plan.js").read_text(encoding="utf-8")
    css = (root / "static/clinics/dental-treatment-plan.css").read_text(encoding="utf-8")
    bootstrap = quote(json.dumps({"patient_id": 1, "active_plan": None, "plans": []}))

    html = f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/clinics/dental-treatment-plan.css">
<style>
.cx-btn{{padding:6px 10px;border:1px solid #ccc;background:#fff;cursor:pointer}}
.cx-btn--primary{{background:#0f766e;color:#fff}}
.cx-btn--sm{{font-size:12px}}
.cx-input,.cx-select,.cx-textarea{{width:100%;padding:8px;margin-top:4px}}
.cx-field{{margin-bottom:10px}} .cx-field-row{{display:flex;gap:8px}}
.cx-empty{{padding:16px;text-align:center}}
.cx-modal-backdrop{{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:20}}
.cx-modal{{background:#fff;padding:16px;border-radius:12px;width:min(420px,92vw)}}
</style></head><body>
<div id="root"></div><div id="modalHost"></div>
<script src="/static/clinics/dental-treatment-plan.js"></script>
<script>
window.__state = JSON.parse(decodeURIComponent('{bootstrap}'));
function openModal(title, body, onSave) {{
  const host = document.getElementById('modalHost');
  host.innerHTML = `<div class="cx-modal-backdrop"><div class="cx-modal" dir="rtl"><h3>${{title}}</h3><div id="modalBody">${{body}}</div>
    <button class="cx-btn cx-btn--primary" id="modalSave">حفظ</button>
    <button class="cx-btn" id="modalClose">إلغاء</button></div></div>`;
  host.querySelector('#modalClose').onclick = () => host.innerHTML = '';
  host.querySelector('#modalSave').onclick = async () => {{ await onSave(); host.innerHTML=''; }};
}}
async function api(url, opts={{}}) {{
  const method = (opts.method||'GET').toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : null;
  if (url.includes('/patients/1/dental-treatment-plans') && method === 'GET') {{
    return JSON.parse(JSON.stringify(window.__state));
  }}
  if (url.includes('/patients/1/dental-treatment-plans') && method === 'POST') {{
    const plan = {{
      plan: {{id:1, name: body.name||'خطة علاج الأسنان', status:'active', status_label_ar:'نشطة', patient_id:1, doctor_name:'د. اختبار', created_at:'2026-09-04'}},
      items: [],
      summary: {{item_count:0, completed_count:0, in_progress_count:0, remaining_count:0, estimated_total:0, progress_ratio:0}},
      permissions: {{can_edit:true, include_financial:true}}
    }};
    window.__state.active_plan = plan;
    window.__state.plans = [plan];
    return plan;
  }}
  if (url.includes('/dental-treatment-plans/1/items') && method === 'POST') {{
    const plan = window.__state.active_plan;
    const item = {{
      id: plan.items.length + 1, plan_id:1, tooth_number: body.tooth_number || null,
      title: body.title || 'علاج', priority: body.priority || 'normal',
      priority_label_ar: body.priority === 'high' ? 'مرتفع' : 'عادي',
      status:'planned', status_label_ar:'مخطط',
      estimated_sessions: Number(body.estimated_sessions||1),
      estimated_price: Number(body.estimated_price||0),
      actual_sessions:0, sessions_label:'0 / '+Number(body.estimated_sessions||1),
      actual_billed:0, paid:0, remaining:0, executions:[]
    }};
    plan.items.push(item);
    plan.summary.item_count = plan.items.length;
    plan.summary.remaining_count = plan.items.length;
    plan.summary.estimated_total = plan.items.reduce((s,i)=>s+Number(i.estimated_price||0),0);
    return plan;
  }}
  if (url.includes('/dental-treatment-plan-items/') && method === 'PATCH') {{
    const id = url.split('/').pop();
    const plan = window.__state.active_plan;
    const item = plan.items.find(i => String(i.id) === String(id));
    Object.assign(item, body);
    if (body.priority === 'high') item.priority_label_ar = 'مرتفع';
    return plan;
  }}
  if (url.includes('/procedures')) return [];
  if (url.includes('/print')) return {{clinic_name:'عيادة', patient_name:'مريض', patient_file:'P1', doctor_name:'د', plan_name:'خطة', plan_date:'2026-09-04', items:[], estimated_total:0}};
  throw new Error('unexpected '+method+' '+url);
}}
ClinicsDentalTreatmentPlan.mount(document.getElementById('root'), {{
  patientId:1, api, showNotice:(m)=>{{window.__notice=m}}, openModal, doctorId:1, specialtyId:1, visitId:1
}});
</script></body></html>"""

    context = dtp_browser.new_context(locale="ar-IQ", viewport={"width": 1366, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def route(request):
        url = request.request.url
        if url.endswith("dental-treatment-plan.js"):
            request.fulfill(content_type="application/javascript", body=js)
        elif url.endswith("dental-treatment-plan.css"):
            request.fulfill(content_type="text/css", body=css)
        elif "clinics.test" in url:
            request.fulfill(content_type="text/html", body=html)
        else:
            request.abort()

    page.route("**/*", route)
    page.goto("http://clinics.test/dtp")
    expect(page.locator(".cx-dtp").get_by_text("لا توجد خطة علاج حالية").first).to_be_visible()
    page.locator("[data-create-plan]").first.click()
    page.locator("#dtpName").fill("خطة علاج تجريبية")
    page.locator("#modalSave").click()
    expect(page.locator(".cx-dtp").get_by_text("خطة علاج تجريبية")).to_be_visible()
    page.locator("[data-add-general]").click()
    page.locator("#dtpTitle").fill("علاج عصب")
    page.locator("#dtpTooth").fill("16")
    page.locator("#dtpPriority").select_option("high")
    page.locator("#dtpSessions").fill("3")
    page.locator("#dtpPrice").fill("300000")
    page.locator("#modalSave").click()
    expect(page.locator(".cx-dtp__item").get_by_text("16 · علاج عصب")).to_be_visible()
    expect(page.locator(".cx-dtp__item").get_by_text("مرتفع")).to_be_visible()
    page.locator("[data-edit-item]").click()
    page.locator("#dtpPriority").select_option("high")
    page.locator("#modalSave").click()
    expect(page.locator(".cx-dtp__item").get_by_text("16 · علاج عصب")).to_be_visible()
    assert not errors, errors

    page.set_viewport_size({"width": 375, "height": 800})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
    context.close()
