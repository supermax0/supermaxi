from utils.invoice_text_format import format_invoice_text


def test_format_invoice_text_builds_bullets_and_inline_bold():
    rendered = str(
        format_invoice_text(
            "## شروط الضمان **مهمة** * يشمل الصيانة فقط * لا يشمل الكسر"
        )
    )

    assert "<h4>شروط الضمان <strong>مهمة</strong></h4>" in rendered
    assert "<ul><li>يشمل الصيانة فقط</li><li>لا يشمل الكسر</li></ul>" in rendered


def test_format_invoice_text_escapes_html():
    rendered = str(format_invoice_text("* <script>alert(1)</script>"))

    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
