# -*- coding: utf-8 -*-
"""D20: 把 SQL 块从镜像工单 alert 块挪到 8/26 inline 区域旁边."""
import re

P = r"G:\MiniMax工作空间\archery_dev\sql\templates\detail.html"
d = open(P, "r", encoding="utf-8").read()

# 1. 删除 alert 块里的 SQL 块
old_sql = re.search(r"\n    \{\% if mirror_sql_content \%\}.*?\{\% endif \%\}\n", d, re.DOTALL)
if not old_sql:
    print("Old SQL block not found, abort")
    raise SystemExit(1)
d = d.replace(old_sql.group(), "\n")
print(f"Removed old SQL block: {old_sql.end() - old_sql.start()} bytes")

# 2. 在 8/26 inline 区域 (line 694) 后插新 SQL 块
# 找 <div id="column-diff-result" style="display:none; margin-top:14px;"></div>\n\n{% endblock content %}
target = '<div id="column-diff-result" style="display:none; margin-top:14px;"></div>\n\n{% endblock content %}'
if target not in d:
    print("Target not found, abort")
    raise SystemExit(1)

NEW_SQL = '''<div id="column-diff-result" style="display:none; margin-top:14px;"></div>

    {# CUSTOM-MODIFIED: D20 镜像工单 SQL 内容直接显示 (9/3 11:05 实战) @ 2026-09-03 @ mavis #}
    {# 业务: 业务 RD 拿到镜像工单想知道"这工单到底要执行什么 SQL", Archery detail.html 把 SQL 藏在 workflow_log 子表展开, 等审批时主表空, 用户看不到 #}
    {# 修法: SQL 块挪到 8/26 inline 字段变更检测区域旁边 (跟原本设计挨着, 不破坏 Archery 主表 workflow_log 设计) #}
    {# D19 9/3 10:15 alert 块 SQL 块用户反馈"不应该用原本位置展示吗", 撤回挪到此处 #}
    {% if mirror_sql_content %}
    <div style="margin-top: 14px; padding: 14px; background: #f5f5f5; border-radius: 4px; border-left: 4px solid #5bc0de;">
        <strong>📝 镜像工单 SQL 内容 (自动生成, 走当前配置审批流):</strong>
        <pre style="background: white; padding: 10px 12px; border-radius: 4px; margin-top: 8px; margin-bottom: 0; font-family: 'Courier New', monospace; font-size: 13px; white-space: pre-wrap; word-wrap: break-word; max-height: 240px; overflow-y: auto;">{{ mirror_sql_content }}</pre>
    </div>
    {% endif %}

{% endblock content %}'''

d = d.replace(target, NEW_SQL, 1)
print(f"Inserted new SQL block after inline area")

open(P, "w", encoding="utf-8").write(d)
print(f"New file size: {len(d)}")

# 验证
lines = d.split("\n")
print()
print("--- mirror_sql_content 出现位置 ---")
for i, line in enumerate(lines, 1):
    if "mirror_sql_content" in line:
        print(f"{i:3d}: {line[:160]}")

print()
print("--- inline 区域 + SQL 块周边 (line 685-720) ---")
for i in range(685, min(720, len(lines))):
    print(f"{i+1:3d}: {lines[i][:160]}")
