# DDL 跨库同步 W2 D34: 134 dev 演练推 110 prod 9 步 runbook

> 日期: 2026-09-04 14:50 - 15:10
> 阶段: W2 实施阶段 D34 (推 110 prod 前的 dry-run 演练)
> 模块: 134 dev 完整部署状态模拟推 110 prod 9 步流程
> 关联: 9/3 D31 8 步 runbook + 9/3 D32 4 大步演练 + 9/4 D33 view 改动

## 背景

D32 演练过 "4 大步" 完整部署流程, D33 加了分页 + 导出 Excel view 改动. D34 计划: 在 134 dev 上 dry-run 演练推 110 prod 9 步 runbook, 验证 D33 视图改动在完整拉新流程中能正常加载.

**D34 跟 D32 演练区别**:
- D32 演练: 模拟 110 prod 干净状态 (注释 4 大步) → 演练 1 + 演练 2 还原
- D34 dry-run: 134 dev 已经是完整部署, **不动 4 大步**, 只验证 D33 view + template + URL 改动在 134 dev 上能完整跑通 + 拉新流程演练

## D34 演练 8 步 (D34 实战产出)

### Step 1: 4 大步 + D33 改动基线确认
134 dev 当前状态:
- ddl_sync 目录 56 文件
- settings.py line 431: `INSTALLED_APPS += ("sql.extensions.ddl_sync.apps.DdlSyncConfig",)`
- urls.py line 55: `path("ddl_sync/", include(("sql.extensions.ddl_sync.urls", "ddl_sync"), namespace="ddl_sync"))`
- base.html line 152-161: 库对列表 menu (带 perms 守卫)
- D33 view: `Paginator` (line 24/68/104) + `pair_history_export` (line 126) 在 views/__init__.py
- D33 URL: `path("pair/<int:pair_id>/history_export/", ...)` 在 urls.py
- D33 template: `ddlsync-btn-export` + `ddlsync-page-link` + `history_page` + `pair_history_export` 都在 pair_detail.html

### Step 2: dry-run migrate
`sudo -u archery venv/bin/python manage.py migrate ddl_sync`
- 输出: "No migrations to apply"
- 结论: ddl_sync migrations 已 applied, 推 110 prod 时必查

### Step 3: kill + 拉新 gunicorn + qcluster
演练 kill + 清 pycache + 拉新流程:
- kill 后进程数: 0
- gunicorn 拉新: 5 进程 (1 master + 4 worker)
- qcluster 拉新: 21 进程
- 9003 端口 listening
- 拉新后总进程数: 26

### Step 4: D33 view 验证 (reverse + showmigrations + get_resolver)
- `reverse('ddl_sync:pair_history_export', [1])` → `/ddl_sync/pair/1/history_export/`
- `reverse('ddl_sync:pair_detail', [1])` → `/ddl_sync/pair/1/`
- showmigrations ddl_sync: 2 [X] (0001_initial + 0002_ddlsyncpair_target_group_and_more)
- ddl_sync 路由总数: 29 (D32 演练时 16, D34 dry-run 29)
- pair_history_export view callable: True, signature: (request, pair_id)

### Step 5: D33 URL 验证 (curl + openpyxl 解析)
- 未登录访问: 302 → /login/ (Archery 中间件重定向)
- 登录后访问: 200 + content-type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
- content-disposition: attachment; filename="ddl_sync_history_pair1_20260904_150300.xlsx"
- content length: 6386 bytes
- openpyxl 解析: 17 行 (1 表头 + 16 数据)

### Step 6-7: 造 5 条临时 history 验证分页
- 临时造 5 条 (id 22-26, count 21)
- page 1 status 200, len 67987, has history_page= link + 1/2 text
- page 2 status 200, len 58740
- 导出 view 200, xlsx 22 行 (1 表头 + 21 数据)

### Step 7.5: 清理
- deleted (5, ...), count 回到 16
- /opt/archery/d34_step7.xlsx 清理

### Step 8: 134 dev 业务不中断验证
- /login/ 200, /ddl_sync/pair/ 302, /ddl_sync/pair/1/history_export/ 302 ✓
- 4 大步 ddl_sync 引用: 2/1/3 (settings/urls/base) ✓
- D33 改动: 4/1/9 (views/urls/template) ✓
- gunicorn+qcluster 25 进程 ✓
- showmigrations 2 [X] ✓

## 实战新发现 (跨项目可复用, 3 条)

