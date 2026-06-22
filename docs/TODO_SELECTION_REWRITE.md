# 设计：划词「就地改写回填」

> 状态：**已实现并测试通过（2026-06-22），剩 live 验证**
> 记录时间：2026-06-22
> 关联：[TODO_SCREENSHOT_AI.md](./TODO_SCREENSHOT_AI.md)（识图动作抽象同源）、`划词改造交接文档.md`

## ⚠️ 实现期的一处关键修正：气泡内容只能只读，不能可编辑

设计初稿设想「改写结果在气泡里可编辑、改完再替换」。**实现时发现这与焦点模型冲突，已放弃。**

根因：气泡 `ResultBubble` 继承 `NonActivatingPopup`，靠 `WS_EX_NOACTIVATE` 保证
**永不抢前台焦点**——而这正是 Ctrl+V 能落回源应用、覆盖选区的前提
（见 `non_activating_popup.py`）。一旦让 QTextEdit 可编辑接收键盘输入，气泡就必须
抢焦点，源应用选区随即丢失，回填的地基就塌了。二者不可兼得。

最终决策：**气泡内容保持只读**。需要微调改写结果时走「续入会话」（那条路本就在主窗、
可自由编辑）。`setPlainText` 在只读 QTextEdit 上仍可用，故「剥离 AI 前缀后回填进
气泡」的清洗仍生效。

> 通用教训：动 `NonActivatingPopup` 子类的交互前，先确认改动是否需要键盘焦点——
> 需要就与不抢焦点的铁律冲突，多半得换方案。

---

## 一句话目标

选中任意应用里的一段文字 → 点划词浮标上的「改写」类动作（润色/翻译/订正…）
→ AI 改写结果就地显示在气泡里 → 点「替换原文」把结果**写回源应用**，
直接覆盖掉原来选中的那段。

这是现有划词能力的**反向补全**：现在的动作都是「把选中文字拿到助手这边」
（解释→气泡、续入→会话、存便签→笔记库），唯独缺「助手把结果送回原应用」。
后者才是桌面助手相对聊天框产品的差异点——**在你正在写东西的地方原地帮你改**。

---

## 核心原则（勿混淆）

1. **回填是新增的第四种动作 mode，与现有三种并列、互不干扰。**
   现有 `oneshot`（解释气泡）/`compose`（续入会话）/`compose_new`（新建会话）
   /`local`（存便签）全部保持不变（见 `app/ui/text_actions.py:33-45`）。
2. **回填永远由用户显式点击触发，绝不自动写回。** 改写结果先展示、可编辑，
   用户确认后才动源应用——写回是不可逆的破坏性操作（覆盖用户原文），必须可控。
3. **回填失败必有兜底**：无法粘贴时（只读控件、PDF 阅读器、Ctrl+V 落点异常）
   自动把结果留在剪贴板并 toast「已复制，可手动粘贴」，绝不静默失败。

---

## 现状盘点（实现前提，均已读代码确认）

1. **取词链路**（`app/core/selection_capture.py`）：
   - `capture_selection()` = 备份剪贴板 → 释放修饰键 → `clipboard.clear()` →
     `keyboard.send("ctrl+c")` → 轮询读 → 还原剪贴板。
   - 已处理三个坑：修饰键残留、复制异步、全局 Ctrl+C 落到控制台触发 SIGINT
     （`except KeyboardInterrupt` 兜底，`selection_capture.py:127`）。
   - `_backup_clipboard` / `_restore_clipboard` 逐 format 深拷贝，保全图片/文件/富文本。
   - **回填可直接复用这套备份/还原/释放修饰键/SIGINT 兜底基建。**

2. **焦点模型**（关键）：浮标 `TextActionPopup` 与气泡 `ResultBubble` 都继承
   `NonActivatingPopup`，靠 `WS_EX_NOACTIVATE` 保证**点击其上按钮也不抢源应用焦点**
   （`text_action_popup.py:8-17`、`result_bubble.py:11`）。
   → 推论：AI 改写完成、用户点气泡上「替换」按钮的那一刻，源应用仍是前台、
   选区仍高亮，此时 Ctrl+V 会落到源应用、替换掉选中文字。**这是整个功能成立的地基。**

3. **动作定义**（`app/ui/text_actions.py`）：
   - `TextAction` 数据类已有 `mode` 字段与 `render(text)`（`{text}` 占位替换）。
   - `goes_to_ai` / `is_compose` / `forces_new_reading` 等属性按 mode 派生。
   - 设置页显隐开关映射在 `_ENABLED_ITEM`（`text_actions.py:133`）。
   - **加新动作只需往 `TEXT_ACTIONS` 加项 + 加显隐开关,浮标自动渲染**
     （`text_action_popup.py:_rebuild_buttons` 每次 show 重建）。

