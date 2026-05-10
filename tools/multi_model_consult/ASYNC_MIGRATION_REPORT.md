# 异步并行调用改造报告

## 改造概述

将 `multi_model_consult` 工具从串行调用改造为异步并行调用，预期速度提升 4 倍。

## 修改的函数

### 1. `call_openai_model` → `call_openai_model_async`
- 改为异步函数（`async def`）
- 使用 `AsyncOpenAI` 替代 `OpenAI`
- 使用 `await client.chat.completions.create()`
- 保留所有参数和错误处理逻辑

### 2. `call_litellm_model` → `call_litellm_model_async`
- 改为异步函数（`async def`）
- 使用 `litellm.acompletion()` 替代 `litellm.completion()`
- 保留所有参数和错误处理逻辑

### 3. `call_model` → `call_model_async`
- 改为异步函数（`async def`）
- 使用 `asyncio.wait_for()` 为每个任务设置超时控制
- 新增 `asyncio.TimeoutError` 异常处理

### 4. `multi_model_consult` → `multi_model_consult_async`
- 改为异步函数（`async def`）
- 使用 `asyncio.gather(*tasks, return_exceptions=True)` 并行调用所有模型
- 新增异常结果处理逻辑
- 统计信息标注"并行调用"

### 5. `main()`
- 使用 `asyncio.run()` 包装异步函数
- 保持 stdin/stdout 的 JSON 通信方式不变

## 新增的 import

```python
import asyncio  # 异步编程支持
from openai import AsyncOpenAI  # 异步 OpenAI 客户端
```

## 关键改进

### 1. 并行调用
使用 `asyncio.gather()` 同时调用所有模型，而不是一个接一个：

```python
tasks = [
    call_model_async(config, p, query, context, timeout)
    for p in valid_perspectives
]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 2. 超时控制
使用 `asyncio.wait_for()` 为每个任务设置独立超时：

```python
content = await asyncio.wait_for(
    call_openai_model_async(...),
    timeout=timeout
)
```

### 3. 错误隔离
使用 `return_exceptions=True` 确保某个模型失败不影响其他模型：

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 4. 异常处理
处理两种异常：
- `asyncio.TimeoutError`：调用超时
- `Exception`：其他错误

## 验证方法

### 1. 语法验证
```bash
python -m py_compile tools/multi_model_consult/tool.py
```

### 2. 功能测试
```bash
python tools/multi_model_consult/test_async.py
```

### 3. 集成测试
通过主应用调用工具，验证 JSON 输入输出格式不变。

### 4. 性能测试
对比串行和并行版本的执行时间：
- 串行：4 个模型 × 5 秒 = 20 秒
- 并行：max(5 秒) = 5 秒
- 提升：4 倍

## 预期性能提升

### 理论提升
- 4 个模型串行调用：4 × T = 4T
- 4 个模型并行调用：max(T) ≈ T
- 提升倍数：4 倍

### 实际提升
考虑网络延迟和 API 限流，实际提升约 3-4 倍。

## 向后兼容性

### 保持不变
- JSON 输入格式
- JSON 输出格式
- 参数名称和类型
- 错误处理逻辑
- 日志格式

### 变更
- 内部实现从串行改为并行
- 统计信息标注"并行调用"

## 依赖版本

- `openai >= 1.0.0`（支持 `AsyncOpenAI`）
- `litellm`（支持 `acompletion()`）

已验证：
- `openai==2.24.0` ✓
- `litellm` 支持 `acompletion()` ✓

## 风险和注意事项

### 1. API 限流
并行调用可能触发 API 限流，建议：
- 监控 429 错误
- 必要时添加重试逻辑

### 2. 内存占用
并行调用会同时持有多个连接，内存占用略有增加。

### 3. 超时设置
确保超时时间合理（默认 30 秒），避免过长等待。

## 后续优化

1. 添加重试逻辑（针对 429 错误）
2. 添加速率限制（避免触发 API 限流）
3. 添加缓存机制（相同问题复用结果）
4. 添加流式输出（实时显示结果）

## 总结

改造成功完成，主要变更：
- 5 个函数改为异步版本
- 新增 2 个 import
- 使用 `asyncio.gather()` 实现并行调用
- 使用 `asyncio.wait_for()` 实现超时控制
- 使用 `return_exceptions=True` 实现错误隔离

预期性能提升 4 倍，向后兼容，无需修改调用方代码。
