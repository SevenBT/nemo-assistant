# 开发笔记

> [English](../en/development-notes.md)

这些笔记记录了对贡献者有用的实现权衡取舍，刻意不包含本地助手规则或仅面向维护者的工作流偏好。

## 无边框窗口

- 窗口拖动使用 `startSystemMove()`，而不是用 Python 计算偏移量。
- 调整大小使用 QApplication 级别的事件过滤器加 `setGeometry()`，以避免 `startSystemResize()` 产生的幽灵边框。
- 空的边缘值应使用 `Qt.Edge(0)`。
- 不使用 `QSizeGrip`，因为它在这套无边框方案里无法可靠工作。

## 划词取词

- 划词取词优先使用 UI Automation，失败时回退到临时剪贴板复制。
- 剪贴板回退方案会注入 `Ctrl+C`，随后还原之前的剪贴板内容。
- 开发期间，全局 `Ctrl+C` 可能意外落到启动应用的终端上，因此取词层会处理 `KeyboardInterrupt` 并保持应用存活。

## 主题

- FluentWindow 可能在控件构造完成后重新应用内部样式。
- QTextEdit 的前景色有时需要在焦点变化时重新加固。
- QPlainTextEdit 不支持 `setTextColor`；改用当前字符格式合并（current character format merging）。
- 主题感知的高亮应使用半透明叠加，而不是单一固定颜色。

## 嵌入式对话框

嵌入式设置页使用原生 `QMessageBox` 做确认对话框。qfluentwidgets 的 `MessageBox` 要求 parent 是顶层窗口，在堆叠面板（stacked panel）内使用时会阻塞交互。

## 拖动排序

当两个 Qt 列表控件行为不一致时，先对比它们的事件重写差异，再考虑增加绘制或拖动逻辑。尽量使用原生的 `InternalMove`，并在可行时从 model 的行移动结果中持久化顺序。

## 截图 AI

截图 OCR 与截图送模型的视觉分析是两条独立路径：

- OCR 在本地进行，从像素中提取文字。
- 视觉分析将图片内容发送给所选模型（前提是该模型被配置为具备视觉能力）。

截图 AI 的完整流程见 [screenshot-ai.md](screenshot-ai.md)。
