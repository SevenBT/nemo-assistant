"""检查最新评估的 judge scores"""
import sqlite3
import json

conn = sqlite3.connect('data/traces.db')

# 检查最新 run 的 judge_scores
cursor = conn.execute('''
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN judge_scores IS NOT NULL THEN 1 ELSE 0 END) as has_judge,
        judge_scores
    FROM eval_results
    WHERE run_id LIKE "bbb2d873%"
    LIMIT 1
''')

row = cursor.fetchone()
print(f'Run bbb2d873:')
print(f'  Total cases: {row[0]}')
print(f'  Has judge_scores: {row[1]}')
print(f'  Sample judge_scores: {row[2][:100] if row[2] else None}...')

# 如果有 judge_scores，显示一些详情
if row[1] > 0:
    cursor2 = conn.execute('''
        SELECT case_id, judge_scores
        FROM eval_results
        WHERE run_id LIKE "bbb2d873%"
        AND judge_scores IS NOT NULL
        LIMIT 5
    ''')
    print('\nSample judge scores:')
    for r in cursor2:
        scores = json.loads(r[1]) if r[1] else {}
        print(f'  Case {r[0][:8]}: {scores}')

conn.close()

conn.close()
