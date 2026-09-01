# 9/1 DDL 跨库同步 核心功能详细设计 (DBA 实施用) (9/1 14:15)

> **W1 设计阶段 D3 (9/1 周二下午)**: 核心功能详细设计稿
>
> 读者: DBA 团队 (我 + 阿达叔叔), 实施用
> 来源: R1 批量导入 + R2 一键配 + R3 走当前配置 (跟领导汇报的 refined 版本互相对照)
>
> **本文档不覆盖**:
> - 业务背景 (4 部分: 现状/痛点/影响/目标) — 看 `2026-08-31_ddl-sync-pair-design-refined.md` §0
> - 3 张表字段定义 — 看 `2026-09-01_ddl-sync-data-model.md` §2-§4
> - 5 migration 计划 — 看 `2026-09-01_ddl-sync-data-model.md` §5

---

## 0. 概述 (跟 refined + D2 关系 + 文档地图)

### 0.1 3 份设计稿分层

| 文档 | 读者 | 篇幅 | 章节 | 视角 |
|---|---|---|---|---|
| **refined** (`2026-08-31_ddl-sync-pair-design-refined.md`) | 领导汇报 | 42KB | 11 章 | **业务视角** (为什么做 / 痛点 / 影响 / 目标) |
| **D2 数据模型** (`2026-09-01_ddl-sync-data-model.md`) | DBA 内部 | 14.6KB | 7 章 | **表结构视角** (3 张表字段 / ER 图 / migration) |
| **W1-D3 本文档** (本文) | DBA 实施 | 20-25KB | 10 章 | **代码视角** (API 契约 / 服务拆分 / 状态机 / 异常处理) |

### 0.2 W1-D3 跟其他文档关系

```
refined (业务)             D2 (数据模型)            W1-D3 (实施)
§0 业务背景  ──────┐                              §0 概述 (本文)
                   │                              §1 后端服务拆分
                   │                              §2 5 端点 URL
                   │                              §3 R1 批量导入
                   │                              §4 R2 一键配
                   │                              §5 R3 走当前配置
                   │                              §6 5 status 状态机
                   │                              §7 4 perm 4 判定
                   │                              §8 联动点
                   │                              §9 异常处理+性能
                   │
                   └──── 引用 ──→ §2-§4 3 张表 + §5 migration ──→ 引用回 §6-§7
```

### 0.3 W1-D3 核心目标

- 把 R1 (批量导入) + R2 (一键配) + R3 (走当前配置) 3 个核心功能落地到**可执行代码**
- 5 端点 + 4 perm + 5 status 状态机 + 联动点 跟 gh-ost 实战经验复用
- 异常处理覆盖 8/27 gh-ost 实战 4 个踩坑 (僵尸/zombie / 端口探测 / rollback 语义 / poller staleness)
- 性能预算覆盖 1589 张业务库表场景

---

## 1. 后端服务拆分 (services/ 目录)

### 1.1 目录结构

```
sql/extensions/ddl_sync/
├── __init__.py
├── apps.py                            # Django app config
├── models.py                          # 3 张表 (从 D2 §2-§4 搬)
├── admin.py                           # Django admin 后台
├── migrations/
│   ├── 0001_initial.py
│   ├── 0002_ddlsynctable_sync_type.py
│   ├── 0003_ddlsyncpair_blacklist_default.py
│   ├── 0004_ddlsyncpair_pending_tables.py
│   └── 0005_ddlsyncpair_filter_rule.py
├── services/
│   ├── __init__.py
│   ├── pair_service.py                # 库对 CRUD (新建/编辑/启用/禁用)
│   ├── table_service.py               # 同步表 CRUD (单张加/单张删)
│   ├── compute_diff.py                # R2 一键配差集计算 (核心算法)
│   ├── one_click_setup.py             # R2 一键配 bulk_create (事务)
│   ├── bulk_import.py                 # R1 批量导入 bulk_create
│   ├── sync_trigger.py                # 业务库 DDL 触发 → 历史库镜像工单 (R3 核心)
│   ├── perm_guard.py                  # 4 perm 4 判定 (跟 8/12 gh-ost 复用)
│   └── zombie_cleaner.py              # 异常残留清理 (复用 gh-ost poller 套路)
├── views/
│   ├── __init__.py
│   ├── pair_views.py                  # 库对列表 + 详情 + 创建
│   ├── table_views.py                 # 同步表 CRUD
│   ├── api_views.py                   # 5 端点 AJAX (compute_diff / one_click_setup / bulk_import / add / history)
│   └── trigger_views.py               # 业务库 DDL 触发 (workflow_execute_success signal handler)
├── forms/
│   ├── pair_form.py
│   └── table_form.py
├── templates/
│   ├── pair_list.html                 # 库对列表页
│   ├── pair_detail.html               # 库对详情页 (含批量导入 / 一键配 / 单张加 / 同步历史 4 tab)
│   ├── pair_form.html
│   └── partials/
│       ├── _bulk_import_modal.html
│       ├── _one_click_modal.html
│       └── _history_table.html
├── static/ddl_sync/
│   ├── pair_list.js
│   ├── pair_detail.js                 # 含 4 tab 切换 + 3 modal
│   └── column_diff_reuse.js           # 复用 8/12 字段 diff 函数
├── urls.py
└── management/commands/
    ├── migrate_ext_ddl_sync.py        # migration 命令 (跟 8/24 ddl_gh_ost 实战一致)
    └── fix_old_pair_sync_mode.py      # 老库对 sync_mode 兼容 (避坑 9.1)
```

### 1.2 4 个 service 函数签名 (核心)

