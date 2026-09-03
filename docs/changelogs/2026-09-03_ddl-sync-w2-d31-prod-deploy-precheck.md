# DDL 跨库同步 W2 D31: 110 prod 首次部署 v0.5.0 ddl_sync app 推前检查

> 日期: 2026-09-03 19:50 - 21:50
> 阶段: W2 实施阶段 D31 (推 110 prod 前的预检)
> 模块: 110 prod 实际部署状态 + 完整推 110 prod 清单
> 关联: 9/3 17:35 D29 实战时发现 110 prod 推 v0.5.0 缺 settings.py / urls.py / base.html 注册

## 背景

W2 v0.5.0 跨库同步 ddl_sync app 实战分 2 阶段:
- **134 dev 阶段 (D6-D9 实战)**: 在 134 dev 完整部署 + 演练 + 修
- **110 prod 阶段 (D14 实战)**: D14 推 110 prod 修汪银和工单 (v0.3.x 字段 diff 修复) — **不包含 v0.5.0 ddl_sync app**

D30 准备推 110 prod 实战时, 发现:
- 110 prod 没 `sql/extensions/ddl_sync/` 目录
- 110 prod settings.py 没注册 ddl_sync INSTALLED_APPS
- 110 prod urls.py 没注册 ddl_sync 路由
- 110 prod common/templates/base.html 没 ddl_sync menu 入口

也就是 W2 跨库同步 ddl_sync app **从来没推过 110 prod**。

## 症状 (9/3 17:35 D29 实战时发现)

D29 实战时验证 D28 大表 alert 弹窗化, 排查 110 prod 实际状态:
- 之前 D14 推 110 prod 修汪银和工单 (commit ed1c20c + e939ffe + 289adc7 等) — **只推 v0.3.x 字段 diff 修复**
- D6-D21 实战 + D22-D28 修复 (commit 5f261e0 + d864187 + e67d2f8 + 29998bf + 3a59e8b) — **只在 134 dev 上, 没推 110 prod**

## 根因

134 dev 实战时, 我在 D9 阶段 1 实战已经改过 134 dev 的:
- `archery/settings.py` line 431: `INSTALLED_APPS += ("sql.extensions.ddl_sync.apps.DdlSyncConfig",)`
- `archery/urls.py` line 55: `path("ddl_sync/", include(("sql.extensions.ddl_sync.urls", "ddl_sync"), namespace="ddl_sync"))`
- `common/templates/base.html` line 152-161: 加 ddl_sync menu 入口 + 守卫用 `perms.ddl_sync.view_ddlsyncpair` 权限

但这些改动**只改了 134 dev**, **没在 110 prod 同步改过**。D14 实战时, 我以为"D14 推 110 prod 修汪银和工单"包括了 v0.5.0 ddl_sync app, 实际只推了 v0.3.x 字段 diff 修复。

**D31 实战新发现 (跨项目可复用, 3 条)**:
1. **"推 prod" 不只推 8 文件 + 1 migration, 还要改 settings.py + urls.py + base.html** (D31 实战新发现) - Django app 部署是 4 大步: copy 目录 + INSTALLED_APPS 注册 + 路由注册 + base.html menu. 实战前必查远端 settings.py + urls.py + base.html 状态
2. **134 dev 演练 v0.5.0 实战时改了 settings.py + urls.py + base.html, 但没在 110 prod 同步改** (D31 实战新发现) - 实战套路: 134 dev 改了的文件 (settings.py / urls.py / base.html) **必须** 跟 110 prod 同步修改, 不能只推 app 目录
3. **110 prod 路径 `/dbdata/archery_v114_c9236a0/` 不是 `/dbdata/archery_v114/`** (D31 实战新发现) - D9 memory 说"110 prod c9236a0 跟 v114 区分" 实际是: 110 prod 部署在 `_c9236a0` 子目录 (git commit c9236a0 base), 不是 `_v114` 目录. 实战前必 ssh 上 110 prod 看 pwd 确认实际路径

## 完整推 110 prod v0.5.0 ddl_sync app 清单 (D31 实战产出)

### Step 1: 整个 `sql/extensions/ddl_sync/` 目录

