class TelemetryError(Exception):
    """Raised when the cursor-flow aggregate store fails. Mirrors
    backend/main_block/reasoning_engine/runtime/exceptions.py's StateStoreError pattern -- a typed boundary
    per package, not a bare Exception leaking sqlite's own error type upward.
    """
