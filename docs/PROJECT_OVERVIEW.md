# AI Agent Desktop Assistant - 项目概要

## 项目简介

这是一个基于 PyQt6 的桌面 AI 助手应用，采用无边框透明浮窗设计，支持多会话聊天、工具调用、笔记管理、定时任务和截图等功能。

---

## 整体架构

```
AI Agent Desktop Assistant
│
├── 核心层 (app/core/)
│   ├── ai_client.py          # OpenAI API 客户端，流式响应处理
│   ├── session_manager.py    # 会话管理（多会话支持）
│   ├── note_manager.py       # 笔记管理（SQLite 存储）
│   ├── scheduler.py          # 定时任务调度（APScheduler）
│   ├── tool_manager.py       # 工具加载与执行
│   ├── builtin_tools.py      # 内置工具定义与处理器
│   ├── file_parser.py        # 文件解析（文本/图片 OCR）
│   ├── hotkey_manager.py     # 全局快捷键管理
│   ├── config.py             # 配置管理（API、主题、窗口）
│   └── db_manager.py         # SQLite 数据库管理
│
├── 数据模型层 (app/models/)
│   ├── message.py            # 消息模型（用户/助手/工具）
│   ├── session.py            # 会话模型
│   ├── note.py               # 笔记模型（支持笔记/待办/日记）
│   ├── attachment.py         # 附件模型（文件上传）
│   └── tool_def.py           # 工具定义模型
│
├── UI 层 (app/ui/)
│   ├── main_window.py        # 主窗口（无边框浮窗）
│   ├── title_bar.py          # 自定义标题栏
│   ├── chat_widget.py        # 聊天界面（消息气泡、拖拽上传）
│   ├── chat_worker.py        # 后台聊天线程（流式响应）
│   ├── input_widget.py       # 输入框
│   ├── session_panel.py      # 会话列表面板
│   ├── notes_dialog.py       # 笔记管理面板
│   ├── sticky_note_window.py # 桌面便签浮窗
│   ├── scheduler_dialog.py   # 定时任务面板
│   ├── settings_dialog.py    # 设置对话框
│   ├── screenshot_overlay.py # 截图工具（OCR 支持）
│   ├── pin_window.py         # 图片贴图窗口
│   ├── resize_filter.py      # 窗口边缘调整大小
│   ├── edge_snap.py          # 窗口边缘吸附
│   ├── tray_manager.py       # 系统托盘
│   ├── toast.py              # 通知提示
│   ├── style.py              # 主题样式生成
│   └── components/           # 可复用 UI 组件
│       ├── tag_input.py      # 标签输入
│       ├── tag_filter_panel.py # 标签过滤
│       ├── search_bar.py     # 搜索栏
│       ├── todo_editor.py    # 待办编辑器
│       ├── todo_item_widget.py # 待办列表项
│       ├── checklist_editor.py # 清单编辑器
│       └── horizontal_tag_bar.py # 横向标签栏
│
├── 工具系统 (tools/)
│   ├── fetch_url/            # URL 抓取
│   ├── web_search/           # 网页搜索
│   ├── read_file/            # 读取文件
│   ├── save_file/            # 保存文件
│   ├── run_python/           # 执行 Python 代码
│   ├── reminder/             # 提醒工具
│   └── example_tool/         # 工具模板
│
└── 数据存储 (data/)
    ├── notes.db              # SQLite 数据库（笔记、标签）
    ├── sessions/             # 会话历史（JSON）
    ├── jobs.json             # 定时任务配置
    └── config.json           # 应用配置
```

---

## 核心模块职责

### 1. 核心业务层 (app/core/)

| 模块 | 职责 | 关键特性 |
|------|------|---------|
| `ai_client.py` | OpenAI API 封装 | 流式响应、工具调用、附件内容合并 |
| `session_manager.py` | 会话生命周期管理 | 多会话支持、消息持久化（JSON） |
| `note_manager.py` | 笔记 CRUD | SQLite 存储、标签、软删除、桌面固定 |
| `scheduler.py` | 定时任务调度 | APScheduler、cron/interval/date 触发器 |
| `tool_manager.py` | 工具加载与执行 | 动态加载 `tools/` 目录、参数验证 |
| `builtin_tools.py` | 内置工具 | 笔记操作、定时任务管理、会话总结 |
| `file_parser.py` | 文件解析 | 文本（多编码）、图片 OCR（RapidOCR） |
| `hotkey_manager.py` | 全局快捷键 | 截图、新建便签、显示/隐藏窗口、快速提问 |
| `config.py` | 配置管理 | API 配置、主题、窗口位置/大小、快捷键 |
| `db_manager.py` | 数据库管理 | SQLite 连接池、事务管理、表结构初始化 |

