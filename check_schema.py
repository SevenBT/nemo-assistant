"""检查表结构"""
import sqlite3

conn = sqlite3.connect('data/traces.db')

cursor = conn.execute("PRAGMA table_info(eval_results)")
print("eval_results columns:")
for row in cursor:
    print(f"  {row[1]} ({row[2]})")

conn.close()
