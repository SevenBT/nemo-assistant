"""直接测试 judge_fn"""
import sqlite3
import sys
sys.path.insert(0, '/d/claudecode-projects/assistant')

from app.eval.judge import default_judge

conn = sqlite3.connect('data/traces.db')

# 找到一个有 actual_output 的 case
cursor = conn.execute("""
    SELECT er.case_id, er.trace_id, er.actual_output, ec.input_text, ec.expected_output
    FROM eval_results er
    JOIN eval_cases ec ON er.case_id = ec.case_id
    WHERE er.run_id LIKE 'd6d7a406%'
    AND er.actual_output IS NOT NULL
    LIMIT 1
""")

row = cursor.fetchone()
if not row:
    print("No case found with actual_output!")
    sys.exit(1)

case_id, trace_id, actual_output, input_text, expected_output = row
print(f"Testing case: {case_id}")
print(f"  Input: {input_text[:100]}...")
print(f"  Expected: {expected_output[:100] if expected_output else 'None'}...")
print(f"  Actual: {actual_output[:100]}...")

# 构造 case 和 turn_data
case = {
    "case_id": case_id,
    "input_text": input_text,
    "expected_output": expected_output
}

# 获取 turn_data
turn_row = conn.execute("SELECT * FROM turns WHERE trace_id = ?", (trace_id,)).fetchone()
llm = conn.execute("SELECT * FROM llm_calls WHERE trace_id = ? ORDER BY seq, id", (trace_id,)).fetchall()
tools = conn.execute("SELECT * FROM tool_calls WHERE trace_id = ? ORDER BY id", (trace_id,)).fetchall()
evals = conn.execute("SELECT * FROM eval_samples WHERE trace_id = ? ORDER BY turn, id", (trace_id,)).fetchall()

turn_data = {
    "turn": dict(turn_row),
    "llm_calls": [dict(r) for r in llm],
    "tool_calls": [dict(r) for r in tools],
    "eval_samples": [dict(r) for r in evals],
}

print(f"\nTurn data:")
print(f"  llm_calls: {len(turn_data['llm_calls'])}")
print(f"  tool_calls: {len(turn_data['tool_calls'])}")
print(f"  eval_samples: {len(turn_data['eval_samples'])}")

# 调用 judge_fn
print("\n--- Calling judge_fn ---")
try:
    result = default_judge(case, turn_data)
    print(f"Judge result: {result}")
except Exception as e:
    print(f"Judge failed: {e}")
    import traceback
    traceback.print_exc()

conn.close()
