"""生成完整评估报告"""
import sqlite3
import json
from collections import defaultdict

conn = sqlite3.connect('data/traces.db')

run_id = 'bbb2d873'

# 1. 获取 run 信息
cursor = conn.execute('''
    SELECT run_id, label, started_at, completed_at, case_count, avg_scores, baseline_run_id
    FROM eval_runs
    WHERE run_id LIKE ?
''', (run_id + '%',))

run = cursor.fetchone()
if not run:
    print(f"Run {run_id} not found!")
    exit(1)

print("=" * 80)
print("NEMO ASSISTANT - EVALUATION REPORT")
print("=" * 80)
print(f"\nRun ID: {run[0]}")
print(f"Label: {run[1]}")
print(f"Started: {run[2]}")
print(f"Completed: {run[3]}")
print(f"Duration: {(float(run[3].split('T')[1].split(':')[0]) - float(run[2].split('T')[1].split(':')[0])) * 60:.1f} minutes")
print(f"Cases: {run[4]}")

# 2. 平均分数
avg_scores = json.loads(run[5]) if run[5] else {}
print(f"\n--- Average Scores ---")
for dim, score in sorted(avg_scores.items()):
    print(f"  {dim:30s}: {score:.2f}")

# 3. Judge 分数统计
cursor2 = conn.execute('''
    SELECT judge_scores
    FROM eval_results
    WHERE run_id LIKE ?
    AND judge_scores IS NOT NULL
''', (run_id + '%',))

judge_stats = defaultdict(list)
total_judge = 0
for row in cursor2:
    total_judge += 1
    scores = json.loads(row[0])
    for dim, val in scores.items():
        if dim != 'reasoning' and isinstance(val, (int, float)):
            judge_stats[dim].append(val)

print(f"\n--- Judge Scores (n={total_judge}) ---")
for dim in ['helpfulness', 'correctness', 'safety']:
    if dim in judge_stats and judge_stats[dim]:
        vals = judge_stats[dim]
        avg = sum(vals) / len(vals)
        min_v = min(vals)
        max_v = max(vals)
        print(f"  {dim:30s}: avg={avg:.2f}, range=[{min_v}, {max_v}]")

# 4. 按分数分布
print(f"\n--- Score Distribution ---")
for dim in ['helpfulness', 'correctness', 'safety']:
    if dim in judge_stats:
        print(f"\n  {dim}:")
        for score in [1, 2, 3, 4, 5]:
            count = sum(1 for v in judge_stats[dim] if v == score)
            pct = count / len(judge_stats[dim]) * 100 if judge_stats[dim] else 0
            bar = '█' * int(pct / 5)
            print(f"    {score}: {count:2d} ({pct:5.1f}%) {bar}")

# 5. 得分最低的用例
print(f"\n--- Low Score Cases (judge < 4 in any dimension) ---")
cursor3 = conn.execute('''
    SELECT er.case_id, ec.title, er.judge_scores
    FROM eval_results er
    JOIN eval_cases ec ON er.case_id = ec.case_id
    WHERE er.run_id LIKE ?
    AND er.judge_scores IS NOT NULL
''', (run_id + '%',))

low_score_cases = []
for row in cursor3:
    case_id, title, judge_scores_str = row
    scores = json.loads(judge_scores_str)
    min_score = min([v for k, v in scores.items() if k != 'reasoning' and isinstance(v, (int, float))])
    if min_score < 4:
        low_score_cases.append((case_id, title, scores, min_score))

low_score_cases.sort(key=lambda x: x[3])
for case_id, title, scores, min_score in low_score_cases[:10]:
    print(f"\n  Case: {title[:60]}")
    print(f"    ID: {case_id}")
    print(f"    Scores: h={scores.get('helpfulness', 'N/A')}, c={scores.get('correctness', 'N/A')}, s={scores.get('safety', 'N/A')}")
    reasoning = scores.get('reasoning', '')
    if reasoning:
        print(f"    Reason: {reasoning[:100]}...")

# 6. 工具命中率分析
print(f"\n--- Tool Hit Rate Analysis ---")
cursor4 = conn.execute('''
    SELECT er.case_id, ec.expected_tools, er.rule_scores
    FROM eval_results er
    JOIN eval_cases ec ON er.case_id = ec.case_id
    WHERE er.run_id LIKE ?
''', (run_id + '%',))

tool_cases = []
for row in cursor4:
    case_id, expected_tools_str, rule_scores_str = row
    if expected_tools_str:
        expected = json.loads(expected_tools_str) if isinstance(expected_tools_str, str) else expected_tools_str
        if expected:
            rule_scores = json.loads(rule_scores_str) if rule_scores_str else {}
            hit_rate = rule_scores.get('expected_tool_hit_rate', 0)
            tool_cases.append((expected, hit_rate))

if tool_cases:
    avg_hit_rate = sum(h for _, h in tool_cases) / len(tool_cases)
    print(f"  Average tool hit rate: {avg_hit_rate:.2%}")
    print(f"  Cases with expected tools: {len(tool_cases)}/{run[4]}")

    perfect = sum(1 for _, h in tool_cases if h >= 0.99)
    partial = sum(1 for _, h in tool_cases if 0.01 < h < 0.99)
    miss = sum(1 for _, h in tool_cases if h < 0.01)
    print(f"  Perfect match (100%): {perfect}")
    print(f"  Partial match (1-99%): {partial}")
    print(f"  Complete miss (0%): {miss}")

print(f"\n{'=' * 80}")
print("Report generated successfully")
print(f"{'=' * 80}\n")

conn.close()
