# Nemo Assistant v0.1.0

First public release. Nemo Assistant is a local-first floating desktop AI
assistant that stays close to your work: select text to translate or explain,
capture and OCR the screen, keep Markdown notes and desktop stickies, and let
the assistant call local tools when it needs to.

> **Windows only.** Requires Windows 10/11. No Python setup needed if you use
> the packaged download below.

## Highlights

- **Selection actions** — Select text in any app to get an action bar for
  explain, translate, polish, fix grammar, rewrite-in-place, or continue in a
  chat session. Reads selections via UIA with a clipboard fallback that
  restores your clipboard afterward.
- **Screenshot + OCR** — `Ctrl+Alt+A` to grab a region, then recognize text
  locally (RapidOCR / ONNX Runtime), pin it to the desktop, or send it to a
  vision model.
- **Notes & stickies** — Desktop sticky notes (`Ctrl+Alt+N`) plus a Markdown
  notebook with folders, tags, full-text search, `[[wiki links]]`, and syntax
  highlighting. The assistant can read and update notes.
- **Tool-calling agent** — Built-in tools for web search/fetch, file
  read/write, Python execution, notes, memory, reminders, scheduled tasks,
  multi-model consultation, and clipboard. Add your own Python tool scripts.
- **Observable runs** — Every turn records latency, token usage, tool calls,
  and security audit details, and can be saved as eval samples.
- **Bring your own models** — Connect OpenAI, Anthropic, DeepSeek, Gemini, and
  any OpenAI-compatible API through LiteLLM. API keys are stored in the system
  keyring, not plaintext config. Web search works keyless via DuckDuckGo.

## Install

**Download (recommended):** grab the packaged Windows build attached to this
release, unzip, and run the executable. No Python required.

**From source:**

```bash
git clone https://github.com/SevenBT/nemo-assistant.git
cd nemo-assistant
pip install .
python main.py
```

Requires Python 3.12+. See the README for the uv-based development workflow.

## First run

Open **Settings → API**, add a model, and set it as the default to enable AI
features. Configuration is stored locally in `config/app_config.json` (created
on first launch) and is never committed.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+Alt+Q` | Open quick ask |
| `Ctrl+Alt+A` | Screenshot + OCR |
| `Ctrl+Alt+N` | Create desktop sticky note |
| `Ctrl+Alt+Space` | Show / hide main window |

## Notes

- Third-party code (note editor wiki-links, find/replace, Markdown
  highlighting) is adapted from [noteration](https://github.com/lilamr/noteration)
  (MIT). See `THIRD_PARTY_NOTICES.md`.
- Reproducible builds and CI use a pinned `uv.lock`; repository consistency
  checks guard metadata, Markdown links, and PyInstaller hidden imports.

**License:** MIT
