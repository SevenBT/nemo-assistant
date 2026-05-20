"""
多模型咨询工具 - 异步并行版本
并行调用多个 AI 模型，从不同视角分析问题
"""
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.config import cfg, get_api_key, get_litellm_provider_api_key
from openai import AsyncOpenAI

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 视角配置（仅使用 OpenAI 模型）
PERSPECTIVES = {
    "architect": {
        "name": "架构师",
        "provider": "openai",
        "model": "gpt-4o",
        "system_prompt": "你是一位经验丰富的系统架构师。关注可扩展性、模块化、技术选型、系统设计。提供具体的架构建议和技术方案。",
    },
    "security": {
        "name": "安全专家",
        "provider": "openai",
        "model": "gpt-4o",
        "system_prompt": "你是一位安全专家。关注漏洞、权限控制、数据保护、OWASP Top 10。指出潜在的安全风险并提供加固建议。",
    },
    "performance": {
        "name": "性能专家",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "system_prompt": "你是一位性能优化专家。关注响应时间、并发处理、资源占用、缓存策略。提供性能优化建议。",
    },
    "cost": {
        "name": "成本优化",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "system_prompt": "你是一位成本优化专家。关注资源利用率、云服务成本、开发维护成本。提供成本优化建议。",
    },
}


async def call_openai_model_async(
    model: str,
    system_prompt: str,
    query: str,
    context: str,
    timeout: float = 30.0
) -> str:
    """异步调用 OpenAI 模型"""
    # 验证 API Key
    api_key = get_api_key()
    if not api_key or api_key.strip() == "":
        raise ValueError("OpenAI API Key 未配置，请在设置中配置 API Key")

    logger.info(f"异步调用 OpenAI 模型: {model}, timeout={timeout}s")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=cfg.get(cfg.apiBaseUrl),
        timeout=timeout,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"问题：{query}\n\n上下文：{context}" if context else f"问题：{query}"}
    ]

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=cfg.get(cfg.maxTokens),
            temperature=cfg.get(cfg.temperature),
        )

        content = response.choices[0].message.content
        logger.info(f"模型 {model} 调用成功，返回内容长度: {len(content)}")
        return content

    except Exception as e:
        logger.error(f"调用 OpenAI 模型 {model} 失败: {str(e)}")
        raise


async def call_litellm_model_async(
    model_id: str,
    model_name: str,
    provider: str,
    system_prompt: str,
    query: str,
    context: str,
    timeout: float = 30.0
) -> dict:
    """异步调用 LiteLLM 模型"""
    try:
        import litellm
    except ImportError:
        return {
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "status": "error",
            "error": "LiteLLM 未安装",
        }

    api_key = get_litellm_provider_api_key(provider)
    if not api_key:
        return {
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "status": "error",
            "error": f"{provider} API Key 未配置",
        }

    logger.info(f"异步调用 LiteLLM 模型: {model_id} ({provider}), timeout={timeout}s")

    litellm_model = f"{provider}/{model_id}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"问题：{query}\n\n上下文：{context}" if context else f"问题：{query}"}
    ]

    try:
        response = await litellm.acompletion(
            model=litellm_model,
            messages=messages,
            max_tokens=cfg.get(cfg.maxTokens),
            temperature=cfg.get(cfg.temperature),
            api_key=api_key,
            timeout=timeout,
        )

        content = response.choices[0].message.content
        logger.info(f"模型 {model_id} 调用成功，返回内容长度: {len(content)}")

        return {
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "status": "success",
            "content": content,
        }

    except Exception as e:
        logger.error(f"调用 LiteLLM 模型 {model_id} 失败: {str(e)}")
        return {
            "model_id": model_id,
            "model_name": model_name,
            "provider": provider,
            "status": "error",
            "error": str(e),
        }

