# Nanobot 源码分析：可借鉴的设计模式

## 概述

Nanobot 是一个成熟的 AI Agent 框架，围绕异步消息总线构建，支持多渠道、多会话、工具调用、定时任务和记忆系统。以下从六个维度分析其设计，对比我们当前项目的实现，提炼可借鉴的模式。

---

## 1. Agent Loop（核心循环）

### Nanobot 的设计

**状态机驱动的 Turn 处理**（`agent/loop.py`）：

```
RESTORE → COMPACT → COMMAND → BUILD → RUN → SAVE → RESPOND → DONE
```

- 每个状态对应一个 `_state_xxx` 方法，返回事件字符串
- 通过 `_TRANSITIONS` 字典查表决定下一状态
- `TurnContext` dataclass 贯穿整个 turn，携带所有中间状态

**AgentRunner**（`agent/runner.py`）是纯粹的 LLM 对话循环：
- 发送消息 → 接收响应 → 解析 tool_calls → 并发执行工具 → 拼接结果 → 继续循环
- 与产品层（session、channel）完全解耦
- 支持 checkpoint 回调（中途崩溃可恢复）
- 支持 injection 回调（mid-turn 注入新消息）

**并发控制**：
- `_concurrency_gate`（Semaphore）限制全局并发请求数
- `_session_locks` 保证同一 session 串行处理
- `_pending_queues` 实现 mid-turn 消息注入而非创建新 task

### 我们当前的实现

`chat_worker.py` 用 QThread + 信号槽，单线程串行处理，无状态机。

### 可借鉴

| 模式 | 价值 | 适配建议 |
|------|------|----------|
| 状态机 Turn 处理 | 清晰的生命周期，易于插入 hook | 将 chat_worker 的处理流程拆为状态机 |
| Runner 与 Loop 分离 | Runner 可复用于子任务、定时任务 | 抽取纯 LLM 对话循环为独立类 |
| Checkpoint 恢复 | 崩溃不丢失已完成的工具结果 | 每次工具执行后持久化中间状态 |
| Mid-turn 注入 | 用户可在 AI 思考时追加消息 | 用 Queue 实现"AI 执行中追加上下文" |

---

## 2. 记忆模块

### Nanobot 的设计

三层记忆架构（`agent/memory.py`）：

**MemoryStore**（纯 I/O 层）：
- `MEMORY.md` — 长期事实记忆
- `SOUL.md` — Agent 人格/身份
- `USER.md` — 用户画像
- `history.jsonl` — append-only 对话摘要日志，cursor 机制追踪已处理位置

**Consolidator**（轻量压缩）：
- Token 预算驱动：估算当前 prompt 大小，超出阈值时触发
- 按 user-turn 边界切割旧消息
- LLM 摘要 → 写入 history.jsonl
- 失败时 raw_archive 兜底（不丢数据）
- 多轮循环直到 prompt 降到 `consolidation_ratio` 以下

**Dream**（重量级记忆整理，cron 触发）：
- Phase 1：分析 history.jsonl 中未处理的条目，生成分析报告
- Phase 2：用 AgentRunner + read_file/edit_file 工具增量编辑 MEMORY.md
- Git 自动提交变更，支持 line_ages 标注过期信息
- 可自动创建 Skill（从对话模式中提炼可复用知识）

**AutoCompact**（空闲压缩）：
- TTL 过期的 session 自动归档
- 保留最近 N 条消息作为上下文尾巴
- 摘要注入下次对话的 system prompt

### 我们当前的实现

`session_manager.py` 全量 JSON 持久化，无压缩、无摘要、无长期记忆。

### 可借鉴

| 模式 | 价值 | 适配建议 |
|------|------|----------|
| JSONL append-only + cursor | 高效追加，不需重写整个文件 | 对话摘要用 JSONL 存储 |
| Token 预算驱动的压缩 | 自动控制 context 大小 | 发送前估算 token，超限时摘要旧消息 |
| LLM 摘要 + raw 兜底 | 摘要失败不丢数据 | 摘要失败时保留原始文本截断版 |
| Dream 两阶段记忆整理 | 从对话中提炼长期知识 | 定时任务触发"记忆整理"，更新用户画像 |
| 原子写入（tmp + replace + fsync） | 防崩溃数据损坏 | 所有 JSON 持久化改用原子写入 |

---

## 3. 工具调用

### Nanobot 的设计

