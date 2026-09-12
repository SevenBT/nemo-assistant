import sqlite3

db = sqlite3.connect('data/traces.db')
db.row_factory = sqlite3.Row

# 检查表结构
print('=== eval_runs schema ===')
schema = db.execute("PRAGMA table_info(eval_runs)").fetchall()
for col in schema:
    print(f"  {col['name']} ({col['type']})")

print('\n=== eval_cases schema ===')
schema = db.execute("PRAGMA table_info(eval_cases)").fetchall()
for col in schema:
    print(f"  {col['name']} ({col['type']})")

print('\n=== eval_results schema ===')
schema = db.execute("PRAGMA table_info(eval_results)").fetchall()
for col in schema:
    print(f"  {col['name']} ({col['type']})")

# 检查 eval_cases 表
cases = db.execute('SELECT case_id, title, user_input, enabled FROM eval_cases').fetchall()
print(f'\n=== eval_cases: {len(cases)} 条 ===')
for c in cases:
    title = c["title"] if c["title"] else "(no title)"
    print(f'  {c["case_id"][:8]}... | {title[:40]} | enabled={c["enabled"]}')

# 检查 eval_runs 表（使用正确的列名）
runs = db.execute('SELECT * FROM eval_runs ORDER BY rowid DESC LIMIT 5').fetchall()
print(f'\n=== eval_runs: {len(runs)} 条（最近5条）===')
for r in runs:
    print(f'  {dict(r)}')

# 检查 eval_results 表
results = db.execute('SELECT COUNT(*) as cnt FROM eval_results').fetchone()
print(f'\n=== eval_results: {results["cnt"]} 条 ===')

db.close()
