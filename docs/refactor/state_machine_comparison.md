# 聊天状态管理对比：当前项目 vs Nanobot 状态机

## 概述

本文对比当前项目（ChatWorker 线性循环）与 Nanobot（状态机驱动）在聊天消息处理流程上的设计差异，分析各自的优劣和可借鉴之处。

---

## 1. 当前项目：线性循环

### 架构

```
main_window._on_submit()
    ├── 创建 Message，保存到 session
    ├── 构建 api_messages
    └── 启动 ChatWorker (QThread)

ChatWorker.run()
    └── for turn in range(MAX_TURNS):
            ├── chat_stream() → 收集文本 + tool_calls
            ├── 无 tool_calls → finished，退出
            └── 有 tool_calls:
                ├── 逐个执行工具
                ├── 结果追加到 messages
                └── emit new_ai_turn，继续循环
```

### 关键代码（`chat_worker.py`）

```python
def run(self):
    messages = list(self._messages)
    for _turn in range(MAX_TURNS):
        if self._cancelled:
            return
        # 1. 调用 LLM
        for chunk in self._ai.chat_stream(messages, self._tools):
            ...
        # 2. 无工具调用 → 结束
        if not tool_calls:
            self.finished.emit()
            return
        # 3. 执行工具 → 追加结果 → 下一轮
        for tc in tool_calls:
            result = self._tm.execute(tool_name, resolved)
            messages.append({"role": "tool", ...})
        self.new_ai_turn.emit()
    self.finished.emit()
```

### 状态管理方式

| 方面 | 实现 |
|------|------|
| 流程控制 | `for` 循环 + `if/return` |
| 状态存储 | 局部变量（`messages`, `tool_calls`, `full_text`） |
| 持久化时机 | 提交时立即保存用户消息；完成后由 `_on_bg_finished` 保存 AI 消息 |
| 错误处理 | `error.emit(msg)` → 直接终止 |
| 取消机制 | `_cancelled` 标志位，每轮开头检查 |
| 中间状态恢复 | 无 |

---

## 2. Nanobot：状态机驱动

### 架构

```
MessageBus → AgentLoop._process_message()
    ├── 创建 TurnContext(state=RESTORE)
    └── while state != DONE:
            handler = _state_{state.name}(ctx)
            event = await handler(ctx)
            state = _TRANSITIONS[(state, event)]

状态流转：
RESTORE → COMPACT → COMMAND → BUILD → RUN → SAVE → RESPOND → DONE
                        ↓ (shortcut)
                       DONE
```

### 关键代码（`loop.py`）

```python
_TRANSITIONS = {
    (TurnState.RESTORE, "ok"):      TurnState.COMPACT,
    (TurnState.COMPACT, "ok"):      TurnState.COMMAND,
    (TurnState.COMMAND, "dispatch"): TurnState.BUILD,
    (TurnState.COMMAND, "shortcut"): TurnState.DONE,
    (TurnState.BUILD, "ok"):        TurnState.RUN,
    (TurnState.RUN, "ok"):          TurnState.SAVE,
    (TurnState.SAVE, "ok"):         TurnState.RESPOND,
    (TurnState.RESPOND, "ok"):      TurnState.DONE,
}

while ctx.state is not TurnState.DONE:
    handler = getattr(self, f"_state_{ctx.state.name.lower()}")
    event = await handler(ctx)
    ctx.state = self._TRANSITIONS[(ctx.state, event)]
```

### 状态管理方式

| 方面 | 实现 |
|------|------|
| 流程控制 | 转换表查表 + while 循环 |
| 状态存储 | `TurnContext` dataclass（贯穿整个 turn） |
| 持久化时机 | SAVE 状态专门负责；checkpoint 在工具执行后立即保存 |
| 错误处理 | 每个状态独立处理；工具错误返回文本让 LLM 重试 |
| 取消机制 | `CancelledError` 异常 + 优雅中断 |
| 中间状态恢复 | Checkpoint 机制，崩溃后从断点恢复 |

---

## 3. 逐维度对比

### 3.1 流程可见性

| | 当前项目 | Nanobot |
|--|---------|---------|
| 当前阶段 | 不可知（在 for 循环的某处） | `ctx.state` 明确标识 |
| 执行轨迹 | 无记录 | `ctx.trace` 记录每个状态的耗时和事件 |
| 调试 | 需要断点或 print | 日志自动输出 `[turn xxx] State BUILD took 12.3ms -> event ok` |

### 3.2 分支与跳转

| | 当前项目 | Nanobot |
|--|---------|---------|
| 提前结束 | `if not tool_calls: return` | COMMAND 返回 `"shortcut"` → 跳到 DONE |
| 新增分支 | 在 for 循环中加 if/else | 加一行转换规则 + 一个 handler |
| 条件跳过 | 硬编码 | 状态 handler 返回不同 event 即可 |