134 dev 上 `/opt/archery/prod/sql/extensions/ddl_sync/` 完整结构:
```
__init__.py (563 B)
admin.py (7597 B)
apps.py (663 B)
forms.py (3980 B)
models.py (10639 B)
urls.py (1613 B)
migrations/
  __init__.py
  0001_initial.py (6648 B)
  0002_ddlsyncpair_target_group_and_more.py (994 B)  ← D22
services/
  __init__.py
  sync_trigger.py (D9 + D22 + D23 + D25 共用)
  compute_diff.py
  bulk_import.py
  one_click_setup.py
  perm_guard.py
  table_service.py
static/
  ddl_sync/  (CSS/JS 资源)
templates/
  ddl_sync/
    pair_form.html
    pair_detail.html
    partials/_add_table_modal.html
views/
  __init__.py
  api_views.py
```

推 110 prod: 整个 `sql/extensions/ddl_sync/` 目录 rsync / scp -r 过去 (包括子目录).

### Step 2: `archery/settings.py` 加 ddl_sync INSTALLED_APPS

110 prod `/dbdata/archery_v114_c9236a0/archery/settings.py` line 419 之后加:
```python
INSTALLED_APPS += ("sql.extensions.ddl_sync.apps.DdlSyncConfig",)
```

参考 134 dev line 431 已有 ddl_sync 注册.

### Step 3: `archery/urls.py` 加 ddl_sync 路由

110 prod `/dbdata/archery_v114_c9236a0/archery/urls.py` line 47 之后加:
```python
path("ddl_sync/", include(("sql.extensions.ddl_sync.urls", "ddl_sync"), namespace="ddl_sync")),
```

参考 134 dev line 55 已有 ddl_sync 路由.

### Step 4: `common/templates/base.html` 加 ddl_sync menu

110 prod `/dbdata/archery_v114_c9236a0/common/templates/base.html` line 152 之后加:
```html
{# 守卫: superuser 或有 ddl_sync.view_ddlsyncpair 权限 #}
{% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %}
    <li>
        <a href="{% url 'ddl_sync:pair_list' %}"><i class="fa fa-list fa-fw"></i> 库对列表</a>
    </li>
{% endif %}
```

参考 134 dev line 152-161 已有 ddl_sync menu. **必加守卫, 不加会让没权限的用户看 base.html 报 NoReverseMatch 500** (D9 实战 line 428 注释).

### Step 5: 推 migration 0002

```bash
cd /dbdata/archery_v114_c9236a0
sudo -u archery venv/bin/python manage.py migrate ddl_sync
```

**前提**: Step 2 (INSTALLED_APPS) + Step 3 (urls.py) 都已经改, migrate 才能找到 ddl_sync app.

### Step 6: 推 D22-D28 其他 4 个文件

跨 app 改的 4 文件, 实战推 110 prod 时一起推:
- `sql/templates/detail.html` (D18 + D25 v2 实战改的)
- `sql/templates/sqlsubmit.html` (D28 实战改的)
- `sql/extensions/ddl_gh_ost/services/column_diff.py` (D27 实战改的)
- `sql/extensions/ddl_sync/services/sync_trigger.py` (D9 + D22 + D23 + D25 共用) — **已包含在 Step 1 整个目录 copy 里**

但 `detail.html` / `sqlsubmit.html` / `column_diff.py` 是 `sql/` 跟 `sql/extensions/ddl_gh_ost/` 下的, 不是 `ddl_sync/` 目录. 实战时:
- 跟 Step 1 一起推 (rsync `sql/` 整个目录) — 但风险大, 容易把不相关的也覆盖
- 或者单独推 3 个文件 — 精准但需要分多次操作

**建议**: 单独推 3 个文件 (`detail.html` / `sqlsubmit.html` / `column_diff.py`), 配合 Step 1 整个 ddl_sync/ 目录 copy + Step 2-4 settings/urls/base.html 修改.

### Step 7: kill + 拉新 gunicorn + qcluster (D24 实战新发现)

