"""检查 eval_samples 表中是否有数据"""
import sqlite3

conn = sqlite3.connect('data/traces.db')

# 获取最近一次评估的 trace_id
cursor = conn.execute("""
    SELECT trace_id
    FROM eval_results
    WHERE run_id='38f6f6ca4aa94c76ab6678bdd5df0aba'
    LIMIT 3
""")
trace_ids = [row[0] for row in cursor.fetchall()]

print(f"Checking {len(trace_ids)} trace_ids from latest eval run:\n")

for trace_id in trace_ids:
    print(f"trace_id: {trace_id}")

    # 检查 turns 表
    cursor = conn.execute("SELECT COUNT(*) FROM turns WHERE trace_id=?", (trace_id,))
    turn_count = cursor.fetchone()[0]
    print(f"  turns: {turn_count}")

    # 检查 eval_samples 表
    cursor = conn.execute("SELECT COUNT(*) FROM eval_samples WHERE trace_id=?", (trace_id,))
    sample_count = cursor.fetchone()[0]
    print(f"  eval_samples: {sample_count}")

    if sample_count > 0:
        cursor = conn.execute("SELECT turn, answer FROM eval_samples WHERE trace_id=? LIMIT 3", (trace_id,))
        for row in cursor:
            print(f"    turn={row[0]}, answer={row[1][:80] if row[1] else None}...")
    print()

conn.close()
