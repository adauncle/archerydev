# -*- coding: utf-8 -*-
"""D19: 把 SQL 块挪到 </p> 之后, 错误信息之前 (字符串替换版)."""
import re

P = r"G:\MiniMax工作空间\archery_dev\sql\templates\detail.html"
d = open(P, "r", encoding="utf-8").read()

# 1. 删除之前错放的 SQL 块
old_block = re.search(r"\n    \{\% if mirror_sql_content \%\}.*?\{\% endif \%\}\n", d, re.DOTALL)
if old_block:
    d = d.replace(old_block.group(), "\n")
    print(f"Removed old block: {old_block.end() - old_block.start()} bytes")
else:
    print("Old block not found, abort")
    raise SystemExit(1)

# 2. 在 </p> 之后, 错误信息之前 插入新 SQL 块
target = "    </p>\n    {% if ddl_sync_as_target.error_message %}"
SQL_BLOCK = '''    {% if mirror_sql_content %}
    <div style="margin-top: 8px; margin-bottom: 0;">
        <strong>📝 自动生成的 SQL (镜像工单实际内容):</strong>
        <pre style="background: #f5f5f5; padding: 10px 12px; border-radius: 4px; margin-top: 4px; margin-bottom: 0; font-family: 'Courier New', monospace; font-size: 13px; white-space: pre-wrap; word-wrap: break-word; max-height: 240px; overflow-y: auto;">{{ mirror_sql_content }}</pre>
    </div>
    {% endif %}
''' + target

if target in d:
    d = d.replace(target, new := SQL_BLOCK, 1)
    print(f"Inserted new SQL block before error_message, total file size: {len(d)}")
else:
    print(f"Target not found, abort")
    raise SystemExit(1)

open(P, "w", encoding="utf-8").write(d)

# 验证
lines = d.split("\n")
print()
print("--- mirror_sql_content 出现位置 ---")
for i, line in enumerate(lines, 1):
    if "mirror_sql_content" in line:
        print(f"{i:3d}: {line[:160]}")

print()
print("--- 镜像工单 alert 块尾部 (line 48-65) ---")
for i in range(48, min(65, len(lines))):
    print(f"{i+1:3d}: {lines[i][:160]}")
