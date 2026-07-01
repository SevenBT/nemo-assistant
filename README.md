# Nemo Assistant · 桌面浮窗助手

把划词翻译、截图取词、桌面便签、Markdown 笔记和 AI 对话，收进一个常驻桌面的轻量浮窗里。

它不是又一个“什么都想做”的聊天框，而是一个更贴近桌面工作流的本地助手：读文档时顺手翻译，写东西时随手润色，看到内容时截图取词，想到事情时贴张便签，必要时再让 AI 把这些工具串起来。

基于 **PyQt6 + Fluent Design** 构建，强调本地优先。笔记、记忆、配置等数据默认保存在你自己的电脑上。

---

## 为什么做它

通用 AI 助手和编码 agent 已经很强，但很多日常场景并不需要一个更复杂的对话框，而是需要一组**不打断当前工作的桌面小动作**：

> 选中一句话就解释或翻译；框选一块屏幕就 OCR；想到什么立刻贴到桌面；聊天时让 AI 顺手读取笔记、记录记忆或调用工具。

这些能力单独看并不稀奇，市面上也有很多划词、截图、笔记和便签软件。Nemo Assistant 的重点在于**把它们做成一个整体**：

- **核心工具内建**：划词捕获、截图 overlay、OCR、Markdown 编辑器、SQLite 存储等基础能力都在应用内部实现，不依赖外部软件拼接。
- **全局快捷键直达**：在任意应用里划词、截图、贴便签，浮窗就地响应；做完即走，尽量不抢焦点、不打断上下文。
- **AI 作为连接层**：AI 不是唯一主角，而是把这些内建工具粘合起来的协作层。它可以解释选中文字、处理截图、读写笔记、整理记忆，或在聊天中按需调用工具。

产品路线很简单：**先把常用桌面工具做扎实，再让 AI 恰到好处地参与其中。**

---

## 核心特色

### ✏️ 划词即用

在任意应用中选中文字，屏幕角落会出现浮标。点一下即可：

- 解释、翻译、润色、订正语法
- 基于选中文本继续追问对话
- 将翻译、润色或订正结果一键写回原处，覆盖原选区

选区捕获采用 UIA + 剪贴板兜底的多态分流：优先直接读取，失败时才注入 `Ctrl+C`，并在结束后还原剪贴板。取词逻辑由项目内部实现，不依赖第三方划词软件。

### ✂️ 截图 + OCR

按下 `Ctrl+Alt+A` 框选屏幕，即可：

- 使用 RapidOCR / ONNX 在本地识别文字
- 将截图贴在桌面上
- 直接把截图发送给 AI 提问

截图不是外部工具的简单调用，而是完整集成在浮窗工作流里：一个快捷键完成框选、识别、贴图或发送给 AI。

### 📝 笔记 & 便签

- **桌面便签**：按 `Ctrl+Alt+N` 新建浮动便签，内容自动保存
- **笔记本**：支持 Markdown、文件夹、标签、全文搜索、`[[双链]]` 跳转和语法高亮

笔记系统是内部集成模块，与聊天、记忆和工具调用共享同一套数据基础，AI 可以直接读取和写入相关内容。

---

## 其他能力

| | 功能 | 说明 |
|---|---|---|
| 💬 | **对话调用工具** | 聊天时可按需调用搜索、网页抓取、文件读写、脚本执行、笔记、记忆和提醒等工具 |
| 🧰 | **工具工坊** | 内置多种工具；也可以放入自己的 Python 脚本，或让 AI 辅助生成新工具 |
| 🧠 | **长期记忆** | 记录跨会话的重要信息，并在后台自动整合 |
| ⏰ | **定时任务** | 支持一次性提醒和周期性任务（APScheduler） |
| 🪟 | **浮窗体验** | 支持边缘吸附隐藏、悬停展开、置顶和托盘驻留 |

