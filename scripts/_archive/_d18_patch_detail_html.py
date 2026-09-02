# -*- coding: utf-8 -*-
"""D18: 给 sql/templates/detail.html 加 DDL 跨库同步 alert 块 (镜像/源工单标识)."""
P = r"G:\MiniMax工作空间\archery_dev\sql\templates\detail.html"
d = open(P, "r", encoding="utf-8").read()
lines = d.split("\n")

# 找 line 22 之后插入
insert_after = None
for i, line in enumerate(lines):
    if "editSqlContent" in line and "sqlworkflowcontent" in line:
        insert_after = i
        break
print(f"Insert after line (0-idx): {insert_after}")
print(f"Original: {lines[insert_after][:120]}")

# 准备 alert block, 用三引号 raw string 避免转义问题
ALERT = r'''<input type="hidden" id="sqlInstanceId" value="{{ instance_id_for_diff }}"/>
<input type="hidden" id="dbNameForDiff" value="{{ db_name_for_diff|safe }}"/>
{% if ddl_sync_as_target %}
<!-- CUSTOM-MODIFIED: 镜像工单 alert 块 (D9 阶段 1 sync_trigger.py 联动) @ 2026-09-02 @ mavis
     业务: 业务 RD 拿到镜像工单时知道这是 v0.5.0 自动生成, 能跳回源工单 -->
<div class="alert alert-info" style="margin-top: 10px;">
    <strong>🤖 DDL 跨库同步 - 镜像工单</strong>
    &nbsp; <span class="label label-default">v0.5.0 自动生成</span>
    <p style="margin-top: 8px; margin-bottom: 4px;">
        本工单由
        <a href="/detail/{{ ddl_sync_as_target.source_workflow_id }}/" target="_blank">
            wf#{{ ddl_sync_as_target.source_workflow_id }} ({{ ddl_sync_as_target.source_workflow.workflow_name }})
        </a>
        在源库 <code>{{ ddl_sync_as_target.source_workflow.instance.instance_name }} / {{ ddl_sync_as_target.source_workflow.db_name }}</code> 通过 DDL 同步触发。
    </p>
    <p style="margin-bottom: 4px;">
        目标库: <strong><code>{{ ddl_sync_as_target.target_workflow.instance.instance_name }} / {{ ddl_sync_as_target.target_workflow.db_name }}</code></strong>
        &nbsp;|&nbsp;
        同步状态:
        <span class="label label-{% if ddl_sync_as_target.sync_status == 'synced' %}success{% elif ddl_sync_as_target.sync_status == 'failed' or ddl_sync_as_target.sync_status == 'rolled_back' %}danger{% elif ddl_sync_as_target.sync_status == 'syncing' %}info{% elif ddl_sync_as_target.sync_status == 'skipped' %}warning{% else %}default{% endif %}">
            {{ ddl_sync_as_target.get_sync_status_display }}
        </span>
        &nbsp;|&nbsp;
        库对: {{ ddl_sync_as_target.pair.name }}
        &nbsp;|&nbsp;
        表: <code>{{ ddl_sync_as_target.table_name }}</code>
    </p>
    {% if ddl_sync_as_target.error_message %}
    <p style="margin-bottom: 0; color: #a94442;">
        <strong>错误信息:</strong> {{ ddl_sync_as_target.error_message }}
    </p>
    {% endif %}
</div>
{% endif %}

{% if ddl_sync_as_source %}
<!-- CUSTOM-MODIFIED: 源工单已配置跨库同步 alert 块 (W1-D4 §2.2 设计) @ 2026-09-02 @ mavis -->
<div class="alert alert-warning" style="margin-top: 10px;">
    <strong>📡 DDL 跨库同步 - 已配置</strong>
    &nbsp; <span class="label label-default">v0.5.0 联动中</span>
    <p style="margin-top: 8px; margin-bottom: 4px;">
        本工单已配置跨库同步, 共触发 <strong>{{ ddl_sync_as_source|length }}</strong> 个镜像工单:
    </p>
    <ul style="margin-bottom: 0;">
        {% for h in ddl_sync_as_source %}
        <li>
            镜像工单
            <a href="/detail/{{ h.target_workflow_id }}/" target="_blank">
                wf#{{ h.target_workflow_id }} ({{ h.target_workflow.workflow_name }})
            </a>
            → <code>{{ h.target_workflow.instance.instance_name }} / {{ h.target_workflow.db_name }}</code>
            · 状态
            <span class="label label-{% if h.sync_status == 'synced' %}success{% elif h.sync_status == 'failed' or h.sync_status == 'rolled_back' %}danger{% elif h.sync_status == 'syncing' %}info{% elif h.sync_status == 'skipped' %}warning{% else %}default{% endif %}">
                {{ h.get_sync_status_display }}
            </span>
            · 表 <code>{{ h.table_name }}</code>
        </li>
        {% endfor %}
    </ul>
</div>
{% endif %}
'''

# 拼接
new_lines = lines[: insert_after + 1] + [""] + ALERT.split("\n") + lines[insert_after + 1:]
new_d = "\n".join(new_lines)
open(P, "w", encoding="utf-8").write(new_d)
print(f"OK, new file size: {len(new_d)}, lines: {len(new_lines)}")
print()
print("--- 插入位置周边 ---")
for i in range(insert_after, min(insert_after + 6, len(new_lines))):
    print(f"{i+1:3d}: {new_lines[i][:130]}")
