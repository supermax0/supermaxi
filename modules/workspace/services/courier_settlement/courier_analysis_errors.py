class CourierAnalysisError(Exception):
    pass


class CourierAnalysisNotFoundError(CourierAnalysisError):
    pass


class CourierAnalysisAccessError(CourierAnalysisError):
    pass


class CourierNoDocumentError(CourierAnalysisError):
    pass
