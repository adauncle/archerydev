# -*- coding: utf-8 -*-
"""D19: 把 SQL 块挪到 </p> 之后, 错误信息之前."""
P = r"G:\MiniMax工作空间\archery_dev\sql\templates\detail.html"
d = open(P, "r", encoding="utf-8").read()
lines = d.split("\n")

# 1. 删除之前错放的 SQL 块 (line 50-57 0-idx)
# 找 3 个 marker 一起匹配
del_start = None
for i, line in enumerate(lines):
    if "{% if mirror_sql_content %}" in line and i < 100:  # 在 alert 块里
        del_start = i
        break
print(f"Delete start (0-idx): {del_start}")

# 找到对应 {% endif %} 行
del_end = None
for j in range(del_start, len(lines)):
    if "{% endif %}" in lines[j]:
        del_end = j
        break
print(f"Delete end (0-idx): {del_end}")

# 删除这 6 行 (含前后空行)
# 实际: del_start 上面可能空行, 下面也可能
# 让我精准: del_start-1 到 del_end+1 全删 (含空行)
to_delete = list(range(max(0, del_start - 1), del_end + 2))
print(f"Delete lines: {[i+1 for i in to_delete]}")

# 2. 在 </p> 之后, {% if error_message %} 之前插入新 SQL 块
err_idx = None
for i, line in enumerate(lines):
    if "{% if ddl_sync_as_target.error_message %}" in line:
        err_idx = i
        break
print(f"Insert before (0-idx): {err_idx}")
print(f"Line before: {lines[err_idx-1][:100] if err_idx else '?'}")

# 准备新 SQL 块
SQL_BLOCK = r'''    {% if mirror_sql_content %}
    <div style="margin-top: 8px; margin-bottom: 0;">
        <strong>📝 自动生成的 SQL (镜像工单实际内容):</strong>
        <pre style="background: #f5f5f5; padding: 10px 12px; border-radius: 4px; margin-top: 4px; margin-bottom: 0; font-family: 'Courier New', monospace; font-size: 13px; white-space: pre-wrap; word-wrap: break-word; max-height: 240px; overflow-y: auto;">{{ mirror_sql_content }}</pre>
    </div>
    {% endif %}
'''

# 3. 删除错放的, 在新位置插入
new_lines = []
skip_until = -1
for i, line in enumerate(lines):
    if skip_until >= 0:
        if i <= skip_until:
            continue
        else:
            skip_until = -1
    if i in to_delete:
        skip_until = del_end + 1
        continue
    new_lines.append(line)
    if err_idx and i == err_idx - 1:
        # 插在 err_idx 之前 (line 索引), 即 new_lines 当前长度 - 1 之后
        new_lines.append("")  # 空行
        for sql_line in SQL_BLOCK.split("\n"):
            if sql_line:
                new_lines.append(sql_line)
            else:
                new_lines.append("")

new_d = "\n".join(new_lines)
open(P, "w", encoding="utf-8").write(new_d)
print(f"OK, new file size: {len(new_d)}, lines: {len(new_lines)}")
print()
print("--- 新位置周边 ---")
for i in range(err_idx - 3, min(err_idx + 12, len(new_lines))):
    print(f"{i+1:3d}: {new_lines[i][:160]}")
