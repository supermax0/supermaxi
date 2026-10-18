"""Navigation preserves exactly the links emitted by existing access guards."""
from collections import Counter
import re

import pytest
from jinja2 import Environment

from utils.sidebar_navigation import organized_sidebar, section_for_path, _RenderedLinks


@pytest.mark.parametrize("path,group", [
    ("/", "home"), ("/pos", "sales"), ("/orders/ordered", "sales"),
    ("/installments/contracts", "sales"), ("/customers/credit", "sales"),
    ("/inventory/audit", "stock"), ("/purchases/lists", "stock"), ("/suppliers", "stock"),
    ("/agents/pending-execution", "shipping"), ("/shipping/company-returns", "shipping"),
    ("/accounts/finance", "finance"), ("/finance/rotating-savings", "finance"),
    ("/reports/monitors", "reports"), ("/executive-dashboard", "reports"),
    ("/payroll", "team"), ("/employees", "team"), ("/employee-desk", "team"),
    ("/employees/page-warnings", "tools"), ("/pages", "tools"), ("/workspace/", "tools"),
    ("/customers/provinces/", "settings"), ("/settings/invoice", "settings"),
    ("/admin/permissions/roles", "settings"), ("/activity", "settings"),
])
def test_pages_have_one_stable_section(path, group):
    assert section_for_path(path) == group


def links(html):
    parser = _RenderedLinks()
    parser.feed(str(html))
    return parser.links


def test_attributes_badges_escaping_and_upgrade_choices_survive_grouping():
    original = '''<div><button>Old heading</button><a href="/messages" class="active" target="_blank" rel="noopener">
      <i class="fa fa-comments"></i> A &amp; B <span id="messagesBadge">3</span></a>
      <a href="/upgrade" title="inventory">Inventory locked</a>
      <a href="/upgrade" title="reports">Reports locked</a></div>'''
    grouped = organized_sidebar(original, "/messages")
    assert Counter("".join(a["html"]) for a in links(original)) == Counter("".join(a["html"]) for a in links(grouped))
    assert 'id="messagesBadge"' in grouped
    assert "&amp;" in grouped
    assert "Old heading" not in grouped
    assert grouped.count("data-nav-section=") == 2


@pytest.mark.parametrize("granted", [False, True])
def test_grouping_cannot_reintroduce_denied_links(granted):
    template = Environment(autoescape=True).from_string('''<a href="/orders">Orders</a>
      {% if granted %}<a href="/accounts/finance">Finance</a>{% endif %}''')
    guarded = template.render(granted=granted)
    grouped = organized_sidebar(guarded, "/orders")
    assert Counter(a["attrs"]["href"] for a in links(grouped)) == Counter(a["attrs"]["href"] for a in links(guarded))
    assert ('href="/accounts/finance"' in grouped) == granted
    assert ('data-nav-section="finance"' in grouped) == granted


def test_active_section_opens_and_empty_sections_are_not_rendered():
    result = organized_sidebar('<a href="/orders">Orders</a><a href="/payroll">Payroll</a>', "/payroll/")
    assert 'data-nav-section="team" open' in result
    assert 'data-nav-section="sales" open' not in result
    assert 'data-nav-section="finance"' not in result


def test_customer_synonyms_are_searchable_without_adding_a_new_link():
    result = organized_sidebar('<a href="/customers">الزبائن</a>')
    assert "عميل العملاء" in result
    assert len(links(result)) == 1


def test_search_favorites_and_sections_use_the_selected_language():
    result = organized_sidebar('<a href="/orders">Orders</a>', "/orders", "en")
    assert 'aria-label="Search navigation"' in result
    assert 'aria-label="Clear search"' in result
    assert 'aria-label="Favorites"' in result
    assert 'aria-label="Pin Orders"' in result
    assert 'Sales &amp; customers' in result
    assert 'data-nav-section-count' in result
    assert len(links(result)) == 1


def test_existing_template_links_match_organized_preview(safety, client):
    classic = client.get("/orders/?navigation=classic")
    preview = client.get("/orders/?navigation=organized")
    assert classic.status_code == preview.status_code == 200
    def hrefs(response):
        nav = re.search(r'<nav class="menu"[^>]*>(.*?)</nav>', response.get_data(as_text=True), re.S)
        assert nav
        return Counter(a["attrs"].get("href") for a in links(nav.group(1)))
    assert hrefs(classic) == hrefs(preview)
    assert re.search(r'<nav\b[^>]*\bdata-organized-navigation(?:\s|>)', preview.get_data(as_text=True))
    assert not re.search(r'<nav\b[^>]*\bdata-organized-navigation(?:\s|>)', classic.get_data(as_text=True))


def test_appearance_opt_in_and_rollback_never_change_money(safety, client):
    from tests.test_page_read_safety import money_state
    before = money_state(safety)
    for enabled in (True, False):
        response = client.post("/settings/appearance/update", json={"ui_flags": {"navigation_v2": enabled}})
        assert response.status_code == 200 and response.json["success"], response.json
        page = client.get("/orders/")
        assert page.status_code == 200
        assert bool(re.search(r'<nav\b[^>]*\bdata-organized-navigation(?:\s|>)', page.get_data(as_text=True))) == enabled
        assert money_state(safety) == before


# Reuse the real isolated tenant fixture; no application/financial mocks.
from tests.test_page_read_safety import safety, client  # noqa: E402,F401
