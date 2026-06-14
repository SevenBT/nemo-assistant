# 设计：截图识图 → 多模态 AI（独立于 OCR 识字）

> 状态：**第一层 + 第二层 + 设置页 UI + 拖放/粘贴接入 + 内联预览/待发预览条 已实现并测试通过；剩 live 验证**
> 记录时间：2026-06-12
> 关联：[TODO_TABLE_OCR.md](./TODO_TABLE_OCR.md)

## 拖放/粘贴 + 预览（2026-06-12 补，修真实问题）

用户拖图进对话发现「只显示路径、模型收不到图」。根因：图被拖进了**输入框**
（QTextEdit 默认把文件 URL 当文本插入），根本没进附件管线。修复：

- `app/ui/attachment_intake.py`（新）：`attachments_from_mime()` 统一把文件 URL +
  剪贴板图片像素解析成 Attachment（粘贴的截图像素存进 SCREENSHOTS_DIR）。
- `app/ui/input_widget.py`：`_TextEdit` 重写 `canInsertFromMimeData`/`insertFromMimeData`/
  拖放事件 → 文件和图片走附件管线，不再插成文字；普通文本粘贴不受影响。支持粘贴图片。
- `app/ui/image_preview_widget.py`（新）：聊天气泡里图片附件渲染成内联缩略图
  （≤360×320，点击打开原图），非图片仍用 FileCardWidget。
- `app/ui/pending_attachment_bar.py`（新）：输入框上方「待发送预览条」，拖放/粘贴/截图识图的
  附件在发送前显示为缩略图 + 删除按钮。
- 附件归属统一到 InputWidget（单一来源）：`add_pending_attachments` / `take_pending_attachments`；
  控制器 submit 时 take，`on_files_attached` 改为往预览条加。允许仅附件无文字发送。
- 测试：`tests/test_attachment_intake.py`（5 例）。

---

## 核心原则（重要，勿混淆）

**OCR 识字 与 识图走大模型 是两条完全独立、并列的路径，互不为兜底。**

- **📝 识字（OCR）**：本地 RapidOCR 提取文字，是**独立的、主要的**文字提取逻辑。保持现状，不动。它不是任何东西的降级方案。
- **🤖 识图（多模态 AI）**：**新增独立按钮（一个或几个）**，把图片像素发给多模态模型理解。
- 截图后**不会自动走大模型**。用户点哪个按钮走哪条路：点「识字」走 OCR，点「识图/解释/...」走大模型。
- 两条路各干各的，**不互相降级**。OCR 不因为模型不支持 vision 而被当兜底，大模型也不在 OCR 失败时介入。

## 一句话目标

在截图工具栏增加一个或几个**独立的大模型识图按钮**，把截图像素发给多模态模型，让它"看图"并理解（解释/翻译/解题/转表格）。OCR 识字保持独立不变。

---

## 现状盘点（实现前提）

代码已确认的事实：

1. **附件管线目前是纯文本管线**。图片附件进对话时被 OCR 降级成文字：
   - `app/core/file_parser.py:136` `_parse_image` → OCR 出文字存进 `Attachment.parsed_content`
   - `app/core/conversation_prompt_builder.py:85` `merge_attachments_to_content` → 把 `parsed_content` 拼进 content 字符串
   - **模型从未看到过图片像素** —— 这是识图功能要新开的通道。
2. **`Message.to_api_dict`（`app/models/message.py:55`）content 永远是 `str`**。多模态要求 content 支持 `list`（OpenAI `[{type:text},{type:image_url}]` 结构）。
3. **三个 adapter 多模态支持不同**（`app/core/llm_gateway.py`）：
   - `OpenAIAdapter`：messages 原样透传 → **天然支持** list content
   - `LiteLLMAdapter`：原样透传 → **支持**（取决于底层模型）
   - `ShangdaoAdapter`：调 `_messages_with_text_tool_history`，**假设 content 是 str，list 会出问题** → 需处理
