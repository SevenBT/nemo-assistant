# 记忆模块设计

> 本文档梳理 Nemo Assistant 当前的长期记忆实现。
> 涉及文件：`app/models/memory.py`、`app/core/memory_manager.py`、`app/tools/memory.py`、`app/core/consolidator.py`、`app/core/dream.py`，接线在 `app/ui/main_window.py`、`app/core/conversation_prompt_builder.py`、`app/core/agent_loop.py`、`app/ui/chat_session_controller.py`。

## 1. 总览

记忆系统的目标：让 AI 跨对话记住用户偏好、项目决策、关键事实，并在每轮对话自动把这些信息注入 system prompt。

整体是「**单表存储 + 三类写入源 + 一类自动注入**」的结构：

```
                         ┌─────────────────────────────────┐
   写入源（3 种）         │         memories 表 (SQLite)      │       消费
                         │  共用 NoteManager 的 DatabaseMgr │
 ① AI 工具 save_memory ──▶│  category: personality/user/    │──▶ build_memory_context()
   （即时、AI 主动）       │            project/fact/archive  │    注入 system prompt
                         │  scope:    global / session     │    （排除 archive）
 ② Consolidator ────────▶│  source:   tool/consolidator/   │
   （token 超限压缩摘要）   │            dream                │
   写 category=archive    │                                 │
                         │                                 │
 ③ Dream ───────────────▶│  读 archive → 提炼 → 写回结构化   │
   （每小时定时提炼）       └─────────────────────────────────┘
   archive → user/project/fact
```

三种写入源职责不同：

- **save_memory 工具**：AI 在对话中判断「这条值得长期记住」时即时调用，直接写入结构化记忆。
- **Consolidator**：对话太长（token 超限）时，把旧消息压成摘要存为 `archive`，既给当前会话减负，也作为 Dream 的原料。
- **Dream**：定时把堆积的 `archive` 摘要喂给 LLM，提炼出真正值得长期保留的结构化记忆（ADD/UPDATE/DELETE），并标记 archive 已处理。

可以理解为：archive 是「短期记忆草稿」，Dream 像睡眠时的记忆固化过程，把草稿转成长期记忆。

## 2. 数据模型

`app/models/memory.py`

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 主键，自增 |
| `content` | str | 记忆内容，一句话 |
| `category` | str | 分类，见下 |
| `scope` | str | `global`（所有会话可见）/ `session`（仅特定会话） |
| `session_id` | str? | scope=session 时关联的会话 |
| `source` | str | 来源：`tool` / `consolidator` / `dream` |
| `importance` | int | 重要性 1-10，默认 5；查询按它倒序 |
| `is_processed` | bool | 仅 archive 用，标记 Dream 是否已处理 |
| `created_at` / `updated_at` | float | 时间戳 |
| `expired_at` | float? | 过期时间，`expire_stale()` 据此清理 |

### 分类（MemoryCategory）

| 分类 | 含义 | 是否注入 prompt |
|------|------|----------------|
| `personality` | AI 人设/行为风格（极少新增） | 是 |
| `user` | 用户身份/偏好/习惯 | 是 |
| `project` | 项目决策/技术选型/架构 | 是 |
| `fact` | 具体事实（文件位置、配置、流程） | 是 |
| `archive` | 对话摘要，Dream 的输入原料 | **否** |

### 范围（MemoryScope）

- `global`：所有会话共享，是注入 prompt 的主体。
- `session`：仅当前会话可见。Consolidator 生成的 archive 摘要就是 session 范围。

## 3. MemoryManager —— 持久化与生命周期

`app/core/memory_manager.py`

基于 SQLite，启动时 `_ensure_table()` 建表 + 三个索引（scope+session_id / category / is_processed）。与 `NoteManager` **共用同一个 `DatabaseManager`**（`MemoryManager(self._notes.db)`）。

关键方法：

- **CRUD**：`add` / `update` / `delete` / `get_by_id`
- **查询**：
  - `get_global(category?)` —— 所有全局记忆
  - `get_for_session(session_id)` —— 某会话的局部记忆
  - `get_context_memories(session_id)` —— 注入用：全局 + 当前 session 局部，**排除 archive**
  - `get_unprocessed_archives()` —— Dream 取料：`category=archive AND is_processed=0`
- **注入构建**：`build_memory_context(session_id, max_chars=4000)`
  - 取 `get_context_memories`，逐条拼成 `- [category] content`，累计字符超 `max_chars` 截断
  - 输出 `## 长期记忆\n\n...` 文本块，空则返回 `""`
- **维护**：
  - `mark_archives_processed(ids)` —— Dream 处理完标记
  - `expire_stale(max_age_days=30)` —— 清理 `expired_at` 过期记忆
  - `count(scope?)` —— 统计

## 4. 三种写入源

### 4.1 save_memory 工具（AI 主动）

`app/tools/memory.py` 提供三个 BuiltinTool：

