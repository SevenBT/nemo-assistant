# Trace Naming Unification Refactor

## 背景

当前代码库中 Turn 与 Trace 概念混用，导致命名不一致和语义混淆：
- `turns` 表实际存储完整 Agent Trace（一次 `AgentLoop.run()`）
- `start_turn()`, `finish_turn()`, `get_turn()` 实际操作完整 Trace
- `score_turn()` 基于完整 Trace 数据评分
- `turn_data` 变量保存完整 Trace 数据

## 领域术语定义

| 术语 | 定义 | 生命周期 |
|------|------|----------|
| **Trace** | 一次完整的 Agent 运行（一个 trace_id），贯穿所有 LLM 调用、工具调用、状态机流转 | `AgentLoop.__init__()` → `run()` 结束 |
| **Turn** | Trace 内部的一次 LLM 往返（STREAM → EXECUTE → FEEDBACK 循环） | `FEEDBACK` 状态 `turn_count += 1` |

## 重命名映射

### P0 - 核心表重命名（数据库）

| 当前名称 | 新名称 | 理由 |
|---------|--------|------|
| `turns` 表 | `traces` | 表达完整 Trace 概念 |
| `eval_samples.turn` | `eval_samples.turn_index` | 明确表示 Trace 内的 Turn 序号 |

### P1 - 评测批次消歧（数据库）

| 当前名称 | 新名称 | 理由 |
|---------|--------|------|
| `eval_runs.run_id` | `eval_runs.eval_run_id` | 避免与 Agent run 混淆 |
| `eval_runs.baseline_run_id` | `eval_runs.baseline_eval_run_id` | 与主键保持一致 |
| `eval_results.run_id` | `eval_results.eval_run_id` | 与 eval_runs 保持一致 |

### P2 - 评测表主键统一（数据库）

| 当前名称 | 新名称 | 理由 |
|---------|--------|------|
| `eval_samples.id` | `eval_samples.eval_sample_id` | 统一主键命名规范 |
| `eval_results.id` | `eval_results.eval_result_id` | 统一主键命名规范 |

### P3 - API 方法重命名（Python 代码）

| 当前名称 | 新名称 |
|---------|--------|
| `TraceStore.start_turn()` | `start_trace()` |
| `TraceStore.finish_turn()` | `finish_trace()` |
| `TraceStore.get_turn()` | `get_trace()` |
| `TraceStore.list_turns()` | `list_traces()` |
| `rule_checks.score_turn()` | `score_trace()` |
| `AgentLoop._trace_start_turn()` | `_trace_start()` |
| `AgentLoop._trace_finish_turn()` | `_trace_finish()` |

### P4 - 变量名重命名（Python 代码）

| 当前名称 | 新名称 |
|---------|--------|
| `turn_data` | `trace_data` |
| `_turns` (UI) | `_traces` |

## 实施阶段

### Phase 1: 数据库 Schema 迁移 ✅ **已完成**
- [x] 实现 schema version 跟踪
- [x] 实现自动备份功能
- [x] 编写迁移 SQL（V2）
- [x] 测试迁移脚本
- [x] TraceStore 新 API（start_trace, finish_trace, get_trace, list_traces）
- [x] 保留旧 API 兼容层（start_turn → start_trace）
- [x] 动态列名检测（兼容 V1/V2）
- [x] 更新 scorer 和 rule_checks
- [x] 测试通过（test_eval_scorer_store.py）

**Commit:** `437c8bb` - feat(trace): Phase 1 - 实现 Schema V2 迁移基础设施

### Phase 2: 更新其他模块调用 ✅ **已完成**
- [x] AgentLoop (_trace_start, _trace_finish)
- [x] Runner (trace_data, eval_run_id, get_trace, score_trace)
- [x] Cases (get_trace)
- [x] Judge (trace_data)
- [x] 测试验证通过

**Commit:** `9b1436d` - feat(trace): Phase 2 - 更新核心模块调用新 API

### Phase 3: UI 层更新 ✅ **已完成**
- [x] TracePage (_traces, _TraceDetailView, _make_trace_row)
- [x] list_traces(), get_trace()
- [x] _OverviewCard.set_trace()
- [x] V1/V2 数据兼容
- [x] 测试验证通过（597 passed）

**Commit:** `d4f2876` - feat(trace): Phase 3 - 更新 UI 层命名

### Phase 4: 文档与清理（进行中）
- [ ] 删除旧 API
- [ ] 全量测试
- [ ] 文档更新

## 迁移策略

### 数据库迁移
- 在 `_ensure_schema()` 中添加版本检测
- 自动执行迁移脚本
- 迁移前自动备份 `traces.db`

### 代码兼容
- 新旧 API 共存期（1-2 个版本）
- 旧 API 标记 `@deprecated`
- 渐进式删除旧代码

## 风险评估

| 变更 | 风险等级 | 缓解措施 |
|------|---------|---------|
| turns → traces 表重命名 | 中 | 自动备份、迁移脚本测试 |
| eval_runs 主键重命名 | 高 | 需重建表、数据完整性验证 |
| API 方法重命名 | 低 | IDE 辅助重构、渐进式迁移 |

## 验证清单

- [ ] 所有单元测试通过
- [ ] 迁移脚本在空库和有数据库上测试通过
- [ ] UI 所有 Trace 相关页面手动验证
- [ ] 评测流程端到端验证
- [ ] 文档更新完成