**必 kill + 拉新 qcluster** (D24 实战新发现, 不能只 restart gunicorn):
```bash
# kill 老的
pkill -9 -f 'manage.py qcluster'
pkill -9 -f 'gunicorn.*archery.*9123'
sleep 2

# 清 pycache
find /dbdata/archery_v114_c9236a0 -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
find /dbdata/archery_v114_c9236a0 -name '*.pyc' -delete 2>/dev/null

# 拉新
cd /dbdata/archery_v114_c9236a0
setsid nohup sudo -u archery venv/bin/python venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 </dev/null >/var/log/archery/gunicorn_d31.log 2>&1 & disown

setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster_d31.log 2>&1 & disown

sleep 4
pgrep -fa 'gunicorn.*archery.*9123|manage.py qcluster' | head -10
```

注意 110 prod venv python 是 `python3.9` (跟 134 dev `python3.11` 不同, D14 实战已知).

### Step 8: 验证 + 演练

推完后演练 6 项:
1. `curl -I http://172.20.2.110:9123/login/` — 业务方登录页 200 OK
2. `curl -I http://172.20.2.110:9123/ddl_sync/pair/` — 库对列表 200 OK (D9 阶段 1 实战)
3. SQL 检测按钮 / 字段 diff 弹窗 (D28) + 大表 alert (D29)
4. 镜像工单 detail 页 alert 块 (D18)
5. D26 健康检查 10 项
6. 老 pair 配 target_group (DBA 手动) + 老镜像工单 group_id 改 (D22 演练 1 套路)

## 实战新发现 (跨项目可复用, 5 条)

1. **Django app 部署是 4 大步: copy 目录 + INSTALLED_APPS + 路由 + base.html** (D31 实战新发现) - 实战前必查远端 4 个地方, 不能只 copy 目录
2. **"推 prod" 实际要改 6 文件: 4 settings/urls/base.html + 1 app 目录 + N 业务文件** (D31 实战新发现) - 实战前 checklist 必列全, 漏一个就 NoReverseMatch 500
3. **110 prod 路径 `/dbdata/archery_v114_c9236a0/` 不是 `/dbdata/archery_v114/`** (D31 实战新发现) - 实战前必 ssh 上 110 prod 看 pwd 确认实际路径, 不要凭 memory 猜
4. **base.html 守卫 `{% if user.is_superuser or perms.ddl_sync.view_ddlsyncpair %}` 必加** (D9 实战新发现, D31 实战复用) - 不加守卫, 没权限用户访问 base.html 会 NoReverseMatch 500 (D9 实战 line 428 注释)
5. **D31 实战前必演练"完整 copy + 改 settings/urls/base.html"流程** (D31 实战新发现) - 134 dev 演练完整首次部署流程, 验证 4 大步能 work, 才能推 110 prod. 不演练直接推, 漏一个就 500

## D31 实战踩坑 (3 条)

1. **D31 SSH PowerShell 终端 "Command aborted" 错误** (D31 实战踩坑) - Windows PowerShell 跑 ssh 偶发 "Command aborted" 错误, 实战胜率 60% (跑 3 次 1 次成功), 改用 paramiko Python 脚本稳定
2. **D31 D30 md5 校验脚本对路径 110 prod 第一次跑错** (D30 实战踩坑复用) - 110 prod 实际部署在 `/dbdata/archery_v114_c9236a0/`, 我之前 D30 md5 校验跑 `/dbdata/archery_v114/`, 全 DIFF + md5sum 空字符串. 实战前必 ssh 上 110 prod 看 pwd 确认
3. **D31 Step 1 用 ls -la + find 看路径比 D30 md5 校验更准** (D31 实战新发现) - D30 md5 校验报错无明确提示"路径不对", D31 Step 1 用 ls + find 直接看目录结构, 一次就搞清楚 110 prod 部署路径是 `_c9236a0` 子目录

## 待办

1. **D32 = 134 dev 演练"完整 copy + 改 settings/urls/base.html"流程** (D32 计划) - 演练 4 大步能 work, 才能推 110 prod
2. **D33 = 推 110 prod 实战** (D33 计划) - 推前 checklist 必查 4 大步完整, 推完演练 6 项验证
3. **D34 = 推完 110 prod 跑 D26 健康检查 + 老 instance/pair 兑底** (D34 计划) - 110 prod 老 instance 必配 target_group, 老镜像工单 group_id 必改

## D31 实战后 W2 状态

D6 → D7 → ... → D27 → D28 → D29 → **D31 推 110 prod 实战预检** (发现 4 大步真实清单)
