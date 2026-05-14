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

