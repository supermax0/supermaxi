"""Browser-style coverage for the unified dental sessions and images frontend."""
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as runtime:
        try:
            instance = runtime.chromium.launch(headless=True)
        except Exception:
            instance = runtime.chromium.launch(channel="msedge", headless=True)
        yield instance
        instance.close()


def _page(browser, body_script: str):
    js = (ROOT / "static/clinics/dental-platform.js").read_text(encoding="utf-8")
    css = (ROOT / "static/clinics/clinics.css").read_text(encoding="utf-8")
    html = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
    <link rel="stylesheet" href="/clinics.css"></head><body>
    <main id="root"></main><div id="modal"></div>
    <script src="/dental-platform.js"></script><script>
    function openModal(title, body, onSave) {{
      const host = document.getElementById("modal");
      host.innerHTML = `<div class="cx-modal-backdrop"><div class="cx-modal"><h3>${{title}}</h3>${{body}}<button id="modalSave">حفظ</button></div></div>`;
      host.querySelector("#modalSave").onclick = async () => {{ await onSave(); host.innerHTML = ""; }};
    }}
    function showNotice(message, error) {{ window.__notice = {{message, error}}; }}
    {body_script}
    </script></body></html>"""
    context = browser.new_context(locale="ar-IQ", viewport={"width": 1100, "height": 850})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route(request):
        url = request.request.url
        if url.endswith("/dental-platform.js"):
            request.fulfill(content_type="application/javascript", body=js)
        elif url.endswith("/clinics.css"):
            request.fulfill(content_type="text/css", body=css)
        elif "clinics.test" in url:
            request.fulfill(content_type="text/html", body=html)
        else:
            request.abort()

    page.route("**/*", route)
    page.goto("http://clinics.test/platform")
    return context, page, errors


def test_session_lifecycle_and_prefilled_next_booking(browser):
    script = """
    window.__calls = [];
    window.__sessions = [];
    window.__nextId = 1;
    const plan = {active_plan:{plan:{id:7,name:"خطة",status:"active"},permissions:{can_edit:true},
      items:[{id:12,tooth_number:"16",title:"علاج عصب",status:"in_progress",status_label_ar:"قيد التنفيذ",sessions_label:"0 / 3",estimated_sessions:3,procedure_id:4}]},plans:[]};
    async function api(url, options={}) {
      const method = (options.method || "GET").toUpperCase();
      const body = options.body ? JSON.parse(options.body) : {};
      window.__calls.push({url, method, body});
      if (url.includes("/patients/1/dental-treatment-plans")) return structuredClone(plan);
      if (url.endsWith("/dental-treatment-plan-items/12/sessions") && method === "GET") return {items:structuredClone(window.__sessions),next_session:null};
      if (url.endsWith("/dental-treatment-plan-items/12/sessions") && method === "POST") {
        const row = {id:window.__nextId++,treatment_plan_item_id:12,session_number:window.__sessions.length+1,status:body.status,scheduled_for:body.scheduled_for,appointment_id:body.appointment_id||null,notes:body.notes||""};
        window.__sessions.push(row); return structuredClone(row);
      }
      if (url.includes("/dental-sessions/") && method === "PATCH") {
        const row = window.__sessions.find(x => url.includes("/"+x.id)); Object.assign(row, body); return structuredClone(row);
      }
      if (url.endsWith("/complete") && method === "POST") {
        const row = window.__sessions.find(x => url.includes("/"+x.id+"/")); row.status="completed"; return structuredClone(row);
      }
      if (url === "/clinics/api/appointments" && method === "POST") return {id:88,...body};
      throw new Error("unexpected "+method+" "+url);
    }
    ClinicsDentalPlatform.mount(document.getElementById("root"), {view:"sessions",patientId:1,visitId:3,doctorId:2,specialtyId:5,api,openModal,showNotice});
    """
    context, page, errors = _page(browser, script)
    expect(page.get_by_text("لا توجد جلسة قادمة")).to_be_visible()
    page.locator("[data-new-session]").click()
    page.locator("#dpSessionNotes").fill("جلسة أولى")
    page.locator("#modalSave").click()
    expect(page.locator(".cx-dplat-session")).to_contain_text("جلسة أولى")
    page.locator("[data-start-session]").click()
    expect(page.locator(".cx-dplat-session")).to_contain_text("جارية")
    page.locator("[data-complete-session]").click()
    page.locator("#modalSave").click()
    expect(page.locator(".cx-dplat-book")).to_be_visible()
    page.locator("[data-next-at]").fill("2026-09-10T10:30")
    page.locator("[data-book-next]").click()
    expect(page.locator(".cx-dplat-next")).to_contain_text("الجلسة القادمة")
    calls = page.evaluate("window.__calls")
    appointment_index = next(i for i, call in enumerate(calls) if call["url"] == "/clinics/api/appointments")
    linked_index = next(
        i
        for i, call in enumerate(calls)
        if i > appointment_index
        and call["url"].endswith("/dental-treatment-plan-items/12/sessions")
        and call["method"] == "POST"
    )
    assert calls[linked_index]["body"]["appointment_id"] == 88
    assert appointment_index < linked_index
    assert not errors, errors
    context.close()


def test_image_upload_metadata_viewer_filters_and_soft_delete(browser):
    script = """
    window.__calls = []; window.__images = [];
    window.fetch = async (url, options={}) => {
      window.__calls.push({kind:"attachment",url:String(url)});
      return new Response(JSON.stringify({ok:true,data:{items:[{id:44,file_name:"tooth.png"}],count:1}}),{status:200,headers:{"Content-Type":"application/json"}});
    };
    async function api(url, options={}) {
      const method=(options.method||"GET").toUpperCase();
      const body=options.body?JSON.parse(options.body):{};
      window.__calls.push({kind:"api",url,method,body});
      if (url.includes("/dental-images?")) return structuredClone(window.__images);
      if (url === "/clinics/api/dental-images" && method === "POST") {
        const row={id:9,attachment_id:body.attachment_id,patient_id:1,tooth_number:body.tooth_number,image_type:body.image_type,captured_at:"2026-09-07T10:00:00",notes:body.notes,file_name:"tooth.png"};
        window.__images=[row]; return structuredClone(row);
      }
      if (url === "/clinics/api/dental-images/9" && method === "DELETE") {
        window.__images=[]; return {id:9,archived:true};
      }
      throw new Error("unexpected "+method+" "+url);
    }
    ClinicsDentalPlatform.mount(document.getElementById("root"), {view:"images",patientId:1,visitId:3,api,showNotice});
    """
    context, page, errors = _page(browser, script)
    page.locator("[data-image-file]").set_input_files(
        {"name": "tooth.png", "mimeType": "image/png", "buffer": b"\x89PNG\r\n\x1a\n"}
    )
    page.locator("[data-image-type]").select_option("xray")
    page.locator("[data-image-tooth]").fill("16")
    page.locator("[data-image-notes]").fill("قبل العلاج")
    page.locator("[data-dental-upload]").evaluate("(form) => form.requestSubmit()")
    expect(page.locator(".cx-dplat-image")).to_contain_text("السن 16")
    calls = page.evaluate("window.__calls")
    assert calls[0]["kind"] == "api"  # initial metadata list
    attachment_index = next(i for i, call in enumerate(calls) if call["kind"] == "attachment")
    metadata_index = next(i for i, call in enumerate(calls) if call["kind"] == "api" and call["method"] == "POST")
    assert attachment_index < metadata_index
    assert calls[metadata_index]["body"]["attachment_id"] == 44
    page.locator("[data-open-image]").click()
    page.locator("[data-view-rotate]").click()
    expect(page.locator(".cx-dplat-viewer img")).to_have_css("transform", "matrix(0, 1, -1, 0, 0, 0)")
    page.locator("[data-view-close]").click()
    page.locator("[data-image-filter-tooth]").fill("16")
    page.locator("[data-image-filter-type]").select_option("xray")
    page.locator("[data-apply-image-filter]").click()
    expect(page.locator(".cx-dplat-image")).to_be_visible()
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("[data-delete-image]").click()
    expect(page.get_by_text("لا توجد صور مطابقة.")).to_be_visible()
    assert not errors, errors
    context.close()
