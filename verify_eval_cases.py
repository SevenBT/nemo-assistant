import sqlite3

db = sqlite3.connect('data/traces.db')
db.row_factory = sqlite3.Row

cases = db.execute('''
    SELECT case_id, title, completion_note, enabled
    FROM eval_cases
    ORDER BY created_at DESC
''').fetchall()

print(f'=== Total eval_cases: {len(cases)} ===\n')

# 按分类统计
categories = {}
for c in cases:
    note = c["completion_note"] or ""
    if "Category:" in note:
        cat = note.split("Category:")[1].strip()
    else:
        cat = "legacy"
    categories[cat] = categories.get(cat, 0) + 1

print('=== By Category ===')
for cat, count in sorted(categories.items()):
    print(f"  {cat}: {count}")

print('\n=== Recent 10 cases ===')
for i, c in enumerate(cases[:10], 1):
    title = c["title"][:60] if c["title"] else "(no title)"
    enabled = "[Y]" if c["enabled"] else "[N]"
    print(f"{i:2}. {enabled} {title}")

db.close()
