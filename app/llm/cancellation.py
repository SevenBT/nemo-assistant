"""Compatibility exports for the shared cancellation primitive."""
from app.runtime.cancellation import CancellationToken, _close_resource

__all__ = ["CancellationToken", "_close_resource"]
