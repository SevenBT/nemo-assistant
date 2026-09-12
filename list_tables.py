"""列出数据库中的所有表"""
import sqlite3

conn = sqlite3.connect('data/traces.db')
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:')
for row in cursor:
    print(f'  {row[0]}')
conn.close()
