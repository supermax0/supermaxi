"""Return relationships must exist before concurrent request queries start."""
import subprocess
import sys
from pathlib import Path


def test_finance_startup_registers_complete_return_graph():
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
from flask import Flask
from modules.finance import init_finance
init_finance(Flask('return_model_startup_test'))
assert 'modules.sales_returns.models' in sys.modules, 'Return models still load lazily'
# The app imports DeliveryAgent separately before handling requests.
from models.delivery_agent import DeliveryAgent
from sqlalchemy.orm import configure_mappers
from modules.sales_returns.models import (
    SalesReturnOrigin, SalesReturn, SalesReturnLine, SalesReturnCost, SalesReturnFunding,
)
configure_mappers()
assert SalesReturn.lines.property.mapper.class_ is SalesReturnLine
assert SalesReturnLine.document.property.mapper.class_ is SalesReturn
assert SalesReturnLine.costs.property.mapper.class_ is SalesReturnCost
assert SalesReturnCost.line.property.mapper.class_ is SalesReturnLine
assert SalesReturn.origin.property.mapper.class_ is SalesReturnOrigin
assert SalesReturnFunding.__mapper__.configured
"""],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
