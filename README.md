# Nemo Assistant · Floating Desktop AI Assistant

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-green.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue.svg">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows-0078D6.svg">
  <a href="https://github.com/SevenBT/nemo-assistant/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/SevenBT/nemo-assistant/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="GUI" src="https://img.shields.io/badge/GUI-PyQt6%20%2B%20Fluent-8A2BE2.svg">
</p>

Nemo Assistant is a lightweight desktop assistant that brings **selection actions, screenshot OCR, Markdown notes, sticky notes, tool calling, and AI chat** into one local-first workflow.

It is not another chat window waiting for you to switch context. It is a set of small desktop actions that stay close to your work: translate while reading, polish while writing, capture and understand screen content, pin a quick sticky note, and let AI call tools, read notes, or save memories when needed.

> Built with **PyQt6 + Fluent Design**. Notes, memories, configuration, and conversations are stored locally by default. API keys are saved through the system keyring instead of plaintext config files.

[Chinese documentation](docs/README.zh-CN.md)

<p align="center">
  <img src="assets/screenshots/toke.png" alt="Nemo Assistant main window" width="860">
</p>

---

## Who It Is For

- People who switch between browsers, PDFs, IDEs, and chat apps and need quick translation, explanation, or rewriting.
- Users who want a local-first AI desktop assistant instead of moving every workflow into a web app.
- People who like Markdown notes, desktop stickies, global shortcuts, and lightweight toolboxes.
- Users who want AI to safely call local tools: read and write files, search the web, manage notes, save memories, and create reminders.

---

## Core Features

### ✏️ Selection Actions

Select text in any app, and Nemo Assistant shows an action bar near the cursor. You can:

- Explain, translate, polish, or fix grammar.
- Continue asking about the selected text in a temporary session.
- Save the selection to your note library.
- Rewrite the selected text in place and replace the original selection.

Selection capture uses UIA with a clipboard fallback: it reads directly when possible, injects `Ctrl+C` only when needed, and restores the clipboard afterward to avoid disrupting your workflow.

<p align="center">
  <img src="assets/screenshots/selection-toolbar.png" alt="Selection action bar" width="760">
</p>

After clicking Explain, a lightweight result card appears near the original text, so you do not need to copy the content into a separate chat window.

<p align="center">
  <img src="assets/screenshots/selection-explain.png" alt="Selection explanation result" width="760">
</p>

Buttons in the selection action bar can be enabled or disabled in Settings. If you want to explore a selected passage in more depth, click Continue Session or New Session, and the content will be saved under Quick Sessions in the chat view.

<p align="center">
  <img src="assets/screenshots/select.png" alt="Selection button settings" width="760">
</p>

### ✂️ Screenshot + OCR

Press `Ctrl+Alt+A` to select an area of the screen, then recognize text, pin the image, or send it to AI:

- Recognize text locally with RapidOCR / ONNX Runtime.
- Pin screenshots on the desktop as temporary visual references.
- Send screenshots directly to vision-capable models.
- Use the screenshot button in the top-right corner of the chat window; the entry point matches the main chat interface.

Screenshot support is built into the floating-window workflow rather than delegated to an external tool: one shortcut handles region selection, OCR, AI analysis, saving, or pinning.

<p align="center">
  <img src="assets/screenshots/screenshot-actions.png" alt="Screenshot quick actions" width="760">
</p>

### 📝 Notes & Stickies

- **Desktop stickies**: press `Ctrl+Alt+N` to create a floating sticky note with automatic saving.
- **Notebook**: supports Markdown, folders, tags, full-text search, `[[wiki links]]`, and syntax highlighting.
- **AI collaboration**: chat can read, create, and update notes, and important information can be saved as long-term memory.

<p align="center">
  <img src="assets/screenshots/notes-and-stickies.png" alt="Notes and stickies" width="860">
</p>

### 🧰 Workshop

Built-in tools can be viewed, enabled, disabled, and managed in one place. You can also add your own Python tool scripts and let AI call them during a conversation.

Built-in tools cover:

- Web search and web page fetching.
- File reading, saving, and directory listing.
- Python code execution.
- Notes, memory, reminders, and scheduled tasks.
- Multi-model consultation.
- Clipboard read/write.

<p align="center">
  <img src="assets/screenshots/tools.png" alt="Workshop" width="860">
</p>

### 🧠 Observable Agent Runs

Nemo Assistant records the execution chain for each conversation turn, making debugging, evaluation, and review easier:

- LLM latency, token usage, and input/output statistics.
- Tool call records.
- Security audit details.
- Eval samples that can be saved as test cases.

<p align="center">
  <img src="assets/screenshots/traces.png" alt="Traces and evaluation" width="760">
</p>

---

## Models & API

Models are connected through **LiteLLM**, with support for OpenAI, Anthropic, DeepSeek, Gemini, and OpenAI-compatible APIs. Each model can have its own `api_base`, vision capability setting, max tokens, temperature, and other parameters.

After the first launch, open **Settings → API**, add a model, and set it as the default to enable AI features across chat and desktop actions.

Web search tools can use DuckDuckGo without an API key. Bing, Tavily, Brave, and Bocha search can be enabled from **Settings → Tools** by selecting a provider and saving its API key in the system keyring.

<p align="center">
  <img src="assets/screenshots/api.png" alt="API and model settings" width="760">
