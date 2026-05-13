class DataFetchError(Exception):
    """Data fetch error"""
    def __init__(self, message: str, *, fingerprint: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.fingerprint = fingerprint
        self.details = details or {}
