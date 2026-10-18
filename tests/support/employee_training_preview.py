"""Loopback-only, synthetic preview of the real desk templates. No database or external calls.

Run with: py tests/support/employee_training_preview.py
Used by scripts/capture_employee_training.mjs and the academy browser checks.
This fixture is never registered in the production app.
"""
from pathlib import Path

from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).resolve().parents[2]
app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
app.config["SECRET_KEY"] = "synthetic-local-training-preview-only"
VIEWER = {"id": 999, "name": "موظف التدريب", "is_admin": False}
ACCOUNT = dict(name=VIEWER["name"], initial="م", avatar="", active=True,
               role_label="موظف تدريب", username="training.employee", employee_no="999",
               pay_title="تدريبي", pay_note="بيانات توضيحية", salary="—", commission="—",
               orders="0", sales="—", details=[], perms=["مكتب الموظف"])
PRODUCT = dict(id=99001, name="منتج تدريبي", sku="TRAIN-01", price=25000,
               price_label="25,000 د.ع", description="مواصفات توضيحية للتدريب فقط. راجع كتالوج شركتك للمعلومات الفعلية.",
               colors=[{"name": "أسود"}, {"name": "أبيض"}], image_url="")
CUSTOMER = dict(id=99001, name="زبون التدريب", phone="07700000000", city="بغداد", address="عنوان تدريبي — قرب نقطة دالة")
THREAD = dict(thread_id="training-thread", external_page_id="training-page", customer_psid="training-customer",
              customer_name="زبون التدريب", customer_initials="ز", page_name="صفحة التدريب", preview="مرحباً، شنو سعر المنتج ومواصفاته؟",
              status="WAITING_REPLY", status_label="بانتظار الرد", unread_count=1, time_label="الآن")


@app.get("/employee-desk")
def desk():
    return render_template("employee_desk/app.html", viewer=VIEWER, account=ACCOUNT)


@app.get("/employee-desk/login")
def login():
    return render_template("employee_desk/login.html", tenant_slug="training", error="")


@app.get("/employee-desk/training")
def training():
    return render_template("employee_desk/training.html", viewer=VIEWER, training_scope="synthetic-preview:999", preview_only=True)


@app.route("/api/<path:path>", methods=["GET", "POST"])
def fixture_api(path):
    if path == "employee-desk/inbox":
        return jsonify(ok=True, messages=[THREAD], status_counts={"ALL": 1, "WAITING_REPLY": 1, "LATE": 0})
    if path == "employee-desk/alerts":
        return jsonify(ok=True, unread=0)
    if path in ("employee-desk/products", "employee-desk/training/products"):
        term = request.args.get("q", "").strip()
        rows = [PRODUCT] if not term or term in PRODUCT["name"] or term in PRODUCT["sku"] else []
        return jsonify(ok=True, products=rows)
    if path == "employee-desk/customers":
        return jsonify(ok=True, customer=CUSTOMER, customers=[CUSTOMER])
    if path.startswith("employee-desk/customers/"):
        return jsonify(ok=True, orders=[])
    if path == "facebook-monitor/thread":
        return jsonify(ok=True, thread={**THREAD, "messages": [dict(direction="in", text=THREAD["preview"], time_label="10:30")]})
    if path == "employee-desk/quick-replies":
        return jsonify(ok=True, replies=[dict(id=1, text="أهلاً وسهلاً، شلون نكدر نساعدك؟")])
    if path == "facebook-routing/me":
        return jsonify(ok=True, accept_messages=True)
    if path == "facebook-routing/teammates":
        return jsonify(ok=True, employees=[])
    if request.method == "POST":
        # Synthetic preview actions are confined to this process and never persisted.
        return jsonify(ok=True, message={"direction": "out", "text": "رد تدريبي"}, invoice_id="TRAINING")
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5099, debug=False, use_reloader=False)
