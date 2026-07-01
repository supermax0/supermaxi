class DocumentIntelligenceError(Exception):
    """Base error for document intelligence pipeline."""


class DocumentNotFoundError(DocumentIntelligenceError):
    pass


class SessionAccessError(DocumentIntelligenceError):
    pass
