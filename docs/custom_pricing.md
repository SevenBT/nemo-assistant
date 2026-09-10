# 自定义模型定价配置

## 概述

nemo-assistant 支持用户自定义任意 LLM 模型的定价。定价配置存储在 `config/model_pricing.json` 文件中。

**优先级规则**：
```
用户自定义定价 > LiteLLM 内置定价 > 无定价（返回 $0）
```

**一旦用户配置了某个模型的定价，系统将始终使用用户配置的价格，不再查询 LiteLLM。**

---

## 配置文件位置

- **开发环境**：`项目根目录/config/model_pricing.json`
- **打包后**：`nemo.exe 同级目录/config/model_pricing.json`

首次启动时，如果配置文件不存在，系统会自动创建默认配置。

---

## 配置格式

```json
{
  "provider/model-name": {
    "input_per_1m": 3.0,           // 输入价格（美元/百万 token）
    "output_per_1m": 15.0,         // 输出价格（美元/百万 token）
    "cache_read_per_1m": 0.3,      // 缓存读取价格（可选，默认 0）
    "source": "anthropic_official", // 定价来源（可选，备注用）
    "updated": "2024-11",          // 更新时间（可选，备注用）
    "note": "备注信息"              // 任意备注（可选）
  }
}
```

**字段说明**：
- `provider/model-name`：模型标识，格式为 `provider/model`（如 `anthropic/claude-sonnet-4-6`）
- `input_per_1m`：**必填**，输入 token 价格（美元/百万 token）
- `output_per_1m`：**必填**，输出 token 价格（美元/百万 token）
- `cache_read_per_1m`：**可选**，缓存 token 价格（Anthropic prompt caching 专用）
- `source`, `updated`, `note`：**可选**，备注字段，不影响计算

---

## 使用示例

### 示例 1：官方模型定价（Anthropic Claude）

```json
{
  "anthropic/claude-sonnet-4-6": {
    "input_per_1m": 3.0,
    "output_per_1m": 15.0,
    "cache_read_per_1m": 0.3,
    "source": "anthropic_official",
    "updated": "2024-11"
  }
}
```

**价格来源**：https://www.anthropic.com/pricing

**计算示例**：
```python
# 调用：1000 prompt + 500 completion + 800 cached
cost = (1000/1_000_000 * 3.0) +    # $0.003 (prompt)
       (500/1_000_000 * 15.0) +    # $0.0075 (completion)
       (800/1_000_000 * 0.3)       # $0.00024 (cache)
     = $0.01074
```

---

### 示例 2：本地模型（Ollama）

```json
{
  "ollama/qwen2.5-coder": {
    "input_per_1m": 0.0,
    "output_per_1m": 0.0,
    "cache_read_per_1m": 0.0,
    "note": "本地模型，零成本"
  }
}
```

**说明**：本地部署的模型设置为零成本，系统仍会记录 token 数用于统计。

---

### 示例 3：自定义 API 端点

```json
{
  "my-company/internal-llm": {
    "input_per_1m": 0.5,
    "output_per_1m": 1.0,
    "note": "公司内部模型，按算力成本计价"
  }
}
```

**说明**：企业内部部署的模型可以自定义定价（如按 GPU 小时计算的分摊成本）。

---

### 示例 4：覆盖官方定价

如果你认为 LiteLLM 的定价不准确，或者想用内部折扣价：

```json
{
  "openai/gpt-4o": {
    "input_per_1m": 4.5,
    "output_per_1m": 13.5,
    "note": "企业折扣价（官方 $5/$15，我们拿到 10% off）"
  }
}
```

**效果**：系统将使用你配置的 $4.5/$13.5，而不是 LiteLLM 内置的官方价格。

---

## 如何更新定价

### 方法 1：手动编辑 JSON（推荐）

