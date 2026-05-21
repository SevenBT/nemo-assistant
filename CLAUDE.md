# AI Agent Desktop Assistant

PyQt6 无边框透明浮窗桌面应用。

## 记忆规则

- 多次（>=2次）修复失败的问题最终解决后，将根因和正确方案保存到记忆中
- 用户纠正做法时，主动保存到记忆中
- 了解到项目背景、决策原因、约束条件时，主动保存到记忆中

## PyQt6 无边框窗口（详见 ~/.claude/rules/pyqt6/）

- 拖动用 `startSystemMove()`，不要 Python 计算偏移
- 调整大小用 QApplication 事件过滤器 + `setGeometry`，不要 `startSystemResize()`（有幽灵边框）
- 光标用 `QApplication.setOverrideCursor` / `restoreOverrideCursor`
- 空 Edges 用 `Qt.Edge(0)`，不要 `Qt.Edges()`
- 事件过滤器装在 `QApplication` 上，不要装在子控件上
- 不用 `QSizeGrip`（无边框下无效）

## 项目特有经验

- **QListWidget 自定义 Widget**：`setItemWidget()` 后必须调用 `item.setSizeHint(widget.sizeHint())`，否则高度被裁剪
- **QSplitter**：`setChildrenCollapsible(False)` + `setMinimumWidth()`；用 `setEnabled()` 控制交互状态，不要用 `setVisible()` 控制显示隐藏
- **自定义按钮信号**：构造函数分离 `display_text` 和数据，信号只传纯数据不传带装饰字符的显示文本
- **数据库**：note/todo/daily 共用 notes 表，用 `note_type` 字段区分，待办特有字段设为可选（NULL）
- **QTextEdit 光标颜色（FluentWindow 环境）**：QSS `color`、palette、viewport stylesheet、setCurrentCharFormat 在 `__init__`/`showEvent` 中设置均无效——FluentWindow 会在后续重新应用内部样式覆盖掉。正确方案：在 `focusInEvent` 中用 `setCurrentCharFormat` + `setTextColor` 强制设置前景色，每次获焦都重新应用，确保不被覆盖。颜色值从 `style.get_text_color()` 获取以跟随主题。
- **QSyntaxHighlighter 主题切换 + FluentWindow**：三个坑——① FluentWindow 内部样式传播时机不定，`palette().window().color().lightness()` 判断深/浅模式不可靠，应从 `style._current_dark_mode` 直接读；② `setFormat()` 是**替换**不是合并，所有 format 必须显式设前景色，否则回退到 FluentWindow 覆盖后的错误默认色；③ 深浅检测错误会导致暗色高亮配色（如 `#E5E7EB` 灰白）套在亮色背景上。正确方案：`_make_format` 无 color 时用 `_default_text_color` 兜底，浅深判断用 `style._current_dark_mode`。
- **qfluentwidgets MessageBox 不能用在 StackedWidget 内嵌面板中**：`MaskDialogBase` 要求 parent 是真正的顶层窗口，会在 parent 上覆盖遮罩并调用 `self.window().installEventFilter(self)`。当面板嵌在 FluentWindow 的 StackedWidget 中时，parent 链指向 `StackedWidgetClassWindow`（非顶层），连续弹出会卡死。正确方案：嵌入式面板中的确认对话框用标准 `QMessageBox`，不用 qfluentwidgets 的 `MessageBox`。

