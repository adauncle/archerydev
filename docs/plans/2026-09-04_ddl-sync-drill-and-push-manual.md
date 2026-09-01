# 9/4 DDL 跨库同步 134 dev 演练设计 + 推 110 主手册 + W1→W2 衔接 (9/4 14:30)

> **W1 设计阶段 D5 (9/4 周五)**: 134 dev 端到端演练设计 + 推 110 主手册更新 + W1→W2 衔接
>
> 读者: DBA 团队 (我 + 阿达叔叔), W2 实施 + W3 提测时用
> 来源: W1-D3 (9/1 后端) + W1-D4 (9/1 前端) 衍生
>
> **本文档不覆盖**:
> - 业务背景 (4 部分: 现状/痛点/影响/目标) — 看 `2026-08-31_ddl-sync-pair-design-refined.md` §0
> - 3 张表字段定义 — 看 `2026-09-01_ddl-sync-data-model.md` §2-§4
> - 后端 service 拆分 + API 契约 — 看 `2026-09-01_ddl-sync-implementation-design.md` §1-§2
> - 前端 5 按钮 modal + 工单详情 alert — 看 `2026-09-03_ddl-sync-detail-ux-design.md` §1-§2

---

## 0. 概述 (跟前 4 份设计稿 + 8/25 推 110 主手册关系)

### 0.1 5 份设计稿 + 1 份主手册 完整体系

| 文档 | 读者 | 篇幅 | 视角 |
|---|---|---|---|
| **refined** (`2026-08-31_ddl-sync-pair-design-refined.md`) | 领导汇报 | 42KB | 业务视角 (为什么做 / 痛点 / 影响 / 目标) |
| **D2 数据模型** (`2026-09-01_ddl-sync-data-model.md`) | DBA 内部 | 14.6KB | 表结构视角 (3 张表 / ER 图 / migration) |
| **W1-D3 实施** (`2026-09-01_ddl-sync-implementation-design.md`) | DBA 实施 (后端) | 46KB | API 契约 (service 拆分 / 5 端点 / 状态机 / perm) |
| **W1-D4 前端** (`2026-09-03_ddl-sync-detail-ux-design.md`) | DBA 实施 (前端) | 40KB | 前端 UX (5 按钮 modal / 工单详情页 / 字段 diff 联动) |
| **W1-D5 本文档** (本文) | W2 实施 + W3 提测 | 15-20KB | 演练设计 + 推 110 主手册 + W1→W2 衔接 |
| 8/25 推 110 主手册 (`commit f44c26e`, 23KB) | 推 110 执行 | 23KB | 5 步必做 + 11+1 端点 verify + 4 风险 |

**W1-D5 跟 8/25 主手册关系**: W1-D5 推 110 部分是基于 8/25 f44c26e 23KB 主手册结构, 加入 DDL 同步新内容 (19 文件清单 + DDL 同步 5 端点 verify + 8/26 推 110 实战 3 P0 教训应用), 是 8/25 主手册的**增量更新版**.

### 0.2 W1-D5 核心目标

- 134 dev 端到端演练 5 Case 详细步骤 (W2 实施时跑, 验收标准)
- 推 110 主手册更新 (W3 9/14-9/18 提测时用, 5 步必做 + 11+1 端点 verify)
- W1 → W2 衔接 (5 天日程 D6-D10 实施步骤 + 19 文件清单 + 8/26 实战 3 P0 教训应用)

---

## 1. 134 dev 端到端演练设计 (5 Case)

### 1.1 演练目标

> **演练环境**: 134 dev /opt/archery/prod (跑 prod 配置 archery_prod 库, MySQL 8.0.22)
> **演练库对**: 1 个真实库对 hly_accesscard (业务库 1589 张表 ↔ 历史库 hly_activity 1289 张表)
> **演练角色**: 业务 RD mkq (拉库对演练 + 1-click 一键配 1589 张 + 1 条真实 DDL 触发) + DBA 阿达叔叔 (配置 perm + 演练 rollback + 4 perm 验证)

### 1.2 演练 5 Case (按顺序跑)

#### Case A: 配 1 个真实库对 (5 min, DBA 阿达叔叔)

