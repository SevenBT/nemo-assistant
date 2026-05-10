# LiteLLM 集成改造完成报告

## 概述

已成功为 AI Agent Desktop Assistant 项目实施 LiteLLM 集成改造，新增第三套 API 系统（LiteLLM），统一管理多个 AI 模型提供商（Anthropic、Google、DeepSeek 等）。

## 改造范围

### Phase 1: 配置层改造（app/core/config.py）

#### 新增常量
- `_ACCOUNT_LITELLM_KEY = "litellm_api_key"`

#### DEFAULT_APP_CONFIG 新增配置块
```python
"litellm": {
    "enabled": False,
    "base_url": "http://localhost:4000",
    "default_model": "gpt-4o",
    "models": [
        {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "provider": "openai",
            "enabled": True,
        },
        {
            "id": "claude-3-5-sonnet-20241022",
            "name": "Claude 3.5 Sonnet",
            "provider": "anthropic",
            "enabled": True,
        },
        {
            "id": "gemini-2.0-flash-exp",
            "name": "Gemini 2.0 Flash",
            "provider": "google",
            "enabled": False,
        },
        {
            "id": "deepseek-chat",
            "name": "DeepSeek Chat",
            "provider": "deepseek",
            "enabled": False,
        },
    ],
}
```

#### ConfigManager 新增属性和方法

**属性：**
- `litellm_config` - 返回完整的 LiteLLM 配置
- `litellm_enabled` - LiteLLM 是否启用
- `litellm_base_url` - LiteLLM 服务地址
- `litellm_api_key` - 从 keyring 读取 API Key
- `litellm_default_model` - 正常聊天使用的默认模型
- `litellm_models` - 所有可用模型列表
- `litellm_enabled_models` - 启用的模型列表（用于多模型调用）

**方法：**
- `get_litellm_model_by_id(model_id)` - 根据 ID 查找模型配置
- `update_litellm_config(api_key, **kwargs)` - 更新 LiteLLM 配置
- `update_litellm_model_enabled(model_id, enabled)` - 更新模型启用状态
- `set_litellm_models(models)` - 批量设置模型列表

#### api_type 更新
- 原值：`"openai" | "shangdao"`
- 新值：`"openai" | "shangdao" | "litellm"`

---

### Phase 2: AIClient 改造（app/core/ai_client.py）

#### chat_stream 方法路由逻辑更新
```python
api_type = self._config.api_type
if api_type == "shangdao":
    yield from self._chat_stream_shangdao(messages, tools)
elif api_type == "litellm":
    yield from self._chat_stream_litellm(messages, tools)
else:
    yield from self._chat_stream_openai(messages, tools)
```

#### 新增 _chat_stream_litellm 方法
- 使用 OpenAI SDK 调用 LiteLLM 服务
- 模型名使用 `config.litellm_default_model`
- 支持流式输出和 Tool Calling
- 完整的错误处理（API Key 缺失、连接失败等）

---

### Phase 3: multi_model_consult 改造（tools/multi_model_consult/tool.py）

#### 新增 call_litellm_model 函数
```python
def call_litellm_model(
    config: ConfigManager,
    model_id: str,
    model_name: str,
    provider: str,
    system_prompt: str,
    query: str,
    context: str,
    timeout: float = 30.0
) -> dict
```

- 使用 OpenAI SDK 调用 LiteLLM 服务
- 非流式调用（直接获取完整响应）
- 返回格式：`{"model_id", "model_name", "provider", "status", "content" or "error"}`

#### multi_model_consult 函数更新
- 从 `config.litellm_enabled_models` 读取启用的模型列表
- 串行调用每个启用的模型
- 如果没有启用的模型，返回错误提示
- 输出格式更新：显示模型名称、提供商和模型 ID

---

## 核心特性

### 1. 两种使用场景

#### 正常聊天
- 使用 `litellm.default_model`（如 gpt-4o）
- 通过 `api_type = "litellm"` 启用
- 即使所有模型开关都关闭，正常聊天仍然可用

