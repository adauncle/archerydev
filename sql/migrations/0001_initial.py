# CUSTOM-MODIFIED: 二次开发仓库 sql app 没有 0001_initial.py (上游 v1.14.0 有但 git 里没有)
# 但 db 里 django_migrations 表已经记录 sql/0001_initial 已跑过
# 这里写一个最小化的 stub, 让 Django migration graph 知道 sql/0001_initial 已就位
#
# 实战新发现 (9/17 推 110 prod 时踩坑):
# 二次开发仓库 134 dev/110 prod 推 0001 时, db 里已记录 sql/0001_initial 跑过,
# 但本地仓库没这个文件 → migration graph 不认; 真 migrate 时 state 检查报 lazy reference
# 找不到 sql.models (因为 state.models 里没有 sql.models 的 ModelState, 0001_initial 是空 operations)
#
# 修法: 用 SeparateDatabaseAndState 加 CreateModel 包含所有 lazy reference 涉及的 sql.models
# - users (AbstractUser, lowercase = 'users')
# - sqlworkflow
# - instance
# - workflowaudit
# - resourcegroup (ddl_sync.DdlSyncPair 也引用)
# database_operations=[] (Django 看到 db 有 0001_initial 记录就 skip, 不真建表)
# state_operations 加 CreateModel (让 state 知道这些 model 存在, lazy reference 能 resolve)
# @ 2026-09-17 @ mavis

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # 空 database operations: 110 prod db 里 sql_workflow / sql_users / sql_instance /
                # workflow_audit / resource_group 表已存在, 不能再 CREATE TABLE
            ],
            state_operations=[
                # 加 lazy reference 涉及的 5 个 sql.models 的 ModelState,
                # 让 state.models 里包含这些 model 的 entry, lazy reference 能 resolve
                # (Django 看到 state.models 里有 ('sql', 'users'), 'sql.users' 就能 resolve)
                # fields 只列必须的 (CharField + primary_key), lazy reference 不需要完整 field 定义
                migrations.CreateModel(
                    name="ResourceGroup",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("group_name", models.CharField(max_length=100, unique=True)),
                    ],
                    options={"db_table": "resource_group", "managed": True},
                ),
                migrations.CreateModel(
                    name="Users",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("username", models.CharField(max_length=150, unique=True)),
                    ],
                    options={"db_table": "sql_users", "managed": True},
                ),
                migrations.CreateModel(
                    name="Instance",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("instance_name", models.CharField(max_length=50)),
                    ],
                    options={"db_table": "sql_instance", "managed": True},
                ),
                migrations.CreateModel(
                    name="SqlWorkflow",
                    fields=[
                        ("id", models.BigAutoField(primary_key=True, serialize=False)),
                        ("workflow_name", models.CharField(max_length=50)),
                    ],
                    options={"db_table": "sql_workflow", "managed": True},
                ),
                migrations.CreateModel(
                    name="WorkflowAudit",
                    fields=[
                        ("audit_id", models.BigAutoField(primary_key=True, serialize=False)),
                    ],
                    options={"db_table": "workflow_audit", "managed": True},
                ),
            ],
        ),
    ]