4. **结果气泡**（`app/ui/result_bubble.py`）：
   - `show_oneshot()` 起一个 `_BubbleWorker` 后台线程流式调 LLM，
     `_text_chunk` 信号 marshal 回主线程，`_append_text` 累积进 `self._full_text`。
   - 内容区 `self._content` 是 **`setReadOnly(True)` 的 QTextEdit**，`setPlainText`。
   - **目前气泡没有任何 footer 按钮**（docstring 提到「转主窗」但代码里未实现）。
   - → 回填要在气泡上加 footer 操作区（替换/复制/编辑），并让内容区在 rewrite
     模式下可编辑。

5. **分发控制器**（`app/ui/selection_controller.py`）：
   - `_on_action_bubble(key)` 按 `action.mode` 分流（`local`/`compose`/`oneshot`）。
   - `_get_text()` 统一取词（优先 UIA 预取 `self._captured`，兜底 Ctrl+C）。
   - → 回填新增一条 `rewrite` 分支即可接入,无需改取词逻辑。

---

## 设计：分两部分

### 第一部分：回填基建 —— `app/core/selection_inject.py`（新）

取词的镜像。纯逻辑与副作用分离，便于单测（与 `selection_capture.py` 同结构）。

```python
def replace_selection(new_text: str) -> bool:
    """把 new_text 写回当前前台应用的选区（模拟粘贴覆盖）。

    必须在源应用仍持有焦点、选区仍高亮时调用（气泡不抢焦点，故成立）。
    返回 True 表示已发出粘贴；False 表示前置条件不满足（keyboard 不可用等）。
    实际是否粘成功无法 100% 确认（见兜底）。
    """
    # 1. backup = _backup_clipboard(clipboard)           # 复用 capture 的实现
    # 2. 释放修饰键（复用 _MODIFIERS）
    # 3. clipboard.setText(new_text)
    # 4. try: keyboard.send("ctrl+v")  except KeyboardInterrupt/Exception: 还原+False
    # 5. QTimer.singleShot(RESTORE_DELAY_MS, lambda: _restore_clipboard(clipboard, backup))
    #    —— 粘贴是异步的，必须延迟还原，否则源应用还没读到就被还原回旧内容。
    return True
```

要点 / 与取词的差异：
- **还原必须延迟**（粘贴异步），取词那边是「立即还原」；这里反过来，立即还原会
  让源应用粘到旧剪贴板。延迟 ~300ms。注意 `selection_capture.py:136` 警告过
  「延迟还原会污染下次取词轮询」——回填与取词不会在同一时刻并发（回填发生在
  气泡展示后、用户点击时），但仍建议用一次性标志避免叠加。
- **共用基建抽取**：把 `_backup_clipboard` / `_restore_clipboard` / `_MODIFIERS`
  / 释放修饰键 从 `selection_capture.py` 提到一个 `clipboard_util.py`，
  capture 与 inject 共享，避免复制粘贴漂移（符合 DRY）。

可选增强（**回填前校验选区仍是原文**，降低误覆盖风险）：
- 回填前先静默 Ctrl+C 取一次当前选区，与原始 `text` 比对：
  - 相等 → 选区没变，安全粘贴。
  - 不等 / 空 → 选区已丢失（用户点别处了），**不粘贴**，转兜底（复制 + toast）。
- 代价是多一次 Ctrl+C；收益是杜绝「等 AI 期间用户点走，结果粘到错误位置」。
  建议**默认开启**，作为破坏性操作的安全闸。

### 第二部分：动作 + 气泡接线

**a) 新增 mode 与动作**（`app/ui/text_actions.py`）

```python
mode = "rewrite"   # 改写回填：气泡显示结果 + 可编辑 + 「替换原文」按钮
```

新增 `TextAction.is_rewrite` 属性（`mode == "rewrite"`）。`goes_to_ai` 已能覆盖
（rewrite 有 prompt，自动为 True）。

建议初始动作集（都走同一条 rewrite 管线，仅 prompt 不同）：

| key | 图标 | 标签 | 提示词（{text} 占位） |
|---|---|---|---|
| `polish`  | EDIT       | 润色   | 润色下面这段文字，使其更通顺自然，**只输出改写后的文字，不要解释**：\n\n{text} |
| `translate_inplace` | LANGUAGE | 翻译回填 | 把下面这段文字翻译成{目标语}，只输出译文：\n\n{text} |
| `fix_grammar` | ACCEPT  | 订正   | 修正下面文字里的错别字和语法错误，保持原意与风格，只输出修正后的文字：\n\n{text} |

