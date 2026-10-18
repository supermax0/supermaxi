from urllib.parse import parse_qs, urlparse

from utils.tenant_registration import (
    build_whatsapp_activation_url,
    normalize_whatsapp_number,
    registration_payload_for_signup,
)


def _registration_payload():
    return registration_payload_for_signup(
        slug="noor-store",
        company_name="متجر النور",
        contact_name="محمد أحمد",
        email="",
        phone="07712345678",
        username="admin",
        password="secret1",
        plan_key="free",
        plan_name="الخطة المجانية",
        billing="monthly",
    )


def test_normalize_iraqi_whatsapp_number_for_wa_me():
    assert normalize_whatsapp_number("0771 234 5678") == "9647712345678"
    assert normalize_whatsapp_number("+964 771 234 5678") == "9647712345678"
    assert normalize_whatsapp_number("00964-771-234-5678") == "9647712345678"


def test_signup_payload_starts_pending_with_readable_activation_code():
    payload = _registration_payload()

    assert payload["activation_status"] == "pending_whatsapp"
    assert len(payload["activation_code"]) == 6
    assert payload["activation_code"].isalnum()


def test_activation_link_contains_matching_business_details_without_password():
    payload = _registration_payload()
    link = build_whatsapp_activation_url("+9647734049148", payload)
    parsed = urlparse(link)
    message = parse_qs(parsed.query)["text"][0]

    assert parsed.netloc == "wa.me"
    assert parsed.path == "/9647734049148"
    assert "الاسم: محمد أحمد" in message
    assert "اسم النشاط: متجر النور" in message
    assert "معرّف الشركة: noor-store" in message
    assert payload["activation_code"] in message
    assert "secret1" not in message

