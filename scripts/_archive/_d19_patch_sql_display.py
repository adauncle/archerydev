# -*- coding: utf-8 -*-
"""D19: 在镜像工单 alert 块加 SQL 直接展示块."""
P = r"G:\MiniMax工作空间\archery_dev\sql\templates\detail.html"
d = open(P, "r", encoding="utf-8").read()
lines = d.split("\n")

# 找 "目标库:" 那行 (在镜像工单 alert 块里)
insert_after = None
for i, line in enumerate(lines):
    if "目标库: <strong><code>{{ ddl_sync_as_target.target_workflow.instance" in line:
        insert_after = i
        break
print(f"Insert after line (0-idx): {insert_after}")
print(f"Original: {lines[insert_after][:140]}")

# 准备 SQL 块 (放在 "目标库" 后面, "库对" 后面, "错误信息" 前面)
# 实际上"目标库 / 同步状态 / 库对 / 表"都在一个 <p> 里, 让我加在 "表" 之后
# 找 "表: <code>{{ ddl_sync_as_target.table_name }}</code>" 那行的结束
insert_after = None
for i, line in enumerate(lines):
    if "表: <code>{{ ddl_sync_as_target.table_name }}</code>" in line:
        insert_after = i
        break

if insert_after is None:
    # 找不到, 用别的 marker
    print("WARNING: 找不到'表:'  行, 用回退 marker")
    for i, line in enumerate(lines):
        if "{% if ddl_sync_as_target.error_message %}" in line:
            insert_after = i - 1  # error_message 前面
            break

print(f"Insert after line (0-idx): {insert_after}")
print(f"Original: {lines[insert_after][:140]}")

# 准备 SQL 块
SQL_BLOCK = r'''{% if mirror_sql_content %}
    <div style="margin-top: 8px; margin-bottom: 0;">
        <strong>📝 自动生成的 SQL (镜像工单实际内容):</strong>
        <pre style="background: #f5f5f5; padding: 10px 12px; border-radius: 4px; margin-top: 4px; margin-bottom: 0; font-family: 'Courier New', monospace; font-size: 13px; white-space: pre-wrap; word-wrap: break-word; max-height: 240px; overflow-y: auto;">{{ mirror_sql_content }}</pre>
    </div>
    {% endif %}
'''

new_lines = lines[: insert_after + 1] + ["", "    " + SQL_BLOCK] + lines[insert_after + 1:]
# 整理: 多个 empty line 合成 1 个
new_d = "\n".join(new_lines)
# 简单清理: 把 "    {% if %}\n\n    " 变成 "    {% if %}\n    "
new_d = new_d.replace("\n\n    {% if %}", "\n    {% if %}")
new_d = new_d.replace("\n\n    <div", "\n    <div")
open(P, "w", encoding="utf-8").write(new_d)
print(f"OK, new file size: {len(new_d)}, lines: {len(new_lines)}")
print()
print("--- 插入位置周边 ---")
for i in range(insert_after, min(insert_after + 15, len(new_lines))):
    print(f"{i+1:3d}: {new_lines[i][:140]}")
