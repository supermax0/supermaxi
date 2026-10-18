"""Loopback-only fixture for the desktop's real partial-return details."""
import json
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

if os.environ.get("FINORA_RETURN_SUMMARY_UI_TEST") != "1":
    raise SystemExit("Explicit isolated test mode is required")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment
from tests.test_sales_return_posting import prepare, body, perform
from modules.sales_returns.models import SalesReturn
from models.journal_entry import JournalEntry
from utils.inventory_lots import current_lot_inventory_value
from modules.sales_returns.collections import read_default_cash_id, undated_balance
from utils.treasury_calculations import calculate_treasury_balance

generator = finance.__wrapped__()
f = shipment.__wrapped__(stock.__wrapped__(next(generator)))
if os.environ.get("FINORA_UNDATED_RETURN_UI_TEST") == "1":
    from tests.test_sales_return_legacy_collections import legacy_sale
    legacy_sale(f)
    perform(f, body(f, acknowledge_undated_collection=True))
else:
    prepare(f)
    perform(f, body(f))
running = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        global running
        status, content = 200, "application/json"
        try:
            if self.path == "/__state__":
                data = {"cash": balance(f), "bank": balance(f, "bank"),
                    "default_cash": calculate_treasury_balance(read_default_cash_id(f["branch"].id)),
                    "undated_collection": undated_balance(),
                    "inventory": current_lot_inventory_value(), "documents": SalesReturn.query.count(),
                    "journals": JournalEntry.query.count(), "total": f["order"].total, "paid": f["order"].paid_amount}
                result = json.dumps(data).encode()
            elif self.path == "/__shutdown__":
                running, result = False, b"{}"
            elif self.path.startswith(("/orders/", "/api/branch/list")):
                response = f["order_request"](self.path)
                result, status, content = response.get_data(), response.status_code, response.content_type
            else:
                result, status = b'{"error":"Isolated endpoint refused"}', 403
        except Exception:
            f["db"].session.rollback()
            import traceback
            traceback.print_exc(file=sys.stderr)
            result, status = b'{"error":"Isolated controller failed"}', 500
        self.send_response(status)
        self.send_header("Content-Type", content)
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)


server = HTTPServer(("127.0.0.1", 0), Handler)
server.timeout = .5
print("RETURN_SUMMARY_TEST_READY " + json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "orderId": f["order"].id}), flush=True)
try:
    while running:
        server.handle_request()
finally:
    server.server_close()
    generator.close()
