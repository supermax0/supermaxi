"""Clinic appearance: real settings controls, persistence, and workspace palettes."""
import pytest
from tests.test_clinics_internal_rtl_mobile import live_workspace, CRITICAL_PATHS, _no_overflow


def _open(page, base, path):
    response = page.goto(base + path, wait_until="networkidle", timeout=30000)
    assert response.status == 200, (path, response.status)
    page.wait_for_selector("#cxRoot > *")


@pytest.mark.parametrize("width", [1440, 390])
def test_clinic_theme_settings_and_pages(live_workspace, width):
    context = live_workspace["browser"].new_context(
        viewport={"width": width, "height": 960}, color_scheme="dark")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _open(page, live_workspace["base"], "/clinics/settings#appearance")
    # Clinics default to light even on a dark device or accounting workspace.
    assert page.locator("html").get_attribute("data-theme") == "light"
    for theme in ("dark", "light"):
        page.locator(f'.cx-theme-choice:has(input[value="{theme}"])').click()
        assert page.locator("html").get_attribute("data-theme") == theme
        assert page.locator(f'input[data-clinic-theme][value="{theme}"]').is_checked()
        assert page.evaluate("localStorage.getItem('finora-clinics-theme')") == theme
        paths = CRITICAL_PATHS + ["/clinics/expenses", "/clinics/cash", "/clinics/settlements",
                                  "/clinics/communications", "/clinics/purchases",
                                  f"/clinics/patients/{live_workspace['patient_id']}",
                                  f"/clinics/doctor/{live_workspace['visit_id']}"]
        for path in paths:
            _open(page, live_workspace["base"], path)
            assert page.locator("html").get_attribute("data-theme") == theme, path
            _no_overflow(page)
            palette = page.evaluate("""() => {
                const style = getComputedStyle(document.body);
                const surface = style.getPropertyValue('--cx-surface').trim();
                return {surface, sidebar: getComputedStyle(document.querySelector('.cx-sidebar')).backgroundColor};
            }""")
            assert palette["surface"] == ("#13212c" if theme == "dark" else "#fff"), (path, palette)
            assert palette["sidebar"] == ("rgb(16, 29, 39)" if theme == "dark" else "rgb(255, 255, 255)"), (path, palette)
        _open(page, live_workspace["base"], "/clinics/settings#appearance")
        page.screenshot(path=f"tests/_artifacts/clinics-theme-{theme}-{width}.png", full_page=True)
    assert not errors, errors
    context.close()


def test_clinic_theme_tabs_storage_failure_and_print(live_workspace):
    context = live_workspace["browser"].new_context()
    page = context.new_page()
    _open(page, live_workspace["base"], "/clinics/settings#appearance")
    page.evaluate("localStorage.setItem('theme', 'light')")
    other = context.new_page()
    _open(other, live_workspace["base"], "/clinics/settings#appearance")
    page.locator('.cx-theme-choice:has(input[value="dark"])').click()
    other.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    assert other.locator('input[value="dark"][data-clinic-theme]').is_checked()
    assert page.evaluate("localStorage.getItem('theme')") == "light"
    page.emulate_media(media="print")
    assert page.evaluate("getComputedStyle(document.body).getPropertyValue('--cx-surface').trim()") == "#fff"
    context.close()
    isolated = live_workspace["browser"].new_context(color_scheme="dark")
    isolated.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('disabled')}})")
    page = isolated.new_page()
    _open(page, live_workspace["base"], "/clinics/settings#appearance")
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.locator('.cx-theme-choice:has(input[value="dark"])').click()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    isolated.close()


def test_clinic_theme_dashboard_and_modal(live_workspace):
    context = live_workspace["browser"].new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    _open(page, live_workspace["base"], "/clinics/")
    for theme, expected in (("light", "rgb(255, 255, 255)"), ("dark", "rgb(19, 33, 44)")):
        page.evaluate("theme => ClinicsTheme.set(theme)", theme)
        assert page.locator(".cx-card").first.evaluate("el => getComputedStyle(el).backgroundColor") == expected
        page.wait_for_function("expected => getComputedStyle(document.querySelector('#cxDashDay')).backgroundColor === expected", arg=expected)
        page.screenshot(path=f"tests/_artifacts/clinics-dashboard-{theme}.png", full_page=True)
        page.locator("#cxDashNewAppt").click()
        page.wait_for_selector("#cxModal:not([hidden])")
        assert page.locator(".cx-modal").evaluate("el => getComputedStyle(el).backgroundColor") == expected
        assert page.locator("#cxModal .cx-input").first.evaluate("el => getComputedStyle(el).backgroundColor") == expected
        page.locator("#cxModalCancel").click()
    context.close()