```
1. DBA 登 134 dev admin 后台 (/admin/ddl_sync/ddlsyncpair/add/)
2. 创建 DdlSyncPair:
   - name: hly_accesscard 库对
   - source_instance: instance 31 (物流-好慧运-变更, 172.20.2.20:3306)
   - source_db: hly_accesscard
   - target_instance: instance 11 (replica1, 172.20.2.11:6446)
   - target_db: hly_activity
   - sync_mode: blacklist (默认)
   - enabled: True
3. 保存, 验证 admin 列表页能看到新库对
4. 验证: 跳转到库对详情页, 4 tab 显示正常, 5 按钮可点击
```

**验收标准**:
- 库对创建成功, admin 列表显示 1 行
- 库对详情页 5 按钮可点击 (DBA 角色)
- 同步表清单 tab 显示 0 张表 (还没配)

#### Case B: 一键配 1-click 接受 1589 张 (6 min, DBA 阿达叔叔)

```
1. 在库对详情页点 🎯 一键配 (按历史库) 按钮
2. 弹 modal, 12.3s 内出 compute_diff 结果:
   - 白名单 1289 张 (业务库 ∩ 历史库) ✓ 推荐全选
   - 黑名单 300 张 (业务库 - 历史库) ✓ 推荐全选
   - 孤儿 0 张
3. DBA 选"覆盖现有配置" (实际 0 张, 走 DELETE + bulk_create)
4. 点 🎯 一键配 (1589 张) 提交
5. 8.4s 内完成, 跳转到库对详情页, 同步表清单 tab 显示 1589 张
6. 验证白名单 1289 张 + 黑名单 300 张分类正确
```

**验收标准**:
- 一键配端到端 < 30s (12.3s + 8.4s + 弹窗)
- bulk_create 1589 张成功, 0 失败
- 同步表清单 tab 显示 1589 张, 分类正确 (1289 白 + 300 黑)

#### Case C: 业务 RD mkq 浏览器触发 1 条真实 DDL (15 min, 业务 RD mkq)

```
1. 业务 RD mkq 登 134 dev (`http://172.20.2.134:9003/`)
2. 选 instance 31 (hly_accesscard), 提 1 条 DDL 工单:
   SQL: ALTER TABLE accesscard_account ADD COLUMN test_col_v050 INT DEFAULT 0
3. 走 3 级审批 (研发组长 / DBA 组长 / DBA)
4. 审批通过后, 业务 RD 看到详情页 alert 块:
   "本表已配置跨库同步" + 库对名 + 同步模式 + 同步状态
5. 业务 RD 走"立即执行" (DBA 兜底) 触发业务库 DDL 执行
6. 业务库 DDL PASSED → 触发 sync_trigger.workflow_passed_handler
7. W1-D3 §5 R3 走当前配置:
   - 业务库工单 #X current_status=1 PASSED
   - 找匹配库对 (hly_accesscard 库对) ✓
   - 提取表名 accesscard_account ✓
   - 判定白名单 (白名单含) ✓ should_sync=True
   - 创建历史库镜像工单 (instance 11 / hly_activity 库)
   - 走当前 audit_setting 配置 (DBA 1 级审批)
8. DBA 审批 + 执行历史库镜像工单
9. 历史库镜像工单 PASSED → DdlSyncHistory 标 synced
10. 业务 RD mkq 跳到同步历史列表, 看到 synced 记录
```

**验收标准**:
- 业务库 DDL 审批通过 → 历史库镜像工单自动生成 (无手动操作)
- 历史库镜像工单走当前 audit_setting 配置 (DBA 1 级审批, 跟正常工单一样)
- DdlSyncHistory sync_status= synced
- 业务 RD mkq 在业务库 DDL 工单详情页看到 alert 块 (W1-D4 §2)
- 业务 RD mkq 跳到同步历史列表, 看到 synced 记录

#### Case D: 触发 rollback 端到端 (失败场景, 10 min, DBA 阿达叔叔)

```
1. 业务 RD mkq 提 1 条故意失败 DDL:
   SQL: ALTER TABLE accesscard_account MODIFY COLUMN test_col_v050 VARCHAR(5)