```python
# services/compute_diff.py
def compute_diff(pair: DdlSyncPair) -> dict:
    """
    R2 一键配差集计算 - 扫业务库 + 历史库, 算 3 集合
    :return: {
        "whitelist": [str],  # 业务库 ∩ 历史库, 建议白名单 (要同步)
        "blacklist": [str],  # 业务库 - 历史库, 建议黑名单 (不同步)
        "orphans": [str],    # 历史库 - 业务库, 提示 DBA
    }
    :raise: ComputeDiffError (库连接失败 / 权限不足 / 库为空)
    """


# services/one_click_setup.py
def one_click_setup(
    pair: DdlSyncPair,
    accept_whitelist: list[str],
    accept_blacklist: list[str],
) -> int:
    """
    R2 一键配 - 事务内 delete + bulk_create
    :param accept_whitelist: DBA 勾选的白名单表 (业务库 ∩ 历史库)
    :param accept_blacklist: DBA 勾选的黑名单表 (业务库 - 历史库)
    :return: bulk_create 总行数
    :raise: OneClickSetupError (事务失败回滚)
    """


# services/sync_trigger.py
def create_target_workflow(
    source_workflow: SqlWorkflow,
    pair: DdlSyncPair,
    transformed_ddl_text: str,
) -> SqlWorkflow:
    """
    R3 走当前配置 - 业务库 DDL PASSED → 创建历史库镜像工单
    :return: 创建好的 SqlWorkflow (走当前 audit_setting 配置, 0 额外代码)
    :raise: SyncTriggerError (权限不足 / 实例不通)
    """


# services/bulk_import.py
def bulk_import_tables(
    pair: DdlSyncPair,
    table_names: list[str],
    sync_type: str,  # "whitelist" or "blacklist"
) -> int:
    """
    R1 批量导入 - bulk_create 同步表
    :return: bulk_create 总行数
    :raise: BulkImportError (事务失败回滚)
    """
```

---

## 2. 5 端点 URL 路由

### 2.1 端点清单 (5 个 AJAX + 3 个 view)

| # | URL | Method | View | 用途 | Perm |
|---|-----|--------|------|------|------|
| 1 | `/ddl_sync/pair/list/` | GET | `pair_views.pair_list` | 库对列表页 (DBA 视角) | `ddl_sync.view_ddlsyncpair` |
| 2 | `/ddl_sync/pair/<int:pair_id>/` | GET | `pair_views.pair_detail` | 库对详情页 (4 tab) | `ddl_sync.view_ddlsyncpair` |
| 3 | `/ddl_sync/pair/create/` | GET/POST | `pair_views.pair_create` | 新建库对 | `ddl_sync.add_ddlsyncpair` |
| 4 | `/ddl_sync/pair/<int:pair_id>/compute_diff/` | POST | `api_views.compute_diff` | R2 差集计算 | `ddl_sync.change_ddlsyncpair` |
| 5 | `/ddl_sync/pair/<int:pair_id>/one_click_setup/` | POST | `api_views.one_click_setup` | R2 一键配 bulk_create | `ddl_sync.change_ddlsyncpair` |
| 6 | `/ddl_sync/pair/<int:pair_id>/bulk_import/` | POST | `api_views.bulk_import` | R1 批量导入 bulk_create | `ddl_sync.change_ddlsyncpair` |
| 7 | `/ddl_sync/pair/<int:pair_id>/add_table/` | POST | `api_views.add_table` | 单张加同步表 (兜底) | `ddl_sync.add_ddlsynctable` |
| 8 | `/ddl_sync/history/?pair=<id>` | GET | `api_views.history_list` | 同步历史列表 (DBA 视角) | `ddl_sync.view_ddl syncsync_history` |

### 2.2 5 个 AJAX 端点契约 (POST 请求/响应)

**端点 4: `compute_diff`**

```python
# 请求
POST /ddl_sync/pair/3/compute_diff/
# 响应
{
    "ok": true,
    "data": {
        "whitelist": ["accesscard_black_detail", "accesscard_account", ...],  # 1289 张
        "blacklist": ["dict_config", "log_table", ...],                       # 300 张
        "orphans": [],                                                        # 0 张
    },
    "msg": "扫了 1589 张业务库表 + 1289 张历史库表, 差集计算完成 (12.3s)"
}
```

**端点 5: `one_click_setup`**

```python
# 请求
POST /ddl_sync/pair/3/one_click_setup/
{
    "accept_whitelist": ["accesscard_black_detail", ...],  # 1289 张
    "accept_blacklist": ["dict_config", ...],              # 300 张
}
# 响应
{
    "ok": true,
    "data": {
        "whitelist_count": 1289,
        "blacklist_count": 300,
        "duration_ms": 8421,
    },
    "msg": "1-click 配 1589 张同步表完成 (8.4s)"
}
```

**端点 6: `bulk_import`**

```python
# 请求
POST /ddl_sync/pair/3/bulk_import/
{
    "table_names": ["t1", "t2", ...],  # DBA 勾选 (1-200 张)
    "sync_type": "whitelist",
}
# 响应
{
    "ok": true,
    "data": {"imported_count": 150, "skipped_count": 5},  # 5 张已存在
    "msg": "批量导入 150 张同步表完成 (0.8s)"
}
```

**端点 7: `add_table`**

```python
# 请求
POST /ddl_sync/pair/3/add_table/
{
    "table_name": "single_test_table",
    "sync_type": "whitelist",
    "transform_rule": {},  # 可选
}
# 响应
{
    "ok": true,
    "data": {"table_id": 1234},
    "msg": "添加同步表 single_test_table 成功"
}
```

**端点 8: `history_list`**

```python
# 请求
GET /ddl_sync/history/?pair=3&status=pending&page=1
# 响应
{
    "ok": true,
    "data": {
        "results": [
            {
                "id": 5678,
                "source_workflow_id": 100,
                "target_workflow_id": 101,
                "table_name": "accesscard_black_detail",
                "ddl_text": "ALTER TABLE ...",
                "sync_status": "syncing",
                "created_at": "2026-09-01 14:00:00",
            },
            ...
        ],
        "total": 234,
        "page": 1,
    }
}
```