1. 找到 `config/model_pricing.json`
2. 用文本编辑器打开（推荐 VS Code / Notepad++）
3. 添加或修改模型定价
4. 保存文件
5. 重启 nemo-assistant（或等待下次自动重载）

**注意**：
- JSON 格式必须正确（逗号、引号、括号匹配）
- 小数点用 `.` 不用 `,`（如 `3.0` 不是 `3,0`）
- 最后一项后面不能有逗号

---

### 方法 2：程序化修改（高级用户）

```python
import json
from pathlib import Path

pricing_file = Path("config/model_pricing.json")

# 读取当前配置
with open(pricing_file, "r", encoding="utf-8") as f:
    pricing = json.load(f)

# 添加新模型
pricing["anthropic/claude-opus-5"] = {
    "input_per_1m": 20.0,
    "output_per_1m": 100.0,
    "cache_read_per_1m": 2.0,
    "updated": "2025-01"
}

# 写回文件
with open(pricing_file, "w", encoding="utf-8") as f:
    json.dump(pricing, f, indent=2, ensure_ascii=False)
```

---

## 常见问题

### Q1：修改配置后需要重启吗？

**A**：当前版本需要重启 nemo-assistant。未来版本可能支持热重载。

---

### Q2：如何恢复默认配置？

**A**：删除 `config/model_pricing.json`，重启应用会自动生成默认配置。

---

### Q3：LiteLLM 有某个模型的定价，但我想用自己的价格？

**A**：直接在 `model_pricing.json` 里添加该模型的配置即可。**用户配置优先级最高**，会覆盖 LiteLLM。

---

### Q4：如何查看某次调用的实际成本？

**A**：查看 `data/traces.db` 数据库的 `llm_calls` 表：

```sql
SELECT model, cost_usd, prompt_tokens, completion_tokens, cached_tokens
FROM llm_calls
ORDER BY timestamp DESC
LIMIT 10;
```

或者使用 nemo-assistant 的 UI 查看对话历史成本统计。

---

### Q5：为什么有的模型成本显示为 $0？

**A**：三种可能：
1. **本地模型**（Ollama）配置为零成本
2. **未知模型**（定价表里没有，LiteLLM 也不认识）
3. **计算失败**（日志里会有 warning）

检查日志文件 `logs/nemo.log` 查看详细信息。

---

## 定价来源参考

**官方定价页面**：
- Anthropic Claude：https://www.anthropic.com/pricing
- OpenAI GPT：https://openai.com/pricing
- Google Gemini：https://ai.google.dev/pricing
- DeepSeek：https://platform.deepseek.com/api-docs/pricing

**更新建议**：每月检查一次官方定价，模型降价时更新配置文件。

---

## 技术实现

**核心代码**：`app/core/cost_calculator.py`

**计算逻辑**：
```python
def calculate_cost(provider, model, prompt_tokens, completion_tokens, cached_tokens):
    # 1. 尝试用户自定义定价（优先级最高）
    if model_key in custom_pricing:
        return calculate_from_custom_pricing(...)
    
    # 2. 回退到 LiteLLM 内置定价
    try:
        return litellm.completion_cost(...)
    except:
        pass
    
    # 3. 无定价，返回 None
    return None
```

**设计原则**：
- **用户第一**：用户配置的价格永远优先
- **离线可用**：基于本地 JSON 文件，不依赖网络
- **透明计算**：日志清楚记录用了哪个定价表
- **可追溯**：每次调用的成本都存入数据库

---

## 贡献定价数据

如果你发现某个模型的官方定价变更，欢迎提交 PR 更新 `_DEFAULT_PRICING`：

1. 修改 `app/core/cost_calculator.py` 里的 `_DEFAULT_PRICING`
2. 添加 `source` 和 `updated` 字段
3. 提交 PR，附上官方定价链接

---

## 更新历史

- **2026-09-10**：首次实现自定义定价配置（JSON 文件）
- **2026-09-08**：初始版本，硬编码定价表
