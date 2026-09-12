"""检查评估进度"""
import sqlite3

conn = sqlite3.connect('data/traces.db')

# 查找最新的 run_id
cursor = conn.execute("""
    SELECT run_id, started_at, case_count, completed_at
    FROM eval_runs
    ORDER BY started_at DESC
    LIMIT 3
""")

print("Recent eval runs:")
for row in cursor:
    print(f"  run_id: {row[0][:8]}...")
    print(f"  started: {row[1]}")
    print(f"  cases: {row[2]}")
    print(f"  finished: {row[3]}")

    # 检查这个 run 的进度
    cursor2 = conn.execute("""
        SELECT COUNT(*), AVG(CASE WHEN actual_output IS NOT NULL THEN 1.0 ELSE 0.0 END)
        FROM eval_results
        WHERE run_id=?
    """, (row[0],))
    count, has_output = cursor2.fetchone()
    print(f"  results: {count}/{row[2]}, {int(has_output*100)}% have output")

    # 检查是否有 eval_samples
    cursor3 = conn.execute("""
        SELECT COUNT(DISTINCT trace_id)
        FROM eval_samples
        WHERE trace_id IN (
            SELECT trace_id FROM eval_results WHERE run_id=?
        )
    """, (row[0],))
    sample_count = cursor3.fetchone()[0]
    print(f"  eval_samples: {sample_count} traces\n")

conn.close()
