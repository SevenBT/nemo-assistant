# Development Notes

> [中文](../zh/development-notes.md)

These notes capture implementation trade-offs that are useful for contributors. They intentionally avoid local assistant rules or maintainer-only workflow preferences.

## Frameless Window

- Window dragging uses `startSystemMove()` instead of Python-calculated offsets.
- Resizing uses a QApplication-level event filter plus `setGeometry()` to avoid ghost borders from `startSystemResize()`.
- Empty edge values should use `Qt.Edge(0)`.
- `QSizeGrip` is not used because it does not work reliably in this frameless setup.

## Selection Capture

- Selection capture prefers UI Automation and falls back to a temporary clipboard copy.
- The clipboard fallback injects `Ctrl+C`, then restores the previous clipboard content.
- During development, global `Ctrl+C` can accidentally reach the launching terminal, so the capture layer handles `KeyboardInterrupt` and keeps the app alive.

## Theming

- FluentWindow may reapply internal styles after widgets are constructed.
- QTextEdit foreground colors sometimes need reinforcement when focus changes.
- QPlainTextEdit does not support `setTextColor`; use current character format merging instead.
- Theme-aware highlights should use translucent overlays rather than one fixed color.

## Embedded Dialogs

Embedded settings pages use native `QMessageBox` for confirmations. qfluentwidgets `MessageBox` expects a top-level parent and can block interactions when used inside stacked panels.

## Drag Reordering

When two Qt list widgets behave differently, compare their event overrides before adding more painting or drag logic. Prefer native `InternalMove` and persist the result from model row movement when possible.

## Screenshot AI

Screenshot OCR and screenshot-to-model vision are separate paths:

- OCR is local and extracts text from pixels.
- Vision sends image content to the selected model, if the model is configured as vision-capable.

See [screenshot-ai.md](screenshot-ai.md) for the dedicated screenshot AI flow.
