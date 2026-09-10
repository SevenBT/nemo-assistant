"""检查 judge 评分结果"""
import sqlite3

conn = sqlite3.connect('data/traces.db')

run_id = 'd6d7a406'  # 最新的 run

# 检查 judge_scores (是 JSON 格式)
cursor = conn.execute("""
    SELECT
        COUNT(*) as total,
        COUNT(judge_scores) as scored,
        judge_scores
    FROM eval_results
    WHERE run_id LIKE ?
    LIMIT 1
""", (run_id + '%',))

row = cursor.fetchone()
print(f"Judge scores for run {run_id}:")
print(f"  Total cases: {row[0]}")
print(f"  Scored: {row[1]}")
print(f"  Sample judge_scores: {row[2]}")

# 查看所有的结果
cursor2 = conn.execute("""
    SELECT case_id, judge_scores, judge_reasoning
    FROM eval_results
    WHERE run_id LIKE ?
""", (run_id + '%',))

print("\nAll results:")
import json
for row in cursor2:
    print(f"\nCase: {row[0]}")
    if row[1]:
        scores = json.loads(row[1])
        print(f"  Scores: {scores}")
    else:
        print(f"  Scores: None")
    print(f"  Reasoning: {row[2][:200] if row[2] else 'None'}...")

conn.close()
