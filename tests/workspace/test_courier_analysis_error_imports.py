from modules.workspace.services.courier_settlement import (
    courier_readonly_analysis_service as service_module,
)
from modules.workspace.services.courier_settlement.courier_analysis_errors import (
    CourierAnalysisNotFoundError,
)


def test_readonly_service_imports_not_found_error():
    assert (
        service_module.CourierAnalysisNotFoundError
        is CourierAnalysisNotFoundError
    )
