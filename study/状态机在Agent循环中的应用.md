# 状态机在 Agent 循环中的应用

> 基于本项目 `app/core/agent_loop.py` 和 `nanobot/nanobot/agent/loop.py` 的实践总结。

## 状态机三要素

| 要素 | 职责 | 本项目对应 |
|------|------|-----------|
| 状态（State） | 定义"我在哪" | `TurnState` 枚举（PREPARE, STREAM, EXECUTE, FEEDBACK, FINALIZE, DONE） |
| 转换表（Transitions） | 定义"怎么走" | `TRANSITIONS` 字典，key=(当前状态, 事件), value=下一状态 |
| 处理器（Handlers） | 定义"到了做什么" | `_state_xxx()` 方法，执行逻辑并返回事件字符串 |

运行时循环：
```
当前状态 → 找到 handler → 执行 → 返回事件 → 查转换表 → 得到下一状态 → 重复
```

## 状态定义语法

```python
from enum import Enum, auto

class TurnState(Enum):
    PREPARE = auto()   # auto() 自动分配递增整数，表明具体值不重要
    STREAM = auto()
    EXECUTE = auto()
```

## 轮次（Turn）的含义

| 层级 | 含义 | 对应 |
|------|------|------|
| 外层轮次 | 用户发一条消息 → Agent 最终回复 | 一个 AgentLoop 实例的完整生命周期 |
| 内层轮次 | AI 调一次工具 → 拿回结果 → 再决策 | `ctx.turn_count` 计数，受 `max_turns` 限制 |

一个外层轮次可能包含多个内层轮次（AI 连续调用多轮工具）。

## 状态机 vs if-else 对比

### 何时该用状态机

问三个问题：
1. **需要知道"我在哪"吗？** — 逻辑依赖于之前走过的路径，不只是当前输入
2. **需要从中间恢复吗？** — checkpoint/重试/断点续传
3. **需要追踪流转历史吗？** — 调试、审计、性能分析

本项目的 agent loop 三条全中：多轮循环、checkpoint 崩溃恢复、trace 计时。

### 状态机的优势

| 优势 | 说明 |
|------|------|
| 可维护性 | 状态多时 if-else 嵌套爆炸，状态机把"我在哪"和"我该做什么"分离 |
| 可观测性 | 天然产出 trace（每步状态+事件+耗时），if-else 需要手动加日志 |
| 崩溃恢复 | 状态可序列化，保存 (当前状态, 上下文) 即可恢复；if-else 的执行位置在调用栈里无法持久化 |
| 中途干预 | 每次状态转移前有明确检查点，cancel/inject 能干净工作 |

### 状态机的代价

- 代码量多 30-50%（转换表、context 类、handler 拆分）
- 简单场景过度设计（一个 API 调用不需要状态机）
- 新人理解成本：需要先看懂转换表才能理解流程

### 判断标准

| 场景 | 推荐 |
|------|------|
| 线性流程，无分支 | 顺序代码 |
| 2-3 个简单条件 | if-else |
| 状态 ≥4，有循环/恢复/观测需求 | 状态机 |

## 两种转换表设计风格

本项目存在两种风格的对比：

### app/core 风格：显式分支（多出口）

```python
# 6 个状态，10 条转移，分支逻辑全在表里
(STREAM, "has_tools") → EXECUTE
(STREAM, "no_tools")  → FINALIZE
(STREAM, "error")     → FINALIZE   # 一个状态有 3 个出口
```

优点：一眼看清所有路径，handler 简单。

### nanobot 风格：线性管道（单出口）

```python
# 8 个状态，8 条转移，几乎每个状态只返回 "ok"
RESTORE →ok→ COMPACT →ok→ COMMAND →ok→ BUILD →ok→ RUN →ok→ ...
```

优点：转换表小，状态职责单一；缺点：分支逻辑藏在 handler 内部。

## 可精简的方向

PREPARE 和 FINALIZE 是"仪式性"状态，不做实质决策：
- PREPARE 只检查空消息 → 可移到 `run()` 入口
- FINALIZE 只发 done 信号 → 可在循环退出后统一处理

去掉后状态机变为 3 个核心状态（STREAM, EXECUTE, FEEDBACK）+ DONE，转换表缩到 5-6 条。
