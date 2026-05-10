"""
多模型咨询工具 - 简化版实现
并行调用多个 AI 模型，从不同视角分析问题
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.config import ConfigManager
from openai import OpenAI

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


def call_openai_model(
    config: ConfigManager,
    model: str,
    system_prompt: str,
    query: str,
    context: str,
    timeout: float = 30.0
) -> str:
    """调用 OpenAI 模型"""
    # 验证 API Key
    if not config.api_key or config.api_key.strip() == "":
        raise ValueError("OpenAI API Key 未配置，请在设置中配置 API Key")
    
    logger.info(f"调用 OpenAI 模型: {model}, timeout={timeout}s")
    
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.api_base_url,
        timeout=timeout,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"问题：{query}\n\n上下文：{context}" if context else f"问题：{query}"}
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
        
        content = response.choices[0].message.content
        logger.info(f"模型 {model} 调用成功，返回内容长度: {len(content)}")
        return content
    
    except Exception as e:
        logger.error(f"调用 OpenAI 模型 {model} 失败: {str(e)}")
        raise


def call_model(
    config: ConfigManager,
    perspective_id: str,
    query: str,
    context: str,
    timeout: float = 30.0
) -> dict:
    """调用单个模型"""
    perspective = PERSPECTIVES[perspective_id]

    try:
        content = call_openai_model(
            config,
            perspective["model"],
            perspective["system_prompt"],
            query,
            context,
            timeout
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


def multi_model_consult(
    query: str,
    perspectives: list,
    context: str = "",
    timeout: float = 30.0
) -> str:
    """串行调用多个模型（简化版，不使用异步）"""
    config = ConfigManager()

    # 验证视角
    valid_perspectives = [p for p in perspectives if p in PERSPECTIVES]
    if not valid_perspectives:
        valid_perspectives = ["architect", "security", "performance"]

    logger.info(f"开始多模型咨询，视角: {valid_perspectives}, timeout={timeout}s")

    # 串行调用（简化实现）
    results = []
    for p in valid_perspectives:
        result = call_model(config, p, query, context, timeout)
        results.append(result)

    # 格式化输出（Markdown）
    output = f"# 多模型咨询结果\n\n"
    output += f"**问题**: {query}\n\n"
    if context:
        output += f"**上下文**: {context[:200]}{'...' if len(context) > 200 else ''}\n\n"
    output += f"**咨询时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    output += "---\n\n"

    # 成功的结果
    success_count = 0
    for r in results:
        if r["status"] == "success":
            success_count += 1
            output += f"## {r['perspective_name']} ({r['model']})\n\n"
            output += f"{r['content']}\n\n"
            output += "---\n\n"

    # 失败的结果
    failed = [r for r in results if r["status"] != "success"]
    if failed:
        output += "## 调用失败的模型\n\n"
        for r in failed:
            output += f"- **{r['perspective_name']}** ({r['model']}): {r.get('error', '未知错误')}\n"
        output += "\n"

    # 统计信息
    output += f"\n**统计**: 成功 {success_count}/{len(results)} 个模型\n"
    
    logger.info(f"多模型咨询完成，成功 {success_count}/{len(results)} 个模型")

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
        result = multi_model_consult(query, perspectives, context, timeout)

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
