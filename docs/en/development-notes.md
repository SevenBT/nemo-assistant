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

## Lightweight Model Transport

- All providers use one httpx transport; LiteLLM, the OpenAI SDK and SDK background warmup are removed. There are no model probe requests at startup. DNS/TLS and server latency can still affect a first request.
- Explicit codecs handle Chat Completions, Responses, Claude Messages and Cohere Chat v2. Provider identity selects the default; a model entry can override api_protocol. Custom unknown providers require api_base. Azure uses its resource /openai/v1 endpoint and deployment name.
- Existing LiteLLM-named config fields and keyring slots are storage aliases only. They do not select a second runtime. The model editor preserves extra fields and offers a protocol selector.
- Pools are owned by gateways and closed explicitly. One background asyncio loop per pool allows cancellation while waiting for headers, receiving keepalives or reading data, without closing other requests. Phase timeouts and optional total deadlines are separate.
- Validate terminal events and every complete tool call before exposing executable calls. Broken JSON, conflicting IDs/signatures, duplicate IDs, truncated tools and missing terminal events fail closed. Once text, reasoning or tool fragments arrive, the gateway does not retry the request or switch protocols.
- Preserve Gemini tool signatures, Claude signed content blocks and Responses reasoning/output items through Agent iterations and persisted Message history. Image content and tool results survive translation; unsupported content raises an error rather than disappearing.
- Usage remains unknown when absent; partial fields do not imply zero. No local pricing lookup is performed. Errors are sanitized before UI/log persistence. Logs include provider/model/protocol/profile revision, without prompts or keys.
- Offline wire contracts, SDK-forbidden subprocesses, loopback cancellation tests and independent evaluation cover this implementation. These are not live certification for every supplier/model. See [the implementation design](../design/shared-lightweight-provider-design.md).

## Theming

- FluentWindow may reapply internal styles after widgets are constructed.
- QTextEdit foreground colors sometimes need reinforcement when focus changes.
- QPlainTextEdit does not support `setTextColor`; use its Text palette and syntax highlighter. Changing character formats on focus can emit `textChanged` and incorrectly update note timestamps.
- Theme-aware highlights should use translucent overlays rather than one fixed color.
- Pair foreground and background colors for normal, hover, pressed and disabled states. Use `theme_text_color` for colored text and `contrasting_text` for filled buttons; an accent suitable for decoration may be unreadable as text.
- Screenshot capture chrome and its AI menu share a fixed dark palette. OCR follows the application theme. Native menus use `menu_stylesheet`, and native status labels use `set_text_role` to follow later theme changes.

## Embedded Dialogs

Embedded settings pages use native `QMessageBox` for confirmations. qfluentwidgets `MessageBox` expects a top-level parent and can block interactions when used inside stacked panels.

## Drag Reordering

When two Qt list widgets behave differently, compare their event overrides before adding more painting or drag logic. Prefer native `InternalMove` and persist the result from model row movement when possible.

## Screenshot AI

Screenshot OCR and screenshot-to-model vision are separate paths:

- OCR is local and extracts text from pixels.
- Vision sends image content to the selected model, if the model is configured as vision-capable.

See [screenshot-ai.md](screenshot-ai.md) for the dedicated screenshot AI flow.
