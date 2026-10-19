"""Legacy asset tables retain every column inside a keyboard-accessible scroller."""
from html.parser import HTMLParser

import pytest

from tests.test_page_read_safety import safety, client, money_state  # noqa: F401


class AssetTables(HTMLParser):
    def __init__(self, table_class="fa-table"):
        super().__init__()
        self.table_class = table_class
        self.regions = []
        self.tables = 0
        self.divs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self.divs.append(attrs)
        if tag == "table" and self.table_class in attrs.get("class", "").split():
            self.tables += 1
            region = self.divs[-1]
            assert "workspace-table-scroll" in region.get("class", "").split()
            assert region.get("tabindex") == "0" and region.get("role") == "region"
            assert region.get("aria-label")
            self.regions.append(region)

    def handle_endtag(self, tag):
        if tag == "div":
            self.divs.pop()


@pytest.mark.parametrize("path", [
    "/assets/dashboard", "/assets/", "/assets/categories", "/assets/depreciation",
    "/assets/maintenance", "/assets/disposal", "/assets/approvals", "/assets/reports", "/assets/audit",
])
def test_asset_tables_keep_accessible_columns_without_financial_writes(safety, client, path):
    before = money_state(safety)
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/static/css/finora-theme.css?v=20261019b" in html
    tables = AssetTables()
    tables.feed(html)
    assert tables.tables and len(tables.regions) == tables.tables
    assert money_state(safety) == before


def test_financial_report_keeps_all_tables_and_export_controls(safety, client):
    before = money_state(safety)
    response = client.get("/reports/financial")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    tables = AssetTables("report-table")
    tables.feed(html)
    assert tables.tables == len(tables.regions) == html.count('class="report-table"')
    assert tables.tables >= 6  # Additional sections depend on the selected period's data.
    assert 'id="exportPdfBtn"' in html and 'id="reportRoot"' in html
    assert money_state(safety) == before