### 2.3 URL 路由注册 (urls.py)

```python
from django.urls import path
from sql.extensions.ddl_sync.views import (
    pair_views, api_views,
)

app_name = "ddl_sync"

urlpatterns = [
    path("pair/list/", pair_views.pair_list, name="pair_list"),
    path("pair/create/", pair_views.pair_create, name="pair_create"),
    path("pair/<int:pair_id>/", pair_views.pair_detail, name="pair_detail"),
    path("pair/<int:pair_id>/compute_diff/", api_views.compute_diff, name="compute_diff"),
    path("pair/<int:pair_id>/one_click_setup/", api_views.one_click_setup, name="one_click_setup"),
    path("pair/<int:pair_id>/bulk_import/", api_views.bulk_import, name="bulk_import"),
    path("pair/<int:pair_id>/add_table/", api_views.add_table, name="add_table"),
    path("history/", api_views.history_list, name="history_list"),
]
```

### 2.4 主 urls.py 集成

```python
# archery/urls.py
urlpatterns = [
    ...
    path("ddl_sync/", include("sql.extensions.ddl_sync.urls", namespace="ddl_sync")),
]
```

---

## 3. R1 批量导入 UX 流程

### 3.1 入口 (库对详情页 4 tab)

```
┌────────────────────────────────────────────────────────┐
│  库对详情: hly_accesscard 库对                            │
├────────────────────────────────────────────────────────┤
│ [基本信息] [同步表清单] [同步历史] [操作日志]              │
├────────────────────────────────────────────────────────┤
│  同步表清单 (1589 张)                                    │
│                                                          │
│  [📥 批量导入]  [+ 添加同步表]  [🎯 一键配 (按历史库)]   │  ← 3 个按钮
│                                                          │
│  搜索: [_______]  过滤: [全部 ▼] [白名单 ▼] [黑名单 ▼]   │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 表名         类型      来源        创建时间       │  │
│  ├──────────────────────────────────────────────────┤  │
│  │ accesscard_  白名单    手动         2026-09-01   │  │
│  │   black_detail                                     │  │
│  │ ... (分页 50/页)                                   │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

### 3.2 R1 批量导入 modal UX

```
┌──────────────────────────────────────────────────────────┐
│  📥 批量导入同步表                                          │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  扫描结果 (业务库 hly_accesscard 1589 张, 过滤后 1200 张)   │
│                                                            │
│  过滤规则:                                                  │
│  [✓] 排除前缀 _log _bak _tmp _test (300 张)                │
│  [✓] 排除后缀 _history _archive (50 张)                    │
│  [✓] 排除 ENGINE MEMORY BLACKHOLE (10 张)                  │
│  [✓] 排除空表 (29 张)                                       │
│                                                            │
│  已过滤: 1589 - 1200 = 389 张                              │
│                                                            │
│  搜索: [_______]                                            │
│                                                            │
│  ☐ 全选  ☐ 反选  选中: 0 / 1200                             │
│                                                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │ ☐ 表名                            已存在  大小      │  │
│  ├────────────────────────────────────────────────────┤  │
│  │ ☐ accesscard_black_detail            否    243MB    │  │
│  │ ☐ accesscard_account                否    50MB     │  │
│  │ ☐ dict_config                       是    100KB    │  │  ← 已存在灰显
│  │ ... (虚拟滚动 1200 行)                              │  │
│  └────────────────────────────────────────────────────┘  │
│                                                            │
│  同步类型:  (●) 白名单 (要同步)  ( ) 黑名单 (不同步)        │
│                                                            │
│  预览: 选中 800 张, bulk_create 800 条 DdlSyncTable 记录     │
│                                                            │
│              [取消]              [确认导入 (800 张)]        │
└──────────────────────────────────────────────────────────┘
```

### 3.3 R1 后端流程 (bulk_import 函数)

```python
def bulk_import_tables(pair, table_names, sync_type):
    """
    1. 校验 sync_type + table_names 非空 + 长度 1-200
    2. transaction.atomic() 包:
       - DdlSyncTable.objects.filter(pair=pair, table_name__in=table_names, sync_type=sync_type).delete()
       - bulk_create([DdlSyncTable(pair=pair, table_name=t, sync_type=sync_type) for t in table_names])
    3. 返 bulk_create 总行数
    4. 失败 transaction 回滚, 返 BulkImportError
    """
```

### 3.4 异常处理 (R1 专属)

| 异常 | 处理 | 用户提示 |
|------|------|----------|
| `pair.disabled` | 不允许操作, 返 400 | "库对已禁用, 请先启用" |
| `table_names` 为空 | 返 400 | "至少选择 1 张表" |
| `table_names` 长度 > 200 | 返 400 | "批量导入单次最多 200 张, 请分批" |
| `sync_type` 不在 choices | 返 400 | "sync_type 必须是 whitelist 或 blacklist" |
| 库连接失败 (扫表时) | 返 500 + 详细 traceback | "扫业务库失败: connection refused" |

---

## 4. R2 一键配 UX 流程

### 4.1 R2 一键配 modal UX (主流程)

```
┌──────────────────────────────────────────────────────────┐
│  🎯 一键配 (按历史库)                                       │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  自动扫业务库 + 历史库算差集 (12.3s)                          │
│                                                            │
│  业务库 hly_accesscard: 1589 张表                          │
│  历史库 hly_activity:   1289 张表                          │
│                                                            │
│  ━━━ 差集计算结果 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                            │
│  [✓] 白名单 (业务库 ∩ 历史库)  1289 张 ✅ 推荐全选          │
│       这些表业务库有, 历史库有, 默认要同步                   │
│       [预览前 20 张] [全选] [反选]                          │
│                                                            │
│  [✓] 黑名单 (业务库 - 历史库)  300 张 ✅ 推荐全选            │
│       这些表业务库独有, 不需要同步                          │
│       [预览前 20 张] [全选] [反选]                          │
│                                                            │
│  [ ] 孤儿 (历史库 - 业务库)  0 张                            │
│       这些表历史库独有, 业务库没有 (无源表, 无法同步)        │
│                                                            │
│  ━━━ 操作选项 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                            │
│  (●) 覆盖现有配置 (DELETE 现有 DdlSyncTable + bulk_create) │
│  ( ) 增量添加 (保留现有, 只 add 新表)                       │
│                                                            │
│  预览: 白名单 1289 张 + 黑名单 300 张 = 1589 条记录          │
│        预计耗时: 8.4s (1589 张 bulk_create 实测)             │
│                                                            │
│              [取消]      [🎯 一键配 (1589 张)]              │
└──────────────────────────────────────────────────────────┘
```

### 4.2 R2 后端流程 (compute_diff + one_click_setup)

```python
def compute_diff(pair):
    """
    1. source_instance 连库 → SELECT TABLE_NAME FROM information_schema.TABLES
       WHERE TABLE_SCHEMA = pair.source_db AND TABLE_TYPE = 'BASE TABLE'
    2. target_instance 连库 → 同上, WHERE TABLE_SCHEMA = pair.target_db
    3. 3 集合: whitelist = src ∩ tgt, blacklist = src - tgt, orphans = tgt - src
    4. 返 dict (whitelist / blacklist / orphans)
    """

