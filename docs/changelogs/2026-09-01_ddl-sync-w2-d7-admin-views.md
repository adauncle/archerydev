# 9/1 W2 D7 DDL 跨库同步 库对管理 CRUD + admin (阶段 1) (9/1 15:35)

## 概要

W2 实施阶段 D7 (按计划 9/8 周二, 实际 9/1 周二提前 5 天) 库对管理 CRUD 后端 + admin 部分跑通. 134 dev /opt/archery/prod 跑通 5 步必做 (SFTP 推 + chown + 清 __pycache__ + kill gunicorn + nohup 拉新) + 4 端点 verify + Django check no issues.

## 5 文件改动

```
sql/extensions/ddl_sync/admin.py              7.6KB  3 张表 admin 注册 (DdlSyncPairAdmin + DdlSyncTableAdmin + DdlSyncHistoryAdmin)
sql/extensions/ddl_sync/forms.py              2.5KB  DdlSyncPairForm (创建/编辑 + 业务/历史库不能同 instance+db 校验)
sql/extensions/ddl_sync/views/__init__.py     5.5KB  4 view: pair_list / pair_detail / pair_create / pair_edit
sql/extensions/ddl_sync/urls.py               1.6KB  5 view 端点 URL 路由 (D8 5 AJAX 端点 留 TODO 注释)
archery/urls.py                              +1 行 include 路由 (CUSTOM-MODIFIED 头, 跟 ddl_gh_ost 套路)
```

## 4 view 端点 (D7 阶段 1)

| URL | view | 用途 | perm 守卫 |
|-----|------|------|-----------|
| `/ddl_sync/pair/list/` | `pair_list` | 库对列表 (DBA 视角) | `ddl_sync.view_ddlsyncpair` |
| `/ddl_sync/pair/create/` | `pair_create` | 新建库对 (DBA 视角) | `ddl_sync.add_ddlsyncpair` |
| `/ddl_sync/pair/<int:pair_id>/` | `pair_detail` | 库对详情 (4 tab, 5 按钮占位) | `ddl_sync.view_ddlsyncpair` |
| `/ddl_sync/pair/<int:pair_id>/edit/` | `pair_edit` | 编辑库对 | `ddl_sync.change_ddlsyncpair` |

D8 阶段 2 留 TODO 5 AJAX 端点 (compute_diff / one_click_setup / bulk_import / add_table / history_list)

## 3 个 admin 实战要点

**DdlSyncPairAdmin**:
- list_display 13 列 (id / name / source_link / target_link / sync_mode_badge / enabled_badge / table_count / history_count / created_by / created_at / updated_at)
- 彩色徽章: sync_mode (红 blacklist / 绿 whitelist) + enabled (绿启用 / 灰禁用)
- 批量操作: admin_enable + admin_disable
- 联动 4 perm 4 判定: view + add + change + delete (跟 8/12 gh-ost 套路)

**DdlSyncTableAdmin**:
- list_display 6 列 (id / pair / table_name / sync_type_badge / has_transform_rule / created_at)
- 彩色徽章: sync_type (绿 whitelist / 红 blacklist)
- Phase 3 字段级规则: has_transform_rule (✓ 已配置 / — 空)

**DdlSyncHistoryAdmin**:
- list_display 8 列 (id / pair / source_workflow_link / target_workflow_link / table_name / sync_status_badge / created_at / finished_at)
- 全部 readonly (同步历史只能自动生成, 不允许手动添加) — has_add_permission = False
- 彩色徽章: sync_status (灰 pending / 蓝 syncing / 绿 synced / 黄 skipped / 红 failed)
- 联动 SqlWorkflow 工单链接 (admin 后台跳转)

## 4 perm 4 判定 (跟 8/12 gh-ost list 套路)

| 角色 | 可见 | 可操作 | 备注 |
|------|------|--------|------|
| 业务 RD | (无, 跳 history_list 自己的) | view | 自己的 source_workflow |
| DBA 组长 | 全部 4 perm | view + add + change + delete | 配置库对 + 排查同步问题 |
| DBA 执行 | view + change | 不 delete | 日常运维配置 |
| 副总 / superuser | 全部 4 perm | 全 | 紧急情况兜底 |

## 134 dev 5 步必做全过

| 步骤 | 命令 | 结果 |
|------|------|------|
| 1. SFTP 推 5 文件 | paramiko SFTP | ✓ 5 文件全部 OK |
| 2. chown archery:archery | chown -R | ✓ ddl_sync/ + urls.py 都 archery 拥有 |
| 3. 清 __pycache__ | rm -rf | ✓ |
| 4. kill gunicorn 4-11h + nohup 拉新 | pkill -9 + setsid nohup | ✓ 新 master pid 42541 (跑 36s) |
| 5. 4 端点 verify + Django check | curl + manage.py check | ✓ 全过 |

**端点 verify**:
- /login/ → 200 ✓
- /admin/ddl_sync/ddlsyncpair/ → 302 (重定向 login) ✓
- /ddl_sync/pair/list/ → 302 ✓
- /ddl_sync/pair/create/ → 302 ✓
- Django check ddl_sync → "System check identified no issues (0 silenced)" ✓

## 避坑 (8/24 ddl_gh_ost 实战经验复用 + 8/11 实战)

1. **D6 跟 D7 端点位置错**: 第一次 makemigrations 用了 `sql_extensions_ddl_sync` (full path) 报 "No installed app with label", 改用 `ddl_sync` (label) 正确
2. **mkdir views 子目录**: D7 新加 views/__init__.py, SFTP 推前先 ssh mkdir -p, 否则 FileNotFoundError
3. **Django app label 是路径最后一段**: `sql.extensions.ddl_sync` → label `ddl_sync` (D6 教训应用)
4. **views/ 目录文件**: forms.py 顶级 (跟 ddl_gh_ost 一致), views/ 子目录含 __init__.py (D7)
5. **8/12 gh-ost 4 perm 4 判定**: `@permission_required("ddl_sync.view_ddlsyncpair", raise_exception=True)` 守卫

## 改动文件

```
sql/extensions/ddl_sync/admin.py               (新, 7.6KB)
sql/extensions/ddl_sync/forms.py               (新, 2.5KB)
sql/extensions/ddl_sync/views/__init__.py      (新, 5.5KB)
sql/extensions/ddl_sync/urls.py                (新, 1.6KB)
archery/urls.py                                (改, +1 行 include)
```

## 134 dev 备份

```
/opt/archery/prod/archery/urls.py.bak_20260901_1530
```

## D7 阶段 2 待推 (9/2 早上)

- 3 个 template: pair_list.html (库对列表) / pair_detail.html (库对详情 4 tab) / pair_form.html (创建/编辑表单)
- common/templates/base.html 侧边栏加 DDL 跨库同步菜单
- 模板 HTML 元素 + JS 块包同一个 `{% if perms.ddl_sync.x %}` 守卫 (8/11 教训)

## W2 进度 (D7 阶段 1 完工)

- **D6 9/1 下午 ✓ (3 张表 migration)**
- **D7 9/1 下午 ✓ 阶段 1 (后端 + admin)**
- D7 9/2 早上 阶段 2 (3 template + base.html 联动)
- D8 9/2 下午 (5 AJAX 端点 + R1 批量导入)
- D9 9/3 (R2 一键配 + R3 走当前配置)
- D10 9/4 (134 dev 端到端演练 5 Case)

W2 整体提前 5 天完成 D6 + D7 阶段 1

## 提交

待 commit + push origin main