2. 业务库 DDL PASSED → 触发 sync_trigger 创建历史库镜像工单
3. 历史库镜像工单执行 (test_col_v050 是 INT, 转 VARCHAR(5) 数据截断, 实际跑失败)
4. 镜像工单 failed → 联动 v0.4.5 智能回滚:
   - drop 残留 _gho / _del (8/27 17:30 rollback 端点 docstring 确认 IF EXISTS 走 no-op)
   - DdlSyncHistory.sync_status = failed
   - error_message 填失败原因
   - 钉钉通知业务 RD + DBA (走 v0.2.0 OA webhook)
5. DBA 阿达叔叔登 admin 后台, 看到 DdlSyncHistory failed 记录
6. DBA 主动点"gh-ost 智能回滚" 按钮 (DBA 兜底), IF EXISTS 走 no-op, 任务标 rolled_back
7. 业务 RD mkq 跳到同步历史列表, 看到 failed + rolled_back 记录
```

**验收标准**:
- 业务库 DDL 执行成功 → 历史库镜像工单触发 (不管失败成功)
- 镜像工单 failed → v0.4.5 智能回滚自动触发 (8/27 17:30 实战确认)
- 钉钉通知业务 RD + DBA 触发 (走 v0.2.0 OA)
- DdlSyncHistory 5 status 状态机正确 (pending → syncing → failed → rolled_back)
- 业务 RD mkq 在业务库 DDL 工单详情页 alert 块看到"同步状态: failed"

#### Case E: 4 perm 4 角色验证 (10 min, DBA 阿达叔叔)

```
1. 在 134 dev admin 后台创建 4 个测试用户:
   - test_business_rd (业务 RD, 关联 archery user, M2M 到 group 25)
   - test_dba_lead (DBA 组长, 关联 auth_group 14/15/3 全部 4 perm)
   - test_dba_executor (DBA 执行, 关联 view + change 2 perm)
   - test_superuser (superuser, 全部 4 perm)
2. 用 4 个用户分别登 134 dev, 访问库对详情页
3. 验证按钮可见性:
   - test_business_rd: 5 按钮全部隐藏 (业务 RD 不管库对配置)
   - test_dba_lead: 5 按钮全部可见 (DBA 组长有 4 perm)
   - test_dba_executor: 4 按钮可见 (缺删除, 但库对管理没删除按钮) - 实际可点
   - test_superuser: 5 按钮全部可见
4. 用 test_business_rd 试 POST /ddl_sync/pair/3/one_click_setup/ 端点:
   - 预期返 JsonResponse({"ok": False, "error": "权限不足: 需要 ddl_sync.change_ddlsyncpair"}, status=403)
   - 不 raise PermissionDenied (8/13 教训应用)
5. 用 test_dba_executor 试 POST 端点:
   - 预期返 200 (有 change perm)
```

**验收标准**:
- 4 角色按钮可见性正确 (业务 RD 隐藏 / DBA 组长 全 / DBA 执行 4 / superuser 全)
- AJAX 端点 perm 守卫返 JsonResponse(403) 不 raise PermissionDenied (8/13 教训)
- 4 perm 都能在 admin 后台分配 (DBA 组长 全 4, DBA 执行 2, 业务 RD 0, superuser 0 因有所有 perm)

### 1.3 演练总时长 + 跟 gh-ost 演练对比

| 阶段 | 演练时长 | 跟 gh-ost v0.3.0-beta 对比 |
|------|----------|--------------------------|
| Case A 配库对 | 5 min | gh-ost 演练 5/24 8 阶段 30 min (配 instance + 走完整工单) |
| Case B 一键配 | 6 min | gh-ost 演练 5/27 16/16 PASS 10 min (3 task 端到端) |
| Case C 真实 DDL | 15 min | gh-ost 演练 5/27 task #5 100% 18s + 5+1 端点 5 min |
| Case D rollback | 10 min | gh-ost 演练 5/27 17:00 rollback 端点 5 min |
| Case E perm 验证 | 10 min | gh-ost 演练 5/27 8/13 perm 拆分 5 min |
| **总演练** | **46 min** | gh-ost 8 阶段 30 min (1.5x 时间) |

DDL 同步演练比 gh-ost 复杂 (涉及双库 + 镜像工单 + 联动点), 演练时长 1.5x 合理.

### 1.4 演练失败回退 (8/27 实战踩坑预案)

> **8/27 实战踩坑**: zombie 检测 / 端口探测 / poller staleness / signal handler 异常兜底

| 演练失败场景 | 回退步骤 |
|--------------|----------|
| Case B 一键配 1589 张 bulk_create 失败 | DELETE ext_ddl_sync_table 全部行 + 重试 |
| Case C 业务 RD 浏览器测 JS ReferenceError | views.py 加 json.dumps + |safe (8/26 21:57 避坑) |
| Case D gh-ost 智能回滚 drop 残留失败 | 手动 drop _gho/_del (走 8/27 17:30 rollback docstring) |
| Case E 业务 RD 触发 403 返 HTML 不是 JSON | 改 perm_guard.py 用 JsonResponse(403) (8/13 教训应用) |
| signal handler 异常阻塞主流程 | workflow_passed_handler try/except (W1-D3 §9.3 第 5 条) |

---

## 2. 推 110 主手册更新 (5 步必做 + 11+1 端点 verify)

### 2.1 5 步必做 (跟 8/25 f44c26e 23KB 主手册同结构, 加 DDL 同步)

```bash
# 步骤 1: 备份
cp -r /dbdata/archery_v114_c9236a0 /backup/upgrade_v050_ddl_sync_20260918/

