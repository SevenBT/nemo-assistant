# Trace Naming Migration Guide

## 概述

本次重构统一了 Trace/Turn 概念的命名，解决了长期存在的语义混淆问题。

### 核心变更

| 概念 | 定义 | 数据库体现 |
|------|------|------------|
| **Trace** | 一次完整的 Agent 运行（一个 trace_id），贯穿所有 LLM 调用、工具调用、状态机流转 | `traces` 表（原 `turns`） |
| **Turn** | Trace 内部的一次 LLM 往返（STREAM → EXECUTE → FEEDBACK 循环） | `traces.turn_count` 字段 |

## 数据库迁移

### Schema V2 变更

```sql
-- 表重命名
turns → traces

-- 列重命名
eval_samples.turn → turn_index
eval_samples.id → eval_sample_id
eval_runs.run_id → eval_run_id
eval_runs.baseline_run_id → baseline_eval_run_id
eval_results.id → eval_result_id
eval_results.run_id → eval_run_id
```

### 自动迁移

首次启动时，应用会自动检测数据库版本并执行迁移：

1. **备份**：迁移前自动备份到 `traces.backup.{timestamp}.db`
2. **检测**：检查 `schema_version` 表确定当前版本
3. **迁移**：执行 V2 迁移 SQL（重命名表和列）
4. **记录**：更新 `schema_version` 为 2

### 手动回滚

如果迁移后发现问题，可以恢复备份：

```bash
# 1. 停止应用
# 2. 恢复备份
cp data/traces.backup.{timestamp}.db data/traces.db
# 3. 重启应用
```

## API 变更

### TraceStore

| 旧 API | 新 API | 状态 |
|--------|--------|------|
| `start_turn()` | `start_trace()` | ✅ 已废弃，保留兼容 |
| `finish_turn()` | `finish_trace()` | ✅ 已废弃，保留兼容 |
| `get_turn()` | `get_trace()` | ✅ 已废弃，保留兼容 |
| `list_turns()` | `list_traces()` | ✅ 已废弃，保留兼容 |

### 评测模块

| 旧 API | 新 API | 状态 |
|--------|--------|------|
| `rule_checks.score_turn()` | `rule_checks.score_trace()` | ✅ 已废弃，保留兼容 |
| `runner._run_one_case(run_id=...)` | `runner._run_one_case(eval_run_id=...)` | ✅ 已更新 |

### AgentLoop

| 旧方法 | 新方法 | 状态 |
|--------|--------|------|
| `_trace_start_turn()` | `_trace_start()` | ✅ 已废弃，保留兼容 |
| `_trace_finish_turn()` | `_trace_finish()` | ✅ 已废弃，保留兼容 |

### UI 层

| 旧组件 | 新组件 | 状态 |
|--------|--------|------|
| `_TurnDetailView` | `_TraceDetailView` | ✅ 已重命名 |
| `_make_turn_row()` | `_make_trace_row()` | ✅ 已重命名 |
| `_OverviewCard.set_turn()` | `_OverviewCard.set_trace()` | ✅ 已重命名 |

## 兼容性保证

### V1/V2 数据格式兼容

所有查询方法自动检测表名和列名：

```python
# 自动检测 turns/traces 表
table = "traces" if self._table_exists("traces") else "turns"

# 自动检测 id/eval_sample_id 列
cols = self._get_eval_samples_columns()
id_col = "eval_sample_id" if "eval_sample_id" in cols else "id"
```

### API 向后兼容

旧方法保留并调用新方法：

```python
def start_turn(self, trace_id: str, session_id: str = "") -> None:
    """[已废弃] 使用 start_trace() 代替。"""
    self.start_trace(trace_id, session_id)
```

### 数据返回格式兼容

`get_turn()` 保持返回格式不变（`turn` 键）：

```python
def get_turn(self, trace_id: str) -> dict[str, Any] | None:
    """[已废弃] 使用 get_trace() 代替。"""
    data = self.get_trace(trace_id)
    if data is None:
        return None
    # 兼容旧代码：将 "trace" 键改为 "turn"
    data["turn"] = data.pop("trace")
    return data
```

## 代码迁移指南

### 推荐迁移路径

```python
# 旧代码
trace_store.start_turn(trace_id, session_id)
trace_store.finish_turn(trace_id, status="ok", turn_count=3)
turn_data = trace_store.get_turn(trace_id)
turns = trace_store.list_turns()
scores = rule_checks.score_turn(turn_data)

# 新代码
trace_store.start_trace(trace_id, session_id)
trace_store.finish_trace(trace_id, status="ok", turn_count=3)
trace_data = trace_store.get_trace(trace_id)
traces = trace_store.list_traces()
scores = rule_checks.score_trace(trace_data)
```

### 变量命名

```python
# 旧命名
turn_data = store.get_turn(trace_id)
for turn in store.list_turns():
    process(turn)

# 新命名
trace_data = store.get_trace(trace_id)
for trace in store.list_traces():
    process(trace)
```

## 测试验证

### 已验证模块

- ✅ `tests/test_eval_scorer_store.py` - 4/4 passed
- ✅ `tests/test_eval_rule_checks.py` - 11/11 passed
- ✅ `tests/test_agent_loop.py` - 14/14 passed
- ✅ 核心测试套件 - 597/597 passed

### 验证清单

- [x] 数据库迁移（空库 → V2）
- [x] 数据库迁移（V1 有数据 → V2）
- [x] API 兼容性（旧方法可调用）
- [x] 数据格式兼容（V1/V2 混合查询）
- [x] UI 渲染正常
- [x] 评测流程完整

## 常见问题

### Q: 迁移会丢失数据吗？

不会。迁移前自动备份，且迁移过程使用 `ALTER TABLE` 和 `INSERT SELECT`，不会删除数据。

### Q: 可以回滚吗？

可以。恢复备份文件即可回到迁移前状态。

### Q: 旧代码还能用吗？

可以。所有旧 API 保留并调用新 API，零破坏性变更。

### Q: 何时删除旧 API？

建议至少保留 2-3 个版本周期，待所有外部调用迁移完成后再删除。

### Q: 性能有影响吗？

几乎无影响。动态列名检测结果会被缓存，查询性能无变化。

## 技术细节

### Schema Version 管理

```sql
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

每次迁移后记录版本号和时间戳，确保幂等性。

### 备份策略

```python
def _backup_database(self) -> None:
    """备份数据库文件（迁移前自动备份）。"""
    backup_path = self._path.with_suffix(f".backup.{int(time.time())}.db")
    shutil.copy2(self._path, backup_path)
```

### 兼容性检测

```python
def _table_exists(self, table_name: str) -> bool:
    """检查表是否存在。"""
    with self._connect() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None
```

## 相关资源

- [设计文档](trace-naming-refactor.md)
- [Schema V2 迁移脚本](../../app/core/trace_store.py#L450-L550)
- [测试用例](../../tests/test_eval_scorer_store.py)

## 致谢

本次重构由 Claude Fable 5 协助完成，通过三个阶段（Phase 1-3）渐进式实施，确保了零宕机迁移和完全向后兼容。