4. **`Attachment` 模型（`app/models/attachment.py`）有 `file_path` 但无 base64**。截图当前不存盘 → 识图需先把 pixmap 存 png 才能构造 image 附件。
5. **配置无 vision 能力标记** → 大模型识图前需要判断当前模型是否支持视觉（不支持就提示用户换模型，**不回退到 OCR**——那是另一条独立路径）。

---

## 设计：分两层

### 第一层：开通多模态附件通道（图片像素 → 模型）

> 注意：这一层**只服务"识图走大模型"**，与 OCR 识字无关。OCR 那条路不经过这里。

> ✅ **已实现（2026-06-12）**，对应改动：
> - `app/core/config.py`：新增 `visionSupport` 配置（auto/on/off）、`SCREENSHOTS_DIR`、
>   `model_supports_vision()` 名称启发式、`current_vision_enabled()` 解析当前 openai 模型能力。
> - `app/models/attachment.py`：新增 `is_image()` 和 `to_data_url()`（发送时即时读盘转 base64，不存进会话 JSON）。
> - `app/core/conversation_prompt_builder.py`：`build()` 解析 `_vision_enabled()`（openai 看配置、
>   litellm 看模型名、shangdao 恒 False，失败安全回 False）；`merge_attachments_to_content(messages, vision_enabled)`
>   分流文本/图片附件，vision 开且能取到图 → OpenAI list content（text + image_url），否则纯文本（图片用 OCR 文字占位）。
> - `app/core/llm_gateway.py`：新增 `_flatten_content()`，`_messages_with_text_tool_history` 用它把任何
>   漏到 shangdao 的 list content 降级为文本（image_url → `[图片]` 占位），保护商道网关。
> - 测试：`tests/test_multimodal_attachments.py`（8 例全过）。
> - 待办：vision 开关的设置页 UI（visionSupport 目前只有配置项，settings 页未加控件）。

> ✅ **设置页 UI 已补（2026-06-12）**：`app/ui/settings_pages/api_page.py` OpenAI 段「模型」下方
> 新增「识图能力」下拉（自动/始终开启/始终关闭 → `cfg.visionSupport`），带 tooltip 说明；
> 该控件随商道/LiteLLM 启用而禁用（与其它 OpenAI 字段一致）。

**改动点：**

1. **`Attachment` 增加图片数据载体**
   - 倾向：存 `file_path`，发送前即时读盘转 base64，避免会话 JSON 膨胀。
   - 需处理临时文件生命周期（截图 png 存哪、会话持久化是否落盘、清理时机）。见"待定问题 1"。

2. **`merge_attachments_to_content` 支持图片像素通道**
   - image 类型附件 + 模型支持 vision → content 变 list：
     ```
     [{"type": "text", "text": <用户文字>},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,<...>"}}]
     ```
   - **不支持 vision 时不静默降级为 OCR**——提示用户"当前模型不支持识图，请切换多模态模型"。OCR 识字是用户主动点「识字」按钮触发的另一条路，不在这里偷偷代偿。
   - 现有的纯文本附件逻辑（文档/文本文件）维持不变。

3. **新增 vision 能力判断**
   - 配置层加"模型是否支持视觉"标记（openai 一个布尔；litellm 每模型字段；shangdao 看 model_meta）。
   - 用于：识图按钮是否可用 / 点击后是否提示换模型。

4. **ShangdaoAdapter 对 list content 的处理**
   - 最小方案：shangdao 不支持多模态时，识图按钮在该 provider 下禁用或提示，不发 list content。

### 第二层：截图工具栏接入识图按钮