### 3.3 崩溃恢复

| | 当前项目 | Nanobot |
|--|---------|---------|
| 进程崩溃 | 丢失所有中间状态，用户需重新发送 | Checkpoint 保存已完成的工具结果，重启后恢复 |
| 网络中断 | 直接报错终止 | 重试机制 + checkpoint |
| 长任务保护 | 无 | 每次工具执行后持久化 |

### 3.4 可扩展性

| | 当前项目 | Nanobot |
|--|---------|---------|
| 加新阶段 | 改 for 循环内部逻辑 | 加 `_state_xxx` 方法 + 转换规则 |
| 加 hook | 需要在具体位置手动调用 | 状态机驱动循环自动在每个状态前后触发 |
| 加监控 | 侵入式修改 | 驱动循环统一记录 trace |

### 3.5 并发与取消

| | 当前项目 | Nanobot |
|--|---------|---------|
| 并发模型 | QThread，一个会话一个线程 | asyncio，session_lock 保证串行 |
| 取消 | `_cancelled` 标志，下一轮才检查 | `CancelledError` 立即中断当前 await |
| 用户追加消息 | 不支持（worker 运行中不能发新消息） | `pending_queue` 支持 mid-turn 注入 |

### 3.6 持久化安全

| | 当前项目 | Nanobot |
|--|---------|---------|
| 写入方式 | `json.dump` 直接写文件 | 原子写入（tmp + os.replace + fsync） |
| 崩溃风险 | 写入中断 → 文件损坏 | 原子操作保证完整性 |
| 损坏恢复 | 无 | 损坏文件重命名为 `.corrupt-<ts>` 保留 |

---

## 4. 当前项目的优势

不是所有场景都需要状态机，当前设计也有其合理性：

| 优势 | 说明 |
|------|------|
| 简单直观 | 线性循环一眼看懂，维护成本低 |
| 适合桌面应用 | QThread + 信号槽是 PyQt 的标准模式 |
| 轻量 | 无额外抽象开销，启动快 |
| 足够当前需求 | 单用户桌面应用，不需要并发/恢复 |

---

## 5. 如果要引入状态机

### 适合引入的时机

- 需要崩溃恢复（长工具链执行中断）
- 需要 mid-turn 消息注入（用户在 AI 思考时追加上下文）
- 需要在流程中插入新阶段（如 token 压缩、记忆检索）
- 需要统一的执行追踪和监控

### 最小改造方案

不需要完全照搬 Nanobot 的 7 个状态，可以从 3 个状态开始：

```python
class TurnState(Enum):
    PREPARE = auto()   # 构建消息、检查 token 预算
    EXECUTE = auto()   # LLM 对话 + 工具循环
    FINALIZE = auto()  # 保存结果、更新 UI
    DONE = auto()

_TRANSITIONS = {
    (TurnState.PREPARE, "ok"):    TurnState.EXECUTE,
    (TurnState.PREPARE, "skip"):  TurnState.DONE,      # 空消息等
    (TurnState.EXECUTE, "ok"):    TurnState.FINALIZE,
    (TurnState.EXECUTE, "error"): TurnState.FINALIZE,   # 错误也要保存
    (TurnState.FINALIZE, "ok"):   TurnState.DONE,
}
```

### 渐进式迁移路径

1. **第一步**：将 `ChatWorker.run()` 拆为 `_prepare()` / `_execute()` / `_finalize()` 三个方法，保持 for 循环不变
2. **第二步**：引入 `TurnContext` dataclass 替代散落的局部变量
3. **第三步**：加转换表和驱动循环，替代硬编码的方法调用顺序
4. **第四步**：在 PREPARE 中加 token 预算检查和历史压缩
5. **第五步**：加 checkpoint 持久化（可选，视需求）

---

## 6. 总结

| 维度 | 当前项目 | Nanobot | 差距影响 |
|------|---------|---------|---------|
| 流程清晰度 | 中（线性但隐式） | 高（状态显式） | 调试和扩展时体现 |
| 崩溃恢复 | 无 | 完善 | 长工具链场景关键 |
| 可扩展性 | 低（改循环体） | 高（加状态） | 功能增多时体现 |
| 复杂度 | 低 | 中 | 当前规模下线性循环够用 |
| 监控追踪 | 无 | 内置 trace | 排查问题时体现 |

**建议**：当前阶段不急于引入完整状态机。优先做两件低成本高收益的事：
1. 将 `ChatWorker.run()` 拆为独立方法（提高可读性，为未来状态机铺路）
2. 加原子写入（防数据丢失，改动极小）
