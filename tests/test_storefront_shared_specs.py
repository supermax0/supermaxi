from modules.storefront.services.product_presenter import description_specs


def test_installment_description_is_split_into_cash_store_specs_and_features():
    parsed = description_specs(
        "السعة: 8 كيلو • نوع التشغيل: أوتوماتيك كامل • "
        "15 برنامج غسيل • محرك هادئ وموفر للطاقة"
    )

    assert parsed["rows"] == [
        {"label": "السعة", "value": "8 كيلو"},
        {"label": "نوع التشغيل", "value": "أوتوماتيك كامل"},
    ]
    assert parsed["features"] == [
        "15 برنامج غسيل",
        "محرك هادئ وموفر للطاقة",
    ]


def test_long_unstructured_description_stays_readable_as_a_paragraph():
    description = "وصف تفصيلي طويل للمنتج " * 12

    parsed = description_specs(description)

    assert parsed["rows"] == []
    assert parsed["features"] == []
    assert parsed["paragraph"] == description.strip()
