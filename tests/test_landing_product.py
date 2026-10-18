"""Landing rendering and installer availability, without opening business databases."""
import json
from pathlib import Path

import pytest
from flask import Flask, render_template

from utils.landing_release import get_desktop_release

ROOT = Path(__file__).resolve().parents[1]


def render(overrides=None):
    app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    payload = {
        'settings': {}, 'seo': {}, 'section_map': {}, 'features': [], 'modules': [],
        'pricing': [], 'faqs': [], 'testimonials': [], 'ctas': [],
        'desktop_release': None, 'free_plan_enabled': True, 'free_trial_days': 14,
    }
    payload.update(overrides or {})
    with app.test_request_context('/'):
        return render_template('landing_dynamic.html', landing=payload, landing_plans={}, platform_app_name='Finora')


def test_public_landing_renders_without_optional_cms_content():
    html = render()
    assert 'id="fpPanel5"' in html
    assert 'id="desktop"' in html
    assert 'data-desktop-download' not in html
    assert '99.9%' not in html


def test_disabled_free_plan_has_no_free_signup_links():
    html = render({'free_plan_enabled': False, 'pricing': [
        {'name': 'Free', 'slug': 'free', 'price': 0, 'cta_url': '/signup?plan=free', 'features': []},
    ]})
    assert 'href="/signup?plan=free' not in html
    assert 'fp-trial"' not in html


def test_cms_hidden_sections_and_custom_gallery_are_respected():
    html = render({'section_map': {
        'desktop': {'is_visible': False},
        'features': {'is_visible': False},
        'product_tour': {'content': {'items': [{
            'label': 'جولة مخصصة', 'title': 'شاشة الإدارة', 'description': 'شرح الإدارة',
            'image_url': '/static/custom.png', 'platform': 'الويب',
        }]}},
    }})
    assert 'id="desktop"' not in html
    assert 'href="#desktop"' not in html
    assert 'id="features"' not in html
    assert 'id="fpPanel2"' not in html
    assert '/static/custom.png' in html


def test_unverified_seed_testimonials_do_not_render():
    html = render({'testimonials': [{'quote': 'UNVERIFIED_QUOTE'}]})
    assert 'UNVERIFIED_QUOTE' not in html


def test_available_release_links_to_actual_installer():
    html = render({'desktop_release': {'version': '1.2.3', 'platform': 'Windows', 'size_mb': 10, 'url': '/static/downloads/test.exe'}})
    assert 'href="/static/downloads/test.exe" download data-desktop-download' in html
    assert 'v1.2.3' in html


def test_cms_content_is_escaped():
    html = render({'section_map': {'hero': {'title': '<script>alert(1)</script>'}}})
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html


def test_custom_hero_copy_and_signup_destination_are_preserved():
    html = render({'section_map': {'hero': {
        'title': 'عنوان مخصص', 'description': 'شرح مخصص',
        'button_primary_text': 'احجز حسابك', 'button_primary_url': '/signup?plan=business',
    }}})
    assert 'عنوان مخصص' in html and 'شرح مخصص' in html
    assert 'href="/signup?plan=business"' in html


def test_legacy_corrupt_logo_is_replaced_with_the_desktop_mark():
    html = render({'settings': {'logo_url': '/static/IMG_0200.png', 'favicon_url': '/static/IMG_0200.png'},
                   'section_map': {'hero': {'image_url': '/static/IMG_0200.png'}}})
    assert 'src="/static/IMG_0200.png"' not in html
    assert 'src="/static/images/landing/finora-mark.svg"' in html
    assert 'src="/static/images/landing/suppliers.png"' in html


def test_release_requires_a_complete_local_file(tmp_path):
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    manifest = downloads / 'finora-management.json'
    manifest.write_text(json.dumps({'filename': 'finora.exe', 'size_bytes': 4, 'version': '1'}))
    assert get_desktop_release(tmp_path) is None
    (downloads / 'finora.exe').write_bytes(b'test')
    assert get_desktop_release(tmp_path)['url'] == '/static/downloads/finora.exe'
    (downloads / 'finora.exe').write_bytes(b'incomplete')
    assert get_desktop_release(tmp_path) is None


@pytest.mark.parametrize('filename', ['../finora.exe', '..\\finora.exe', '/finora.exe', 'https://example.com/file.exe', 'bad.exe?x=1', None])
def test_release_rejects_invalid_filenames(tmp_path, filename):
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    (downloads / 'finora-management.json').write_text(json.dumps({'filename': filename, 'size_bytes': 1}))
    assert get_desktop_release(tmp_path) is None


@pytest.mark.parametrize('content', ['{', '[]', 'null'])
def test_invalid_release_manifest_is_unavailable(tmp_path, content):
    downloads = tmp_path / 'downloads'
    downloads.mkdir()
    (downloads / 'finora-management.json').write_text(content)
    assert get_desktop_release(tmp_path) is None
