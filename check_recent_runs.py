"""检查最近的评估 runs"""
import sqlite3

conn = sqlite3.connect('data/traces.db')
cursor = conn.execute('''
    SELECT run_id, COUNT(*) as cases,
           COUNT(judge_scores) as with_scores,
           datetime(created_at, 'unixepoch', 'localtime') as time
    FROM eval_results
    GROUP BY run_id
    ORDER BY created_at DESC
    LIMIT 5
''')

print('Run ID    | Cases | With Scores | Time')
print('-' * 60)
for row in cursor:
    print(f'{row[0]:9s} | {row[1]:5d} | {row[2]:11d} | {row[3]}')

conn.close()