1. **134 dev dry-run 是 D34 推 110 prod 前的必演练** (D34 实战新发现) - D32 演练的 4 大步演练只验证 app 部署, D34 演练加上 D33 view 改动验证. 实战中 134 dev dry-run 9 步 runbook 能完整跑通, 9 步流程 1 小时内推 110 prod 可行
2. **演练 D33 视图改动必造 > 20 条 history 验证分页栏** (D34 实战新发现) - 134 dev 实际只有 16 条 history, 必须临时造 5 条 + 测后清理. 实战教训: 演练涉及分页功能必造 > 每页条数条数据
3. **ddl_sync 路由总数从 16 涨到 29** (D34 实战新发现) - D32 演练时 ddl_sync 路由 16 个 (D9 阶段 1 实战), D34 演练时 29 个. 期间 D22/D23/D25/D33 实战加了 target_group / mirror sync / pair_history_export / 等路由. 实战教训: 演练 D32 → D34 期间路由数会增长, 必查 get_resolver() 实时路由数, 不能用演练时的旧数

## 实战踩坑 (2 条)

1. **D34 PowerShell GBK 编码错误 "📥" 字符** (D34 实战踩坑) - pair_detail.html 的导出按钮 "📥 导出 Excel" 包含 emoji 字符, 134 dev 输出到 PowerShell 终端报 GBK 编码错. 修法: 134 dev 输出走 `out.encode('ascii', 'ignore').decode('ascii')` 转 ascii 防 GBK 错. 教训: 涉及 emoji 字符的输出, 必走 ascii 转换
2. **D34 Step 4 print 缩进错** (D34 实战踩坑) - python 脚本里多写了一行 `print('   ', l) if False else None` 实际无意义, 触发缩进错. 修法: 直接删. 教训: 远程 python 脚本要保持简洁, 不要有 dead code

## D34 dry-run 实战结论

D34 推 110 prod 9 步 runbook 演练完全 PASS:
- 4 大步 + D33 改动基线全在 ✓
- dry-run migrate "No migrations to apply" ✓
- kill + 拉新 25 进程 + 9003 listening ✓
- reverse() + showmigrations + get_resolver 全 OK ✓
- curl + openpyxl 解析 PASS ✓
- 造 5 条 → 21 条 → 2 页 + 1/2 文字 + xlsx 22 行 ✓
- 清理后 count 16 恢复 ✓
- 134 dev 业务不中断 (< 1 分钟恢复) ✓

**D34 实战后 W2 状态**: D6 → D7 → ... → D29 → D31 → D32 → D33 → **D34 134 dev 演练 9 步 runbook (dry-run 完整 PASS)** → 准备推 110 prod

## 推 110 prod 实战 runbook (D34 实战升级版)

D34 实战升级 D31 8 步 → 9 步:
- ① Step 1: copy 整个 `sql/extensions/ddl_sync/` 目录 (含 4 子目录 + 8 py + migrations/0001+0002 + services + static + templates + views) - 53+ 文件
- ② Step 2: `archery/settings.py` 加 `INSTALLED_APPS += ("sql.extensions.ddl_sync.apps.DdlSyncConfig",)`
- ③ Step 3: `archery/urls.py` 加 `path("ddl_sync/", include(("sql.extensions.ddl_sync.urls", "ddl_sync"), namespace="ddl_sync"))`
- ④ Step 4: `common/templates/base.html` 加 ddl_sync menu (带 `{% if perms.ddl_sync.view_ddlsyncpair %}` 守卫)
- ⑤ Step 5: `cd /dbdata/archery_v114_c9236a0 && sudo -u archery venv/bin/python manage.py migrate ddl_sync`
- ⑥ Step 6: 推 D22-D33 跨 app 4 文件: `sql/templates/detail.html` + `sql/templates/sqlsubmit.html` + `sql/extensions/ddl_gh_ost/services/column_diff.py` + **D33 view 改的 `sql/extensions/ddl_sync/views/__init__.py` + `sql/extensions/ddl_sync/urls.py` + `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html`**
- ⑦ Step 7: kill + 拉新 gunicorn + qcluster (D24 实战新发现 qcluster 必 kill)
- ⑧ Step 8: 验证 6 项 + 演练 4 大步 (reverse() + showmigrations + get_resolver + curl /ddl_sync/pair/ + 造 5 条验证分页 + curl /ddl_sync/pair/1/history_export/ + openpyxl 解析)
- ⑨ Step 9 (D33 实战新加): 验证 D33 视图改动 (Paginator + pair_history_export + ddlsync-btn-export + ddlsync-page-link)