> 提示词统一要求「只输出结果」，否则 AI 会带「好的，这是润色后的版本：」之类前缀，
> 直接回填会污染原文。这是 rewrite 区别于 explain（解释要解释）的关键。

每个动作配一个显隐开关 + 自定义提示词（沿用 `_ENABLED_ITEM` 与 explain 的
`selectionExplainPrompt` 模式），在设置页可改。

**浮标按钮会变多**（现有 4 个 + 3 个 rewrite = 7），单排可能偏长。两个选项：
- A. 直接平铺（最简单，先上）。
- B. rewrite 类收进一个「✍️ 改写」二级菜单（hover/click 展开）。
  → 建议先 A 跑通，按钮真的挤了再做 B（YAGNI）。

**b) 气泡支持 rewrite 模式**（`app/ui/result_bubble.py`）

- 新增 `show_rewrite(x, y, text, action_key)`，与 `show_oneshot` 共用 worker/流式，
  差异：
  - 内容区 `setReadOnly(False)`，让用户在替换前能改两笔。
  - 流式期间禁用 footer 按钮；`_on_stream_done` 后启用。
  - 底部加 footer 操作区：**[替换原文] [复制] [编辑/转主窗]**。
- footer 新增信号 `replace_requested(str)` / `copy_requested(str)`，气泡只发信号，
  实际回填由 `SelectionController` 调 `selection_inject.replace_selection` 执行
  （UI 与副作用分离）。

**c) 控制器接线**（`app/ui/selection_controller.py`）

- `_on_action_bubble` 增加 `action.is_rewrite` 分支 → `_show_rewrite(text, key)`。
- 连接气泡的 `replace_requested` → 调 `replace_selection`，失败/选区已变则兜底：
  `clipboard.setText(result)` + toast「已复制改写结果，可手动粘贴」。
- 回填成功后关闭气泡 + 轻 toast「已替换」。

---

## 待定问题（实现前需定）

1. **回填前是否默认开启「选区校验」**（多一次 Ctrl+C 换安全）？
   建议：默认开。这是覆盖用户原文的破坏性动作，宁可慢一点也别粘错地方。
2. **气泡内容默认可编辑 vs 只读 + 单独「编辑」按钮**？
   建议：rewrite 模式直接可编辑（用户经常想微调一个词再替换）。
3. **「翻译回填」的目标语**：固定中英互译？还是读设置页的目标语言配置？
   建议：先固定「中↔英自动判向」，目标语配置后续再加。
4. **浮标按钮布局**：平铺 vs 二级菜单（见上 A/B）。建议先平铺。
5. **富文本应用回填**：Word/飞书粘纯文本会套用光标处样式。可接受，不特殊处理。

---

## 落地顺序建议

1. **基建抽取**：`clipboard_util.py`（备份/还原/释放修饰键），capture 改为复用。
   纯重构，先有测试护栏（`tests/test_selection_capture.py` 已存在）。
2. **`selection_inject.py`**：`replace_selection` + 选区校验，纯逻辑单测
   （mock keyboard/clipboard，复用 capture 测试的套路）。
3. **气泡 rewrite 模式**：`show_rewrite` + footer + 信号。
4. **动作 + 控制器接线**：加 `mode="rewrite"` 动作、`_on_action_bubble` 分支、
   兜底逻辑。
5. **设置页**：rewrite 动作显隐开关 + 自定义提示词。
6. **live 验证**：在浏览器输入框、记事本、Word、VSCode 各测一遍替换与兜底。

---

## 风险与边界

| 风险 | 缓解 |
|---|---|
| 等 AI 期间用户点走，选区丢失 → 粘到错误位置 | 回填前 Ctrl+C 校验选区==原文，不符则转兜底复制 |
| 只读控件（网页正文、PDF）无法粘贴 | 无法可靠预判；Ctrl+V 后即使无效也不报错 → 统一提供「复制」兜底 |
| 全局 Ctrl+V 落到本应用控制台触发 SIGINT | 复用 capture 的 `except KeyboardInterrupt` 兜底 |
| 粘贴异步，还原剪贴板过早导致粘到旧内容 | 延迟还原（~300ms），一次性标志避免与取词叠加 |
| AI 输出带「这是改写后的：」前缀污染原文 | 提示词强约束「只输出结果」；必要时后处理剥离常见前缀 |
| 富文本样式被光标处样式覆盖 | 可接受，纯文本回填，不做富文本注入 |

## 与现有功能的边界（再强调）

- 取词路径（`capture_selection`）**不改逻辑**，仅抽取共享基建。
- 解释/续入/新建/存便签四个现有动作**完全不动**。
- rewrite 是新增的并行第五条路，唯一新副作用是「把文字写回源应用」，
  且只在用户显式点击时发生。
