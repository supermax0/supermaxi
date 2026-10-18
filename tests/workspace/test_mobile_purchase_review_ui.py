from pathlib import Path


WORKSPACE_APP = Path(__file__).resolve().parents[2] / "static" / "workspace" / "js" / "workspace-app.js"


def test_mobile_purchase_editor_refreshes_through_shared_renderer():
    source = WORKSPACE_APP.read_text(encoding="utf-8")
    editor = source.split("async function appendMobilePurchaseEditor", 1)[1].split(
        "function storedMobileChatSession", 1
    )[0]

    assert 'appendMobilePurchaseResult(updatedAnalysis || analysis)' in editor
    assert 'appendMobileWorkspaceResult("purchase_invoice")' not in editor


def test_mobile_purchase_editor_has_explicit_two_step_execution():
    source = WORKSPACE_APP.read_text(encoding="utf-8")

    assert "مراجعة نهائية وتنفيذ الفاتورة" in source
    assert "نعم، نفّذ وأضف للمخزون" in source
    assert "purchaseAnalysisClient.prepare(analysis.id)" in source
    assert "purchaseAnalysisClient.approve(analysis.id)" in source
