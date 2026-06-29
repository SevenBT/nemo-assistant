# Assistant · 桌面 AI 助手浮窗

常驻屏幕角落的个人 AI 助手。**划一段词、贴一张便签、框一块屏幕、说一句话让它替你干活** —— 划词解释翻译、截图取词、随手记录、对话即可调用工具完成日常任务。

基于 PyQt6 + Fluent Design 的无边框透明浮窗，本地优先，数据存在你自己的电脑上。

> 不是 IDE 里的编码 agent，而是一直待在桌面、随手可达的生活与工作助手。

---

## 它能做什么

| | 功能 | 说明 |
|---|---|---|
| 💬 | **对话即调用工具** | 和助手聊天，它会自己决定调用搜索、读写文件、执行命令、记笔记、定提醒等工具来完成任务 |
| ✏️ | **划词即用** | 在任意软件里选中文字，浮标一点即可**解释 / 翻译 / 润色 / 订正语法 / 存便签**，或追问对话；润色、翻译、订正的结果可一键**写回原处覆盖选区** |
| 📌 | **桌面便签** | `Ctrl+Alt+N` 随手贴一张浮动便签到屏幕上，内容自动存档 |
| ✂️ | **截图 + OCR** | `Ctrl+Alt+A` 框选截图，一键 OCR 取词、贴图到桌面、或直接发给 AI |
| 📝 | **笔记管理** | Markdown 笔记，支持文件夹、标签、全文搜索、`[[双链]]` 跳转 |
| 🧰 | **工具工坊** | 内置 18+ 工具；也能让 AI 帮你**自动生成**新工具，或放入自己的 Python 脚本 |
| 🧠 | **长期记忆** | 助手会记住跨会话的关键信息，后台自动整合（"做梦"机制） |
| ⏰ | **定时任务** | 让助手定时提醒你、或周期性执行某个任务 |
| 🪟 | **浮窗体验** | 边缘吸附隐藏、鼠标悬停展开、置顶、托盘驻留，不打扰 |

---

## 截图

> _（建议在此处放 2-3 张实际界面截图：浮窗聊天、截图 OCR、桌面便签）_

---

## 快速开始

需要 Python 3.10+。

```bash
git clone <repo-url>
cd assistant
pip install -r requirements.txt
python main.py
```

首次启动后，进入 **设置 → API** 添加模型即可开始。

所有模型统一通过 **LiteLLM** 接入：可添加任意 LiteLLM 支持的模型 —— OpenAI、Anthropic、DeepSeek、Gemini 等各家，以及任何兼容 OpenAI 接口的服务（每个模型可单独填写 `api_base`）。选择一个模型设为默认即可对话。

API Key 通过系统 keyring 安全存储，不写入明文配置。

> 应用配置存放在 `config/app_config.json`（不入库）。可参考 `config/app_config.example.json` 了解可用字段，应用首次启动会自动生成默认配置。

---

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Alt+Q` | 唤起快速提问 |
| `Ctrl+Alt+A` | 截图 |
| `Ctrl+Alt+N` | 新建桌面便签 |
| `Ctrl+Alt+H` | 显示 / 隐藏主窗口 |

（均可在 设置 → 快捷键 中修改）

---

## 架构

应用分为四层，关注点清晰分离：

```
main.py                  入口：依赖检查 → 崩溃日志 → 启动 Qt
│
├── app/core/            核心业务层
│   ├── llm_gateway      统一 LLM 网关（LiteLLM 接入 / 限流 / 重试 / 流式 / 日志）
│   ├── agent_loop       Agent 状态机循环（prepare→stream→execute→feedback→finalize）
│   ├── note_manager     笔记 / 便签 / 待办存储（SQLite）
│   ├── memory_manager   长期记忆
│   ├── consolidator     会话压缩（超长自动摘要）
│   ├── dream            后台记忆整合
│   ├── scheduler        定时任务（APScheduler）
│   └── session_manager  多会话管理
│
├── app/tools/           工具系统
│   ├── registry         注册 / 发现 / 执行 / 错误分类与重试
│   ├── script_adapter   动态加载用户自定义 Python 工具
│   └── *.py             内置工具（搜索、抓取、文件、命令、笔记、记忆…）
│
├── app/models/          数据模型（Message / Session / Note / Memory）
│
└── app/ui/              UI 层
    ├── main_window      无边框浮窗主窗口（聊天 / 笔记 / 工坊 三页）
    ├── components/      可复用组件（消息气泡、Markdown 编辑器…）
    └── settings_pages/  设置分页
```

### Agent 循环

每个会话运行在独立的 `QThread` 上，互不阻塞。一个 turn 的生命周期：

```
prepare   组装系统提示词 + 注入记忆 + 历史消息
   ↓
stream    流式接收 LLM 输出，实时渲染
   ↓
execute   解析工具调用，并发执行一批工具
   ↓
feedback  把工具结果回灌给 LLM
   ↓
finalize  无更多工具调用时结束，持久化会话
```

支持随时取消、崩溃后从 checkpoint 恢复。

### 工具系统

所有工具继承 `BuiltinTool`，声明 `name / description / parameters / execute`，由 `ToolRegistry` 统一管理并导出为 OpenAI Functions 格式。三种来源：

1. **内置工具** —— 随应用分发
2. **用户脚本** —— 在工具目录放入 `tool.py` 即被动态加载
3. **AI 生成** —— 描述需求，让 LLM 写出工具代码

---

## 技术栈

- **GUI**：PyQt6 + [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
- **LLM**：LiteLLM（统一接入各家模型）
- **存储**：SQLite（笔记、记忆）+ JSON（会话、配置）
- **调度**：APScheduler
- **OCR**：RapidOCR (ONNX Runtime)
- **其他**：keyring（密钥）、keyboard（全局快捷键）、BeautifulSoup（网页解析）

---

## 打包

```bash
build.bat        # 调用 PyInstaller (AI_Agent.spec)
```

---

## 设计取舍

构建过程中踩过、并已沉淀为方案的一些坑（见 `CLAUDE.md`）：

- 无边框窗口拖动用 `startSystemMove()`，调整大小用事件过滤器 + `setGeometry`（避免 `startSystemResize()` 的幽灵边框）
- FluentWindow 会重新应用内部样式，QTextEdit 前景色须在 `focusInEvent` 中强制设置
- 嵌入式面板的确认对话框用原生 `QMessageBox`，不用 qfluentwidgets 的 `MessageBox`（`MaskDialogBase` 要求顶层窗口）

---

## 致谢

- 笔记编辑器的 wiki 双链解析、查找替换、Markdown 语法高亮等代码移植/改编自 [noteration](https://github.com/lilamr/noteration)（MIT）。完整的第三方许可证声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## License

[MIT](LICENSE)

本项目使用了第三方开源代码，其版权与许可证声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