### 2. 数据模型层 (app/models/)

| 模型 | 字段 | 用途 |
|------|------|------|
| `Message` | role, content, tool_calls, attachments | 聊天消息（用户/助手/工具） |
| `Session` | id, title, messages, created_at | 会话容器 |
| `Note` | id, title, content, note_type, tags, priority, due_date, is_pinned | 笔记/待办/日记 |
| `Attachment` | file_name, file_path, file_size, parsed_content | 文件附件 |
| `ToolDef` | name, description, parameters, manual_params | 工具定义 |

### 3. UI 层 (app/ui/)

**主窗口结构**：
```
MainWindow (无边框透明浮窗)
├── TitleBar (自定义标题栏)
│   ├── 菜单按钮
│   ├── 视图切换按钮（聊天/笔记/定时）
│   └── 窗口控制按钮（最小化/关闭）
├── QStackedWidget (多页面容器)
│   ├── Page 0: 聊天视图
│   │   ├── SessionPanel (会话列表)
│   │   └── ChatWidget + InputWidget (聊天区域)
│   ├── Page 1: NotesPanel (笔记管理)
│   └── Page 2: SchedulerPanel (定时任务)
└── ResizeFilter (边缘调整大小)
```

**关键 UI 组件**：
- **ChatWidget**: 消息气泡、工具卡片、拖拽上传、打字动画
- **MessageBubble**: 用户/助手消息、附件显示、工具执行状态
- **StickyNoteWindow**: 桌面便签浮窗（可拖动、可固定）
- **ScreenshotOverlay**: 全屏截图工具（矩形选择、OCR、贴图）
- **NotesPanel**: 笔记列表、编辑器、标签过滤、搜索
- **SchedulerPanel**: 定时任务列表、添加/删除任务

---

## 主要功能特性

### 1. 多会话 AI 聊天
- 流式响应（逐字显示）
- 工具调用（Function Calling）
- 多会话并行（后台继续执行）
- 会话历史持久化（JSON）
- 文件拖拽上传（文本/图片 OCR）

### 2. 笔记管理
- 笔记类型：普通笔记、待办事项、日记
- 标签系统（多标签、过滤）
- 软删除（回收站）
- 桌面固定（便签浮窗）
- 全文搜索
- 待办功能：优先级（P1/P2/P3）、截止日期、重复任务

### 3. 定时任务
- 触发器类型：cron（定时）、interval（间隔）、date（一次性）
- 工具调用（执行任何已加载的工具）
- 任务结果通知（Toast）
- 任务持久化（jobs.json）

### 4. 工具系统
- 动态加载（`tools/` 目录）
- 内置工具：笔记操作、定时任务管理、会话总结
- 外部工具：URL 抓取、网页搜索、文件读写、Python 执行
- 参数验证（JSON Schema）
- 手动参数输入（对话框）

### 5. 截图与 OCR
- 全屏截图（矩形选择）
- OCR 文字识别（RapidOCR）
- 图片贴图（桌面浮窗）
- 复制到剪贴板
- 保存为文件

### 6. 全局快捷键
- `Ctrl+Alt+A`: 截图
- `Ctrl+Alt+N`: 新建便签
- `Ctrl+Alt+Space`: 显示/隐藏窗口
- `Ctrl+Alt+Q`: 快速提问

### 7. 窗口特性
- 无边框透明浮窗
- 边缘调整大小（手动 setGeometry）
- 边缘吸附（自动隐藏/展开）
- 窗口拖动（系统级 startSystemMove）
- 置顶显示
- 系统托盘（最小化到托盘）

---

## 技术栈

### 核心框架
- **PyQt6** (6.5.0+): GUI 框架
- **OpenAI** (1.0.0+): AI API 客户端
- **APScheduler** (3.10.0+): 定时任务调度
- **SQLite**: 数据库（笔记、标签）

### 文件处理
- **httpx** (0.25.0+): HTTP 客户端
- **BeautifulSoup4** (4.12.0+): HTML 解析
- **RapidOCR** (1.2.0): 图片 OCR
- **PyPDF2** (3.0.0+): PDF 解析

### 系统集成
- **keyboard** (0.13.5+): 全局快捷键
- **pyperclip** (1.8.2+): 剪贴板操作
- **keyring** (24.0.0+): 密钥存储

### 打包工具
- **PyInstaller**: 打包为独立可执行文件（`AI_Agent.spec`）

---

## 数据流

### 聊天流程
```
用户输入 → InputWidget.submitted
         ↓
MainWindow._on_submit → 创建 Message（含附件）
         ↓
ChatWorker.start → AIClient.chat_stream（流式响应）
         ↓
信号回调 → text_chunk / tool_started / tool_done
         ↓
MessageBubble 更新 → 显示文本/工具卡片
         ↓
SessionManager.save_session → 持久化到 JSON
```

