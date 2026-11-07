"""运行完整评估（规则打分 + LLM-as-Judge）并生成报告。

运行：
    python -m scripts.eval.run_eval_with_judge --label manual-with-judge
"""
import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "traces.db"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """运行评估主流程。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--label", default="manual-with-judge")
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Only run rule-based scoring.",
    )
    args = parser.parse_args(argv)

    from app.core.trace_store import TraceStore
    from app.core.llm_gateway import LLMGateway
    from app.tools.registry import ToolRegistry
    from app.eval import runner
    from app.eval.judge import judge_answer
    from scripts.eval.report import print_eval_report

    # 1. 初始化依赖
    logger.info("Initializing components...")
    trace_store = TraceStore(args.db.resolve())
    llm_gateway = LLMGateway()
    registry = ToolRegistry()
    # prompt_builder 可选，为 None 时会 fallback 到用例存储的消息

    # 注册所有工具（使用自动发现机制）
    logger.info("Registering tools...")
    from app.tools.loader import load_builtin_tools
    from app.tools.context import ToolContext
    from app.core.config import cfg

    tool_ctx = ToolContext(
        config=cfg,
        workspace=PROJECT_ROOT / "data",
        llm_gateway=llm_gateway,
    )
    load_builtin_tools(tool_ctx, registry)  # 注意参数顺序：ctx 在前，registry 在后

    # 2. 定义 judge 函数（适配 runner 的签名）
    def judge_fn(case: dict, turn_data: dict) -> dict | None:
        """适配器：将 runner 的调用转换为 judge_answer 的参数。"""
        question = case.get("user_input", "")

        # 从 eval_samples 中提取最后一轮的答案
        samples = turn_data.get("eval_samples") or []
        answer = None
        for s in reversed(samples):
            if s.get("answer"):
                answer = s["answer"]
                break

        if not answer or not answer.strip():
            logger.debug(f"Skipping judge for case {case.get('case_id', '')[:8]}: no answer")
            return None

        try:
            logger.info(f"Calling judge for case {case.get('case_id', '')[:8]}...")
            result = judge_answer(
                llm_gateway=llm_gateway,
                question=question,
                answer=answer,
            )
            logger.info(f"Judge result: {result}")
            return result
        except Exception as e:
            logger.warning(f"Judge failed for case {case.get('case_id', '')[:8]}: {e}")
            return None

    # 3. 运行评估
    logger.info("Starting evaluation run...")

    try:
        run_id = runner.run_eval(
            trace_store=trace_store,
            llm_gateway=llm_gateway,
            registry=registry,
            prompt_builder=None,  # 使用用例存储的原始消息
            label=args.label,
            judge_fn=None if args.no_judge else judge_fn,
            progress_fn=lambda done, total, title: logger.info(
                f"Progress: {done}/{total} - {title[:50]}"
            ),
        )

        logger.info(f"✓ Evaluation completed! Run ID: {run_id}")

        # 4. 生成报告
        logger.info("\nGenerating report...")
        print_eval_report(trace_store, run_id)

    except Exception as e:
        logger.error(f"✗ Evaluation failed: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