#### 多模型调用
- multi_model_consult 工具同时调用多个模型
- 通过配置中的 `enabled` 开关控制
- 只调用 `enabled=True` 的模型

### 2. 关键约束

- **商道系统完全不动**：所有商道相关代码保持原样
- **模型开关仅用于多模型调用**：不影响正常聊天
- **改动最小化**：只新增代码，不修改现有逻辑

---

## 使用指南

### 1. 配置 LiteLLM

在应用设置中：
1. 设置 `api.api_type` 为 `"litellm"`
2. 配置 LiteLLM API Key（存储在 keyring 中）
3. 设置 `litellm.base_url`（默认 `http://localhost:4000`）
4. 设置 `litellm.default_model`（默认 `gpt-4o`）

### 2. 配置多模型调用

在 `litellm.models` 中：
- 设置 `enabled: true` 启用模型
- 设置 `enabled: false` 禁用模型

示例：
```python
config.update_litellm_model_enabled("claude-3-5-sonnet-20241022", True)
config.update_litellm_model_enabled("gemini-2.0-flash-exp", False)
```

### 3. 测试验证

#### 测试正常聊天
```python
from app.core.config import ConfigManager
from app.core.ai_client import AIClient

config = ConfigManager()
client = AIClient(config)

messages = [{"role": "user", "content": "Hello"}]
for chunk in client.chat_stream(messages):
    print(chunk)
```

#### 测试多模型调用
```python
from tools.multi_model_consult.tool import multi_model_consult

result = multi_model_consult(
    query="What is AI?",
    perspectives=[],  # 不再使用，保留兼容性
    context="",
    timeout=30.0
)
print(result)
```

---

## 文件清单

### 修改的文件
1. `app/core/config.py` - 配置管理
2. `app/core/ai_client.py` - AI 客户端
3. `tools/multi_model_consult/tool.py` - 多模型咨询工具

### 备份文件
1. `app/core/config.py.backup`
2. `app/core/ai_client.py.backup`
3. `tools/multi_model_consult/tool.py.backup`

---

## 注意事项

### 1. API Key 管理
- LiteLLM API Key 存储在系统 keyring 中
- 使用 `config.litellm_api_key` 读取
- 使用 `config.update_litellm_config(api_key="xxx")` 更新

### 2. 模型配置
- `default_model` 用于正常聊天
- `models[].enabled` 用于多模型调用
- 两者互不影响

### 3. 错误处理
- API Key 缺失：返回错误提示
- 连接失败：捕获异常并返回错误信息
- 模型调用失败：在结果中标记为 `status: "error"`

### 4. 商道系统
- 所有商道相关代码保持不变
- `api_type = "shangdao"` 时使用商道系统
- `api_type = "litellm"` 时使用 LiteLLM 系统

---

## 后续优化建议

### 1. 并行调用
- 当前 multi_model_consult 是串行调用
- 可以改为并行调用提高效率
- 使用 `asyncio` 或 `concurrent.futures`

### 2. 模型配置 UI
- 在设置界面添加 LiteLLM 配置页面
- 可视化管理模型列表和开关
- 实时测试模型连接

### 3. 缓存机制
- 对相同问题的模型响应进行缓存
- 减少重复调用
- 提高响应速度

### 4. 流式多模型调用
- 支持多个模型同时流式输出
- 实时显示每个模型的响应
- 更好的用户体验

---

## 验证清单

- [x] Phase 1: 配置层改造完成
- [x] Phase 2: AIClient 改造完成
- [x] Phase 3: multi_model_consult 改造完成
- [x] 语法检查通过
- [x] 导入测试通过
- [x] 商道系统未受影响
- [ ] 实际运行测试（需要 LiteLLM 服务）
- [ ] UI 集成测试
- [ ] 端到端测试

---

## 联系方式

如有问题或建议，请联系开发团队。

---

**改造完成时间**: 2026-05-10
**改造人员**: Claude Sonnet 4.6
**版本**: v1.0