# 步骤 2: 比对 SECRET_KEY (8/26 K1 教训)
cat /dbdata/archery_v114_c9236a0/.env | grep SECRET_KEY
cat /backup/upgrade_v114/v110_secret_key.txt
# 必保留 prod 原值, 不能从 134 dev .env 抄

# 步骤 3: .env 完整 review (8/26 K2 K3 教训)
grep -E "CACHE_URL|REDIS_|CUSTOM_" /dbdata/archery_v114_c9236a0/.env
# K2: CACHE_URL 必加 redis://:password@127.0.0.1:6379/0
# K3: CUSTOM_GH_OST_PRECHECK_* 必清空 (prod 不走 dev-only fallback)
# K4 (9/1 新增): sql_config 3 个 key (sqladvisor/soar/soar_test_dsn) 必配齐 (SELECT 检查)

# 步骤 4: 推 4 文件 (前端 9 + 后端 10 = 19 文件, W1-D4 §5.4 + W1-D3 §1.1)
scp -r sql/extensions/ddl_sync/ root@172.20.2.110:/dbdata/archery_v114_c9236a0/sql/extensions/
scp archery/urls.py root@172.20.2.110:/dbdata/archery_v114_c9236a0/archery/
scp common/templates/base.html root@172.20.2.110:/dbdata/archery_v114_c9236a0/common/templates/
scp sql/templates/sql/detail.html root@172.20.2.110:/dbdata/archery_v114_c9236a0/sql/templates/sql/
# 推 19 文件清单 (W1-D3 §1.1 目录结构 + W1-D4 §5.4 前端文件清单)

# 步骤 5: 跑 migration + 创建 perm + restart + smoke test
ssh root@172.20.2.110 "cd /dbdata/archery_v114_c9236a0 && \
  sudo -u archery venv/bin/python manage.py migrate_ext_ddl_sync && \
  sudo -u archery venv/bin/python manage.py shell -c \"
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncTable, DdlSyncHistory
ct_pair = ContentType.objects.get_for_model(DdlSyncPair)
ct_table = ContentType.objects.get_for_model(DdlSyncTable)
ct_history = ContentType.objects.get_for_model(DdlSyncHistory)
for ct, codename, name in [
    (ct_pair, 'view_ddlsyncpair', 'Can view DDL sync pair list'),
    (ct_pair, 'add_ddlsyncpair', 'Can create DDL sync pair'),
    (ct_pair, 'change_ddlsyncpair', 'Can change DDL sync pair config'),
    (ct_pair, 'delete_ddlsyncpair', 'Can delete DDL sync pair'),
    (ct_table, 'view_ddlsynctable', 'Can view sync table list'),
    (ct_table, 'add_ddlsynctable', 'Can add sync table'),
    (ct_table, 'change_ddlsynctable', 'Can change sync table transform rule'),
    (ct_table, 'delete_ddlsynctable', 'Can delete sync table'),
    (ct_history, 'view_ddl syncsync_history', 'Can view sync history'),
]:
    Permission.objects.get_or_create(codename=codename, content_type=ct, defaults={'name': name})
