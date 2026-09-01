# 9/1 W2 D6 DDL 跨库同步 数据模型 migration (3 张表) (9/1 15:25)

## 概要

W2 实施阶段 D6 (按计划 9/7 周一, 实际 9/1 周二提前 5 天落地) 数据模型 migration 跑通. 3 张表 DdlSyncPair + DdlSyncTable + DdlSyncHistory 在 134 dev /opt/archery/prod 跑通 makemigrations + migrate + Django ORM 验证 22 字段全部跟 D2 §2-§4 一致.

## 4 文件本地代码 (W1-D2 数据模型 + W1-D3 service 拆分)

```
sql/extensions/ddl_sync/
├── __init__.py                    563B  default_app_config 引用
├── apps.py                        215B  DdlSyncConfig
├── models.py                     9.3KB  3 张表完整字段定义
└── migrations/
    ├── __init__.py                  0B  空
    └── 0001_initial.py          6.6KB  Django 自动生成 (1 个合并 migration)
```

## 3 张表 22 字段 + 7 关联字段 (跟 D2 §2-§4 1:1)

**DdlSyncPair (13 字段 + 2 关联)**:
- name / source_instance / source_db / target_instance / target_db
- sync_mode (CharField, default='blacklist') R1
- enabled (BooleanField)
- pending_tables (JSONField) R3 Phase 2
- filter_rule (JSONField) R3 Phase 3
- created_by / created_at / updated_at

**DdlSyncTable (5 字段 + 1 关联)**:
- pair (FK) / table_name
- sync_type (CharField, default='whitelist') R2
- transform_rule (JSONField) / created_at

**DdlSyncHistory (9 字段 + 2 关联)**:
- pair (FK) / source_workflow (FK PROTECT) / target_workflow (FK SET_NULL)
- table_name / ddl_text / transformed_ddl_text (D2 拍板 3A)
- sync_status (CharField, 5 选 1) / error_message
- created_at / finished_at

## archery/settings.py 改动 (1 行 + 4 行注释)

```python
## CUSTOM-MODIFIED: v0.5.0-alpha DDL 跨库同步 启用开关 @ 2026-09-01 @ mavis
## 跟 v0.3.0 gh-ost 套路一致, 默认 True, 需要时通过 env 关
## 设计参考: docs/designs/2026-09-01_ddl-sync-data-model.md
if env("CUSTOM_DDL_SYNC_ENABLED", default=True):
    INSTALLED_APPS += ("sql.extensions.ddl_sync.apps.DdlSyncConfig",)
```

按 8/24 ddl_gh_ost 实战套路 (`if CUSTOM_GH_OST_ENABLED:`), 用 env 守门, 默认 True 启用.

## 134 dev 跑通验证 (5/5 PASS)

| 步骤 | 命令 | 结果 |
|------|------|------|
| 1. SFTP 推 4 文件 | scp + chown | ✓ archery:archery |
| 2. settings.py 加 INSTALLED_APPS | sed edit + SFTP 推 | ✓ 备份 settings.py.bak_20260901_1511 |
| 3. kill gunicorn + nohup 拉新 | pkill -9 + setsid nohup | ✓ 4-11h 老 master 杀, 新 master 启动 (pid 21763) |
| 4. makemigrations ddl_sync | manage.py makemigrations | ✓ 1 个 0001_initial.py (82 行, Django 合并 3 个 model) |
| 5. migrate ddl_sync | manage.py migrate | ✓ 3 张表创建成功 + 9 个 Django Permission 自动生成 |

**Django ORM 验证 (manage.py shell)**:
- `<DdlSyncConfig: ddl_sync>` 已在 INSTALLED_APPS ✓
- DdlSyncPair 13 字段 (含 2 FK 关联) ✓
- DdlSyncTable 5 字段 (含 1 FK) ✓
- DdlSyncHistory 9 字段 (含 2 FK) ✓

**5+1 端点 verify (8/27 实战 11+1 加 DDL 同步端点)**:
- /admin/ddl_sync/ddlsyncpair/ → 302 (重定向 login) ✓
- /admin/ddl_sync/ddlsynctable/ → 302 ✓
- /admin/ddl_sync/ddlsynchistory/ → 302 ✓
- /login/ → 200 ✓

## 避坑 (8/24 ddl_gh_ost 实战经验复用)

1. **5.7/8.0 兼容**: models.py 字段类型选 MySQL 5.7 + 8.0 都支持 (JSONField 8.0 5.7.8+ 都支持)
2. **8/24 ddl_gh_ost INSTALLED_APPS 套路**: 用 `if env("CUSTOM_DDL_SYNC_ENABLED", default=True):` 守门, 跟 gh-ost 一致
3. **kill gunicorn**: gunicorn master 跑 4-11h 不 reload Python, 必 pkill -9 + nohup 拉新 (8/24 + 8/27 实战)
4. **app label 不是 full path**: `manage.py makemigrations ddl_sync` (label) 不是 `sql_extensions_ddl_sync` (path) — 这个错我踩了, 第一次 makemigrations 报 "No installed app with label 'sql_extensions_ddl_sync'"
5. **mysqldump 跳过 .env 跟 admin 后台**: 134 dev 没 .my.cnf, mysql 验证失败, 改用 Django ORM 验证更稳

## D2 §5 5 migration 计划 调整

D2 §5 规划 5 个 migration (0001_initial + 0002_ddlsynctable_sync_type + 0003_ddlghostpair_blacklist_default + 0004_ddlghostpair_pending_tables + 0005_ddlghostpair_filter_rule), 但 Django 自动合并进 1 个 0001_initial.py.

DBA 团队后续是否要拆 5 个 migration (按 R1/R2/R3 阶段命名) 待 D7 库对管理 CRUD 时拍板. 134 dev / 110 prod 都是新装, 1 个 initial migration 已足够功能等价.

## 改动文件

```
sql/extensions/ddl_sync/__init__.py              (新, 563B)
sql/extensions/ddl_sync/apps.py                  (新, 215B)
sql/extensions/ddl_sync/models.py                (新, 9.3KB)
sql/extensions/ddl_sync/migrations/__init__.py   (新, 0B)
sql/extensions/ddl_sync/migrations/0001_initial.py (新, 6.6KB, Django 自动生成)
archery/settings.py                              (改, 加 1 行 INSTALLED_APPS + 4 行注释)
```

## 134 dev 备份

```
/opt/archery/prod/archery/settings.py.bak_20260901_1511
```

## 提交

待 commit + push origin main

## 下一步 (W2 D7 按计划 9/8 周二, 实际可提前)

- D7 (9/8 周二): 库对管理 CRUD + admin (W1-D3 §2 + W1-D4 §1)
  - views/pair_views.py (库对列表 + 详情 + 创建)
  - admin.py (Django admin 后台)
  - forms/pair_form.py
  - templates/pair_list.html / pair_detail.html / pair_form.html
- D8 (9/9 周三): 5 按钮 + R1 批量导入 (W1-D3 §3 + W1-D4 §1.1-§1.3)
- D9 (9/10 周四): R2 一键配 + R3 走当前配置 (W1-D3 §4 §5 + W1-D4 §1.2)
- D10 (9/11 周五): 134 dev 端到端演练 5 Case (W1-D5 §1)