> ✅ **已实现（2026-06-12）**，对应改动：
> - `app/ui/vision_actions.py`（新）：`VisionAction` 数据类 + `VISION_ACTIONS` 默认动作集
>   （问AI/解释/翻译/解题/转表格）+ `get_vision_action()`。动作 id 形如 `vision:<key>`。
> - `app/ui/screenshot_overlay.py`：工具栏在 📌贴图/📝识字 之后插入识图动作按钮，
>   点击 emit `captured(pixmap, "vision:<key>", "", pos)`。`_on_action` 复用 pin/copy/save 的
>   立即截图分支（vision 不跑 OCR）。
> - `app/ui/screenshot_controller.py`：构造支持 `attach_callback`/`prefill_callback`
>   （或 `set_chat_callbacks()` 延迟注入）；`_on_done` 增加 `vision:*` 分支 →
>   `_save_as_attachment()` 存 PNG 到 SCREENSHOTS_DIR + 包成 image Attachment →
>   attach_callback 挂附件 + prefill_callback 预填动作提示词。**识图分支不跑 OCR。**
> - `app/ui/input_widget.py`：新增 `set_text()` 预填输入框并聚焦、光标置末尾。
> - `app/ui/main_window.py`：session controller 创建后调 `set_chat_callbacks` 接线
>   （attach → `on_files_attached`，prefill → `input.set_text`）。
> - 测试：`tests/test_screenshot_vision.py`（5 例全过）。
> - 决策：预设动作点击后**预填+聚焦等用户回车**（不自动提交），动作直接拆成多个按钮（非子菜单）。

**改动点：**

1. **`screenshot_overlay.py` 工具栏加独立识图按钮**
   - 现有：📌贴图 / 📝识字(OCR，独立保留) / 📋复制 / 💾保存 / ✕
   - 新增：🤖 识图（或拆成几个：解释 / 翻译 / 解题 / 转表格）
   - `captured` 信号已有 action 字段，扩展取值即可（如 `"vision"` 或 `"vision:explain"`）。
   - **识字按钮与识图按钮并列、互不影响。**

2. **`screenshot_controller.py` 的 `_on_done` 接识图分支**
   - 把 pixmap 存成 png → 构造 image 类型 `Attachment`（**不在此处跑 OCR**，识图就是发图）
   - 调 `on_files_attached([attachment])`（已有管线）把图挂到下次提交
   - 带提示词的动作 → 预填提示词到输入框，聚焦窗口
   - controller 需拿到 `chat_session_controller` / `input_widget` 引用（目前只持有 `_window`）

3. **「识图动作」抽象**
   - 定义一组识图动作：`{key, 图标, 标签, 提示词模板}`
   - 截图工具栏从配置生成识图按钮；未来其他入口可复用
   - 加动作不改 UI

---

## 待定问题（实现前需定）

1. **截图图片的存储与生命周期**：png 存哪、会话持久化是否落盘、清理时机？
   - 建议：存 `DATA_DIR/screenshots/`，会话引用 file_path，删会话时清理。
2. **识图预设动作点击后**：自动提交还是预填等用户确认？
   - 建议：预填 + 聚焦，用户可补充后回车（可控，避免误发）。
3. **vision 能力标记**：手动开关 vs 按模型名启发式推断？
   - 建议：手动开关为主（可靠），辅以常见 vision 模型名默认推断。
4. **识图按钮数量**：一个通用「识图」按钮，还是直接拆成 解释/翻译/解题/转表格 多个？
   - 待定。

---

## 落地顺序建议

1. 第一层：`Attachment` 图片载体 + `merge_attachments_to_content` 图片通道 + vision 判断 + shangdao 处理（先用"粘贴/拖入图片"验证通道，不依赖截图）
2. 第二层：截图工具栏「识图」按钮 + controller 识图分支（最小：发图+预填提示词）
3. 识图动作抽象 + 多按钮（解释/翻译/解题/转表格）
4. 表格识别作为识图动作之一（见 TODO_TABLE_OCR.md）

## 与 OCR 识字的边界（再次强调）

- OCR 识字路径（`📝识字` → `_do_ocr` → `_reconstruct_layout` → 复制/编辑）**完全独立，本设计不改动它**。
- 识图路径是新增的并行通道，发的是图片像素。
- 两者唯一的共同点是都从同一个框选区域取图，之后各走各的。

## 顺手可清理的技术债（与本设计独立）

- `file_parser.py:155` 的 `_parse_image` 仍用旧的 `'\n'.join(line[1])` 拼法（丢坐标）。可统一复用 `screenshot_overlay._reconstruct_layout`，让图片附件 OCR 也保留版面结构。这是 OCR 侧的改进，与识图无关。