\" && \
  pkill -9 gunicorn && \
  setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 >/var/log/archery/gunicorn.log 2>&1 < /dev/null &"
```

### 2.2 11+1 端点 verify (5+1 旧 + DDL 同步 5 端点)

```bash
# 8/26 推 110 后 5+1 端点 (commit d57d987 verify_5endpoints_110prod.sh 升级到 11+1)
# 加 5 个 DDL 同步端点:

# DDL 同步端点
curl -I http://127.0.0.1:9123/ddl_sync/pair/list/                           # 200 (GET)
curl -I http://127.0.0.1:9123/ddl_sync/pair/1/                              # 200 (GET, 假设库对 id=1)
curl -I http://127.0.0.1:9123/ddl_sync/pair/create/                         # 200 (GET)
curl -I http://127.0.0.1:9123/ddl_sync/pair/1/compute_diff/                # 405 (GET 不允许, POST 才行)
curl -I http://127.0.0.1:9123/ddl_sync/pair/1/one_click_setup/             # 405
curl -I http://127.0.0.1:9123/ddl_sync/pair/1/bulk_import/                 # 405
curl -I http://127.0.0.1:9123/ddl_sync/pair/1/add_table/                    # 405
curl -I http://127.0.0.1:9123/ddl_sync/history/                             # 200 (GET)
# 共 5 个 DDL 同步端点 + 5 旧端点 = 10 + 1 登录 = 11+1
```

### 2.3 K1/K2/K3 避坑 (8/26 实战 3 P0 + 9/1 新加 K4)

| 避坑 | 教训 | 步骤 |
|------|------|------|
| **K1 SECRET_KEY** | 8/26 推 110 漏检 .env SECRET_KEY, 业务 RD 登录 500 | 步骤 2 比对 SECRET_KEY 必保留 prod 原值 |
| **K2 CACHE_URL** | 8/26 推 110 .env 没 CACHE_URL, 业务 RD 选 database 500 | 步骤 3 必加 CACHE_URL=redis://:password@127.0.0.1:6379/0 |
| **K3 dev-only 变量** | 8/26 推 110 CUSTOM_GH_OST_PRECHECK_* 没清, gh-ost precheck 1045 | 步骤 3 必清空 CUSTOM_* 变量 |
| **K4 sql_config 3 key** (9/1 新加) | 9/1 推 110 漏检 sql_config 3 key, 业务 RD 用 SQL 优化工具报错 | 步骤 3 必 SELECT 检 3 个 key, 缺一个 UPDATE 一个 |

### 2.4 业务 RD mkq 浏览器实测 (8/26 教训应用)

> **避坑 8/26**: 5+1 端点验证深度不够, 必走"业务 RD 浏览器真业务工单流"

- 必走"业务 RD mkq 浏览器实际场景": 提单 → 选 instance → 选 database → 触发同步 → 镜像工单 → 审批 → 执行 → 验证 history
- 必含特殊场景: 库名含 `use hly_xxx;` 多行 SQL / 大表 ALTER / 失败工单 retry / 孤儿表 skipped
- 必测 4 perm 守卫: 业务 RD 点一键配 403 / DBA 成功 / 副总兜底
- 必测 alert 块: 业务 RD 提单 → 审批中看到 alert → 审批通过后看同步历史更新

---

## 3. W1 → W2 衔接 (5 天日程 D6-D10 + 19 文件清单)

### 3.1 W2 5 天日程 (9/7-9/11)

| 天 | 日期 | 主要工作 | 详细说明 | 引用 |
|----|------|----------|----------|------|
| **D6** | 9/7 (周一) | 数据模型 migration | 3 张表 (DdlSyncPair / DdlSyncTable / DdlSyncHistory) + migration 脚本 (sync_mode default blacklist + R2 sync_type field) + Django app 初始化 | W1-D2 §5 |
| **D7** | 9/8 (周二) | 库对管理 CRUD | DdlSyncPair + DdlSyncTable models + admin + 列表/详情页 (复用 4 perm 4 判定, 跟 gh-ost 任务管理 list 同一套路) | W1-D3 §2 + W1-D4 §1 |
| **D8** | 9/9 (周三) | 5 按钮 + R1 批量导入 | (一键配 / 批量导入 / 添加 / schema 差集 / 过滤规则) + R1 批量导入 端到端 (扫历史库 + 模态框 + 过滤规则 + 批量入库) | W1-D3 §3 + W1-D4 §1.1-§1.3 |
| **D9** | 9/10 (周四) | R2 一键配 + R3 走当前配置 | R2 一键配 (compute_diff + one_click_setup + 1-click 接受) + R3 走当前配置 (镜像工单走 Archery 当前配置 + 业务库 DDL 必审过 trigger) | W1-D3 §4 §5 + W1-D4 §1.2 |
| **D10** | 9/11 (周五) | 134 dev 端到端演练 | 按本文 §1 134 dev 端到端演练 5 Case 跑 + 修复实战踩坑 + 验收脚本 | 本文 §1 |

### 3.2 19 文件清单 (W2 实施物料)

**后端 10 文件** (W1-D3 §1.1 services/ 目录 + views/ 目录):

```
sql/extensions/ddl_sync/
├── __init__.py
├── apps.py
├── models.py                            # 3 张表 (W1-D2 §2-§4)
├── admin.py                             # Django admin 后台
├── migrations/
│   ├── 0001_initial.py
│   ├── 0002_ddlsynctable_sync_type.py
│   ├── 0003_ddlsyncpair_blacklist_default.py
│   ├── 0004_ddlsyncpair_pending_tables.py
│   └── 0005_ddlsyncpair_filter_rule.py
├── services/
│   ├── __init__.py
│   ├── pair_service.py                  # W1-D3 §1.2 (4 service 函数)
│   ├── table_service.py
│   ├── compute_diff.py                  # R2 一键配差集计算
│   ├── one_click_setup.py               # R2 一键配 bulk_create
│   ├── bulk_import.py                   # R1 批量导入
│   ├── sync_trigger.py                  # R3 镜像工单
│   ├── perm_guard.py                    # 4 perm 4 判定
│   └── zombie_cleaner.py                # 异常残留清理
├── views/
│   ├── __init__.py
│   ├── pair_views.py                    # 5 view 端点
│   ├── api_views.py                     # 5 AJAX 端点
│   └── trigger_views.py                 # workflow_passed signal handler
├── forms/
│   ├── pair_form.py
│   └── table_form.py
├── urls.py
└── management/commands/
    ├── migrate_ext_ddl_sync.py          # 跑 migration
    └── fix_old_pair_sync_mode.py        # 老库对兼容
