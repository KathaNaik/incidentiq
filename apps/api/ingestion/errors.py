class IngestionError(RuntimeError):
    """A dataset could not be downloaded, or violates an assumption we depend on.

    Raised rather than warned: a partially valid corpus silently becomes a misleading
    evaluation result later.
    """