### 工具调用流程
```
AI 返回 tool_call → ChatWorker 解析
         ↓
ToolManager.execute → 加载工具脚本
         ↓
工具执行 → 返回结果（JSON）
         ↓
结果作为 tool 消息 → 继续对话
```

### 笔记管理流程
```
NotesPanel 操作 → NoteManager CRUD
         ↓
SQLite 数据库 → notes 表 + note_tags 表
         ↓
信号通知 → 更新 UI（列表/编辑器/便签浮窗）
```

---

## 配置与数据文件

| 文件 | 路径 | 用途 |
|------|------|------|
| 配置文件 | `data/config.json` | API 配置、主题、窗口位置、快捷键 |
| 笔记数据库 | `data/notes.db` | SQLite（笔记、标签、待办） |
| 会话历史 | `data/sessions/*.json` | 每个会话一个 JSON 文件 |
| 定时任务 | `data/jobs.json` | APScheduler 任务配置 |
| 工具脚本 | `tools/*/tool.py` | 动态加载的工具 |

---

## 构建与打包

**开发运行**：
```bash
python main.py
```

**打包为可执行文件**：
```bash
# Windows
build.bat

# 使用 PyInstaller
pyinstaller AI_Agent.spec
```

**打包特性**：
- 单文件夹模式（`dist/AI Agent/`）
- 包含 `tools/` 目录（用户可自定义工具）
- 无控制台窗口（`console=False`）
- 自动安装缺失依赖（`main.py` 启动时检查）

---

## PyQt6 无边框窗口开发规范

项目在 `CLAUDE.md` 中总结了 15 条 PyQt6 无边框窗口开发的最佳实践，核心要点：

### 窗口拖动
- ✓ 使用 `windowHandle().startSystemMove()`（系统级，零延迟）
- ✗ 避免 Python 层计算偏移（有卡顿）

### 窗口调整大小
- ✓ 使用 `QApplication.installEventFilter` + 手动 `setGeometry`
- ✗ 避免 `nativeEvent` + `ctypes`（PyQt6 中会崩溃）
- ✗ 避免 `startSystemResize()`（与透明背景叠加有幽灵边框）

### 光标管理
- ✓ 使用 `QApplication.setOverrideCursor`（全局生效）
- ✗ 避免 `widget.setCursor()`（子控件会覆盖）

### 透明背景
- ✓ 外层 `MainWindow` 设置 `WA_TranslucentBackground`，不写 CSS 背景
- ✓ 内层 `QFrame` 容器承载主题背景色（用 ID 选择器）
- ✗ 避免全局 `QWidget { background: transparent }`（会影响所有控件）

### 布局稳定性
- ✓ `QSplitter` 子组件设置 `setMinimumWidth` 和 `setChildrenCollapsible(False)`
- ✓ 编辑器区域用 `setEnabled()` 控制交互，而非 `setVisible()`（避免布局抖动）

---

## 架构优势

1. **模块化设计**：核心/模型/UI 三层分离，职责清晰
2. **可扩展性**：工具系统支持动态加载，用户可自定义工具
3. **多会话并行**：后台线程处理 AI 响应，不阻塞 UI
4. **数据持久化**：SQLite（笔记）+ JSON（会话/配置）
5. **跨平台**：PyQt6 支持 Windows/macOS/Linux
6. **无边框窗口最佳实践**：总结了 15 条开发经验，避免常见陷阱

---

## 技术亮点

1. **流式响应处理**：逐字显示 AI 回复，提升用户体验
2. **工具调用系统**：支持 OpenAI Function Calling，可执行任意工具
3. **文件拖拽上传**：支持文本/图片 OCR，自动解析为上下文
4. **桌面便签浮窗**：笔记可固定到桌面，独立窗口编辑
5. **全局快捷键**：后台监听键盘事件，快速唤起功能
6. **边缘吸附**：窗口靠近屏幕边缘自动隐藏，鼠标悬停展开
7. **主题系统**：支持多主题切换（Classic/Nord/Dracula/Monokai）

---

## 适用场景

- AI 聊天助手（多会话、工具调用）
- 桌面笔记管理（标签、搜索、待办）
- 定时任务调度（提醒、自动化脚本）
- 截图与 OCR 工具
- 桌面便签（快速记录）

---

## 项目特色

这个项目展示了如何构建一个功能完整的 PyQt6 桌面应用，特别是在无边框窗口、多线程处理、工具系统扩展等方面有很好的实践参考价值。

---

**生成时间**: 2026-05-08  
**项目路径**: D:\claudecode-projects\assistant
