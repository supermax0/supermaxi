from utils.note_content import html_to_text, organize_plain_text, sanitize_note_html


def test_note_html_sanitizer_keeps_editor_features_and_removes_scripts():
    raw = (
        '<script>alert(1)</script><h2 style="color:#2563eb;position:fixed">عنوان</h2>'
        '<a href="javascript:alert(2)">سيئ</a>'
        '<font face="Tajawal" size="5" color="#2563eb">منسق</font>'
        '<p align="center">وسط</p>'
        '<span class="note-check evil" data-state="cancelled" contenteditable="false" role="checkbox" tabindex="0" aria-checked="true"></span>'
        '<table><tr><td colspan="2" onclick="bad()">بيان</td></tr></table>'
        '<div class="note-chart evil" data-chart=\'{"values":[1,2]}\'>رسم</div>'
    )

    clean = sanitize_note_html(raw)

    assert "<script" not in clean
    assert "alert(1)" not in clean
    assert "javascript:" not in clean
    assert "onclick" not in clean
    assert "position:" not in clean
    assert "color:#2563eb" in clean
    assert '<font face="Tajawal" size="5" color="#2563eb">' in clean
    assert '<p align="center">' in clean
    assert 'class="note-check"' in clean
    assert 'data-state="cancelled"' in clean
    assert 'contenteditable="false"' in clean
    assert 'role="checkbox"' in clean
    assert 'aria-checked="true"' in clean
    assert 'class="note-chart"' in clean
    assert "data-chart=" in clean
    assert 'colspan="2"' in clean


def test_note_html_sanitizer_only_allows_embedded_drawing_images():
    clean = sanitize_note_html(
        '<img src="https://evil.example/track.png"><img src="data:image/png;base64,AAAA">'
    )
    assert "https://evil.example" not in clean
    assert "data:image/png;base64,AAAA" in clean


def test_writing_assistant_builds_sections_tasks_and_summary():
    source = "اجتماع اليوم:\nمراجعة المبيعات\nإرسال التقرير\nإرسال التقرير"

    organized = organize_plain_text(source, "organize")
    tasks = organize_plain_text(source, "tasks")
    summary = organize_plain_text(source, "summary")

    assert "<h2>اجتماع اليوم</h2>" in organized
    assert "<li>مراجعة المبيعات</li>" in organized
    assert "<h2>قائمة المهام</h2>" in tasks
    assert "☐ إرسال التقرير" in tasks
    assert summary.count("إرسال التقرير") == 1
    assert html_to_text(organized).startswith("اجتماع اليوم")
