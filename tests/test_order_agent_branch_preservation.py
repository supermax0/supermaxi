from types import SimpleNamespace


def test_agent_report_branch_selection_preserves_deducted_order():
    from utils.branch_sales import preserved_deducted_fulfillment_branch

    items = [
        SimpleNamespace(fulfillment_branch_id=11),
        SimpleNamespace(fulfillment_branch_id=11),
    ]

    preserve, branch_id = preserved_deducted_fulfillment_branch(
        items,
        inventory_is_deducted=True,
        preserve_deducted=True,
    )

    assert preserve is True
    assert branch_id == 11


def test_normal_branch_selection_is_not_preserved():
    from utils.branch_sales import preserved_deducted_fulfillment_branch

    preserve, branch_id = preserved_deducted_fulfillment_branch(
        [SimpleNamespace(fulfillment_branch_id=11)],
        inventory_is_deducted=False,
        preserve_deducted=True,
    )

    assert preserve is False
    assert branch_id is None


def test_agent_report_frontend_marks_branch_update_as_preserve_deducted():
    from pathlib import Path

    template = (Path(__file__).resolve().parents[1] / "templates" / "orders.html").read_text(
        encoding="utf-8"
    )
    start = template.index("async function submitAgentReport")
    end = template.index("function printAgentReport", start)
    assert "preserve_deducted: true" in template[start:end]