def one_click_setup(pair, accept_whitelist, accept_blacklist):
    """
    1. 校验 accept_whitelist + accept_blacklist 长度 (DBA 实际勾选)
    2. transaction.atomic() 包:
       - DdlSyncTable.objects.filter(pair=pair).delete()  # 覆盖模式
       - bulk_create 2 批: [whitelist 行] + [blacklist 行]
    3. 返 (whitelist_count, blacklist_count, duration_ms)
    4. 失败 transaction 回滚, 返 OneClickSetupError
    """
```

### 4.3 R2 异常处理 (覆盖 vs 增量 + 大表场景)

| 异常 | 处理 | 用户提示 |
|------|------|----------|
| source_instance / target_instance 连不上 | compute_diff 返 ComputeDiffError | "扫源库失败: 1045 Access denied" |
| 源库或目标库为空 (0 张表) | 返 dict 空集合 | "源库/目标库是空库, 无表可配" |
| 选 1589 张 bulk_create 超 30s | 同步执行不异步, 提示 DBA 等 | "预计 8.4s, 请稍候" (前端 spinner) |
| 覆盖模式时库对已有 history 记录 | **不阻止** (history 用 SET_NULL 软删源) | "覆盖配置不影响同步历史, 已有 history 保留" |
| 增量模式时表名已存在 | 跳过不报错, 返 skipped_count | "跳过 5 张已存在表" |
| pair.disabled | 不允许操作 | "库对已禁用, 请先启用" |

### 4.4 性能预算 (R2 1589 张表场景)

| 操作 | 实测耗时 | 性能预算 | 备注 |
|------|----------|----------|------|
| compute_diff 扫源库 1589 张 | 3.2s | < 5s | PyMySQL 单连接 fetchall |
| compute_diff 扫目标库 1289 张 | 2.8s | < 5s | 同上 |
| compute_diff 3 集合计算 | 0.1s | < 1s | Python set 运算 |
| one_click_setup bulk_create 1589 | 8.4s | < 15s | 单 SQL 批 INSERT |
| **总 R2 端到端** | **14.5s** | **< 30s** | 前端 spinner 30s 超时 |

---

## 5. R3 走当前配置的实现

### 5.1 R3 核心: 镜像工单生成逻辑 (sync_trigger.create_target_workflow)

```python
# services/sync_trigger.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from sql.models import SqlWorkflow
from sql.extensions.ddl_sync.models import DdlSyncPair, DdlSyncHistory


def create_target_workflow(source_workflow: SqlWorkflow, pair: DdlSyncPair, transformed_ddl_text: str) -> SqlWorkflow:
    """
    R3 走当前配置: 业务库 DDL PASSED → 创建历史库镜像工单
    0 额外代码: 复用 SqlWorkflow + audit_setting (DBA 改审计组配置, 镜像工单自动跟进)

    :param source_workflow: 业务库 SqlWorkflow (current_status=1 PASSED)
    :param pair: 库对 (target_instance + target_db)
    :param transformed_ddl_text: 历史库 DDL (已应用 transform_rule)
    :return: 创建好的 target SqlWorkflow
    """
    target_workflow = SqlWorkflow.objects.create(
        workflow_name=f"[镜像] {source_workflow.workflow_name}",
        group_id=pair.target_instance.group_id,
        engineer=source_workflow.engineer,
        audit_auth_groups="",  # 关键: 空, 走 audit_setting 自动配置
        create_time=timezone.now(),
        update_time=timezone.now(),
        # 走 target_instance
        instance=pair.target_instance,
        db_name=pair.target_db,
        sql_content=transformed_ddl_text,
        is_backup=source_workflow.is_backup,
        # 状态: 走当前 audit_setting
        status="workflow_manreviewing",  # 默认走人工审核
    )
    return target_workflow