| 工具 | 作用 | read_only |
|------|------|-----------|
| `save_memory` | 保存一条记忆（content/category/scope/importance） | 否 |
| `recall_memory` | 检索记忆（按 category/scope 过滤） | 是 |
| `forget_memory` | 按 id 删除 | 否 |

- 工具通过 `ctx.extra["memory_mgr"]` 拿到 MemoryManager。
- `scope=session` 时，会用注入的 `_session_id` 关联会话。
- **`_session_id` 注入机制**：`agent_loop.py` 在执行工具前把 `_session_id` 塞进 `arguments`（`agent_loop.py:404`、`:422`），不在工具 schema 中，所以 LLM 不可见也不会乱传。

### 4.2 Consolidator（对话压缩 → archive）

`app/core/consolidator.py`

触发点：每轮发消息前，`chat_session_controller.py:366` 调 `maybe_consolidate`。

流程：

1. 估算当前会话消息 token（`_estimate_tokens`：中文 1.5 字/token，英文 4 字符/token）
2. 超过阈值（`max_context_tokens=60000` 的 70%）才压缩
3. 计算保留消息数（目标压到 50%，至少保留最近 4 条）
4. 把旧消息调 LLM 生成中文 bullet 摘要（失败则 raw 截断每条前 100 字）
5. 摘要写入 memories 表：`category=archive, scope=session, importance=3, source=consolidator`
6. 返回 `[摘要系统消息] + 保留的近期消息`，controller 用它替换会话消息并存盘

注意：摘要既进了 memories 表（给 Dream 用），又作为一条 system 消息留在会话里（给当前对话用），两个用途。

### 4.3 Dream（定时提炼 archive → 结构化记忆）

`app/core/dream.py`

触发：`main_window.py` 起一个 QTimer，**每小时**（`3600_000` ms）在后台线程跑 `_run_dream`，避免阻塞 UI。

流程：

1. `get_unprocessed_archives()` 取未处理摘要，没有就直接返回
2. 连同现有全局记忆一起拼进 `_DREAM_PROMPT`
3. 调 LLM，要求输出 JSON 指令数组（ADD / UPDATE / DELETE）
4. `_parse_response` 解析（容忍 ```json 代码块包裹）
5. `_execute_directives` 执行：
   - ADD：校验 category 合法（非法回退 fact），importance 钳到 1-10，`source=dream`，写 global
   - UPDATE：按 id 更新 content/importance
   - DELETE：按 id 删除
6. `mark_archives_processed` 标记处理完

Dream 的 prompt 显式要求：冲突则 UPDATE 覆盖，过时则 DELETE，不重复已有记忆，无新信息输出 `[]`。

## 5. 消费：注入 system prompt

`app/core/conversation_prompt_builder.py:70-80`

`_build_system_prompt(session_id)` 拼接顺序：

```
用户 prompt + 内置工具说明 + [长期记忆块] + 日期时间信息
```

记忆块由 `memory_mgr.build_memory_context(session_id)` 生成，只在 `session_id` 存在且 `memory_mgr` 非空时加入。这是记忆「被读出来用」的唯一入口。

## 6. 接线与初始化

`app/ui/main_window.py`

1. `_init_tools()`：建 `MemoryManager(self._notes.db)`，放进 `ToolContext.extra["memory_mgr"]`，供 save/recall/forget 工具用。
2. `_init_memory()`：建 Consolidator 和 Dream，启动 Dream 每小时定时器。
3. `prompt_builder` 持有 `memory_mgr`，每轮构建 prompt 时注入记忆。
4. `agent_loop` 执行工具时注入 `_session_id`。

## 7. 数据流时序

**写入（AI 主动）**：对话中 AI 判断 → 调 `save_memory` → MemoryManager.add → memories 表

**写入（自动压缩）**：消息过长 → Consolidator 摘要 → archive 入库 + 会话替换为摘要消息

**提炼（睡眠固化）**：每小时 → Dream 读 archive → LLM 提炼 → ADD/UPDATE/DELETE 结构化记忆 → 标记 archive 已处理

**读取（每轮注入）**：发消息 → prompt_builder → build_memory_context（全局+session 局部，排除 archive）→ 拼进 system prompt

## 8. 现状与可改进点

- **无 UI 管理界面**：目前只能靠 AI 工具或直接读库管理记忆，用户看不到、改不了已存记忆。
- **`expire_stale` 未接线**：方法存在但没有定时调用，`expired_at` 也没有写入逻辑，过期清理实际未生效。
- **无单元测试**：`tests/` 下没有 memory/dream/consolidator 的测试。
- **token 估算粗糙**：Consolidator 用字符比例估算，与真实 tokenizer 有偏差。
- **Dream 与 Consolidator 串联依赖**：archive 只有 session 范围，Dream 提炼出的是 global，但 archive 不会自动清理（只标 is_processed），长期会堆积。