</p>

> App configuration is stored in `config/app_config.json` and is not committed. It is generated automatically on first launch; see [`config/app_config.example.json`](config/app_config.example.json) for an example.

---

## Shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+Alt+Q` | Open quick ask |
| `Ctrl+Alt+A` | Screenshot + OCR |
| `Ctrl+Alt+N` | Create desktop sticky note |
| `Ctrl+Alt+Space` | Show / hide main window |

Shortcuts can be changed in **Settings → Hotkeys**. The selection action bar appears automatically after text is selected.

---

## Quick Start

> **Windows only for now.** Nemo Assistant relies on Windows-specific libraries
> (`pywin32`, `uiautomation`, global hotkeys), and CI runs on Windows only.
> macOS / Linux are not supported yet.

### Download (recommended)

Grab the latest packaged build from the [Releases](https://github.com/SevenBT/nemo-assistant/releases)
page — no Python setup required. Unzip and run the executable.

### Run from source

Requires Python 3.10+.

```bash
git clone https://github.com/SevenBT/nemo-assistant.git
cd nemo-assistant
pip install .
python main.py
```

For development:

```bash
pip install -e ".[dev]"
python main.py
```

For reproducible development with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --extra dev
uv run pytest -q
uv run python main.py
```

On Windows, you can also run:

```bat
run.bat
```

---

## Project Structure

Nemo Assistant uses a layered architecture: desktop tools have independent implementations, while the AI layer connects through a unified tool protocol.

```text
main.py                  Entry: dependency checks → crash logs → Qt startup
│
├── app/ui/              UI layer, with dedicated controllers for key features
│   ├── main_window          Frameless floating main window (chat / notes / workshop)
│   ├── selection_controller Selection capture + action bar
│   ├── screenshot_*         Screenshot overlay / OCR / pinned images
│   ├── sticky_note_*        Desktop sticky notes
│   ├── text_actions         Explain / translate / polish / write back to selection
│   └── components/          Reusable components (message bubbles, Markdown editor, etc.)
│
├── app/core/            Core business layer
│   ├── llm_gateway          Unified LLM gateway (LiteLLM / rate limit / retry / streaming)
│   ├── agent_loop           Agent state machine (prepare → stream → execute → feedback → finalize)
│   ├── note_manager         Notes / stickies / todo storage (SQLite)
│   ├── memory_manager       Long-term memory
│   ├── consolidator / dream Conversation compression and background memory consolidation
│   ├── scheduler            Scheduled tasks (APScheduler)
│   └── session_manager      Multi-session management
│
├── app/tools/           Tool system
│   ├── registry             Registration / discovery / execution / error classification and retry
│   ├── script_adapter       Dynamic loading for user-defined Python tools
│   └── *.py                 Built-in tools (search, fetch, files, shell, notes, memory, etc.)
│
└── app/models/          Data models (Message / Session / Note / Memory)
```

### Agent Loop

Each session runs in its own `QThread`, so conversations do not block each other. One turn follows this lifecycle:

```text
prepare → stream → execute → feedback → finalize
prompt     stream     run tools        feed back   persist session
```

Runs can be cancelled at any time, and failures can recover from checkpoints.

### Tool System

All tools inherit from `BuiltinTool`, declare `name / description / parameters / execute`, and are managed by `ToolRegistry`. They are exported in OpenAI Functions format. Tool sources include:

1. **Built-in tools**: shipped with the app.
2. **User scripts**: dynamically loaded after adding `tool.py` to the tools directory.
3. **AI-generated tools**: describe a need and let the model help generate tool code.

---

## Tech Stack

- **GUI**: PyQt6 + [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
- **Model access**: LiteLLM
- **Storage**: SQLite (notes, memory) + JSON (sessions, config)
- **OCR**: RapidOCR (ONNX Runtime, local recognition)
- **Scheduling**: APScheduler
- **Other**: keyring (secrets), keyboard (global hotkeys), BeautifulSoup (web parsing)

---

## Packaging

```bat
build.bat
```

The script invokes PyInstaller and uses `Nemo_Assistant.spec` to build the desktop app.
Before publishing a binary release, review [docs/en/release-checklist.md](docs/en/release-checklist.md).

---

## Design Notes

Some implementation trade-offs from building a frameless floating window and cross-app desktop workflows are documented in [`docs/en/development-notes.md`](docs/en/development-notes.md):

- Dragging uses `startSystemMove()`; resizing uses a QApplication event filter + `setGeometry` to avoid ghost borders from `startSystemResize()`.
- Selection capture may inject `Ctrl+C`, which can accidentally trigger SIGINT in terminals, so the outer layer handles `KeyboardInterrupt` and restores the clipboard.
- FluentWindow reapplies internal styles, so QTextEdit foreground color is enforced in `focusInEvent`.
- Embedded-panel confirmation dialogs use native `QMessageBox` instead of qfluentwidgets `MessageBox`, because `MaskDialogBase` expects a top-level window.

---

## Credits

The wiki-link parser, find/replace, and Markdown syntax highlighting in the note editor are ported / adapted from [noteration](https://github.com/lilamr/noteration) (MIT). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for full third-party license notices.

---

## License

[MIT](LICENSE)

This project uses third-party open-source code. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for copyright and license notices.