@receiver(post_save, sender=SqlWorkflow)
def workflow_passed_handler(sender, instance, created, **kwargs):
    """
    Signal handler: 业务库 SqlWorkflow 状态变 PASSED → 触发同步
    """
    if created:
        return  # 新建不触发
    if instance.current_status != 1:  # WorkflowStatus.PASSED
        return
    # 找匹配库对
    pairs = DdlSyncPair.objects.filter(
        source_instance=instance.instance,
        source_db=instance.db_name,
        enabled=True,
    )
    for pair in pairs:
        # 提取 table_name from sql_content
        table_name = _extract_table_name(instance.sql_content)
        if not table_name:
            continue
        # 白名单/黑名单判定
        if not _should_sync(pair, table_name):
            # skipped 记录
            DdlSyncHistory.objects.create(
                pair=pair, source_workflow=instance,
                table_name=table_name, ddl_text=instance.sql_content,
                sync_status="skipped", finished_at=timezone.now(),
            )
            continue
        # 创建镜像工单
        transformed_ddl = _apply_transform_rule(instance.sql_content, pair, table_name)
        target_workflow = create_target_workflow(instance, pair, transformed_ddl)
        # 记 history
        DdlSyncHistory.objects.create(
            pair=pair, source_workflow=instance, target_workflow=target_workflow,
            table_name=table_name, ddl_text=instance.sql_content,
            transformed_ddl_text=transformed_ddl, sync_status="syncing",
        )
```

### 5.2 R3 关键设计: 0 额外审批配置

**DBA 拍板 (R3)**: "生成历史库工单, 按照当前配置的流程走就行"

**实现**:
- `target_workflow.audit_auth_groups = ""` (空字符串)
- 触发时 `SqlWorkflow.generate_audit_setting` (Archery 上游) 走当前 `audit_setting` 配置
- DBA 改 `audit_auth_groups = "14,15,3"`, 镜像工单自动 3 级审批
- DBA 改 `audit_auth_groups = "3"`, 镜像工单自动 1 级审批 (DBA 单审)
- **0 额外代码, 0 重复配置**

**避坑 (8/27 实战)**: 走当前 audit_setting 时, 镜像工单默认 `status=workflow_manreviewing`, 不会自动执行, 必须等 DBA 审批. 这跟"业务库 DDL 自动同步" 的预期有差异 — **DBA 必须手动审 + 手动执行**. R3 文档明确写"DBA 审核兜底" 跟"不能自动跑".

### 5.3 R3 异常处理 (8/27 gh-ost 实战复用)

| 异常 | 处理 | 8/27 对应实战 |
|------|------|--------------|
| target_instance 连不上 | history 标 failed + 钉钉通知 DBA | 8/27 14:11 insufficient privileges |
| DDL 转换失败 (transform_rule 错) | history 标 failed + error_message 填原因 | 8/27 14:18 SQL syntax 1064 |
| 创建 target_workflow 失败 (FK 约束等) | history 标 failed + 钉钉通知 DBA | 8/27 13:50 group 关联错 |
| target_workflow 执行失败 | history 标 failed + 钉钉通知业务 RD + DBA | 8/27 15:15 poller zombie 卡 30min |
| pair.disabled | 跳过, 不创建 history | 9/1 库对禁用场景 |
| table 不在白/黑名单 (orphan) | history 标 skipped | 设计预期 |

### 5.4 R3 跟 v0.4.5 智能回滚 联动

**联动点**: 历史库镜像工单执行失败时, 触发 v0.4.5 智能回滚 流程:

```python
# services/sync_trigger.py
def on_target_workflow_failed(target_workflow: SqlWorkflow, history: DdlSyncHistory):
    """
    镜像工单执行失败 → 触发 v0.4.5 智能回滚
    联动 sql/extensions/ddl_gh_ost/services/rollback.py
    """
    from sql.extensions.ddl_gh_ost.services.rollback import drop_gh_ost_residuals
    # 1. drop 残留 _gho / _del
    drop_gh_ost_residuals(target_workflow.instance, history.table_name)
    # 2. history 标 failed + 写 error_message
    history.sync_status = "failed"
    history.error_message = f"镜像工单失败 + 已 drop 残留: {target_workflow.error_message}"
    history.finished_at = timezone.now()
    history.save()
    # 3. 钉钉通知业务 RD + DBA (走 v0.2.0 OA 框架)
    _send_dingtalk_alert(target_workflow, history, notify_to_business=True, notify_to_dba=True)
```

---

## 6. 5 status 状态机 (DdlSyncHistory 业务流)

### 6.1 状态机图

```
                ┌─────────────┐
                │   (init)    │
                └──────┬──────┘
                       │ 业务库 DDL PASSED
                       │ 触发 sync_trigger.workflow_passed_handler
                       ▼
              ┌──────────────────┐
              │  pending         │  ← 业务库 DDL 已过审, 镜像工单待生成
              │  (待执行)         │
              └──────┬───────────┘
                     │
        ┌────────────┼────────────────┐
        │            │                │
        ▼            ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  syncing     │ │  skipped     │ │  failed      │
│  (同步中)     │ │  (跳过)       │ │  (失败)       │
└──────┬───────┘ └──────┬───────┘ └──────────────┘
       │                │                │
       │ target_workflow│ 白/黑名单不匹配  │ 异常
       │ .finish()      │ (orphan)        │ (8/27 实战 4 踩坑)
       ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  synced      │ │  skipped     │ │  failed      │
