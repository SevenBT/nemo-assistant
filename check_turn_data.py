"""检查 turn_data 是否存在"""
import sqlite3

conn = sqlite3.connect('data/traces.db')

# 找到最新 run 的一个 trace_id
cursor = conn.execute("""
    SELECT trace_id
    FROM eval_results
    WHERE run_id LIKE 'd6d7a406%'
    LIMIT 1
""")

trace_id = cursor.fetchone()[0]
print(f"Checking trace_id: {trace_id}")

# 检查这个 trace 的 turns 表
cursor2 = conn.execute("""
    SELECT trace_id, status, turn_count
    FROM turns
    WHERE trace_id = ?
""", (trace_id,))

print("\nturns table:")
row = cursor2.fetchone()
if row:
    print(f"  trace_id: {row[0]}")
    print(f"  status: {row[1]}")
    print(f"  turn_count: {row[2]}")
else:
    print("  No turn found!")

# 检查 eval_samples
cursor3 = conn.execute("""
    SELECT COUNT(*)
    FROM eval_samples
    WHERE trace_id = ?
""", (trace_id,))

count = cursor3.fetchone()[0]
print(f"\neval_samples count: {count}")

# 检查 trace_store.get_turn() 返回什么
print("\n--- Simulating get_turn() ---")
from app.infrastructure.trace_store import TraceStore
store = TraceStore('data/traces.db')
turn_data = store.get_turn(trace_id)
if turn_data:
    print(f"turn_data keys: {list(turn_data.keys())}")
    print(f"eval_samples: {len(turn_data.get('eval_samples', []))}")
else:
    print("get_turn() returned None!")

conn.close()