---

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Alt+Q` | 唤起快速提问 |
| `Ctrl+Alt+A` | 截图 + OCR |
| `Ctrl+Alt+N` | 新建桌面便签 |
| `Ctrl+Alt+H` | 显示 / 隐藏主窗口 |

快捷键可在 **设置 → 快捷键** 中修改；划词浮标会在选中文字后自动出现。

---

## 快速开始

需要 Python 3.10+。

```bash
git clone <repo-url>
cd assistant
pip install -r requirements.txt
python main.py
```

首次启动后，进入 **设置 → API** 添加模型并设为默认，即可启用聊天与各模块的 AI 功能。

模型通过 **LiteLLM** 统一接入，支持 OpenAI、Anthropic、DeepSeek、Gemini 等服务，也支持兼容 OpenAI 接口的模型。每个模型都可以单独配置 `api_base`。API Key 通过系统 keyring 安全存储，不写入明文配置。

> 应用配置存放在 `config/app_config.json`（不入库），首次启动会自动生成；字段示例可参考 `config/app_config.example.json`。

---

## 架构

Nemo Assistant 采用清晰分层：桌面工具拥有独立实现，AI 层通过统一工具协议接入。

```
main.py                  入口：依赖检查 → 崩溃日志 → 启动 Qt
│
├── app/ui/              UI 层（特色功能都有独立控制器）
│   ├── main_window          无边框浮窗主窗口（聊天 / 笔记 / 工坊）
│   ├── selection_controller 划词捕获 + 浮标
│   ├── screenshot_*         截图 overlay / OCR / 贴图
│   ├── sticky_note_*        桌面便签
│   ├── text_actions         解释 / 翻译 / 润色 / 写回选区
│   └── components/          可复用组件（消息气泡、Markdown 编辑器等）
│
├── app/core/            核心业务层
│   ├── llm_gateway          统一 LLM 网关（LiteLLM / 限流 / 重试 / 流式）
│   ├── agent_loop           Agent 状态机（prepare → stream → execute → feedback → finalize）
│   ├── note_manager         笔记 / 便签 / 待办存储（SQLite）
│   ├── memory_manager       长期记忆
│   ├── consolidator / dream 会话压缩与后台记忆整合
│   ├── scheduler            定时任务（APScheduler）
│   └── session_manager      多会话管理
│
├── app/tools/           工具系统
│   ├── registry             注册 / 发现 / 执行 / 错误分类与重试
│   ├── script_adapter       动态加载用户自定义 Python 工具
│   └── *.py                 内置工具（搜索、抓取、文件、命令、笔记、记忆等）
│
└── app/models/          数据模型（Message / Session / Note / Memory）
```

### Agent 循环

每个会话运行在独立的 `QThread` 上，互不阻塞。一个 turn 的生命周期：

```
prepare → stream → execute → feedback → finalize
组装提示词  流式输出   并发执行工具  结果回灌   持久化会话
```

支持随时取消；发生异常后可从 checkpoint 恢复。

### 工具系统

所有工具继承 `BuiltinTool`，声明 `name / description / parameters / execute`，由 `ToolRegistry` 统一管理，并导出为 OpenAI Functions 格式。工具来源包括：

1. **内置工具**：随应用分发
2. **用户脚本**：在工具目录放入 `tool.py` 后动态加载
3. **AI 生成**：描述需求，让模型辅助生成工具代码

---

## 技术栈

- **GUI**：PyQt6 + [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
- **模型接入**：LiteLLM
- **存储**：SQLite（笔记、记忆）+ JSON（会话、配置）
- **OCR**：RapidOCR（ONNX Runtime，本地识别）
- **调度**：APScheduler
- **其他**：keyring（密钥）、keyboard（全局快捷键）、BeautifulSoup（网页解析）

---

## 打包

```bash
build.bat        # 调用 PyInstaller（AI_Agent.spec）
```

---

## 设计取舍

无边框浮窗与多工具融合过程中踩过的一些坑，已经沉淀为当前实现方案（详见 `CLAUDE.md`）：

- 拖动使用 `startSystemMove()`；调整大小使用 QApplication 事件过滤器 + `setGeometry`，避免 `startSystemResize()` 的幽灵边框
- 划词时注入 `Ctrl+C` 可能误触发控制台 SIGINT，需要在外层兜底 `KeyboardInterrupt` 并还原剪贴板
- FluentWindow 会重新应用内部样式，QTextEdit 前景色需要在 `focusInEvent` 中强制设置
- 嵌入式面板的确认对话框使用原生 `QMessageBox`，不用 qfluentwidgets 的 `MessageBox`，因为 `MaskDialogBase` 要求顶层窗口

---

## 致谢

笔记编辑器的 wiki 双链解析、查找替换、Markdown 语法高亮等代码移植 / 改编自 [noteration](https://github.com/lilamr/noteration)（MIT）。完整的第三方许可证声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## License

[MIT](LICENSE)

本项目使用了第三方开源代码，其版权与许可证声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