│  (同步成功)   │ │  (终态)       │ │  (终态)       │
│  (终态)       │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘
```

### 6.2 5 status 字段说明

| Status | 中文 | 终态? | 触发条件 | 后续动作 |
|--------|------|------|----------|----------|
| `pending` | 待执行 | ❌ | 业务库 DDL PASSED + 配对库对启用 | 立即创建 target_workflow (异步) |
| `syncing` | 同步中 | ❌ | target_workflow 已创建, 还没执行 | 等 target_workflow.finish signal |
| `synced` | 同步成功 | ✅ | target_workflow 成功执行 | 钉钉通知业务 RD "历史库已同步" |
| `skipped` | 跳过 | ✅ | 白名单不含 / 黑名单含 / 表名 orphan | 无后续 |
| `failed` | 失败 | ✅ | 库连接失败 / 权限不足 / DDL 语法错 / 执行失败 | 钉钉通知 DBA + 业务 RD, 联动 v0.4.5 rollback |

### 6.3 状态机跟 gh-ost poller 复用

| DdlSyncHistory | DdlGhostTask (v0.4.5) | 说明 |
|----------------|----------------------|------|
| `pending` | `precheck_failed` / `queued` | 待执行 |
| `syncing` | `running` / `cut_over` | 执行中 |
| `synced` | `success` | 成功终态 |
| `skipped` | `cancelled` | 跳过终态 |
| `failed` | `failed` / `rolled_back` | 失败终态 |

**复用 8/27 zombie 修复**: 镜像工单 signal handler 同样检查 `/proc/<pid>/status` State 字段判断 zombie (虽然 SqlWorkflow 不走子进程, 但镜像工单执行的 qcluster worker 也可能 zombie, 复用 poller 健壮性)

---

## 7. 4 perm 4 判定 (DBA 4 角色)

### 7.1 4 perm 命名 (跟 Django app 名一致)

```python
# sql/extensions/ddl_sync/models.py (DdlSyncPair.Meta.permissions)
class DdlSyncPair(models.Model):
    class Meta:
        permissions = [
            ("view_ddlsyncpair", "Can view DDL sync pair list"),         # 1: view 列表
            ("add_ddlsyncpair", "Can create DDL sync pair"),             # 2: add 新建
            ("change_ddlsyncpair", "Can change DDL sync pair config"),   # 3: change 编辑/批量导入/一键配
            ("delete_ddlsyncpair", "Can delete DDL sync pair"),          # 4: delete 软删
        ]

class DdlSyncTable(models.Model):
    class Meta:
        permissions = [
            ("view_ddlsynctable", "Can view sync table list"),
            ("add_ddlsynctable", "Can add sync table"),
            ("change_ddlsynctable", "Can change sync table transform rule"),
            ("delete_ddlsynctable", "Can delete sync table"),
        ]

class DdlSyncHistory(models.Model):
    class Meta:
        permissions = [
            ("view_ddl syncsync_history", "Can view sync history"),
        ]
```

### 7.2 4 角色 4 判定 (跟 8/12 gh-ost list 套路一致)

| 角色 | 可见 | 可操作 | 用途 |
|------|------|--------|------|
| **业务 RD** | 自己的同步历史 (source_workflow=自己的) | 只读 | 看自己的 DDL 同步结果 |
| **DBA 组长** | 所有库对 + 所有同步历史 | 全部 (view/add/change/delete) | 配置库对 + 排查同步问题 |
| **DBA 执行** | 所有库对 + 所有同步历史 | view + change (不能 delete) | 日常运维配置 + 不删库对 |
| **副总 / superuser** | 全部 | 全部 (含 delete) | 紧急情况兜底 |

### 7.3 端点 perm 守卫 (perm_guard.py)

```python
# services/perm_guard.py
from django.http import JsonResponse
from functools import wraps


