from utils.geo_links import parse_location


def test_plain_coordinates():
    parsed = parse_location("33.3152, 44.3661")
    assert parsed.lat == 33.3152
    assert parsed.lng == 44.3661
    assert parsed.error is None


def test_google_query_link():
    parsed = parse_location("https://maps.google.com/?q=33.3152,44.3661")
    assert parsed.lat == 33.3152
    assert parsed.lng == 44.3661


def test_short_link_keeps_url_without_coords():
    parsed = parse_location("https://maps.app.goo.gl/abc123")
    assert parsed.lat is None
    assert parsed.url.startswith("https://maps.app.goo.gl/")


def test_rejects_javascript_url():
    parsed = parse_location("javascript:alert(1)")
    assert parsed.error
    assert parsed.url is None