async def call_model_async(
    perspective_id: str,
    query: str,
    context: str,
    timeout: float = 30.0
) -> dict:
    """异步调用单个模型，带超时控制"""
    perspective = PERSPECTIVES[perspective_id]

    try:
        # 使用 asyncio.wait_for 为每个任务设置超时
        content = await asyncio.wait_for(
            call_openai_model_async(
                perspective["model"],
                perspective["system_prompt"],
                query,
                context,
                timeout
            ),
            timeout=timeout
        )

        return {
            "perspective_id": perspective_id,
            "perspective_name": perspective["name"],
            "model": perspective["model"],
            "provider": perspective["provider"],
            "status": "success",
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }

    except asyncio.TimeoutError:
        logger.error(f"视角 {perspective['name']} 调用超时 ({timeout}s)")
        return {
            "perspective_id": perspective_id,
            "perspective_name": perspective["name"],
            "model": perspective["model"],
            "provider": perspective["provider"],
            "status": "error",
            "error": f"调用超时 ({timeout}s)",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"视角 {perspective['name']} 调用失败: {str(e)}")
        return {
            "perspective_id": perspective_id,
            "perspective_name": perspective["name"],
            "model": perspective["model"],
            "provider": perspective["provider"],
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }


async def multi_model_consult_async(
    query: str,
    perspectives: list,
    context: str = "",
    timeout: float = 30.0
) -> str:
    """并行调用多个模型（异步版本）"""

    # 验证视角
    valid_perspectives = [p for p in perspectives if p in PERSPECTIVES]
    if not valid_perspectives:
        valid_perspectives = ["architect", "security", "performance"]

    logger.info(f"开始多模型并行咨询，视角: {valid_perspectives}, timeout={timeout}s")

    # 并行调用所有模型，使用 return_exceptions=True 确保某个模型失败不影响其他模型
    tasks = [
        call_model_async(p, query, context, timeout)
        for p in valid_perspectives
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理异常结果
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            perspective_id = valid_perspectives[i]
            perspective = PERSPECTIVES[perspective_id]
            logger.error(f"视角 {perspective['name']} 返回异常: {str(result)}")
            processed_results.append({
                "perspective_id": perspective_id,
                "perspective_name": perspective["name"],
                "model": perspective["model"],
                "provider": perspective["provider"],
                "status": "error",
                "error": str(result),
                "timestamp": datetime.now().isoformat(),
            })
        else:
            processed_results.append(result)

    # 格式化输出（Markdown）
    output = f"# 多模型咨询结果\n\n"
    output += f"**问题**: {query}\n\n"
    if context:
        output += f"**上下文**: {context[:200]}{'...' if len(context) > 200 else ''}\n\n"
    output += f"**咨询时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    output += "---\n\n"

    # 成功的结果
    success_count = 0
    for r in processed_results:
        if r["status"] == "success":
            success_count += 1
            output += f"## {r['perspective_name']} ({r['model']})\n\n"
            output += f"{r['content']}\n\n"
            output += "---\n\n"

    # 失败的结果
    failed = [r for r in processed_results if r["status"] != "success"]
    if failed:
        output += "## 调用失败的模型\n\n"
        for r in failed:
            output += f"- **{r['perspective_name']}** ({r['model']}): {r.get('error', '未知错误')}\n"
        output += "\n"

    # 统计信息
    output += f"\n**统计**: 成功 {success_count}/{len(processed_results)} 个模型（并行调用）\n"
    
    logger.info(f"多模型并行咨询完成，成功 {success_count}/{len(processed_results)} 个模型")

    return output


def main():
    """工具入口"""
    payload = json.loads(sys.stdin.read() or "{}")
    params = payload.get("params", {})

    query = params.get("query", "").strip()
    perspectives = params.get("perspectives", ["architect", "security", "performance"])
    context = params.get("context", "").strip()
    timeout = params.get("timeout", 30.0)

    if not query:
        print(
            json.dumps(
                {"status": "error", "data": {"message": "query is required"}},
                ensure_ascii=False,
            )
        )
        return

    try:
        # 使用 asyncio.run() 运行异步函数
        result = asyncio.run(multi_model_consult_async(query, perspectives, context, timeout))

        print(
            json.dumps(
                {
                    "status": "success",
                    "data": {
                        "query": query,
                        "perspectives": perspectives,
                        "result": result,
                    },
                },
                ensure_ascii=False,
            )
        )

    except Exception as e:
        logger.error(f"多模型咨询失败: {str(e)}")
        print(
            json.dumps(
                {"status": "error", "data": {"message": str(e)}},
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
