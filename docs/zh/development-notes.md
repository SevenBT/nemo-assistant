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

## 轻量模型传输

- 所有供应商共用 httpx 传输层；已移除 LiteLLM、OpenAI SDK 和后台 SDK 预热。启动不发送模型探测请求；首次调用仍可能受 DNS/TLS 和服务端延迟影响。
- 分别处理 Chat Completions、Responses、Claude Messages 和 Cohere Chat v2。provider 选择默认协议，模型条目可用 api_protocol 覆盖；未知厂商需要明确 api_base。Azure 使用资源地址下 /openai/v1，Model ID 填部署名称。
- LiteLLM 命名的配置字段和 keyring 槽位仅为兼容旧数据保留，不表示第二套调用体系。编辑模型保留额外字段，并可选择协议。
- 每个网关持有可关闭的连接池。池内使用单个后台 asyncio 循环，等待响应头、保活及读取中均可取消；单次取消不关闭其他请求。阶段超时和可选总时限分别处理。
- 收到协议结束事件并验证全部工具调用后才提交执行。无效 JSON、冲突 ID/签名、重复 ID、截断工具或缺少结束事件均报错。文本、推理或工具分片开始后不再整次重试，不自动换协议重发。
- Gemini 工具签名、Claude 签名内容块和 Responses 推理/输出项贯穿 Agent 多轮及 Message 持久化；保留图片和工具结果，不支持的内容报错。
- usage 缺失保持未知，部分字段缺失不当作零。不读取本地价格表；错误展示和落库前脱敏。日志记录 provider/model/protocol/profile revision，不记录提示词和密钥。
- 验证使用离线协议、禁止 SDK 导入的子进程、真实本机连接取消及独立评估；不等于所有厂商/模型已经实网认证。详见[实现方案](../design/shared-lightweight-provider-design.md)。

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
