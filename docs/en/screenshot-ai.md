# Screenshot AI Flow

> [中文](../zh/screenshot-ai.md)

Nemo Assistant has two independent screenshot paths.

## Local OCR

Local OCR is used when the user wants text from an image. It runs through RapidOCR / ONNX Runtime and does not require an LLM provider.

Typical use:

1. Press `Ctrl+Alt+A`.
2. Select a screen region.
3. Choose OCR from the screenshot actions.
4. Use or copy the recognized text.

## Vision Model Analysis

Vision analysis is used when the user wants the selected model to inspect the image itself. This requires:

- A configured LiteLLM model.
- A provider API key saved in the system keyring.
- Vision capability enabled or auto-detected for the selected model.

Typical use:

1. Press `Ctrl+Alt+A`.
2. Select a screen region.
3. Choose the AI/vision action.
4. Nemo Assistant sends the image attachment to the active chat turn.

## Why They Are Separate

OCR and vision solve different problems. OCR extracts text locally and is cheaper, faster, and private by default. Vision is better for layouts, diagrams, UI screenshots, and images where text extraction is not enough.
