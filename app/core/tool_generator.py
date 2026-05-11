"""AI-powered tool script generator.

Builds a prompt, calls AIClient, and parses the response into
manifest.json + tool.py content.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterator, Optional

from app.core.ai_client import AIClient
from app.core.config import ConfigManager


@dataclass
class ModelOverride:
    """Describes a specific model selection for tool generation.

    api_type: "openai" | "shangdao" | "litellm"
    model_id:  model identifier (e.g. "gpt-4o", "Qwen3_235B", "claude-3-5-sonnet-20241022")
    provider:  only used when api_type == "litellm" (e.g. "anthropic", "openai")
    label:     human-readable display name
    """
    api_type: str
    model_id: str
    label: str
    provider: str = ""


class _ConfigProxy:
    """Thin wrapper around ConfigManager that overrides api_type and model.

    Delegates all other attribute access to the real config so AIClient
    works without modification.
    """

    def __init__(self, real: ConfigManager, override: ModelOverride):
        self._real = real
        self._override = override

    # Overridden fields
    @property
    def api_type(self) -> str:
        return self._override.api_type

    @property
    def model(self) -> str:
        return self._override.model_id

    @property
    def shangdao_model(self) -> str:
        return self._override.model_id

    @property
    def litellm_default_model(self) -> str:
        return self._override.model_id

    def get_litellm_model_by_id(self, model_id: str) -> dict | None:
        # Return a synthetic model config for the override
        if model_id == self._override.model_id:
            return {
                "id": self._override.model_id,
                "provider": self._override.provider,
                "enabled": True,
            }
        return self._real.get_litellm_model_by_id(model_id)

    # Delegate everything else to the real config
    def __getattr__(self, name: str):
        return getattr(self._real, name)


def build_model_options(config: ConfigManager) -> list[ModelOverride]:
    """Build the list of available model options from current config."""
    options: list[ModelOverride] = []

    # Current OpenAI-compatible endpoint
    options.append(ModelOverride(
        api_type="openai",
        model_id=config.model,
        label=f"{config.model}  (当前接口)",
    ))

    # Shangdao models
    if config.shangdao_enabled:
        from app.core.config import SHANGDAO_MODELS
        for name in SHANGDAO_MODELS:
            options.append(ModelOverride(
                api_type="shangdao",
                model_id=name,
                label=f"{name}  (商道)",
            ))

    # LiteLLM enabled models
    if config.litellm_enabled:
        for m in config.litellm_enabled_models:
            options.append(ModelOverride(
                api_type="litellm",
                model_id=m["id"],
                label=f"{m['name']}  ({m['provider']})",
                provider=m["provider"],
            ))

    return options


_SYSTEM_PROMPT = """\
你是一个工具脚本生成助手，专门为「AI Agent 桌面助手」生成可直接运行的工具脚本。

## 系统协议

工具由两个文件组成：manifest.json（工具描述和参数定义）和 tool.py（工具逻辑脚本）。

### manifest.json 格式

```json
{
  "name": "tool_name",
  "description": "简明描述工具用途，AI 根据此决定何时调用",
  "script": "tool.py",
  "version": "1.0.0",
  "author": "",
  "dependencies": [],
  "parameters": {
    "param_name": {
      "type": "string|number|boolean|array|object",
      "description": "参数说明，帮助 AI 正确填写",
      "source": "ai|config|manual",
      "required": true,
      "default": "可选默认值"
    }
  }
}
```

参数 source 说明：
- ai：由 AI 根据对话上下文自动填写，会暴露给 AI
- config：由用户在设置中配置（API Key、路径等敏感信息），不暴露给 AI
- manual：每次执行前弹窗让用户手动输入

### tool.py 协议

```python
import json
import sys

def main():
    # 1. 从 stdin 读取参数（固定写法）
    payload = json.loads(sys.stdin.read() or "{}")
    params = payload.get("params", {})

    # 2. 取出参数
    value = params.get("param_name", "default")

    # 3. 执行逻辑
    # ...

    # 4. 输出结果（必须是最后一行 JSON）
    print(json.dumps({
        "status": "success",
        "data": {
            "message": "结果描述"
        }
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

关键约束：
- stdout 最后一行必须是合法 JSON，格式为 {"status": "success"|"error", "data": {...}}
- 错误时返回 {"status": "error", "data": {"message": "错误原因"}}
- 超时限制 60 秒
- 第三方库在 dependencies 中声明，系统会自动安装，无需手动 pip install
- 敏感信息（API Key、路径、账号密码）一律用 source: config，不要硬编码

## 输出要求

1. 用 ```json 代码块输出完整的 manifest.json
2. 用 ```python 代码块输出完整的 tool.py
3. 不要输出其他解释性文字，直接给出两个代码块
"""


def _extract_blocks(text: str) -> tuple[str, str]:
    """Extract manifest JSON and Python script from AI response.

    Returns (manifest_str, script_str). Either may be empty if not found.
    """
    json_match = re.search(r"```json\s*([\s\S]*?)```", text)
    py_match = re.search(r"```python\s*([\s\S]*?)```", text)
    manifest = json_match.group(1).strip() if json_match else ""
    script = py_match.group(1).strip() if py_match else ""
    return manifest, script


def stream_generate(
    requirement: str,
    config: ConfigManager,
    model_override: Optional[ModelOverride] = None,
) -> Iterator[dict]:
    """Stream tool generation from AI.

    Yields the same event dicts as AIClient.chat_stream:
      {"type": "text", "delta": str}
      {"type": "done"}
      {"type": "error", "message": str}
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"请生成一个工具：{requirement}\n\n"
                "要求：\n"
                "- 用 ```json 代码块输出 manifest.json\n"
                "- 用 ```python 代码块输出 tool.py\n"
                "- 不要输出其他内容"
            ),
        },
    ]
    effective_config = _ConfigProxy(config, model_override) if model_override else config
    client = AIClient(effective_config)
    yield from client.chat_stream(messages)


def parse_result(full_text: str) -> tuple[str, str, str]:
    """Parse the full AI response into (manifest_str, script_str, error).

    Returns (manifest_str, script_str, error_msg).
    error_msg is empty on success.
    """
    manifest_str, script_str = _extract_blocks(full_text)

    if not manifest_str:
        return "", script_str, "未找到 manifest.json 代码块，请重新生成"
    if not script_str:
        return manifest_str, "", "未找到 tool.py 代码块，请重新生成"

    # Validate manifest JSON
    try:
        manifest = json.loads(manifest_str)
    except json.JSONDecodeError as e:
        return manifest_str, script_str, f"manifest.json 格式错误：{e}"

    if "name" not in manifest:
        return manifest_str, script_str, "manifest.json 缺少 name 字段"
    if "description" not in manifest:
        return manifest_str, script_str, "manifest.json 缺少 description 字段"

    return manifest_str, script_str, ""
