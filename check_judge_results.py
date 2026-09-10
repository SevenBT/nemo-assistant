"""检查最新的带 judge 评分的结果"""
import sqlite3
import json

conn = sqlite3.connect('data/traces.db')

run_id = 'bbb2d873'

# 检查统计
cursor = conn.execute("""
    SELECT
        COUNT(*) as total,
        COUNT(judge_scores) as with_scores,
        AVG(json_extract(judge_scores, '$.helpfulness')) as avg_helpfulness,
        AVG(json_extract(judge_scores, '$.correctness')) as avg_correctness,
        AVG(json_extract(judge_scores, '$.safety')) as avg_safety
    FROM eval_results
    WHERE run_id LIKE ?
""", (run_id + '%',))

row = cursor.fetchone()
print(f"=== Run {run_id} Summary ===")
print(f"Total cases: {row[0]}")
print(f"With judge scores: {row[1]}")
print(f"\nAverage Judge Scores:")
print(f"  Helpfulness: {row[2]:.2f}/5" if row[2] else "  Helpfulness: N/A")
print(f"  Correctness: {row[3]:.2f}/5" if row[3] else "  Correctness: N/A")
print(f"  Safety: {row[4]:.2f}/5" if row[4] else "  Safety: N/A")

# 查看几个样例
print(f"\n=== Sample Cases ===")
cursor2 = conn.execute("""
    SELECT case_id, judge_scores, judge_reasoning
    FROM eval_results
    WHERE run_id LIKE ?
    LIMIT 3
""", (run_id + '%',))

for i, row in enumerate(cursor2, 1):
    print(f"\n{i}. Case {row[0][:8]}...")
    if row[1]:
        scores = json.loads(row[1])
        print(f"   Scores: H={scores.get('helpfulness')}, C={scores.get('correctness')}, S={scores.get('safety')}")
        reasoning = row[2] or scores.get('reasoning', '')
        print(f"   Reasoning: {reasoning[:100]}...")

conn.close()
