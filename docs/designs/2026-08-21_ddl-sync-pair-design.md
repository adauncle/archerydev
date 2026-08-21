# DDL 跨库同步 · 业务库 ↔ 历史库 详细设计

> **Archery v0.5.0 · 二次开发设计稿**
> 解决"业务库 DDL 变更容易遗漏同步到历史库"的痛点 — DBA 配库对白名单, Archery 自动判断 + 自动建历史库 DDL 工单, 业务 RD 啥都不用管。

**作者**: mavis
**日期**: 2026-08-21
**版本**: v0.5.0 详细设计
**粒度**: 可直接动手写代码
**配套**: [HTML 版](2026-08-21_ddl-sync-pair-design.html)

---

## 目录

1. [设计原则](#1-设计原则)
2. [业务场景](#2-业务场景)
3. [产品界面 (5 个核心页面)](#3-产品界面-5-个核心页面)
4. [权限模型](#4-权限模型)
5. [数据模型 (3 张表)](#5-数据模型-3-张表)
6. [URL 路由](#6-url-路由)
7. [联动点 (v0.4.5 / v0.3.0 / v0.2.0)](#7-联动点-v045--v030--v020)
8. [实施阶段 (短期 C → 中期 B)](#8-实施阶段-短期-c--中期-b)
9. [风险与验证](#9-风险与验证)
10. [跟 8/19 教训对照](#10-跟-819-教训对照)

---

## 1. 设计原则

跟之前 5 个二次开发项目 (gh-ost / DDL 智能回滚 / OA / RaccoonX / v0.4.5 rebuild) 一致, 走"扩展 + 复用 + 不重写"路线。

| 原则 | 落地方式 |
|---|---|
| 二次开发, 不动上游 | 新建 `sql/extensions/ddl_sync/` extension, 跟 `ddl_gh_ost/` / `audit_drivers/` 同级 |
| 复用现有 SQL 工单 | 历史库 DDL 工单直接复用 `SqlWorkflow` 表 + `audit_drivers` 审批, 0 业务代码改动 |
| DBA 配库对, RD 不用管 | DBA 在 Archery 后台配"业务库 ↔ 历史库 白名单表清单", 业务 RD 提工单 Archery 自动判断 |
| 权限跟 gh-ost 任务一致 | 4 个标准 perm, `{% if perms %}` 条件渲染, 跟 `c80c1ad` (8/12) 一套机制 |
| 复用 Archery 已有 | SqlWorkflow / Instance / audit_drivers / dingtalk_oa / Q2 schedule / mirage-field 加密 |
| 跟 5 个二次开发联动 | v0.4.5 智能回滚 + v0.3.0 gh-ost + v0.3.x 大表防呆 + v0.2.0 钉钉 OA 全部联动 |

> **核心思路 (8/21 拍板)**: 历史库只同步**部分表** (不是全量), 业务 RD 不知道"要不要同步"。解法 — DBA 在 Archery 后台配"业务库 ↔ 历史库 白名单表清单", 业务 RD 提 DDL 时 Archery 自动查表, 在白名单 → 自动建历史库 DDL 工单, 不在 → 走原流程不联动, UI 提示清晰。

---

## 2. 业务场景

### 2.1 真实痛点

业务库 (源) 和历史库 (归档) 通过时间戳同步数据, 但 DDL 不同步。常见 DDL 类型对应的处理:

| DDL 类型 | 历史库是否要同步 | 漏同步后果 |
|---|---|---|
| `ADD COLUMN` | **必须** | 时间戳同步跑历史库报 `Unknown column 'xxx'`, 同步断 |
| `MODIFY COLUMN` (改类型/长度) | **必须** | 同步超长字段报错 / 类型转换报错 |
| `CHANGE COLUMN` (重命名+改类型) | **必须** | 历史库字段对不上, 同步逻辑出错 |
| `RENAME TABLE` | **必须** | 同步任务找不到原表 |
| `DROP COLUMN` | 可选 | 历史数据保留, 后续清理时再同步 |
| `ADD INDEX` | 通常不用 | 历史库数据少, 索引意义不大 |
| `DROP INDEX` | 通常不用 | 同上 |

### 2.2 4 个角色 + 2 个新角色

| 角色 | 场景 |
|---|---|
| **业务 RD** | 提 DDL, **不用判断要不要同步**。Archery 提工单时自动查库对配置, 工单详情页提示"本表已/未配置进历史库" |
| **DBA (业务库)** | 配**库对白名单** (业务库 ↔ 历史库 + 同步表清单), 审业务库 DDL 工单 |
| **DBA (历史库)** [新增角色] | 审**历史库 DDL 工单**, 看库对巡检结果, 修复历史库 schema 不一致 |
| **业务 leader** | 看自己业务库 DDL 同步状态, 工单页能看到"业务库完成 / 历史库完成"两个状态 |
| **admin** | 在 Django admin 后台给权限组勾 perm (4 个 perm 4 个判定) |
| **历史库 DDL 审批人** | **同业务库 DDL 审批人** (8/21 拍板), 简化流程, 跟现有 3 级审批一致 |

---

## 3. 产品界面 (5 个核心页面)

### 3.1 库对管理列表 (`/ddl_sync/pair_list/`, DBA 专属)

跟 "gh-ost 任务" / "数据库巡检" 并列, 条件渲染 (有 `view_ddlsyncpair` perm 才显示)。

```
🔗 DDL 同步库对管理                                       [+ 新建库对]
┌──────────┬────────────────┬──────┬──────────┬──────────┬────────┐
│ 配对名   │ 业务库          │ ⇄   │ 历史库    │ 模式     │ 操作   │
├──────────┼────────────────┼──────┼──────────┼──────────┼────────┤
│ accesscard│ hly_accesscard@134│ ⇄  │ hly_history@X│ 白名单  │ ✏️📋📊│
│ log 库对 │ hly_log@134     │ ⇄  │ hly_log_hist@X│ 白名单  │ ✏️📋📊│
│ ...                                                                │
└──────────┴────────────────┴──────┴──────────┴──────────┴────────┘
```

### 3.2 库对详情 (`/ddl_sync/pair/<id>/detail/`)

```
accesscard 库对 ⇄ 白名单模式
业务库: hly_accesscard (172.20.2.134:3306) · 历史库: hly_history (172.20.2.X:3306)

同步表清单 (3 / 12)
  accesscard_black_detail     [同步] 字段 35 个  ✏️🗑️
  accesscard_log              [同步] 字段 12 个  ✏️🗑️
  accesscard_audit            [同步] 字段 8 个   ✏️🗑️
  ... 还有 9 张表未配置同步 (按需添加)
                                              [+ 添加同步表]

最近 5 次同步历史
  #12345 业务库工单  2026-08-21 19:30  [已完成]  历史库 #12346 执行成功
  #12280 业务库工单  2026-08-19 14:12  [已完成]  历史库 #12281 执行成功
  ...

[🔍 立即跑巡检 (C 方案兜底)]
```

### 3.3 业务库 DDL 工单详情 (核心 UX 改造)

工单详情页增加"历史库联动"子状态, 业务 RD 一眼看到"本表要不要同步"。

```
SQL 工单 #12345 [DDL 跨库同步]
业务 RD @张三 · 提交时间 2026-08-21 19:00

ALTER TABLE accesscard_black_detail ADD COLUMN card_serial VARCHAR(64) DEFAULT NULL;

执行状态
  ✅ 业务库 (hly_accesscard@134)
     执行完成 2026-08-21 19:30 · 影响行数 0 · 耗时 2.3s

  🔄 历史库 (hly_history@X) [⇄ 联动]
     DDL 工单 #12346 审核中 · DBA @李四 待审 · 查看 →

💡 本表 accesscard_black_detail 已配置进历史库同步
   (accesscard 库对 · 白名单)。业务库审批通过后, Archery 自动
   生成历史库 DDL 工单, 走同一审批人审批。
```

### 3.4 历史库 DDL 工单列表 (DBA 兜底视角)

```
🔗 历史库 DDL 工单 [由业务库联动生成]
┌────────┬──────────┬────────────────────┬──────────┬──────────┬────────┐
│ 工单   │ 业务库   │ 表                 │ 时间     │ 状态     │ 原工单 │
├────────┼──────────┼────────────────────┼──────────┼──────────┼────────┤
│ #12346 │ accesscard│ accesscard_black_detail│ 8/21 19:30│ 审核中 │ → #12345│
│ #12281 │ accesscard│ accesscard_log     │ 8/19 14:12│ 已完成  │ → #12280│
│ #12100 │ log      │ accesscard_log_archive│ 8/15 10:00│ 失败  │ → #12099│
│ ...                                                                          │
└────────┴──────────┴────────────────────┴──────────┴──────────┴────────┘
```

### 3.5 库对巡检结果 (C 方案兜底)

```
accesscard 库对 · 巡检结果
巡检时间: 2026-08-21 20:00 · 对比 3 张同步表

🔴 1 张表 schema 不一致
  accesscard_black_detail  [5 列缺失]  [card_serial (8/21 漏同步)]  [idx_xxx (8/15 漏同步)]  [生成补 DDL →]
  详情: 业务库新增 5 个字段 / 历史库 0 个 — 业务库 DDL 未联动到历史库, 需要补 DDL 工单。

🟢 2 张表 schema 一致
  accesscard_log · accesscard_audit — 同步正常, 无需修复。

⚠️ 此巡检由 DBA @张三 在 8/21 20:00 手动触发, 建议配定时任务 (每天凌晨跑) + 不一致推钉钉给历史库 DBA。
```

---

## 4. 权限模型

跟 8/12 gh-ost 任务管理列表页 (commit `c80c1ad`) + RaccoonX 接入 (commit `ddba8f9`) 一套机制, **0 业务代码改动做权限** — 纯靠 Django admin 自动注册 perm。

### 4.1 4 个 perm 全部注册

Django admin 会自动给 `DdlSyncPair` model 注册这 4 个标准 perm:

| Perm | 用途 | 谁有 (默认) |
|---|---|---|
| `view_ddlsyncpair` | 看库对管理菜单 + 库对列表 + 库对详情 + 巡检 | DBA + admin |
| `add_ddlsyncpair` | 新建库对 (配业务库 ↔ 历史库) | 仅 DBA + admin |
| `change_ddlsyncpair` | 编辑库对 / 添加删除同步表 / 启用禁用 | 仅 DBA + admin |
| `delete_ddlsyncpair` | 删除库对 | 仅 DBA + admin |

> **8/21 拍板**: 4 个 perm 全部注册, 业务 RD **默认不能**看到库对管理菜单 (不需要看), 库对管理菜单仅 DBA 看。8/13 教训: 默认权限最小化。

### 4.2 菜单条件渲染 (base.html)

```django
{% if perms.ddl_sync.view_ddlsyncpair %}
  <li class="nav-item">
    <a href="{% url 'ddl_sync:pair_list' %}">
      🔗 DDL 同步管理
    </a>
  </li>
{% endif %}
```

### 4.3 页面装饰器 (views.py)

```python
from django.contrib.auth.decorators import permission_required

@permission_required("ddl_sync.view_ddlsyncpair")
def pair_list(request): ...
@permission_required("ddl_sync.view_ddlsyncpair")
def pair_detail(request, pair_id): ...
@permission_required("ddl_sync.add_ddlsyncpair")
def pair_new(request): ...
@permission_required("ddl_sync.change_ddlsyncpair")
def pair_edit(request, pair_id): ...

# 历史库 DDL 工单本身用现有 SqlWorkflow, 走 audit_drivers 审批
# 不需要单独 perm — 跟业务库 DDL 工单共享 SqlWorkflow perm
```

### 4.4 业务 RD 工单页提示 (无库对 perm 也看得到)

业务 RD 提 DDL 时, Archery 自动查库对配置, 工单详情页显示"本表已/未配置进历史库同步"。这个提示**不需要 perm 守卫**, 所有登录用户看自己工单都能看到。

### 4.5 DBA 在 admin 后台配置权限

```
Django admin → 认证和授权 → 组
  ├─ "DBA" 组:      权限 → 勾选 ddl_sync 4 个 perm ✓
  ├─ "DBA组长" 组:  跟 DBA 一样
  └─ "业务RD" 组:   权限 → 不勾 ddl_sync (业务 RD 不需要看库对配置)
```

---

## 5. 数据模型 (3 张表)

### ER Diagram

```
┌──────────────────────────┐
│  ext_ddl_sync_pair       │
├──────────────────────────┤
│ 🔑 id (PK)               │
│ → source_instance_id     │  1:N
│ source_db                │  ↓
│ → target_instance_id     │  ┌──────────────────────────┐
│ target_db                │  │  ext_ddl_sync_table      │
│ sync_mode                │  ├──────────────────────────┤
│ enabled                  │  │ 🔑 id (PK)               │
│ name, created_by         │  │ → pair_id (FK)           │
│ ↳ unique(source_inst,    │  │ table_name               │
│          source_db)      │  │ transform_rule (JSON)    │
└──────────────────────────┘  │ created_at               │
                             │ ↳ unique(pair, table)    │
                             └──────────────────────────┘

┌──────────────────────────┐
│  ext_ddl_sync_history    │
├──────────────────────────┤
│ 🔑 id (PK)               │
│ → pair_id (FK)           │
│ → source_workflow_id (FK)│
│ → target_workflow_id (FK)│
│ table_name, ddl_text     │
│ sync_status              │
│ created_at, finished_at  │
└──────────────────────────┘
```

### 5.1 `ext_ddl_sync_pair` (库对配置)

```python
class DdlSyncPair(models.Model):
    """业务库 ↔ 历史库 同步关系 (DBA 配)

    业务键: (source_instance, source_db) 唯一
    """
    SYNC_MODE_CHOICES = [
        ("whitelist", "白名单"),  # DBA 显式配要同步的表 (8/21 拍板)
        ("blacklist", "黑名单"),  # 默认全同步, DBA 排除不要的
    ]

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=128)  # 配对名, 如 "accesscard 库对"

    # 业务库
    source_instance = models.ForeignKey(Instance, on_delete=models.CASCADE, related_name="sync_pair_source")
    source_db = models.CharField(max_length=64)

    # 历史库
    target_instance = models.ForeignKey(Instance, on_delete=models.CASCADE, related_name="sync_pair_target")
    target_db = models.CharField(max_length=64)

    sync_mode = models.CharField(max_length=16, choices=SYNC_MODE_CHOICES, default="whitelist")
    enabled = models.BooleanField(default=True)

    # 元数据
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ext_ddl_sync_pair"
        unique_together = [("source_instance", "source_db")]
```

### 5.2 `ext_ddl_sync_table` (同步表清单)

```python
class DdlSyncTable(models.Model):
    """业务库下要同步的表 (DBA 配)

    跟 ddl_sync_pair 多对一, 一个库对可配多张同步表
    """
    id = models.AutoField(primary_key=True)
    pair = models.ForeignKey(DdlSyncPair, on_delete=models.CASCADE, related_name="tables")
    table_name = models.CharField(max_length=128)

    # 可选: 历史库 DDL 调整规则 (Phase 2 扩展, Phase 1 默认空)
    # 例如: {"skip_columns": ["temp_flag"], "rename_columns": {"xxx": "yyy"}}
    transform_rule = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ext_ddl_sync_table"
        unique_together = [("pair", "table_name")]
        indexes = [
            models.Index(fields=["pair", "table_name"]),
        ]
```

### 5.3 `ext_ddl_sync_history` (同步历史审计)

```python
class DdlSyncHistory(models.Model):
    """同步历史审计 (DBA 看, 出问题追溯)

    业务库 DDL 工单执行成功后 + 自动建历史库 DDL 工单 + 历史库执行成功/失败
    """
    SYNC_STATUS_CHOICES = [
        ("pending", "待发起"),  # 业务库执行中, 还没建历史库工单
        ("created", "已发起"),  # 历史库 DDL 工单已建, 待审
        ("success", "成功"),    # 历史库 DDL 执行成功
        ("failed", "失败"),     # 历史库 DDL 失败, 需人工修复
        ("skipped", "跳过"),    # 业务库 DDL 类型不需要同步 (DROP INDEX 等)
    ]

    id = models.AutoField(primary_key=True)
    pair = models.ForeignKey(DdlSyncPair, on_delete=models.CASCADE, related_name="history")
    source_workflow = models.ForeignKey(SqlWorkflow, on_delete=models.PROTECT, related_name="sync_source")
    target_workflow = models.ForeignKey(SqlWorkflow, on_delete=models.SET_NULL, null=True, blank=True, related_name="sync_target")

    table_name = models.CharField(max_length=128)
    ddl_text = models.TextField()  # 原始 DDL (业务库)
    sync_status = models.CharField(max_length=16, choices=SYNC_STATUS_CHOICES, default="pending")

    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ext_ddl_sync_history"
        indexes = [
            models.Index(fields=["pair", "-created_at"]),
            models.Index(fields=["sync_status", "-created_at"]),
        ]
```

> **3 张表 migration 计划**:
> `0001_initial.py` (pair) →
> `0002_ddlsynctable.py` →
> `0003_ddlsynchistory.py`。
> 推 110 时通过 5 步必做补一条 `migrate_ext_ddl_sync`, 5.7/8.0 兼容 (跟 ddl_gh_ost 4 个 migration 8/18 演练一致)。

---

## 6. URL 路由

```python
# sql/extensions/ddl_sync/urls.py
from django.urls import path
from . import views

app_name = "ddl_sync"

urlpatterns = [
    # 库对管理 (DBA 专属)
    path("pair_list/", views.pair_list, name="pair_list"),
    path("pair/new/", views.pair_new, name="pair_new"),
    path("pair/<int:pair_id>/edit/", views.pair_edit, name="pair_edit"),
    path("pair/<int:pair_id>/delete/", views.pair_delete, name="pair_delete"),
    path("pair/<int:pair_id>/detail/", views.pair_detail, name="pair_detail"),

    # 同步表管理 (DBA 专属)
    path("pair/<int:pair_id>/table/add/", views.table_add, name="table_add"),
    path("pair/<int:pair_id>/table/<int:table_id>/delete/", views.table_delete, name="table_delete"),

    # 历史库 DDL 工单列表 (DBA 兜底视角)
    path("history_workflows/", views.history_workflows, name="history_workflows"),

    # 库对巡检 (C 方案兜底)
    path("inspect/run/", views.inspect_run, name="inspect_run"),
    path("inspect/result/<int:pair_id>/", views.inspect_result, name="inspect_result"),

    # AJAX 端点 (前端用)
    path("api/check_table_sync/", views.api_check_table_sync, name="api_check_table_sync"),
]
```

```python
# archery/urls.py  (include 段)
if getattr(settings, "CUSTOM_DDL_SYNC_ENABLED", False):
    urlpatterns += [
        path("ddl_sync/", include(("sql.extensions.ddl_sync.urls", "ddl_sync"))),
    ]
```

---

## 7. 联动点 (v0.4.5 / v0.3.0 / v0.2.0)

这个功能不是孤立的, 跟 Archery 现有 5 个二次开发全部联动 — 这是为什么能在 2 周内出活的原因。

| 已有功能 | 联动方式 | 业务价值 |
|---|---|---|
| **v0.4.5 DDL 智能回滚** (commit `e54a663`) | 历史库 DDL 工单也走智能回滚 (ADD COLUMN 逆向 DROP COLUMN, MODIFY COLUMN 逆向回原值) | 历史库 DDL 失败能自动回滚, 减少人工修复 |
| **v0.3.0 gh-ost** (commit `cd2ce88`) | 历史库 DDL 如果是大表 (检测跟业务库一样, 走 `ext_ddl_ghost_task` 大表阈值), 自动套 gh-ost 避免锁表 | 历史库大表 DDL 也能无锁执行 |
| **v0.3.x 大表 DDL 防呆** (commit `374d990`) | 历史库 DDL 提单时也走大表防呆 (大表 → 提示 gh-ost / 立即执行 / 终止) | 历史库大表 DDL 不会一不小心直接执行锁表 |
| **v0.2.0 钉钉 OA** (commit `d5f88d1`) | 历史库 DDL 工单审批人跟业务库一样 (走同一 audit driver), 审批消息推钉钉 | DBA 不用切系统, 钉钉里就能审 |
| **audit_drivers 3 级审批** | 历史库 DDL 工单走 ext_approval_flow 配置的审批流 (默认 DBA 单审, 可配多级) | 跟业务库 DDL 一致的安全审批 |

### 7.1 跟 v0.4.5 DDL 智能回滚联动 (核心)

历史库 DDL 工单走 `SqlWorkflow` 现有流程, 自动调用 v0.4.5 的智能回滚服务:

```python
# sql/extensions/ddl_sync/services/sync_trigger.py (核心逻辑)
def on_source_workflow_executed(source_workflow):
    """业务库 DDL 工单执行成功后触发 (signal)"""

    # 1. 解析 DDL 拿到目标表名 + 数据库名
    table_name = _parse_first_table(source_workflow.sql_content)
    source_db = source_workflow.db_name

    # 2. 查库对配置
    pair = DdlSyncPair.objects.filter(
        source_instance=source_workflow.instance,
        source_db=source_db,
        enabled=True,
    ).first()
    if not pair:
        return  # 没配库对, 不联动

    # 3. 查表是否在白名单 (黑名单模式: 默认同步, 不在黑名单)
    if pair.sync_mode == "whitelist":
        is_synced = pair.tables.filter(table_name=table_name).exists()
    else:  # blacklist
        is_synced = not pair.tables.filter(table_name=table_name).exists()

    if not is_synced:
        # 写 history (状态=skipped), 留痕
        DdlSyncHistory.objects.create(
            pair=pair, source_workflow=source_workflow,
            table_name=table_name, ddl_text=source_workflow.sql_content,
            sync_status="skipped",
        )
        return

    # 4. 解析 DDL 类型, 决定要不要同步 (DROP INDEX / ADD INDEX 通常不用)
    if not _should_sync_ddl(source_workflow.sql_content):
        DdlSyncHistory.objects.create(
            pair=pair, source_workflow=source_workflow,
            table_name=table_name, ddl_text=source_workflow.sql_content,
            sync_status="skipped",
        )
        return

    # 5. 自动建历史库 DDL 工单 (跟业务库同一个 SqlWorkflow 表)
    target_workflow = _create_target_workflow(source_workflow, pair)
    DdlSyncHistory.objects.create(
        pair=pair, source_workflow=source_workflow, target_workflow=target_workflow,
        table_name=table_name, ddl_text=source_workflow.sql_content,
        sync_status="created",
    )
```

### 7.2 跟 v0.3.0 gh-ost 联动

历史库 DDL 提交时, 跟业务库一样走大表判定 (复用 v0.3.0 `ext_ddl_ghost_task` 大表阈值):
- 历史库表行数 > 100 万 (跟业务库一样) → 提示走 gh-ost
- 历史库 DDL 也走 DdlGhostTask 异步执行, 不阻塞 SQL 提交流
- 跟 v0.4.5 rebuild 联动: 历史库 DDL 执行完成后, 物理页重写 + DATA_FREE 归零

### 7.3 跟 audit_drivers 联动

历史库 DDL 工单跟业务库 DDL 工单**走同一个 audit_driver 配置** (ext_approval_flow 表里的 audit_auth_groups):
- 8/21 拍板: **同审批人**, 简化流程, 跟现有 3 级审批一致
- 历史库 DDL 走 `workflow_type = "ddl_sync_history"` (新枚举值), audit_drivers 看这个值决定审批流
- Phase 2 评估: 是否要给历史库 DDL 单独配审批组 (历史库 DBA 跟业务库 DBA 不同)

### 7.4 跟 v0.2.0 钉钉 OA 联动

历史库 DDL 工单审批消息推钉钉, 复用现有 dingtalk_oa driver:
- 审批人 (业务库 DDL 审批人) 直接收到钉钉通知
- 消息含"业务库工单 #xxx 已完成, 历史库工单 #xxx 待审"
- DBA 一键审批, 不用切 Archery 界面

---

## 8. 实施阶段 (短期 C → 中期 B)

```
SHORT                    MID                       LONG
短期 · C 巡检兜底         中期 · B 工单联动           长期 · A 评估
8/22~8/28                8/29~9/11                 后续
1 周                     2 周                      评估 Archery 直连历史库
schema 巡检               库对管理 + 自动建工单       全自动同步
DBA 手动触发              业务 RD 零感知
```

### 短期 (C 方案) — Schema 巡检兜底 · 1 周

**目标**: 业务库改了 DDL 但漏同步历史库 → Archery 后置发现 + 推钉钉报警

| 模块 | 内容 | 工作量 |
|---|---|---|
| 3 张表 migration | pair / table / history (5.7/8.0 兼容) | 半天 |
| 库对管理 views + 模板 | pair_list / new / edit / detail (5 个页面) | 1.5 天 |
| 巡检服务 (核心) | 遍历库对同步表清单, 对比 schema, 生成 diff 报告 | 1.5 天 |
| 巡检结果页 | 显示不一致表 + 缺失列 + 一键生成补 DDL 工单 | 1 天 |
| 钉钉通知 | 不一致推钉钉 (复用 v0.2.0 dingtalk_oa driver) | 半天 |
| 权限细分 | 4 个 perm + 菜单条件渲染 | 半天 |
| DBA 演练 | 配 1 个库对, 跑巡检, 验证报告 | 1 天 |

**短期验证标准**: DBA 配 1 个库对 (业务库 + 历史库 + 3 张同步表), 手动跑巡检, 报告正确显示 schema diff, 一键生成补 DDL 工单走完流程。

### 中期 (B 方案) — 工单联动 · 2 周

**目标**: 业务库 DDL 工单审批通过 → Archery 自动建历史库 DDL 工单 → DBA 审核 → 执行

| 模块 | 内容 | 工作量 |
|---|---|---|
| DDL 解析服务 | 从 SqlWorkflow.sql_content 提取表名 + DDL 类型 | 1 天 |
| 库对查表逻辑 | 查 (source_instance, source_db, table_name) 是否在白名单 | 半天 |
| DDL 类型过滤 | ADD/MODIFY/CHANGE/RENAME 必同步, DROP INDEX/ADD INDEX 通常跳过 | 半天 |
| 自动建历史库工单 | 复制业务库工单, 改 instance/db_name, 走 audit_drivers 审批 | 2 天 |
| 业务库工单状态联动 | 工单页增加"历史库联动"子状态, 跳历史库工单 | 1 天 |
| 历史库 DDL 智能回滚联动 | 复用 v0.4.5 `_reverse_single_op`, 适配历史库 DDL | 1.5 天 |
| 历史库 gh-ost 联动 | 大表 DDL 走 gh-ost, 复用 v0.3.0 runner | 1.5 天 |
| 大表防呆复用 | 历史库 DDL 也走 v0.3.x 大表 alert | 半天 |
| 业务 RD 业务验收 | 真提 DDL 测全流程, 验证零感知 | 1 天 |

**中期验证标准**: 业务 RD 提 DDL → 自动建历史库 DDL 工单 → DBA 审核 → 执行成功 → 业务库工单关闭。业务 RD 不用手动同步, 不用关心要不要同步, 工单页有清晰提示。

### 长期 (A 方案) — Archery 自动同步 · 后续评估

等中期跑通后再评估, 看是否需要"Archery 直连历史库"全自动执行 (绕过工单流程):
- 优点: 业务 RD 审批通过后, 历史库 DDL 立即执行, 0 等待
- 缺点: 风险高, DDL 错历史库也错, 跟业务库 + 历史库 DDL 差异有关
- 触发条件: 业务库跟历史库 DDL 100% 一致 (不需要 transform_rule)

---

## 9. 风险与验证

| 风险 | 等级 | 应对 |
|---|---|---|
| **业务库跟历史库 DDL 不一致** | 🔴 高 | transform_rule 字段预留 (Phase 1 不用, Phase 2 扩展), DBA 配白名单时标记 |
| **历史库 DDL 失败业务库已成功** | 🔴 高 | 8/21 拍板: 业务库失败 → 历史库工单**不发起**; 业务库成功 + 历史库失败 → 推钉钉报警 + 巡检兜底 (C 方案) |
| **历史库 DDL 锁表影响同步** | 🟡 中 | 跟 v0.3.0 gh-ost 联动, 大表走 gh-ost 避免锁表 (复用大表判定) |
| **历史库 DBA 不是业务库 DBA** | 🟡 中 | 8/21 拍板: 同审批人 (跟业务库 DDL 一致); Phase 2 评估是否要给历史库 DDL 单独配审批组 |
| **DBA 配错库对 (业务库/历史库搞反)** | 🟡 中 | 新建库对时, Archery 提示"业务库 vs 历史库", 配错会立即连一下验证 |
| **巡检误报 (schema 一致但元数据不同)** | ⚪ 低 | 巡检只对比**白名单表**的**列定义**, 忽略 CHARSET/COLLATE 等次要差异 (跟 ddl_gh_ost 字段 diff 端点一致) |
| **DBA 误改库对白名单** | ⚪ 低 | 4 个 perm 4 个判定, 业务 RD 默认不能看, 跟 gh-ost 任务管理一致 |
| **历史库实例被删除** | ⚪ 低 | cascade 删除会同步删库对 (DBA 配库对时要小心), 禁用需要手动 archive |
| **DBA 配错白名单 (该同步的没配, 不该同步的配了)** | ⚪ 低 | 巡检兜底 (C 方案), 一键生成补 DDL 工单 |

### 每个 Phase 验证标准

- **短期 C (巡检)**: DBA 配 1 个库对, 跑巡检拿到正确 diff 报告, 一键生成补 DDL 工单走完流程
- **中期 B (工单联动)**: 业务 RD 提 DDL → 自动建历史库 DDL 工单 → DBA 审核 → 执行成功 → 业务库工单关闭
- **长期 A (评估)**: 业务库/历史库 DDL 100% 一致时, 全自动同步, 0 人工介入

---

## 10. 跟 8/19 教训对照

| 8/19 教训 | 本次设计应对 |
|---|---|
| SQLAdvisor 装上但跑不出 add index | 短期 C (巡检) 先验证 schema diff 报告内容, 真能找出漏同步才往下做 |
| SOAR 工具装到 /usr/local/bin/ 报 permission denied | 历史库实例用 `archery` user 连 (跟 Archery 一致), 避免 8/19 权限坑 |
| 业务 SQL 出境合规风险 | 历史库 DDL 不需要 AI, 纯 schema 同步, 跟 8/19 一样保守 |
| 8/18 教训 1.10.0 → 1.14.0 切换历史 bug | 3 张表 migration 5.7/8.0 兼容演练 (推 110 前) |
| 8/12 gh-ost 任务管理 perm 细分 (commit c80c1ad) | 复用同一套机制, 4 个标准 perm + 业务 RD 默认不能 (8/13 教训) |
| 8/13 教训 默认权限最小化 | 业务 RD 不勾库对管理 perm, 仅 DBA 可见 |
| 8/12 教训 Archery password 在内存明文 | 历史库连接跟现有 SQL 工单一致, 接受这个风险 |
| 8/18 教训 django-mirage-field 加密 | 历史库实例 password 走 Archery 现有加密机制 (跟其他实例一致) |
| 8/19 教训 errno 7 (Argument list too long) | 历史库 DDL 也是 SQL 工单, 复用现有 sql_optimize.py / goinception, 走现有限制 |
| 8/17 教训 Dashboard 优雅降级 | 巡检结果页 (库对 diff) 跟 RaccoonX 巡检任务页风格一致, 失败时友好提示 |
| 8/17 教训 5 步必做 idempotent | 5 步必做补一条 `migrate_ext_ddl_sync`, 推 110 当天可重复跑 |
| 8/12 教训 gh-ost 任务管理菜单并列 | 新菜单 "🔗 DDL 同步管理" 跟 "gh-ost 任务" / "数据库巡检" 并列, 风格统一 |

### 跟推 110 prod 的关系

跟 RaccoonX 接入 (8/21 commit `ddba8f9`) 一样, 5 步必做补一条:

```bash
# 步骤 11: 推 110 当天跑 ddl_sync 迁移
ssh 110 'cd /opt/archery && python manage.py migrate sql_extensions_ddl_sync'
# - 创建 3 张表 (5.7/8.0 兼容)
# - 幂等, 已建跳过

# 步骤 12: DBA 在 110 prod 配库对
# - 跟 134 dev 一样, 业务库 ↔ 历史库 + 同步表清单
# - 配 1 次, 之后增删实例手动重跑
```

---

## 关联

- **HTML 版**: [2026-08-21_ddl-sync-pair-design.html](2026-08-21_ddl-sync-pair-design.html)
- **项目主页**: [README.md](../README.md) (Archery 二次开发主页)
- **踩坑速查**: [troubleshooting.md](../troubleshooting.md)
- **二次开发规范**: [customization.md](../customization.md)
- **同源设计稿**:
  - RaccoonX 浣巡接入: `2026-08-21_raccoonx-integration-design.html` (70KB, commit `ddba8f9`)
  - gh-ost 详设: `2026-08-10_gh-ost-detail-design.html` (80KB, 13 章节)
  - DDL 智能回滚: `2026-08-13_ddl-rollback-parse-design.html` (38KB)
  - v0.4.0 归档专题: `2026-08-10_v040-archive-rebuild-design.html` (64KB)
  - v0.4.5 ghost rebuild: `2026-08-13_v0405-ghost-rebuild-design.html` (40KB)
  - 钉钉 OA: `2026-08-10_dingtalk-oa-detail-design.html` (102KB)
