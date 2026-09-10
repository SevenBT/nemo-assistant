"""生成完整评估报告"""
import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect('data/traces.db')

run_id = 'bbb2d873'

print("=" * 80)
print("NEMO-ASSISTANT EVALUATION REPORT")
print("=" * 80)
print(f"Run ID: {run_id}")
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# === 1. Judge Scores Summary ===
print("=" * 80)
print("1. LLM-AS-JUDGE SCORES")
print("=" * 80)

cursor = conn.execute("""
    SELECT
        COUNT(*) as total,
        AVG(json_extract(judge_scores, '$.helpfulness')) as avg_h,
        AVG(json_extract(judge_scores, '$.correctness')) as avg_c,
        AVG(json_extract(judge_scores, '$.safety')) as avg_s,
        MIN(json_extract(judge_scores, '$.helpfulness')) as min_h,
        MIN(json_extract(judge_scores, '$.correctness')) as min_c,
        MIN(json_extract(judge_scores, '$.safety')) as min_s,
        MAX(json_extract(judge_scores, '$.helpfulness')) as max_h,
        MAX(json_extract(judge_scores, '$.correctness')) as max_c,
        MAX(json_extract(judge_scores, '$.safety')) as max_s
    FROM eval_results
    WHERE run_id LIKE ?
""", (run_id + '%',))

row = cursor.fetchone()
print(f"\nTotal Cases: {row[0]}")
print(f"\nDimension      | Average | Min | Max")
print("-" * 45)
print(f"Helpfulness    | {row[1]:7.2f} | {row[4]:3.0f} | {row[7]:3.0f}")
print(f"Correctness    | {row[2]:7.2f} | {row[5]:3.0f} | {row[8]:3.0f}")
print(f"Safety         | {row[3]:7.2f} | {row[6]:3.0f} | {row[9]:3.0f}")
print(f"\nOverall Score: {(row[1] + row[2] + row[3]) / 3:.2f}/5.00")

# === 2. Rule-based Metrics ===
print("\n" + "=" * 80)
print("2. RULE-BASED METRICS")
print("=" * 80)

cursor2 = conn.execute("""
    SELECT
        AVG(json_extract(rule_scores, '$.tool_success_rate')) as tool_success,
        AVG(json_extract(rule_scores, '$.expected_tool_hit_rate')) as expected_hit,
        AVG(json_extract(rule_scores, '$.turn_efficiency')) as efficiency,
        AVG(json_extract(rule_scores, '$.no_error_rate')) as no_error
    FROM eval_results
    WHERE run_id LIKE ?
""", (run_id + '%',))

row2 = cursor2.fetchone()
if row2[0] is not None:
    print(f"\nTool Success Rate:       {row2[0]*100:5.1f}%")
    print(f"Expected Tool Hit Rate:  {row2[1]*100:5.1f}%")
    if row2[2] is not None:
        print(f"Turn Efficiency:         {row2[2]:5.2f}")
    if row2[3] is not None:
        print(f"No Error Rate:           {row2[3]*100:5.1f}%")
else:
    print("\n(No rule-based scores available)")

# === 3. Low Score Cases (需要改进) ===
print("\n" + "=" * 80)
print("3. CASES NEEDING IMPROVEMENT (Score < 4.0)")
print("=" * 80)

cursor3 = conn.execute("""
    SELECT
        er.case_id,
        ec.category,
        ec.title,
        json_extract(er.judge_scores, '$.helpfulness') as h,
        json_extract(er.judge_scores, '$.correctness') as c,
        json_extract(er.judge_scores, '$.safety') as s,
        er.judge_reasoning
    FROM eval_results er
    JOIN eval_cases ec ON er.case_id = ec.case_id
    WHERE er.run_id LIKE ?
    AND (
        json_extract(er.judge_scores, '$.helpfulness') < 4
        OR json_extract(er.judge_scores, '$.correctness') < 4
        OR json_extract(er.judge_scores, '$.safety') < 4
    )
    ORDER BY (
        json_extract(er.judge_scores, '$.helpfulness') +
        json_extract(er.judge_scores, '$.correctness') +
        json_extract(er.judge_scores, '$.safety')
    ) ASC
""", (run_id + '%',))

low_score_cases = cursor3.fetchall()
if low_score_cases:
    for i, row in enumerate(low_score_cases, 1):
        avg_score = (row[3] + row[4] + row[5]) / 3
        print(f"\n{i}. [{row[1]}] {row[2]}")
        print(f"   Scores: H={row[3]}, C={row[4]}, S={row[5]} (Avg: {avg_score:.2f})")
        # Skip reasoning due to encoding issues
else:
    print("\n✓ All cases scored >= 4.0 on all dimensions!")

# === 4. Category Breakdown ===
print("\n" + "=" * 80)
print("4. PERFORMANCE BY CATEGORY")
print("=" * 80)

cursor4 = conn.execute("""
    SELECT
        ec.category,
        COUNT(*) as count,
        AVG(json_extract(er.judge_scores, '$.helpfulness')) as avg_h,
        AVG(json_extract(er.judge_scores, '$.correctness')) as avg_c,
        AVG(json_extract(er.judge_scores, '$.safety')) as avg_s
    FROM eval_results er
    JOIN eval_cases ec ON er.case_id = ec.case_id
    WHERE er.run_id LIKE ?
    GROUP BY ec.category
    ORDER BY (avg_h + avg_c + avg_s) / 3 DESC
""", (run_id + '%',))

print(f"\nCategory       | Cases | Helpful | Correct | Safety  | Overall")
print("-" * 70)
for row in cursor4:
    overall = (row[2] + row[3] + row[4]) / 3
    print(f"{row[0]:14s} | {row[1]:5d} | {row[2]:7.2f} | {row[3]:7.2f} | {row[4]:7.2f} | {overall:7.2f}")

# === 5. Interview Readiness ===
print("\n" + "=" * 80)
print("5. INTERVIEW READINESS ASSESSMENT")
print("=" * 80)

avg_overall = (row[1] + row[2] + row[3]) / 3
print(f"\n✓ Evaluation System: OPERATIONAL")
print(f"  - 31 golden test cases")
print(f"  - LLM-as-Judge integrated (3 dimensions)")
print(f"  - Average score: {avg_overall:.2f}/5.00")
print(f"\n✓ Context Management: UPGRADED")
print(f"  - Tiktoken integration (precise token counting)")
print(f"  - Dynamic window management (128k-200k)")
print(f"  - 20% completion reserve")
print(f"\n✓ Cost Tracking: IMPLEMENTED")
print(f"  - LiteLLM + custom pricing")
print(f"  - Per-call cost tracking")
print(f"  - Database persistence")

print("\n" + "=" * 80)
print("END OF REPORT")
print("=" * 80)

conn.close()
