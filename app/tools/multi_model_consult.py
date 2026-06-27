"""
多模型咨询工具 — 并行调用多个 AI 模型从不同视角分析问题。

设计思路：
  对于复杂问题（架构设计、安全评估等），单一模型可能有盲区。
  本工具并行调用多个模型，每个模型扮演不同角色（架构师、安全专家等），
  汇总多视角分析结果。

特点：
  - 使用 asyncio 并行调用，减少总等待时间
  - 每个视角使用不同的 system prompt 引导分析方向
  - 支持自定义视角组合和超时时间
  - enabled 属性依赖 API Key 是否配置（无 Key 则自动禁用）

注意：
  虽然工具系统整体是同步的（QThread 中执行），但本工具内部使用
  asyncio.run() 来并行调用多个 API，这在同步上下文中是安全的。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Arr, Num, Str, tool_params

if TYPE_CHECKING:
    from app.tools.context import ToolContext

logger = logging.getLogger(__name__)

# 预定义的分析视角，每个视角有独立的角色设定。
# 所有视角统一使用当前 LiteLLM 默认模型（跟随用户选择的供应商）。
PERSPECTIVES = {
    "architect": {
        "name": "架构师",
        "system_prompt": "你是一位经验丰富的系统架构师。关注可扩展性、模块化、技术选型、系统设计。提供具体的架构建议和技术方案。",
    },
    "security": {
        "name": "安全专家",
        "system_prompt": "你是一位安全专家。关注漏洞、权限控制、数据保护、OWASP Top 10。指出潜在的安全风险并提供加固建议。",
    },
    "performance": {
        "name": "性能专家",
        "system_prompt": "你是一位性能优化专家。关注响应时间、并发处理、资源占用、缓存策略。提供性能优化建议。",
    },
    "cost": {
        "name": "成本优化",
        "system_prompt": "你是一位成本优化专家。关注资源利用率、云服务成本、开发维护成本。提供成本优化建议。",
    },
}


class MultiModelConsultTool(BuiltinTool):
    """多模型并行咨询工具。"""

    def __init__(
        self,
        model: str = "",
        provider: str = "",
        api_key: str = "",
        api_base: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        self._model = model
        self._provider = provider
        self._api_key = api_key
        self._api_base = api_base
        self._max_tokens = max_tokens
        self._temperature = temperature

    @classmethod
    def create(cls, ctx: "ToolContext") -> "MultiModelConsultTool":
        """从配置中读取当前 LiteLLM 默认模型的连接信息。"""
        from app.core.config import cfg, get_litellm_provider_api_key

        model_id = cfg.get(cfg.litellmDefaultModel)
        model_cfg = next(
            (m for m in cfg.get(cfg.litellmModels) if m.get("id") == model_id),
            None,
        )
        provider = model_cfg.get("provider", "") if model_cfg else ""
        api_base = model_cfg.get("api_base", "") if model_cfg else ""
        return cls(
            model=model_id,
            provider=provider,
            api_key=get_litellm_provider_api_key(provider) if provider else "",
            api_base=api_base,
            max_tokens=cfg.get(cfg.maxTokens),
            temperature=cfg.get(cfg.temperature),
        )

    @property
    def name(self) -> str:
        return "multi_model_consult"

    @property
    def description(self) -> str:
        return "并行调用多个 AI 模型，从架构师、安全专家、性能专家等不同视角分析问题"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "query",  # query 是唯一必填参数
            query=Str("要咨询的问题"),
            perspectives=Arr(Str(), "视角列表，可选: architect, security, performance, cost"),
            context=Str("补充上下文信息"),
            timeout=Num("单个模型超时秒数，默认 30"),
        )

    @property
    def read_only(self) -> bool:
        """只读操作（只调用 API 获取分析结果）。"""
        return True

    @property
    def enabled(self) -> bool:
        """无 API Key 时自动禁用，不出现在 LLM 可用工具列表中。"""
        return bool(self._api_key)

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "").strip()
        perspectives = params.get("perspectives", ["architect", "security", "performance"])
        context = params.get("context", "").strip()
        timeout = float(params.get("timeout", 30.0))

        if not query:
            return {"status": "error", "data": {"message": "query is required"}}

        try:
            # 在同步上下文中启动 asyncio 事件循环并行调用多个模型
            result = asyncio.run(self._consult_async(query, perspectives, context, timeout))
            return {"status": "success", "data": {"query": query, "perspectives": perspectives, "result": result}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    async def _consult_async(self, query: str, perspectives: list, context: str, timeout: float) -> str:
        """异步并行调用多个视角（统一使用当前 LiteLLM 默认模型）。"""
        import litellm

        # 过滤无效的视角名称
        valid = [p for p in perspectives if p in PERSPECTIVES]
        if not valid:
            valid = ["architect", "security", "performance"]

        model_label = f"{self._provider}/{self._model}" if self._provider else self._model

        async def call_one(pid: str) -> dict:
            """调用单个模型视角。"""
            p = PERSPECTIVES[pid]
            user_content = f"问题：{query}\n\n上下文：{context}" if context else f"问题：{query}"
            kwargs: dict[str, Any] = {
                "model": model_label,
                "messages": [
                    {"role": "system", "content": p["system_prompt"]},
                    {"role": "user", "content": user_content},
                ],
                "max_tokens": self._max_tokens,
                "temperature": self._temperature,
                "api_key": self._api_key,
            }
            if self._api_base:
                kwargs["api_base"] = self._api_base
            try:
                resp = await asyncio.wait_for(
                    litellm.acompletion(**kwargs),
                    timeout=timeout,
                )
                return {"id": pid, "name": p["name"], "model": self._model, "status": "success",
                        "content": resp.choices[0].message.content}
            except Exception as e:
                return {"id": pid, "name": p["name"], "model": self._model, "status": "error", "error": str(e)}

        # 并行调用所有选中的视角
        results = await asyncio.gather(*[call_one(p) for p in valid], return_exceptions=True)

        # 格式化为 Markdown 输出
        output = f"# 多模型咨询结果\n\n**问题**: {query}\n\n"
        output += f"**咨询时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"

        success_count = 0
        for r in results:
            if isinstance(r, Exception):
                continue
            if r["status"] == "success":
                success_count += 1
                output += f"## {r['name']} ({r['model']})\n\n{r['content']}\n\n---\n\n"

        # 汇总失败的调用
        failed = [r for r in results if not isinstance(r, Exception) and r["status"] != "success"]
        if failed:
            output += "## 调用失败\n\n"
            for r in failed:
                output += f"- **{r['name']}** ({r['model']}): {r.get('error', '未知错误')}\n"

        output += f"\n**统计**: 成功 {success_count}/{len(valid)} 个模型\n"
        return output
