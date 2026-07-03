# Nemo Assistant Desktop Assistant

PyQt6 无边框透明浮窗桌面应用。

## 回复规则

- 一律用**中文**回复

## 记忆规则

- 多次（>=2次）修复失败的问题最终解决后，将根因和正确方案保存到记忆中
- 用户纠正做法时，主动保存到记忆中
- 了解到项目背景、决策原因、约束条件时，主动保存到记忆中

## 提交规则

- commit message 一律用**英文**
- 一次会话涉及多个模块/功能改动时，**可拆成多次提交**；但不要过度拆分，**单模块改动最多 3 次**

## PyQt6 无边框窗口（详见 ~/.claude/rules/pyqt6/）

- 拖动用 `startSystemMove()`，不要 Python 计算偏移
- 调整大小用 QApplication 事件过滤器 + `setGeometry`，不要 `startSystemResize()`（有幽灵边框）
- 光标用 `QApplication.setOverrideCursor` / `restoreOverrideCursor`
- 空 Edges 用 `Qt.Edge(0)`，不要 `Qt.Edges()`
- 事件过滤器装在 `QApplication` 上，不要装在子控件上
- 不用 `QSizeGrip`（无边框下无效）

## 项目特有经验

- **QListWidget 自定义 Widget**：`setItemWidget()` 后必须调用 `item.setSizeHint(widget.sizeHint())`，否则高度被裁剪
- **QSplitter**：① 折叠/隐藏子面板用 `setSizes([0, total])`，**不要用 `setVisible()`**（会破坏 splitter 布局）；② `setChildrenCollapsible(False)` + `setMinimumWidth()` 防止用户拖动分割条时把面板误折叠到 0 宽；③ `setEnabled()` 仅用于切换编辑器只读/可编辑态（如回收站只读），与面板显隐无关，别混为一谈。
- **自定义按钮信号**：构造函数分离 `display_text` 和数据，信号只传纯数据不传带装饰字符的显示文本
- **数据库**：note/todo/daily 共用 notes 表，用 `note_type` 字段区分，待办特有字段设为可选（NULL）
- **sticky 便签前景色（已改为 QWidget，非 FluentWindow）**：`StickyNoteWindow` 现在是裸 `QWidget`（不是 FluentWindow），不存在「FluentWindow 后续重新应用内部样式覆盖前景色」的问题。其 `_content_edit`（`QTextEdit`）的文字颜色直接在构造时用 QSS 固定即可（`setStyleSheet("QTextEdit { color: <ink>; ... }")`），无需 `focusInEvent` + `setTextColor` 兜底。**历史教训保留**：当某控件确实嵌在 FluentWindow 内、QSS/palette 前景色被内部样式覆盖时，QTextEdit 用 `focusInEvent` 里 `setCurrentCharFormat` + `setTextColor` 强制设色，QPlainTextEdit 见下方 MarkdownEditor 专条。
- **QSyntaxHighlighter 主题切换 + FluentWindow**：三个坑——① FluentWindow 内部样式传播时机不定，`palette().window().color().lightness()` 判断深/浅模式不可靠，应从 `style._current_dark_mode` 直接读；② `setFormat()` 是**替换**不是合并，所有 format 必须显式设前景色，否则回退到 FluentWindow 覆盖后的错误默认色；③ 深浅检测错误会导致暗色高亮配色（如 `#E5E7EB` 灰白）套在亮色背景上。正确方案：`_make_format` 无 color 时用 `_default_text_color` 兜底，浅深判断用 `style._current_dark_mode`。
- **划词取词的全局 Ctrl+C 会触发控制台 SIGINT**：`selection_capture.capture_selection()` 用 `keyboard.send("ctrl+c")` 注入的是**全局**按键，无法控制落到哪个窗口。开发期从命令行启动 app，拖选后若把焦点快速切到运行本进程的控制台，这个 Ctrl+C 被控制台解释成中断信号 → 给附着进程发 SIGINT → 在 `time.sleep` 处抛 `KeyboardInterrupt` 打断整个 app（报错栈停在 `_poll_clipboard` 的 sleep）。正确方案：在 send + 轮询外层显式 `except KeyboardInterrupt`，还原剪贴板后静默返回，不让取词副作用波及主进程存活。
- **qfluentwidgets MessageBox 不能用在 StackedWidget 内嵌面板中**：`MaskDialogBase` 要求 parent 是真正的顶层窗口，会在 parent 上覆盖遮罩并调用 `self.window().installEventFilter(self)`。当面板嵌在 FluentWindow 的 StackedWidget 中时，parent 链指向 `StackedWidgetClassWindow`（非顶层），连续弹出会卡死。正确方案：嵌入式面板中的确认对话框用标准 `QMessageBox`，不用 qfluentwidgets 的 `MessageBox`。
- **当前行高亮（ExtraSelection）跨主题**：项目有十几套主题，暗色底色从 `rgba(18,18,18)` 到 `rgba(46,52,64)` 跨度大，且浮窗半透明。写死单一颜色（如 `#3A3A3A`）在最暗主题里会糊成黑块。正确方案：用**半透明叠加**——暗色 `QColor(255,255,255,20)`、浅色 `QColor(0,0,0,14)`，当前行只在任意底色上微微提亮/压暗，永不撞色。深浅判断同样从 `style._current_dark_mode` 读，不用 palette lightness。
- **MarkdownEditor 是 QPlainTextEdit，没有 `setTextColor`**：`setTextColor`/`textColor` 是 `QTextEdit` 独有的方法，`QPlainTextEdit` 调用会 `AttributeError`。上面 FluentWindow 内 QTextEdit 用的「`setCurrentCharFormat` + `setTextColor`」方案**不能照搬到 MarkdownEditor**。QPlainTextEdit 的文字前景色加固用 `setCurrentCharFormat` + `mergeCurrentCharFormat`（见 `markdown_editor.py:_apply_text_color`，在 `focusInEvent` 中调用）。
- **PyQt6 `pyqtSignal(int,...)` 收到 str 不报错、会静默变垃圾数**：声明为 int 的信号 `emit("5", ...)` 不抛 TypeError，而是把 `"5"` 转成无意义的大整数（如 `863819264`）。便签同步链路 note_id 实际是 `int`（`Note.id`），信号声明正确；但若类型标注误写成 `str`（`_current_note_id: str`、`note_id: str`），一旦有人照标注真传 str，同步会无声损坏。标注务必与运行时实际类型一致，都用 `int`。
- **审查报告/旧记忆会误判，改前必须追运行时实际值**：自动调查报告可能凭类型标注或 CLAUDE.md 字面套用得出错误结论（如误判「信号类型不匹配导致同步失效」「该加 setTextColor」，实际前者运行时是 int 没坏、后者方法不存在会崩）。涉及信号类型、控件方法是否存在等，改前用最小脚本实测验证，不要盲信报告。
- **QListWidget 拖动卡顿：别改绘制，照搬「能用原生移动」的那个列表**：笔记列表拖动卡了好几个会话都没修好，根因是历次都在改 delegate 绘制（关抗锯齿、去圆角、降级 paint）和落点判定，全是无效补丁。实测证伪：一次拖动里 `paint` 只占 0.4%（241 次调用 23ms / 拖动 5.5s），`_on_selection_changed` 拖动中触发 0 次，`cfg.get` 0.33µs——绘制和我们的代码全程几乎没干活。真因是笔记列表**重写了 `dropEvent` 做 `event.ignore()` + 整表 `_load()` 重建**，而同窗口的会话列表（`session_panel.py`）对 `InternalMove` **零重写**、让 Qt 原生移动行（`model().rowsMoved` 读新顺序）所以丝滑。正确方案：删掉所有自定义拖动重写（`mouseMoveEvent`/`startDrag`/`dropEvent` 和 delegate 的降级绘制），改用原生移动；文件夹结构靠「头不可拖动当分界 + 松手后按行位置重新推断每条笔记归属」在 `rowsMoved` 里持久化（`reorder_notes` 顺带改写 folder_id，故跨文件夹拖动＝移动归属）。注意在 `rowsMoved` 里重建列表会重入 model，用 `QTimer.singleShot(0, ...)` 延迟一拍再 `_load()`。**通用教训：两个相似控件一个顺一个卡时，先 diff 它们对 Qt 的重写差异，对齐到「不重写」的那个，别在被卡的那个上叠补丁。**
- **手动拖边调整大小后必须清 `_is_maximized`**：最大化是自定义状态（`_is_maximized` 标志 + `setGeometry`，非原生）。标题栏拖动靠 `if not is_maximized` 守卫——最大化态下禁止 `startSystemMove()`。但用户在最大化时从边缘手动拖小窗口走的是 `ResizeFilter`，它原先只设 `_user_has_resized`、从不清 `_is_maximized`，导致应用仍以为处于最大化态、窗口头拖不动。正确方案：`ResizeFilter` 边缘拖拽**开始**时若处于最大化态，立即 `_is_maximized=False` 并 `update_max_btn(False)`，让尺寸与状态一致。
- **`ResizeFilter` 装在 QApplication 上会误伤其它顶层窗口（如设置对话框）**：过滤器装 `QApplication` 是为了拦截子控件区域的边缘拖拽，但它会收到**所有**顶层窗口的鼠标事件。设置对话框盖在主窗口上时，过滤器把鼠标全局坐标映射回主窗口矩形、判定落在 resize 边框 12px 内 → 显示双向箭头光标并 `return True` 吞掉点击（设置项点不动）。正确方案：`eventFilter` 开头用 `QApplication.topLevelAt(gpos)` 取鼠标所在顶层窗口，非主窗口直接 `return False` 放行；加 `not self._active` 例外避免打断进行中的拖拽。
- **长耗时工具执行期间要保持亮条转动**：聊天底部的 `IndeterminateProgressBar`（亮条）表示「任务进行中」。工具开始执行（`_on_tool_event` phase=="start"）时原先调了 `stop_typing()` 关掉亮条，气泡里的 `⟳` 只是静态文本不会转——遇到 websearch 等长耗时工具，整段执行期没有任何动画反馈，看着像卡死/失败（发送按钮虽仍是取消态、worker 也在跑）。正确方案：工具开始时改 `start_typing()` 保持亮条转动，直到 `new_turn`（继续）或 `done`（结束）才停。
- **三个主视图（聊天/笔记/工坊）的列表区边距要对齐**：最外层布局都用 `setContentsMargins(0,0,0,0)`（列表贴窗口头，别留边距）；列表内层面板用 `setContentsMargins(8,10,8,8)`（对齐 `session_panel` 与 `toolListPanel`）。笔记面板曾用 `12,12,12,12` + `6,6,6,6`，导致列表和窗口头之间空一段、与另两个视图不一致。
- **PyInstaller onefile 打包的三个坑（改 onedir→onefile 时一次性踩全）**：① **动态发现的模块必须 `collect_submodules` 显式收集**——内置工具靠 `pkgutil.iter_modules` + `importlib` 动态发现，无任何 import 语句直接引用，PyInstaller 静态分析看不到 → 不打进 exe → 运行时 `discover_builtin_tools()` 返回 0 个工具（工坊只剩零星几个）。spec 里加 `tool_hiddenimports = collect_submodules('app.tools')` 并入 `hiddenimports`。② **顶层 `_ensure_deps()` 在 onefile 下是进程炸弹**——`sys.executable` 冻结后＝exe 本身，`subprocess.check_call([sys.executable, "-m", "pip", ...])` 不是跑 pip 而是**再启动一个完整 app 实例**，雪崩式自我复制（实测 27 个进程）。修：`_ensure_deps()` 开头 `if getattr(sys, "frozen", False): return`，且 `main.py` 顶部加 `multiprocessing.freeze_support()`。③ **打包资源路径要走 `sys._MEIPASS` 而非 exe 旁边**——onefile 把 datas 解压到临时目录 `_MEIPASS`，但可写数据（config/data）仍应在 exe 旁边。config.py 分两个根：`BASE_DIR=Path(sys.executable).parent`（可写）、`BUNDLE_DIR=Path(getattr(sys,"_MEIPASS",BASE_DIR))`（只读资源，assets/图标走它）。**另注**：spec 里 `('tools','tools')` 引用的根级 tools 目录其实根本不存在（onedir 时代就坏的死引用，且 `TOOLS_DIR` 是无人使用的死常量），onefile 才暴露。**被证伪的弯路（别重蹈）**：一度以为 `pkgutil.iter_modules` 在冻结后失效、改用读 `__loader__.toc` 的特殊分支——**错的，反而返回 0**。实地探测证明 PyInstaller 6.x 的 `PyiFrozenLoader` **完全支持** `pkgutil.iter_modules(pkg.__path__)`（能列全 23 个模块），源码/打包共用一套 pkgutil 逻辑即可，真因只是模块没被 `collect_submodules` 打进包。**通用教训：打包类问题别靠猜 PyInstaller 内部 API，加一段 probe（dump `pkgutil.iter_modules`/`__loader__` 类型/`__path__`）实地打一次 exe 看真值；GUI 程序无 console 看不到 logger.info，临时 `console=True`+`logging.basicConfig` 验证完再还原。**



