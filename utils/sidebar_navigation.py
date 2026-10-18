"""Group only links already rendered by the existing role/plan/business guards."""
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from markupsafe import Markup


SECTIONS = (
    ("home", "الرئيسية", "Home", "fa-house"),
    ("sales", "المبيعات والعملاء", "Sales & customers", "fa-cart-shopping"),
    ("stock", "المخزون والمشتريات", "Inventory & purchasing", "fa-boxes-stacked"),
    ("shipping", "الشحن والتوصيل", "Shipping & delivery", "fa-truck"),
    ("finance", "المالية", "Finance", "fa-wallet"),
    ("reports", "التقارير والرقابة", "Reports & monitoring", "fa-chart-pie"),
    ("team", "الفريق", "Team", "fa-users"),
    ("tools", "القنوات والأدوات", "Channels & tools", "fa-layer-group"),
    ("settings", "الإعدادات", "Settings", "fa-gear"),
)

SEARCH_ALIASES = {
    "/customers": "عميل العملاء زبون الزبائن customer",
    "/inventory": "منتج منتجات مخزن مخزون جرد product stock",
    "/orders": "طلب طلبات فاتورة مبيعات order sales",
    "/payroll": "راتب رواتب عمولة عمولات salary payroll",
    "/shipping": "شحن توصيل نقل كشف shipping delivery",
    "/agents": "مندوب مندوبين توصيل courier",
    "/accounts": "خزينة حسابات مالية قبض صرف سلفة قرض finance",
    "/receipts": "قبض تحصيل تسديد سند receipt",
    "/suppliers": "مورد موردين مشتريات supplier",
}


def section_for_path(path):
    path = urlsplit(str(path)).path.rstrip("/") or "/"
    if path == "/":
        return "home"
    if path == "/customers/provinces":
        return "settings"
    groups = (
        ("settings", ("/settings", "/admin", "/activity", "/upgrade")),
        ("shipping", ("/shipping", "/agents", "/delivery")),
        ("team", ("/employees", "/payroll", "/hr", "/employee-desk")),
        ("reports", ("/reports", "/executive-dashboard")),
        ("finance", ("/accounts", "/cash", "/receipts", "/expenses", "/assets", "/finance")),
        ("stock", ("/inventory", "/purchases", "/suppliers", "/maintenance")),
        ("sales", ("/pos", "/quick-sale", "/orders", "/customers", "/installments")),
    )
    if path == "/employees/page-warnings":
        return "tools"
    for group, prefixes in groups:
        if any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes):
            return group
    return "tools"


class _RenderedLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {"attrs": dict(attrs), "html": [self.get_starttag_text()], "label": []}
        elif self.current is not None:
            self.current["html"].append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        if self.current is not None:
            self.current["html"].append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.current is None:
            return
        self.current["html"].append(f"</{tag}>")
        if tag == "a":
            self.links.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current["html"].append(data)
            self.current["label"].append(data)

    def handle_entityref(self, name):
        if self.current is not None:
            self.current["html"].append(f"&{name};")
            self.current["label"].append(f"&{name};")

    def handle_charref(self, name):
        if self.current is not None:
            self.current["html"].append(f"&#{name};")
            self.current["label"].append(f"&#{name};")


def organized_sidebar(rendered_links, current_path="/", language="ar"):
    """Keep the exact guarded anchor markup; change its grouping, never its access."""
    english = language == "en"
    parser = _RenderedLinks()
    parser.feed(str(rendered_links))
    parser.close()
    groups = {key: [] for key, *_ in SECTIONS}
    for link in parser.links:
        href = link["attrs"].get("href", "")
        group = section_for_path(href)
        label = " ".join(" ".join(link["label"]).split())
        anchor = "".join(link["html"])
        pin = ""
        if href.startswith("/") and urlsplit(href).path != "/upgrade":
            pin = (
                f'<button type="button" class="organized-nav-pin" data-nav-pin="{escape(href, quote=True)}" '
                f'aria-label="{escape(("Pin " if english else "تثبيت ") + label, quote=True)}" aria-pressed="false" title="{"Pin to favorites" if english else "تثبيت في المفضلة"}">'
                '<i class="fa-regular fa-star" aria-hidden="true"></i></button>'
            )
        path = urlsplit(href).path.rstrip("/")
        aliases = " ".join(value for prefix, value in SEARCH_ALIASES.items()
                           if path == prefix or path.startswith(prefix + "/"))
        groups[group].append(
            f'<div class="organized-nav-item" data-nav-item data-nav-search-terms="{escape(aliases, quote=True)}">{anchor}{pin}</div>'
        )
    active_group = section_for_path(current_path)
    search_label = "Search navigation" if english else "بحث في القائمة"
    favorites_label = "Favorites" if english else "المفضلة"
    html = [
        '<div class="organized-nav-tools"><div class="organized-nav-search"><i class="fa fa-search" aria-hidden="true"></i>'
        f'<input type="search" data-nav-search aria-label="{search_label}" placeholder="{"Find a page…" if english else "ابحث عن صفحة…"}" autocomplete="off">'
        f'<button type="button" class="organized-nav-clear" data-nav-clear hidden aria-label="{"Clear search" if english else "مسح البحث"}"><i class="fa fa-xmark" aria-hidden="true"></i></button></div>'
        f'<div class="organized-nav-caption"><span>{"WORKSPACE" if english else "مساحة العمل"}</span><span data-nav-search-status role="status" aria-live="polite"></span></div></div>',
        f'<section class="organized-nav-favorites" data-nav-favorites hidden aria-label="{favorites_label}">'
        f'<div class="organized-nav-favorites-heading"><strong><i class="fa-regular fa-star" aria-hidden="true"></i> {favorites_label}</strong><span data-nav-favorite-count></span></div><div data-nav-favorite-links></div></section>',
        f'<p data-nav-empty hidden role="status"><i class="fa fa-magnifying-glass" aria-hidden="true"></i><span>{"No matching pages" if english else "لا توجد صفحات مطابقة"}</span></p>',
    ]
    for key, ar, en, icon in SECTIONS:
        if not groups[key]:
            continue
        title = en if english else ar
        opened = " open" if key == active_group else ""
        html.append(
            f'<details class="organized-nav-section" data-nav-section="{key}"{opened}>'
            f'<summary><i class="fa {icon} organized-nav-section-icon" aria-hidden="true"></i><span class="organized-nav-section-title">{escape(title)}</span>'
            f'<span class="organized-nav-count" data-nav-section-count aria-hidden="true">{len(groups[key])}</span>'
            '<i class="fa fa-chevron-left organized-nav-chevron" aria-hidden="true"></i></summary>'
            f'<div class="organized-nav-links">{"".join(groups[key])}</div></details>'
        )
    return Markup("".join(html))