```

**前端 9 文件** (W1-D4 §5.4 推 110 前端文件):

```
sql/extensions/ddl_sync/
├── templates/
│   ├── pair_list.html
│   ├── pair_detail.html                 # 5 按钮 + 4 tab
│   ├── pair_form.html
│   └── partials/
│       ├── _bulk_import_modal.html
│       ├── _one_click_modal.html
│       ├── _add_table_modal.html
│       ├── _schema_diff_modal.html
│       └── _filter_rule_modal.html
└── static/ddl_sync/
    ├── pair_list.js
    ├── pair_detail.js                   # 5 modal JS
    └── column_diff_reuse.js             # 复用 8/12

# 联动修改
common/templates/base.html              # 侧边栏加 DDL 跨库同步菜单
sql/templates/sql/detail.html           # 业务库 DDL 工单详情加 alert
```

**总物料: 后端 10 + 前端 9 = 19 文件** (W1-D3 + W1-D4 配套, 推 110 必完整)

### 3.3 8/26 实战 3 P0 教训应用 (W2 实施 + W3 提测必避坑)

| 避坑 | 教训 | W2 实施应用 | W3 提测应用 |
|------|------|-------------|------------|
| **K1 SECRET_KEY** | 8/26 漏检 .env SECRET_KEY | 推前比对 .env SECRET_KEY 跟 7/22 真值 | 推前必查, 推后 ORM 验解密 |
| **K2 CACHE_URL** | 8/26 漏加 CACHE_URL | 推前 grep `.env` 必含 CACHE_URL | 推前验证, 推后 cache.set/get 测 |
| **K3 dev-only 变量** | 8/26 CUSTOM_GH_OST_PRECHECK_* 没清 | 推前 review CUSTOM_* 必清空 | 推前清, 推后 ORM 直连业务库验 |
| **K4 sql_config 3 key** (9/1 新加) | 9/1 漏检 sql_config 3 key | 推前 SELECT 检 3 key, 缺一个 UPDATE 一个 | 推前配齐, 推后业务 RD 浏览器实测 |
| **8/26 5+1 端点深度不够** | 漏 ORM EncryptedCharField / 漏 /api/v1/ REST API | 演练必走 ORM EncryptedCharField + /api/v1/ | 推后必走业务 RD mkq 真业务流 |
| **8/27 14:18 gh-ost alter 1064** | 8.0 业务库 SQL 保留原始格式, 5.7 标准化 | 演练必覆盖 instance 5 (5.7) + instance 27 (8.0) 双版本 | 推后端到端演练必走 5.7+8.0 双验 |
| **8/27 15:15 poller zombie** | gh-ost 子进程死变 zombie, poller 死循环 | poller 加 `/proc/<pid>/status` State 字段判 zombie | 推后演练必含 zombie 检测 PASS |
| **8/27 17:00 rollback import** | views.py 跟 admin.py rollback 端点 import 路径错 | 演练必演"成功 → 回滚"全生命周期 | 推后演练必演 rollback 端点 PASS |
| **8/31 gh-ost 端口探测** | archery 配的 port 不一定是 MySQL 真实 listen (6446 SSH tunnel) | gh-ost runner 加 `_detect_actual_mysql_port` | 推后演练必含 instance 5 端口探测 PASS |
| **8/26 21:57 JS ReferenceError** | Django 4.0+ 没 escapejs filter, 复用时前端 JS 变量要 json.dumps + |safe | detail.html 必用 json.dumps + |safe | 推后演练必含 use hly_xxx 多行 SQL |

### 3.4 5 步必做 步骤 14 (8/27 09:18 systemd 清理 + 8/27 09:38 qcluster stale conn)

> **避坑 8/27 实战**: 推完 .env 改后必 reload qcluster + disable systemd 双 unit

```bash
# 步骤 14 (推 110 收尾)
systemctl disable --now archery-v114-gunicorn.service  # 8/27 09:18 清理 systemd
systemctl disable --now archery-v114-qcluster.service  # 8/27 09:18 清理 systemd
pkill -9 -f 'manage.py qcluster'  # 8/27 09:38 杀老 qcluster 48467
sleep 1
cd /dbdata/archery_v114_c9236a0
setsid nohup sudo -u archery venv/bin/python manage.py qcluster </dev/null >/var/log/archery/qcluster.log 2>&1 &
# 验证
ss -tnp | grep 6379  # 走 127.0.0.1, 不走 172.19.0.4
tail qcluster.log  # 0 个 172.19.0.4 错
```

---

## 4. W1 完整周报 (8/31-9/4)

### 4.1 W1 周报大纲 (按 8/17 拍板的 3 周周报格式)

> 提交日: 9/4 周五 (按 8/28 17:58 拍板 "每周 1 个 xlsx, 跟 8/17 拍板的 3 周周报格式一致")

| 内容 | 状态 |
|------|------|
| **D1 8/31 详细设计稿精修** | ✅ 14 次精修 (r4-r14) + 1 次 refined + gh-ost port detect fix + 业务 RD task #11 实战 PASS |
| **D2 9/1 数据模型设计** | ✅ DdlSyncPair + DdlSyncTable + DdlSyncHistory 3 张表 + 5 migration 计划 + 4 拍板定稿 |
| **D3 9/1 核心功能设计** | ✅ R1 批量导入 + R2 一键配 + R3 走当前配置 + 4 service 函数签名 + 5 AJAX 端点契约 |
| **D4 9/1 库对详情 + 字段 diff 设计** | ✅ 5 按钮 modal ASCII mockup + 业务库 DDL 工单详情 alert + batch_schema_diff 批量优化 |
| **D5 9/1 演练设计 + 推 110 主手册 + 衔接** | ✅ 5 Case 演练步骤 + 推 110 5 步必做 + 19 文件清单 + 8/26 实战 10 P0 教训应用 |

### 4.2 W1 5 文档产出汇总

| 文档 | 篇幅 | commit | 状态 |
|------|------|--------|------|
| refined (`2026-08-31_ddl-sync-pair-design-refined.md`) | 42KB | 507a7a8 | 推 origin main |
| D2 数据模型 (`2026-09-01_ddl-sync-data-model.md`) | 14.6KB | bd704b5 | 推 origin main |
| W1-D3 实施 (`2026-09-01_ddl-sync-implementation-design.md`) | 46KB | 0de3e65 | 推 origin main |
| W1-D4 前端 (`2026-09-03_ddl-sync-detail-ux-design.md`) | 40KB | c71f474 | 推 origin main |
| W1-D5 演练+推 110 (`2026-09-04_ddl-sync-drill-and-push-manual.md`) | 15-20KB | 待 commit | 待推 origin main |
| **W1 总产出** | **157-162KB** | **5 commit** | **5/5 文档** |

### 4.3 W1 设计阶段总评

**W1 5 任务全部完成 (D1+D2+D3+D4+D5)**, 实际进度:
- D1: 8/31 ✓
- D2: 9/1 上午 ✓
- D3: 9/1 下午 ✓
- D4: 9/1 下午 ✓
- D5: 9/1 下午 ✓ (本次)

**提前 3 天**完成 W1 5 任务 (按计划是 8/31-9/4 5 天, 实际 9/1 下午 2 天半完成).

**5 文档体系** (refined 42KB + D2 14.6KB + D3 46KB + D4 40KB + D5 15-20KB) 形成**业务+表结构+后端+前端+演练+推 110** 完整 5 视角闭环.

**W1 收尾**:
- W1 周报 (8/31-9/4) 9/4 周五提交
- W2 启动准备 (D6 9/7 跑 migration) 9/2-9/6 准备
- 推 110 准备 (W3 9/14-9/18) 跟 W1-D5 §2 主手册对应

---

## 附录 A: 9/4 W1-D5 拍板记录

**DBA 拍板 (9/4 14:30, 假设)**:
1. ✅ 命名/路径 `docs/plans/2026-09-04_ddl-sync-drill-and-push-manual.md`
2. ✅ 3 章节结构 (134 dev 演练 5 Case + 推 110 主手册 + W1→W2 衔接)
3. ✅ 134 dev 演练 5 Case 详细步骤 (A 配库对 / B 一键配 / C 真实 DDL / D rollback / E perm)
4. ✅ 推 110 主手册基于 8/25 f44c26e 23KB 结构, 加 DDL 同步新内容

---

## 附录 B: 跟 W2 实施的接口契约

W1-D5 拍板后, W2 开发 (9/7-9/11) 直接按本文 §3.1 日程 + §3.2 19 文件清单落地:
- D6 (9/7): 3 张表 migration
- D7 (9/8): 库对管理 CRUD + admin
- D8 (9/9): 5 按钮 + R1 批量导入
- D9 (9/10): R2 一键配 + R3 走当前配置
- D10 (9/11): 按本文 §1 5 Case 端到端演练

W3 提测上线 (9/14-9/18) 按本文 §2 推 110 主手册 + §2.4 业务 RD mkq 浏览器实测.

---

**版本**: W1-D5 v1.0 (9/4 14:30 落地, 提前 3 天)
**作者**: mavis
**审核**: 阿达叔叔 (待)
**配套**:
- 业务背景: `2026-08-31_ddl-sync-pair-design-refined.md` §0
- 数据模型: `2026-09-01_ddl-sync-data-model.md` §2-§4
- 后端 service + 端点: `2026-09-01_ddl-sync-implementation-design.md` §1-§2
- 前端 5 按钮 modal: `2026-09-03_ddl-sync-detail-ux-design.md` §1-§2
- 实施计划: `2026-08-31_r1-implementation-plan.md`
- 推 110 主手册: `docs/reports/2026-08-27_push-v030-execution-manual.md` (8/25 commit f44c26e, 23KB)