**Tool 基类**（`agent/tools/base.py`）：
```python
class Tool(ABC):
    name: str           # 工具名
    description: str    # 给 LLM 看的描述
    parameters: dict    # JSON Schema
    read_only: bool     # 是否无副作用
    
    async def execute(self, **kwargs) -> Any: ...
    def cast_params(self, params) -> dict: ...    # 类型转换
    def validate_params(self, params) -> list: ... # 参数校验
    def to_schema(self) -> dict: ...              # OpenAI function schema
```

**ToolRegistry**（`agent/tools/registry.py`）：
- `register/unregister` 动态管理
- `prepare_call` = resolve + cast + validate（一步到位）
- `execute` 包含错误处理和提示
- `get_definitions` 缓存 + 稳定排序（利于 prompt cache）

**ToolLoader**（`agent/tools/loader.py`）：
- `pkgutil.iter_modules` 自动发现包内所有 Tool 子类
- `entry_points("nanobot.tools")` 支持外部插件
- `Tool.enabled(ctx)` 条件启用（根据配置/环境）
- `Tool._scopes` 控制工具在哪些场景可用

**并发执行**：
- `concurrent_tools=True` 时，同一轮多个 tool_call 并发执行
- `read_only` 和 `concurrency_safe` 属性控制哪些工具可并发

### 我们当前的实现

`tool_manager.py` 通过 manifest.json 发现工具，子进程隔离执行，同步阻塞。

### 可借鉴

| 模式 | 价值 | 适配建议 |
|------|------|----------|
| Tool 抽象基类 + JSON Schema | 统一的工具接口，LLM 直接用 | 将 manifest.json 改为 Python 类 |
| 自动发现 + 插件机制 | 新增工具零配置 | 保留 manifest 但加 entry_points 扩展 |
| cast_params 自动类型转换 | LLM 传 "123" 自动转 int | 在执行前加类型转换层 |
| prepare_call 一步校验 | 校验失败直接返回错误给 LLM | 统一校验入口 |
| 并发工具执行 | 多工具调用不串行等待 | asyncio.gather 并发执行无副作用工具 |
| 稳定排序的 definitions | 利于 API prompt cache | 工具列表排序后发送 |

---

## 4. 错误处理

### Nanobot 的设计

**多层防御**：

1. **Provider 层**：`chat_with_retry` 内置重试，支持 retry-after header
2. **Runner 层**：
   - 空响应重试（`_MAX_EMPTY_RETRIES = 2`）
   - 长度截断恢复（`_MAX_LENGTH_RECOVERIES = 3`）
   - 工具执行错误 → 返回错误文本给 LLM 让它自行修正
   - 重复违规检测（workspace violation、external lookup）→ 自动终止
3. **Loop 层**：
   - Checkpoint 持久化 → 崩溃恢复
   - `_restore_pending_user_turn` → 只保存了用户消息就崩溃的恢复
   - CancelledError 处理 → /stop 命令优雅中断
4. **Cron 层**：
   - 损坏文件 → 重命名为 `.corrupt-<ts>` 保留
   - 原子写入防止写入中断导致数据丢失
   - `run_history` 记录每次执行状态

**错误传播策略**：
- 工具错误 → 不抛异常，返回 `"Error: ..."` 字符串 + hint 让 LLM 换方法
- LLM 错误 → 重试 → 降级消息
- 系统错误 → 日志 + 用户友好提示

### 我们当前的实现

try/except 包裹，错误直接显示给用户，无重试、无恢复。

### 可借鉴

| 模式 | 价值 | 适配建议 |
|------|------|----------|
| 工具错误返回文本而非抛异常 | LLM 可自行修正参数重试 | tool 执行失败返回错误描述 |
| 空响应/截断自动重试 | 减少用户手动重试 | 检测空响应自动重发 |
| Checkpoint + 恢复 | 长任务中断不丢进度 | 工具链执行中持久化中间结果 |
| 损坏文件保留 + 原子写入 | 数据安全 | 所有持久化用 tmp+replace |
| 重复违规自动终止 | 防止 LLM 死循环 | 检测连续相同错误后停止 |

---

## 5. 定时任务

### Nanobot 的设计

**CronService**（`cron/service.py`）：

调度类型：
- `at` — 一次性定时（毫秒时间戳）
- `every` — 固定间隔
- `cron` — cron 表达式（支持时区）

核心机制：
- 纯 asyncio 实现（不依赖 APScheduler）
- `_arm_timer` → `asyncio.sleep` → `_on_timer` → 执行到期任务 → 重新 arm
- `max_sleep_ms` 上限（5分钟），保证不会睡太久错过任务
- FileLock 保护多实例并发写入
- Action JSONL 支持跨实例操作合并

