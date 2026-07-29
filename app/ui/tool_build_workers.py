"""Background workers for generated-tool generation and build operations."""
from __future__ import annotations

from typing import Protocol

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.llm_gateway import CancellationToken
from app.core.tool_build import BuildReview, InstallResult, ToolPermission
from app.core.tool_generator import ModelOverride, stream_generate


class ToolBuildServiceProtocol(Protocol):
    """UI-facing subset of the staged build service."""

    def stage(
        self, requirement: str, manifest_text: str, script_text: str
    ) -> BuildReview: ...

    def review(
        self,
        build_id: str,
        approved_permissions: frozenset[ToolPermission],
        *,
        acknowledged_overrides: frozenset[str] = frozenset(),
    ) -> BuildReview: ...

    def install(
        self,
        build_id: str,
        approved_permissions: frozenset[ToolPermission],
        *,
        overwrite: bool,
        acknowledged_overrides: frozenset[str] = frozenset(),
    ) -> InstallResult: ...


class _BuildWorker(QThread):
    """Run one filesystem/AST/install service operation outside the GUI thread."""

    result_ready = pyqtSignal(int, str, object)
    error = pyqtSignal(int, str, str)

    def __init__(
        self,
        service: ToolBuildServiceProtocol,
        token: int,
        operation: str,
        arguments: tuple[object, ...],
    ) -> None:
        super().__init__()
        self._service = service
        self._token = token
        self._operation = operation
        self._arguments = arguments

    def run(self) -> None:
        try:
            if self._operation == "stage_review":
                requirement, manifest_text, script_text = self._arguments
                staged = self._service.stage(requirement, manifest_text, script_text)
                result = self._service.review(staged.build_id, frozenset())
            elif self._operation == "review":
                build_id, approvals, overrides = self._arguments
                result = self._service.review(
                    build_id, approvals, acknowledged_overrides=overrides
                )
            elif self._operation == "install":
                build_id, approvals, overwrite, overrides = self._arguments
                result = self._service.install(
                    build_id,
                    approvals,
                    overwrite=bool(overwrite),
                    acknowledged_overrides=overrides,
                )
            else:
                raise ValueError("INVALID_INPUT")
        except Exception:
            self.error.emit(self._token, self._operation, "VALIDATION_FAILED")
            return
        self.result_ready.emit(self._token, self._operation, result)


class _GenerateWorker(QThread):
    """Run one generation request outside the GUI thread."""

    chunk = pyqtSignal(str)
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self, requirement: str, model_override: ModelOverride | None = None
    ) -> None:
        super().__init__()
        self._requirement = requirement
        self._model_override = model_override
        self._cancel_token = CancellationToken()
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True
        self._cancel_token.cancel()

    def run(self) -> None:
        full = ""
        try:
            for event in stream_generate(
                self._requirement,
                self._model_override,
                cancel_token=self._cancel_token,
            ):
                if self._stopped:
                    return
                if event["type"] == "text":
                    delta = event["delta"]
                    full += delta
                    self.chunk.emit(delta)
                elif event["type"] == "error":
                    self.error.emit(event["message"])
                    return
            if not self._stopped:
                self.result_ready.emit(full)
        except Exception as exc:
            if not self._stopped:
                self.error.emit(str(exc))
