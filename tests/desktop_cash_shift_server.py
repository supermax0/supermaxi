"""Loopback-only real finance backend for Electron; never uses an existing tenant."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

if os.environ.get("FINORA_CASH_SHIFT_UI_TEST") != "1":
    raise SystemExit("Explicit isolated test mode is required")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
from tests.test_finance_operations import finance, voucher, balance, review_opening
from modules.finance.common import FinanceError
from modules.finance.models import FinanceCashShift, FinanceControlSnapshot
from models.journal_entry import JournalEntry

generator = finance.__wrapped__()
f = next(generator)
if os.environ.get("FINORA_FINANCIAL_CONTROL_UI_TEST") == "1":
    review_opening(f)
running = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def serve(self):
        global running
        status, content = 200, "application/json"
        try:
            if self.path == "/__state__":
                data = {"cash": balance(f), "journals": JournalEntry.query.count(),
                    "shifts": FinanceCashShift.query.count(), "closed": FinanceCashShift.query.filter_by(status="closed").count(),
                    "snapshots": FinanceControlSnapshot.query.count()}
            elif self.path == "/__shutdown__":
                running, data = False, {}
            elif self.path == "/__expense__":
                data = voucher(f, "expense", 100_000, party_name="مصروف اختبار الوردية")
            elif self.path == "/__capital__":
                data = voucher(f, "capital", 100_000, party_name="تمويل مالك اختبار")
            elif self.path == "/__draw__":
                data = voucher(f, "owner_draw", 20_000, party_name="سحب مالك اختبار")
            elif self.command == "POST" and self.path == "/api/finance/commands":
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                operation, key = data.pop("operation"), data.pop("idempotency_key")
                data = {"success": True, "data": f["call"](operation, data, key)}
            elif self.command == "GET" and self.path.startswith(("/api/finance/", "/accounts/finance/cash-shifts/", "/accounts/finance/control/")):
                response = f["get"](self.path)
                if isinstance(response, str):
                    body, content = response.encode("utf-8"), "text/html; charset=utf-8"
                else:
                    body, status, content = response.get_data(), response.status_code, response.content_type
                self.reply(body, status, content)
                return
            else:
                data, status = {"error": "Isolated endpoint refused"}, 403
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        except FinanceError as error:
            f["db"].session.rollback()
            body = json.dumps({"success": False, "error": str(error), "code": error.code}, ensure_ascii=False).encode("utf-8")
            status = error.status
        except Exception:
            import traceback
            f["db"].session.rollback()
            traceback.print_exc()
            body, status = b'{"error":"Isolated backend failed"}', 500
        self.reply(body, status, content)

    def reply(self, body, status, content):
        self.send_response(status)
        self.send_header("Content-Type", content)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = serve
    do_POST = serve


server = HTTPServer(("127.0.0.1", 0), Handler)
server.timeout = .5
print("CASH_SHIFT_TEST_READY " + json.dumps({"url": f"http://127.0.0.1:{server.server_port}"}), flush=True)
try:
    while running:
        server.handle_request()
finally:
    server.server_close()
    generator.close()