任务执行：
- `on_job` 回调 → 注入 InboundMessage 到 MessageBus → 触发 Agent 处理
- `delete_after_run` 支持一次性任务自动清理
- `run_history` 保留最近 20 条执行记录
- 系统任务（`system_event`）受保护不可删除

### 我们当前的实现

`scheduler.py` 基于 APScheduler，执行时调用 ToolManager 运行工具脚本。

### 可借鉴

| 模式 | 价值 | 适配建议 |
|------|------|----------|
| 任务执行触发 Agent 对话 | 定时任务可以用自然语言描述 | 定时任务 → 注入消息 → AI 处理 |
| run_history 执行记录 | 可追溯、可调试 | 记录每次执行的状态和耗时 |
| 原子持久化 + 损坏恢复 | 数据安全 | jobs.json 用原子写入 |
| Action JSONL 跨实例合并 | 多进程安全 | 如果未来多窗口，可借鉴 |
| delete_after_run | 一次性提醒自动清理 | 支持"提醒我一次"类任务 |

**注意**：我们用 APScheduler 已经够用，不需要换成纯 asyncio。但"定时任务触发 AI 对话"这个模式很有价值——用户可以说"每天早上 9 点帮我总结昨天的笔记"。

---

## 6. Skill 系统

### Nanobot 的设计

**SkillsLoader**（`agent/skills.py`）：

结构：
```
skills/
  skill-name/
    SKILL.md          # Markdown 内容 + YAML frontmatter
```

Frontmatter 支持：
- `description` — 技能描述
- `always: true` — 始终加载到 context
- `requires.bins` — 依赖的命令行工具
- `requires.env` — 依赖的环境变量

加载策略：
- **Always skills** → 始终注入 system prompt
- **Summary** → 所有技能的名称+描述列表注入 prompt，LLM 按需 read_file 加载完整内容
- **Progressive loading** — 不一次性加载所有技能，按需读取

来源优先级：
- workspace/skills/ > builtin skills（同名覆盖）
- `disabled_skills` 配置可禁用

Dream 自动创建 Skill：
- 从对话模式中识别可复用知识
- 自动生成 SKILL.md 文件
- 避免与已有 skill 重复

### 我们当前的实现

无 Skill 系统。工具有 manifest.json 描述，但没有"知识/模式"层面的抽象。

### 可借鉴

| 模式 | 价值 | 适配建议 |
|------|------|----------|
| Skill = Markdown + frontmatter | 简单、人类可读、LLM 友好 | 用 Markdown 文件定义"知识片段" |
| Progressive loading | 节省 token，按需加载 | 只在 prompt 中放摘要，需要时读全文 |
| Always skills | 核心能力始终可用 | system prompt 中注入核心指令 |
| 自动 Skill 提炼 | 从使用中学习 | Dream 式定期整理常用模式 |
| 需求检查 | 缺依赖时优雅降级 | 工具缺依赖时标记不可用而非报错 |

---

## 7. 其他值得注意的设计

### Hook 系统（`agent/hook.py`）

```python
class AgentHook:
    async def before_iteration(self, ctx): ...
    async def on_stream(self, ctx, delta): ...
    async def before_execute_tools(self, ctx): ...
    async def after_iteration(self, ctx): ...
```

- `CompositeHook` 扇出到多个 hook，单个 hook 异常不影响其他
- 用于进度回调、流式输出、子 agent 状态追踪

### MessageBus（`bus/queue.py`）

- 异步队列解耦消息生产和消费
- InboundMessage / OutboundMessage 统一消息格式
- 支持多 channel 同时接入

### SubagentManager（`agent/subagent.py`）

- 主 agent 可 spawn 子 agent 执行后台任务
- 子 agent 完成后结果注入主 agent 的 pending_queue
- 独立的 ToolRegistry 和 FileStates

---

## 总结：优先级建议

按投入产出比排序：

1. **原子写入** — 改动小，防数据丢失，立即可做
2. **工具错误返回文本** — 让 LLM 自行修正，提升成功率
3. **Token 预算压缩** — 长对话不爆 context，用户体验关键
4. **定时任务触发 AI 对话** — 差异化功能，"每天帮我总结笔记"
5. **状态机 Turn 处理** — 重构量大但架构收益高，适合下次大改时做
6. **Dream 记忆整理** — 高级功能，可作为后续迭代目标
7. **Skill 系统** — 当工具/知识积累到一定量时再引入
