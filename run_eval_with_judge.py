"""运行完整评估（规则打分 + LLM-as-Judge）并生成报告。

这是 W2.1 的核心脚本：
1. 接通 judge.py（126 行代码终于被调用了）
2. 对 31 个测试用例跑一轮评估
3. 生成包含 rule_scores + judge_scores 的报告
"""
import sys
import logging
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def main():
    """运行评估主流程。"""
    from app.core.trace_store import TraceStore
    from app.core.llm_gateway import LLMGateway
    from app.tools.registry import ToolRegistry
    from app.core.conversation_prompt_builder import ConversationPromptBuilder
    from app.eval import runner
    from app.eval.judge import judge_answer

    # 1. 初始化依赖
    logger.info("Initializing components...")
    trace_store = TraceStore("data/traces.db")
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
        workspace=Path("data"),
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
    logger.info("This will take several minutes (31 cases × LLM calls)...")

    try:
        run_id = runner.run_eval(
            trace_store=trace_store,
            llm_gateway=llm_gateway,
            registry=registry,
            prompt_builder=None,  # 使用用例存储的原始消息
            label="manual_with_judge",
            judge_fn=judge_fn,  # 🎯 关键：传入 judge_fn
            progress_fn=lambda done, total, title: logger.info(
                f"Progress: {done}/{total} - {title[:50]}"
            ),
        )

        logger.info(f"✓ Evaluation completed! Run ID: {run_id}")

        # 4. 生成报告
        logger.info("\nGenerating report...")
        generate_report(trace_store, run_id)

    except Exception as e:
        logger.error(f"✗ Evaluation failed: {e}", exc_info=True)
        return 1

    return 0


def generate_report(trace_store, run_id: str):
    """生成评估报告（文本格式）。"""
    import json

    # 获取运行信息（从 list 中找到匹配的）
    runs = trace_store.list_eval_runs(limit=100)
    run = next((r for r in runs if r.get('run_id') == run_id), None)
    if not run:
        logger.error(f"Run {run_id} not found")
        return

    # 获取所有结果
    results = trace_store.get_eval_results(run_id)

    print("\n" + "=" * 80)
    print(f"EVALUATION REPORT - {run.get('started_at', '')[:19]}")
    print("=" * 80)

    # 运行元信息
    print(f"\nRun ID: {run_id}")
    print(f"Label: {run.get('label', 'N/A')}")
    print(f"Model: {run.get('model', 'N/A')}")
    print(f"Git Commit: {run.get('git_commit', 'N/A')}")
    print(f"Case Count: {run.get('case_count', 0)}")

    # 平均分数
    avg_scores = json.loads(run.get('avg_scores', '{}'))
    print(f"\n--- Average Scores ---")
    for dim, score in sorted(avg_scores.items()):
        print(f"  {dim:30s}: {score:.2f}")

    # 对比基线
    baseline_run_id = run.get('baseline_run_id')
    if baseline_run_id:
        baseline = next((r for r in runs if r.get('run_id') == baseline_run_id), None)
        if baseline:
            base_avg = json.loads(baseline.get('avg_scores', '{}'))
            print(f"\n--- Delta vs Baseline ({baseline_run_id[:8]}) ---")
            for dim in sorted(set(avg_scores.keys()) | set(base_avg.keys())):
                cur = avg_scores.get(dim, 0)
                base = base_avg.get(dim, 0)
                delta = cur - base
                status = "↑" if delta > 0.01 else "↓" if delta < -0.01 else "="
                print(f"  {dim:30s}: {delta:+.2f} {status}")

    # 逐用例详情（只显示有 judge_scores 的）
    print(f"\n--- Case Results (with Judge Scores) ---")
    judged_count = 0
    for i, res in enumerate(results, 1):
        judge_scores = res.get('judge_scores')
        if judge_scores:
            judged_count += 1
            case_id = res.get('case_id', '')[:12]
            print(f"\n{i}. Case {case_id}")

            rule_scores = json.loads(res.get('rule_scores', '{}'))
            print(f"   Rule: {dict(rule_scores)}")
            print(f"   Judge: {judge_scores}")

            reasoning = res.get('judge_reasoning', '')
            if reasoning:
                print(f"   Reasoning: {reasoning[:200]}...")

    print(f"\n{'=' * 80}")
    print(f"Total cases: {len(results)}")
    print(f"Cases with judge scores: {judged_count}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    sys.exit(main())