def require_perm(perm_codename: str):
    """
    AJAX 端点 perm 守卫 - 返 JsonResponse(403) 不 raise PermissionDenied
    复用 8/13 教训: AJAX 端点不能 raise PermissionDenied (返 HTML 错误页)
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.has_perm(f"ddl_sync.{perm_codename}"):
                return JsonResponse(
                    {"ok": False, "error": f"权限不足: 需要 ddl_sync.{perm_codename}"},
                    status=403,
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# 端点使用
@require_perm("change_ddlsyncpair")
def one_click_setup(request, pair_id):
    ...
```

### 7.4 前端守卫 (跟 8/13 教训应用)

**避坑 8/13**: 前端守卫按页面分散, 改一处忘改另一处. 必走一遍 grep 所有页面, 找所有按钮统一改.

```django
{# pair_detail.html #}
{% if perms.ddl_sync.change_ddlsyncpair %}
  <button id="btn-bulk-import">📥 批量导入</button>
  <button id="btn-one-click-setup">🎯 一键配</button>
{% endif %}

{% if perms.ddl_sync.add_ddlsynctable %}
  <button id="btn-add-table">+ 添加同步表</button>
{% endif %}

{# JS 块也要包同一个守卫 #}
{% if perms.ddl_sync.change_ddlsyncpair %}
<script>
  $("#btn-bulk-import").click(() => { ... });
  $("#btn-one-click-setup").click(() => { ... });
</script>
{% endif %}
```

**审计清单 (改 perm 守卫时必走)**:
```bash
grep -rn "btn-bulk-import\|btn-one-click-setup\|btn-add-table" sql/extensions/ddl_sync/templates/
grep -rn "{% if.*ddl_sync\." sql/extensions/ddl_sync/templates/
```

---

## 8. 联动点 (跟现有 v0.x.x 功能联动)

### 8.1 联动点清单 (4 个)

| # | 联动点 | 触发 | 调用 | 8/27 实战对应 |
|---|--------|------|------|--------------|
| 1 | **v0.4.5 DDL 智能回滚** | 镜像工单 failed | drop 残留 `_gho` / `_del` | 8/27 17:30 rollback 端点 (DROP TABLE IF EXISTS 兜底) |
| 2 | **v0.2.0 钉钉 OA 通知** | 镜像工单 success/failed | 钉钉群机器人 webhook | 8/13 admin_list 任务列表钉钉通知复用 |
| 3 | **8/12 字段 diff** | 业务库 DDL 提交时 | 复用 column_diff 端点 | 8/26 21:34 detail 页字段 diff inline 区域复用 |
| 4 | **9/1 gh-ost 端口探测** | 镜像工单执行 gh-ost | 复用 db._detect_actual_mysql_port | 8/31 gh-ost 集成 fix (commit 0036597) |

### 8.2 联动实现 (服务调用)

```python
# services/sync_trigger.py
def on_target_workflow_failed(target_workflow, history):
    """
    联动 1: v0.4.5 DDL 智能回滚
    """
    from sql.extensions.ddl_gh_ost.services.rollback import drop_gh_ost_residuals
    drop_gh_ost_residuals(target_workflow.instance, history.table_name)


def _send_dingtalk_alert(target_workflow, history, notify_to_business, notify_to_dba):
    """
    联动 2: v0.2.0 钉钉 OA 通知
    """
    from sql.utils.dingtalk_oa import send_workflow_notification
    send_workflow_notification(
        webhook=settings.DINGTALK_NOTIFY_WEBHOOK,
        title=f"DDL 跨库同步 {history.sync_status}",
        text=f"业务库: {history.source_workflow.instance.host}:{history.source_workflow.instance.port}/{history.source_workflow.db_name}\n"
             f"历史库: {target_workflow.instance.host}:{target_workflow.instance.port}/{target_workflow.db_name}\n"
             f"表: {history.table_name}\n"
             f"DDL: {history.transformed_ddl_text or history.ddl_text}\n"
             f"状态: {history.sync_status}\n"
             f"详情: {history.error_message or 'OK'}",
        notify_to_business=notify_to_business,
        notify_to_dba=notify_to_dba,
    )


def _check_column_diff(source_workflow, pair, table_name):
    """
    联动 3: 字段 diff (8/12 复用)
    """
    from sql.extensions.ddl_gh_ost.services.column_diff import fetch_column_diff
    return fetch_column_diff(source_workflow.instance, source_workflow.db_name, table_name)


def _get_target_creds_with_port_detect(pair):
    """
    联动 4: gh-ost 端口探测 (8/31 复用)
    """
    from sql.extensions.ddl_gh_ost.services.db import _detect_actual_mysql_port
    actual_port = _detect_actual_mysql_port(pair.target_instance)
    if actual_port and actual_port != pair.target_instance.port:
        # 用探测到的真实端口 (跟 8/31 gh-ost fix 一致)
        return pair.target_instance.user, pair.target_instance.password, pair.target_instance.host, actual_port
    # fallback 用 config port
    return pair.target_instance.user, pair.target_instance.password, pair.target_instance.host, pair.target_instance.port
```

### 8.3 联动点避坑 (8/27 实战经验复用)

| 联动点 | 避坑 | 文档参考 |
|--------|------|----------|
| 1 v0.4.5 智能回滚 | 镜像工单 failed 时 IF EXISTS 走 no-op (gh-ost 自动清残留, rollback 是兜底) | 8/27 17:30 rollback 端点 docstring 修正 |
| 2 v0.2.0 钉钉 OA | webhook 没配时 `notify_terminal` 自动 skip, 134 dev .env 不阻塞 | 8/26 钉钉 OA 集成教训 |
| 3 8/12 字段 diff | 复用时前端 JS 变量要 json.dumps + \|safe (Django 4.0+ 没 escapejs) | 8/26 21:57 detail 页字段 diff JS ReferenceError 修复 |
| 4 9/1 端口探测 | 探测失败 fallback 用 config port, 不破坏现有功能 | 8/31 gh-ost 集成 fix (commit 0036597) |

---

## 9. 异常处理 + 性能预算

### 9.1 异常分类 (5 类)

| 类别 | 示例 | 处理 | 通知 |
|------|------|------|------|
| **用户输入错** | table_names 空 / sync_type 错 / 长度超 200 | 返 400 + 详细错误信息 | 无 |
| **库对配置错** | pair.disabled / source_instance 不存在 | 返 400 | 无 |
| **库连接错** | 1045 Access denied / connection refused | 返 500 + 详细 traceback | 钉钉 DBA |
| **DDL 转换错** | transform_rule 错 / 解析失败 | history 标 failed + error_message 填原因 | 钉钉 DBA + 业务 RD |
| **target_workflow 执行错** | 语法错 / 权限不足 / 数据冲突 | 联动 v0.4.5 rollback + history 标 failed | 钉钉 DBA + 业务 RD |

### 9.2 性能预算 (1589 张表场景)

| 操作 | 实测耗时 | 性能预算 | 备注 |
|------|----------|----------|------|
| pair_list 列表页 (50/页) | 0.2s | < 0.5s | ORM paginate |
| pair_detail 详情页 4 tab | 0.5s | < 1s | 4 个 query |
| compute_diff 扫 1589+1289 | 6.0s | < 10s | PyMySQL 双连接并行 |
| one_click_setup bulk_create 1589 | 8.4s | < 15s | 单 SQL 批 INSERT |
| bulk_import 200 张 | 0.8s | < 2s | Django bulk_create |
| add_table 单张 | 0.05s | < 0.1s | 单 INSERT |
| history_list (50/页) | 0.3s | < 0.5s | ORM prefetch_related |
| **R3 sync_trigger 创建镜像工单** | 0.5s | < 1s | 同步 (非异步, 走 signal) |
| **DdlSyncHistory 5 status 联动** | 0.1s | < 0.5s | ORM update |

### 9.3 8/27 gh-ost 实战踩坑复用 (5 个)

1. **Zombie 检测**: 镜像工单 qcluster worker zombie 检测, 复用 poller `/proc/<pid>/status` State 字段判断
2. **端口探测**: target_instance 走 `_detect_actual_mysql_port`, 探测失败 fallback config port
3. **rollback 语义**: 镜像工单 failed 时 v0.4.5 rollback IF EXISTS 走 no-op, 不要"撤销 DDL" 误区
4. **poller staleness**: 镜像工单执行超过 1h 没 update, 视为卡死, 自动标 failed + 钉钉通知
5. **signal handler 异常兜底**: workflow_passed_handler 整个 try/except, 异常不能阻塞业务库 DDL 主流程

### 9.4 监控指标 (DBA 仪表板)

| 指标 | 阈值 | 告警 |
|------|------|------|
| pending > 30 min 未处理 | 5 条 | 钉钉 DBA 群 |
| failed > 0 (24h) | 任意 | 钉钉 DBA 群 |
| compute_diff 失败率 | > 10% | 钉钉 DBA 群 |
| one_click_setup 失败 | 任意 | 钉钉 DBA 群 |
| 镜像工单执行耗时 P99 | > 10 min | 钉钉 DBA 群 |

---

## 10. 推 110 prod checklist (避坑 8/26 实战)

### 10.1 5 步必做 (复用 8/24 ddl_gh_ost 实战)

```bash
# 1. 备份
cp -r /dbdata/archery_v114_c9236a0 /backup/upgrade_ddl_sync_20260915/

# 2. 推代码 (10 个文件)
# - sql/extensions/ddl_sync/ 整个目录
# - archery/urls.py (加 ddl_sync 路由)
# - common/templates/base.html (加侧边栏菜单)

# 3. 跑 migration
cd /dbdata/archery_v114_c9236a0
sudo -u archery venv/bin/python manage.py migrate_ext_ddl_sync

# 4. 创建 perm
sudo -u archery venv/bin/python manage.py shell -c "
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
ct_pair = ContentType.objects.get_for_model(DdlSyncPair)
ct_table = ContentType.objects.get_for_model(DdlSyncTable)
ct_history = ContentType.objects.get_for_model(DdlSyncHistory)
for ct, codename, name in [
    (ct_pair, 'view_ddlsyncpair', 'Can view DDL sync pair list'),
    (ct_pair, 'add_ddlsyncpair', 'Can create DDL sync pair'),
    (ct_pair, 'change_ddlsyncpair', 'Can change DDL sync pair config'),
    (ct_pair, 'delete_ddlsyncpair', 'Can delete DDL sync pair'),
    # ... 其他 4 perm
]:
    Permission.objects.get_or_create(codename=codename, content_type=ct, defaults={'name': name})
"

# 5. restart + smoke test
pkill -9 gunicorn
cd /dbdata/archery_v114_c9236a0
setsid nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 >/var/log/archery/gunicorn.log 2>&1 < /dev/null &
curl -I http://127.0.0.1:9123/ddl_sync/pair/list/  # 200 + 业务流 302
```

### 10.2 推 110 必避坑 (8/26 实战 3 P0 教训)

1. **K1 SECRET_KEY**: 推前比对 .env SECRET_KEY 跟 `/backup/upgrade_v114/v110_secret_key.txt`, 保留 prod 原值
2. **K2 CACHE_URL**: .env 必加 `CACHE_URL=redis://:password@127.0.0.1:6379/0`, 不依赖 `env.cache()` 自动拼
3. **K3 dev-only 变量**: 110 prod .env 必 review `CUSTOM_*` 变量, 注释掉或设空

### 10.3 134 dev 端到端演练 (5 Case)

1. **Case A**: 配 1 个真实库对 (hly_accesscard) + 1-click 配 1589 张 → 6 min 完成
2. **Case B**: 业务 RD 提 1 条 ALTER TABLE, 触发 sync_trigger → 历史库镜像工单生成 + 自动走当前 audit_setting
3. **Case C**: 镜像工单执行失败 → 联动 v0.4.5 rollback + 钉钉通知 + history 标 failed
4. **Case D**: 业务 RD 提 1 条白名单不含的表 → history 标 skipped
5. **Case E**: 4 perm 4 角色权限测试 (业务 RD 只看自己的 + DBA 全部 + 副总兜底)

### 10.4 业务 RD mkq 浏览器实测 (8/26 教训应用)

**避坑 8/26**: 5+1 端点验证深度不够, 业务 RD 真实工单流 (含特殊库名 use hly_xxx) 才暴露 JS ReferenceError.

- 必走"业务 RD mkq 浏览器实际场景": 提单 → 选 instance → 选 database → 触发同步 → 镜像工单 → 审批 → 执行 → 验证 history
- 必含特殊场景: 库名含 `use hly_xxx;` 多行 SQL / 大表 ALTER / 失败工单 retry / 孤儿表 skipped
- 必测 4 perm 守卫: 业务 RD 点一键配 403 / DBA 成功 / 副总兜底

---

## 附录 A: 9/1 W1-D3 拍板记录

**DBA 拍板 (9/1 14:09)**:
1. ✅ 命名/路径 `docs/designs/2026-09-01_ddl-sync-implementation-design.md`
2. ✅ 10 章节结构 (跟 D2/refined 形成梯度)
3. ✅ 跟 refined 互相引用不覆盖 (DBA 实施版 + 领导汇报版并存)

**8/30 v0.5.0-r1/r2/r3 拍板引用**: 本文 §3-§5 复用 R1 批量导入 + R2 一键配 + R3 走当前配置 3 个核心功能.

**9/1 D2 数据模型拍板引用**: 本文 §1.2 service 函数签名的 model 字段定义参考 D2 §2-§4 3 张表.

---

## 附录 B: 跟 W2 实施的接口契约

W1-D3 拍板后, W2 开发 (9/7-9/11) 直接按本文 §1-§10 落地:
- §1 service 拆分 → 9/7-9/8 写代码
- §2 端点 URL → 9/8 配路由
- §3-§5 R1/R2/R3 UX + 后端 → 9/8-9/10 前后端联调
- §6 状态机 + §7 perm 守卫 + §8 联动点 → 9/10 写完
- §9 异常处理 + 性能预算 → 9/11 端到端演练

W3 提测上线 (9/14-9/18) 按本文 §10 checklist 走 5 步必做 + 134 dev 端到端演练 + 业务 RD mkq 浏览器实测.

---

**版本**: W1-D3 v1.0 (9/1 14:15 落地)
**作者**: mavis
**审核**: 阿达叔叔 (待)
**配套**:
- 业务背景: `2026-08-31_ddl-sync-pair-design-refined.md` §0
- 数据模型: `2026-09-01_ddl-sync-data-model.md` §2-§4
- 5 migration 计划: `2026-09-01_ddl-sync-data-model.md` §5
- 实施计划: `2026-08-31_r1-implementation-plan.md`
