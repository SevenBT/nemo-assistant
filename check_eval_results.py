"""检查评估结果中的 actual_output 和 judge_scores"""
import sqlite3

conn = sqlite3.connect('data/traces.db')
cursor = conn.execute("""
    SELECT case_id, LENGTH(actual_output),
           SUBSTR(actual_output, 1, 100),
           judge_scores
    FROM eval_results
    WHERE run_id='38f6f6ca4aa94c76ab6678bdd5df0aba'
    LIMIT 10
""")

print("Checking eval results:")
for row in cursor:
    print(f"  case_id={row[0]}")
    print(f"  output_len={row[1]}")
    print(f"  output_preview={row[2]!r}")
    print(f"  judge_scores={row[3]!r}")
    print()

conn.close()
