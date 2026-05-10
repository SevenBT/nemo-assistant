# 读取文件
with open("tools/multi_model_consult/tool.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Line 130 before: {repr(lines[129])}")
print(f"Line 131 before: {repr(lines[130])}")
print(f"Line 132 before: {repr(lines[131])}")

# 替换第130-132行为一行
new_line = '        {"role": "user", "content": f"问题：{query}\n\n上下文：{context}" if context else f"问题：{query}"}\n'
lines[129:132] = [new_line]

print(f"New line 130: {repr(lines[129])}")

# 写回文件
with open("tools/multi_model_consult/tool.py", "w", encoding="utf-8") as f:
    f.writelines(lines)

print("已修复")
