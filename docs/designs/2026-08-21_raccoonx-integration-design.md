# 数据库巡检 · RaccoonX 浣巡接入详细设计

> **Archery v0.5.0 · 二次开发设计稿**
> 让 Archery 平台本身具备数据库巡检能力,业务用户和 DBA 不用跳出 Archery 即可一键体检。

**作者**: mavis
**日期**: 2026-08-21
**版本**: v0.5.0-alpha 详细设计
**粒度**: 可直接动手写代码
**配套**: [HTML 版](2026-08-21_raccoonx-integration-design.html)

---

## 目录

1. [设计原则](#1-设计原则)
2. [业务场景](#2-业务场景)
3. [产品界面 (6 个核心页面)](#3-产品界面-6-个核心页面)
4. [权限模型](#4-权限模型)
5. [数据模型 (4 张表)](#5-数据模型-4-张表)
6. [URL 路由](#6-url-路由)
7. [RaccoonX 集成](#7-raccoonx-集成)
8. [实施阶段 (Phase 0~2)](#8-实施阶段-phase-02)
9. [风险与验证](#9-风险与验证)
10. [跟推 110 prod 的关系](#10-跟推-110-prod-的关系)

---

## 1. 设计原则

跟之前 5 个二次开发项目 (gh-ost / DDL 智能回滚 / OA / 归档 / v0.4.5 rebuild) 一致,走"扩展 + 复用 + 不重写"路线。

| 原则 | 落地方式 |
|---|---|
| 二次开发,不动上游 | 新建 `sql/extensions/sql_inspect/` extension,跟 `ddl_gh_ost/` 同级 |
| driver 模式 | 跟 `audit_drivers/` 一样,RaccoonX 是 "remote datasource" driver |
| 权限跟 gh-ost 任务一致 | 4 个标准 perm,`{% if perms.xxx %}` 条件渲染,`_is_inspect_admin()` 判定 |
| 复用 Archery 已有 | `instancepermission` 表 / `sql_instance` 表 / Q2 schedule / `django-mirage-field` 加密 / `dingtalk_oa` driver |
| 8/19 教训落地 | 默认关 AI (8/19 数据出境教训) + 工具装 `/opt/archery/bin/` (8/19 权限教训) |
| 跟推 110 并行不冲突 | RaccoonX 跟 Archery 一起推 110,5 步必做补 3 条 |

> **核心定位调整 (8/20 拍板)**: 之前把 "慢 SQL 联动" 当主菜、"巡检" 当配菜,顺序反了。Archery 平台本身**具备巡检能力**才是核心,慢 SQL 联动 / 工单闭环 放后续 Phase。

---

## 2. 业务场景

从 4 个角色视角看 Archery 接入 RaccoonX 后能干嘛:

| 角色 | 场景 |
|---|---|
| **业务 RD** | 提 SQL 工单前想知道"我的库健康吗" → 一键巡检 → 看风险卡 → 决定要不要先优化 (缺失索引 / 慢 SQL / 锁等待) |
| **DBA** | 兜底定期巡检所有业务库 → 看趋势看板 → 配定时任务 → 处理高风险 → 推钉钉通知 (复用 v0.2.0 OA driver) |
| **业务 leader** | 看自己业务库健康趋势 → 健康分分布 → 跟其他业务库对比 → 给老板汇报有数据 |
| **admin** | 在 Django admin 后台给权限组勾 perm (4 个 perm 4 个判定) → 业务 RD 默认不能, DBA 手动给,跟 8/13 拍板一致 |

---

## 3. 产品界面 (6 个核心页面)

### 3.1 Archery 侧边栏菜单 (新增)

跟 "SQL 审核" / "查询" / "gh-ost 任务" 并列,条件渲染 (有 `view_inspecttask` perm 才显示)。

```
▾ SQL 审核
▾ SQL 查询
▸ gh-ost 任务                                          [8/12 上线]
─────────────
▾ 🏥 数据库巡检                                        [NEW]
  ├ ▸ 任务列表
  ├ ▸ 一键巡检
  ├ ▸ 定时配置                                          [DBA]
  └ ▸ 趋势看板                                          [DBA]
▾ 数据管理
▾ 系统管理
```

### 3.2 巡检任务列表 (`/sql_inspect/task_list/`)

```
数据库巡检                                                [+ 一键巡检]
┌──────────┬──────┬──────┬──────┬──────┬───────────────────────┐
│ 实例      │ 库   │ 时间 │ 健康分│ 风险 │ 操作                  │
├──────────┼──────┼──────┼──────┼──────┼───────────────────────┤
│ 业务库    │ oa   │19:00 │  75  │ 3高5中│ 📄详情  📥报告  🔄重跑│
│ 业务库    │ log  │18:00 │  88  │  1中  │ 📄详情  📥报告  🔄重跑│
│ 业务库    │ card │17:00 │  92  │  -   │ 📄详情  📥报告  🔄重跑│
│ ...                                                            │
├────────────────────────────────────────────────────────────────┤
│ 过滤: [实例▼] [库▼] [时间▼] [状态▼] [健康分▼] [风险▼]        │
└────────────────────────────────────────────────────────────────┘
```

业务 RD 看到自己有 `instancepermission` 的库;DBA 看全公司所有库。

### 3.3 巡检详情 (`/sql_inspect/detail/<task_id>/`)

```
业务库 / oa  ·  健康分 75  ·  巡检时间 8/20 19:00
RaccoonX Task ID: rcnx_xyz  ·  巡检耗时 12s

🔴 高风险 (3 条)
  ┌────────────────────────────────────────────────────────────┐
  │ ● 缺失索引: oa.log 表 create_time 列                       │
  │   影响: 全表扫描,506267 行,平均耗时 3.2s,日均触发 1.2k 次 │
  │   CREATE INDEX idx_ct ON oa.log(create_time);              │
  │   [📋 复制 SQL]  [🛠️ 提交 DDL 工单 - Phase 3]              │
  └────────────────────────────────────────────────────────────┘
  ... 2 条

🟡 中风险 (5 条) ...
🟢 低风险 (2 条) ...

📊 健康分趋势 (7 天): 80 → 75 → 72 → 70 → 75 → 78 → 75

📥 下载完整 Word 报告 (RaccoonX /share/<id> 免登录链接)
```

**第一阶段**: 只有 "📋 复制 SQL","🛠️ 提交 DDL 工单" 放 Phase 3。

### 3.4 一键巡检弹窗 (`/sql_inspect/start/`)

```
一键巡检
┌─────────────────────────────────────────────┐
│ 实例:    [业务库 ............................. ▼]│
│ 库:      [oa / log / card ................. ▼]│
│ 模板:    [MySQL 标准巡检 ................... ▼]│
│ 深度:    [○ 基础 (1min)  ● 标准 (3min)  ○ 深度 (8min)]│
│ AI:      [○ 启用  ● 禁用]    ← 8/19 教训,默认关│
│                                             │
│              [取消]    [开始巡检]           │
└─────────────────────────────────────────────┘

↑ 点"开始巡检" → 跳任务列表,任务状态"排期中"
  → 后台异步调 RaccoonX → 状态变"巡检中" → 完成变"已完成"
```

### 3.5 定时配置 (`/sql_inspect/schedule/`, 仅 DBA)

复用 Django Q2 schedule 框架,跟 v0.4.5 rebuild 定时任务风格一致。

```
定时巡检配置                                              [+ 新建定时]
┌──────────┬──────┬──────┬──────┬──────────────────────────┐
│ 名称     │ 实例 │ cron │ 模板 │ 操作                     │
├──────────┼──────┼──────┼──────┼──────────────────────────┤
│ 业务库日检│ 3 个 │ 0 3 * * * │ MySQL 标准│ ✏️编辑  🗑️删除  ▶️立即跑│
│ 业务库周检│ 全量 │ 0 2 * * 0 │ MySQL 深度│ ✏️编辑  🗑️删除  ▶️立即跑│
│ ...                                                            │
└──────────┴──────┴──────┴──────┴──────────────────────────┘
```

### 3.6 趋势看板 (`/sql_inspect/dashboard/`, 仅 DBA)

DBA 兜底视角,全公司库健康总览。

```
数据库巡检 · 全公司总览

健康分分布:
🟢 优秀 (>90): 5 个   🟡 一般 (70-90): 8 个   🔴 差 (<70): 2 个

Top 10 高风险库 (按风险数降序):
 1. 业务库 / oa      [3高5中]  75
 2. 业务库 / log     [2高3中]  80
 3. 业务库 / card    [1高2中]  85
 ...

30 天健康分趋势 (折线图,所有库平均):
80  78  75  73  70  72  75  ...  (折线图, ECharts 渲染)
```

---

## 4. 权限模型

跟 8/12 gh-ost 任务管理列表页 (commit `c80c1ad`) 一套机制,**0 业务代码改动做权限** — 纯靠 Django admin 自动注册 perm。

### 4.1 4 个 perm 全部注册 (8/20 拍板)

Django admin 会自动给 `InspectTask` model 注册这 4 个标准 perm:

| Perm | 用途 | 谁有 (默认) | 8/20 拍板 |
|---|---|---|---|
| `view_inspecttask` | 看菜单 + 列表 + 详情 | 业务 RD + DBA + admin | DBA 手动勾 |
| `add_inspecttask` | 一键巡检 (发起) | 业务 RD + DBA + admin | DBA 手动勾 |
| `change_inspecttask` | 定时配置 + 取消/重试 + 编辑 | 仅 DBA + admin | 仅 DBA + admin |
| `delete_inspecttask` | 删除巡检任务 (清理历史) | 仅 DBA + admin | 仅 DBA + admin |

> **8/20 拍板 4 条**:
> ① 4 个 perm 全部注册
> ② 默认业务 RD 不能, DBA 手动勾
> ③ 复用 Archery `instancepermission` 表做实例隔离
> ④ 业务 RD 默认不勾, DBA 手动给 (8/13 教训: 默认权限最小化)

### 4.2 菜单条件渲染 (base.html)

跟 gh-ost 任务管理一样,在 Archery 侧边栏 `base.html` 加:

```django
{% if perms.sql_inspect.view_inspecttask %}
  <li class="nav-item">
    <a href="{% url 'sql_inspect:task_list' %}">
      🏥 数据库巡检
    </a>
  </li>
{% endif %}
```

### 4.3 页面装饰器 (views.py)

```python
from django.contrib.auth.decorators import permission_required

@permission_required("sql_inspect.view_inspecttask")
def task_list(request):
    ...

@permission_required("sql_inspect.view_inspecttask")
def task_detail(request, task_id):
    ...

@permission_required("sql_inspect.add_inspecttask")
def task_start(request):
    ...

@permission_required("sql_inspect.change_inspecttask")
def schedule_config(request):
    ...
```

### 4.4 实例级隔离 (业务 RD 自动只看自己库)

跟 8/12 gh-ost 任务管理一致 (commit `c80c1ad`):

```python
def _is_inspect_admin(user):
    """DBA / DBA组长 / superuser 走全量, 其他走 instance 权限过滤"""
    return user.is_superuser or user.groups.filter(
        name__in=("DBA", "DBA组长")
    ).exists()

def task_list_queryset(user):
    qs = InspectTask.objects.select_related("instance", "db_name")
    if _is_inspect_admin(user):
        return qs  # DBA 全量
    # 业务 RD: 复用 Archery instancepermission 表 (跟其他业务页面一致)
    return qs.filter(
        instance__in=user.instancepermission_set.values_list("instance_id")
    )
```

### 4.5 DBA 在 admin 后台配置权限

0 业务代码改动 — DBA 在 admin 后台点几下鼠标就分完了:

```
Django admin → 认证和授权 → 组
  ├─ "DBA" 组:       权限 → 勾选 sql_inspect 4 个 perm ✓
  ├─ "DBA组长" 组:   跟 DBA 一样
  └─ "业务RD" 组:    权限 → 不勾 sql_inspect (默认不能, 8/13 教训)
                                       → DBA 手动给特定业务 RD 勾 view + add
```

### 4.6 跟 gh-ost 任务管理一致的好处

| 维度 | 一致 | 业务价值 |
|---|---|---|
| 菜单渲染 | `{% if perms %}` 条件 | 业务 RD 没勾看不到菜单, 跟现有菜单风格统一 |
| 页面装饰 | `@permission_required` | 没 perm 直接 302 跳登录或 403 |
| 实例隔离 | `_is_inspect_admin()` | DBA 全量, 业务 RD 自动按 instance 权限过滤 |
| 权限粒度 | 4 个标准 perm | 跟 gh-ost / 系统用户/组 一致, 不用学新概念 |
| DBA 操作 | admin 后台点鼠标 | 不用 DBA 改代码, 不用重启服务 |

---

## 5. 数据模型 (4 张表)

### ER Diagram

```
┌──────────────────────────┐
│  ext_inspect_task        │
├──────────────────────────┤
│ 🔑 id (PK)               │
│ → instance_id (FK)       │  1:N
│ db_name, template        │  ↓
│ raccoonx_task_id         │  ┌──────────────────────────┐
│ status, health_score     │  │  ext_inspect_finding     │
│ risk_high/medium/low     │  ├──────────────────────────┤
│ created_by, created_at   │  │ 🔑 id (PK)               │
└──────────────────────────┘  │ → task_id (FK)           │
                              │ level, category          │
┌──────────────────────────┐  │ title, description       │
│  ext_inspect_datasource_map│ │ suggested_sql            │
├──────────────────────────┤  │ affected_rows            │
│ 🔑 id (PK)               │  │ extra (JSON)             │
│ → archery_instance_id    │  └──────────────────────────┘
│   (FK, 1:1)              │
│ raccoonx_datasource_id   │  ┌──────────────────────────┐
│ raccoonx_datasource_name │  │  ext_inspect_schedule    │
│ last_synced_at           │  ├──────────────────────────┤
│ sync_status              │  │ 🔑 id (PK)               │
└──────────────────────────┘  │ ↔ instances (M2M)        │
                              │ name, template           │
                              │ cron_expression          │
                              │ notify_*_risk            │
                              │ enabled, last_run_at     │
                              └──────────────────────────┘
```

### 5.1 `ext_inspect_task` (巡检任务)

```python
class InspectTask(models.Model):
    STATUS_CHOICES = [
        ("queued", "排期中"),
        ("running", "巡检中"),
        ("success", "已完成"),
        ("failed", "失败"),
        ("cancelled", "已取消"),
    ]

    id = models.AutoField(primary_key=True)
    instance = models.ForeignKey(Instance, on_delete=models.CASCADE)  # Archery 数据源
    db_name = models.CharField(max_length=64)
    template = models.CharField(max_length=32, default="mysql_standard")  # 巡检模板

    # RaccoonX 端
    raccoonx_task_id = models.CharField(max_length=64, blank=True)
    raccoonx_datasource_id = models.IntegerField()  # RaccoonX 数据源 ID
    raccoonx_share_url = models.URLField(blank=True)  # Word 报告分享链接

    # 结果
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    health_score = models.IntegerField(null=True, blank=True)  # 健康分 0-100
    risk_high = models.IntegerField(default=0)
    risk_medium = models.IntegerField(default=0)
    risk_low = models.IntegerField(default=0)
    duration_seconds = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)  # 失败原因

    # 元数据
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ext_inspect_task"
        indexes = [
            models.Index(fields=["instance", "db_name", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]
```

### 5.2 `ext_inspect_finding` (风险条目)

```python
class InspectFinding(models.Model):
    LEVEL_CHOICES = [
        ("high", "高"),
        ("medium", "中"),
        ("low", "低"),
    ]

    id = models.AutoField(primary_key=True)
    task = models.ForeignKey(InspectTask, on_delete=models.CASCADE, related_name="findings")
    level = models.CharField(max_length=8, choices=LEVEL_CHOICES)
    category = models.CharField(max_length=64)  # 类别: 缺失索引 / 慢 SQL / 锁等待 / ...
    title = models.CharField(max_length=256)  # 标题
    description = models.TextField()  # 详情
    suggested_sql = models.TextField(blank=True)  # 建议 SQL (如有)
    affected_rows = models.IntegerField(null=True, blank=True)  # 影响行数
    extra = models.JSONField(default=dict)  # 原始 RaccoonX 数据 (json 字段)

    class Meta:
        db_table = "ext_inspect_finding"
        indexes = [
            models.Index(fields=["task", "level"]),
        ]
```

### 5.3 `ext_inspect_datasource_map` (数据源映射)

```python
class InspectDatasourceMap(models.Model):
    """Archery instance ↔ RaccoonX datasource 一对一映射

    避免双维护: Archery 已有 sql_instance 表, RaccoonX 也有数据源,
    启动时一次性脚本同步, 后续 Archery 增删实例时手动重跑。
    """
    id = models.AutoField(primary_key=True)
    archery_instance = models.OneToOneField(Instance, on_delete=models.CASCADE)
    raccoonx_datasource_id = models.IntegerField()  # RaccoonX 端 ID
    raccoonx_datasource_name = models.CharField(max_length=128)  # 冗余存名字
    last_synced_at = models.DateTimeField(auto_now=True)  # 最近同步时间
    sync_status = models.CharField(max_length=16, default="ok")  # ok / failed

    class Meta:
        db_table = "ext_inspect_datasource_map"
```

### 5.4 `ext_inspect_schedule` (定时任务)

```python
class InspectSchedule(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=128)
    instances = models.ManyToManyField(Instance)  # 多对多, 定时跑多实例
    template = models.CharField(max_length=32, default="mysql_standard")
    cron_expression = models.CharField(max_length=64)  # "0 3 * * *"
    notify_high_risk = models.BooleanField(default=True)  # 高风险推钉钉
    notify_daily_report = models.BooleanField(default=True)  # 日报

    enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_task = models.ForeignKey(InspectTask, null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ext_inspect_schedule"
```

> **4 张表 migration 计划**:
> `0001_initial.py` (task + finding) →
> `0002_datasource_map.py` →
> `0003_schedule.py`。
> 推 110 时通过 5 步必做补一条 `migrate_ext_inspect`,5.7/8.0 兼容 (跟 ddl_gh_ost 4 个 migration 8/18 演练一致)。

---

## 6. URL 路由

跟 `ddl_gh_ost/urls.py` 风格一致,在 `archery/urls.py` 里按需 include。

```python
# sql/extensions/sql_inspect/urls.py
from django.urls import path
from . import views

app_name = "sql_inspect"

urlpatterns = [
    # 核心页面
    path("task_list/", views.task_list, name="task_list"),
    path("detail/<int:task_id>/", views.task_detail, name="task_detail"),
    path("start/", views.task_start, name="task_start"),
    path("cancel/<int:task_id>/", views.task_cancel, name="task_cancel"),
    path("rerun/<int:task_id>/", views.task_rerun, name="task_rerun"),

    # 定时配置 (DBA 专属)
    path("schedule/", views.schedule_list, name="schedule_list"),
    path("schedule/new/", views.schedule_new, name="schedule_new"),
    path("schedule/<int:schedule_id>/edit/", views.schedule_edit, name="schedule_edit"),
    path("schedule/<int:schedule_id>/delete/", views.schedule_delete, name="schedule_delete"),
    path("schedule/<int:schedule_id>/run/", views.schedule_run, name="schedule_run"),

    # 趋势看板 (DBA 专属)
    path("dashboard/", views.dashboard, name="dashboard"),

    # AJAX 端点 (前端轮询用)
    path("api/task_status/<int:task_id>/", views.api_task_status, name="api_task_status"),
    path("api/datasource_sync/", views.api_datasource_sync, name="api_datasource_sync"),
]
```

```python
# archery/urls.py  (include 段)
if getattr(settings, "CUSTOM_INSPECT_ENABLED", False):
    urlpatterns += [
        path("sql_inspect/", include(("sql.extensions.sql_inspect.urls", "sql_inspect"))),
    ]
```

---

## 7. RaccoonX 集成

### 7.1 部署 (134 dev 跟 Archery 一起,推 110 时同步)

| 项 | 134 dev | 110 prod (推 110 时同步) |
|---|---|---|
| 位置 | `/opt/raccoonx/` (跟 `/opt/archery/` 同级) | 同 (5 步必做补) |
| 部署 | 源码 (Python 3.10 venv + systemd) | 同 |
| 端口 | 5003 (跟 gh-ost 4000 / goinception 4000 不冲突) | 同 |
| 数据存储 | SQLite (RaccoonX 默认) | 同 |
| 报告 | `/var/lib/raccoonx/reports/` (volume) | 同 |
| 加密 | API Key 存 RaccoonX Fernet 加密 | 同 |
| AI 模式 | `ai_mode = disabled` (8/19 教训) | 同 |
| 用户 | `archery` (跟 Archery 一致, 避免 8/19 权限坑) | 同 |

**systemd unit** (跟 goinception 一样套路):

```ini
[Unit]
Description=RaccoonX Database Inspection
After=network.target

[Service]
Type=simple
User=archery
WorkingDirectory=/opt/raccoonx
ExecStart=/opt/raccoonx/venv/bin/python web_ui.py
Restart=on-failure
RestartSec=5
Environment="PATH=/opt/raccoonx/venv/bin"

[Install]
WantedBy=multi-user.target
```

**nginx 反代** (跟 goinception 一样):

```nginx
# /etc/nginx/conf.d/archery.conf
location /raccoonx/ {
    proxy_pass http://127.0.0.1:5003/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

### 7.2 数据源映射 (一次性同步)

避免双维护 — 启动时跑一次性脚本,后续 Archery 增删实例时手动重跑。

```python
# sql/extensions/sql_inspect/management/commands/sync_raccoonx_datasources.py
class Command(BaseCommand):
    """同步 Archery sql_instance → RaccoonX datasource

    启动时跑一次, 后续 Archery instance 增删时手动重跑。
    """
    def handle(self, *args, **options):
        raccoonx = RaccoonXClient(api_key=settings.RACCOONX_API_KEY)

        for instance in Instance.objects.filter(type="master"):
            # 1. Archery 端解加密密码 (django-mirage-field)
            password = decrypt_password(instance.password)

            # 2. RaccoonX 端创建数据源 (幂等)
            ds = raccoonx.upsert_datasource(
                name=f"archery_{instance.host}_{instance.port}",
                db_type="mysql",
                host=instance.host,
                port=instance.port,
                user=instance.user,
                password=password,
            )

            # 3. Archery 端存映射
            InspectDatasourceMap.objects.update_or_create(
                archery_instance=instance,
                defaults={
                    "raccoonx_datasource_id": ds["id"],
                    "raccoonx_datasource_name": ds["name"],
                    "sync_status": "ok",
                }
            )
```

### 7.3 API 客户端 (Archery 端, 4 个核心端点)

```python
# sql/extensions/sql_inspect/services/raccoonx_client.py
class RaccoonXClient:
    """RaccoonX REST API 客户端 (4 个核心端点)"""

    def __init__(self):
        self.base_url = settings.RACCOONX_API_URL  # http://127.0.0.1:5003
        self.api_key = settings.RACCOONX_API_KEY  # admin API Key (RaccoonX Fernet 加密存库)

    def _request(self, method, path, **kwargs):
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        resp = requests.request(method, f"{self.base_url}{path}",
                                headers=headers, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    def trigger_inspect(self, datasource_id, template, db_name, mode="async"):
        """创建巡检任务 (异步, 返 task_id)"""
        return self._request("POST", "/api/v1/inspect", json={
            "datasource_id": datasource_id,
            "template": template,
            "db_name": db_name,
            "mode": mode,
        })

    def get_task(self, task_id):
        """查任务状态 + 结果"""
        return self._request("GET", f"/api/v1/inspect/{task_id}")

    def list_recent_tasks(self, limit=50):
        """列最近 N 个任务 (看板用)"""
        return self._request("GET", f"/api/v1/inspects?limit={limit}")

    def get_share_url(self, task_id):
        """拿 Word 报告免登录分享 URL"""
        task = self.get_task(task_id)
        return task.get("share_url", "")
```

### 7.4 凭据传递 (Archery 解 → RaccoonX 加)

**Archery 端** (用 `django-mirage-field` 解密,跟 gh-ost 业务一致):

```python
# sql/extensions/sql_inspect/services/credentials.py
from common.utils.aes_decryptor import AESDecryptor  # Archery 上游的解加密 helper

def _get_instance_creds(instance):
    """解 Archery instance 表加密密码 (跟 gh-ost 业务用法一致)"""
    return {
        "host": instance.host,
        "port": instance.port,
        "user": instance.user,
        "password": AESDecryptor().decrypt(instance.password),
    }
```

**RaccoonX 端**: 拿到明文密码后,自己 Fernet 加密存库 (跟 RaccoonX 内部一致,8/18 教训: 配字段用 `SysConfig().set(key, value)` 自动加密, 不要 SQL UPDATE 明文)。

> **风险**: 密码在 Archery 进程内存里明文存在 → 跟 gh-ost 业务一样,接受这个风险 (跟 8/13 gh-ost 任务管理一致)。后续可考虑用 RaccoonX 的 SSH 凭据 + Vault 兜底。

### 7.5 报告解析 (RaccoonX 返 JSON → Archery 存 finding)

RaccoonX `/api/v1/inspect/<id>` 返 JSON (含 findings 列表),Archery 端:

```python
# sql/extensions/sql_inspect/services/result_parser.py
def _parse_raccoonx_result(task_data, archery_task):
    """RaccoonX 任务结果 → Archery InspectFinding 列表"""
    findings = task_data.get("findings", [])
    for f in findings:
        InspectFinding.objects.create(
            task=archery_task,
            level=f["severity"],  # high/medium/low
            category=f["category"],  # 缺失索引/慢 SQL/...
            title=f["title"],
            description=f["description"],
            suggested_sql=f.get("suggestion", ""),
            affected_rows=f.get("affected_rows"),
            extra=f,  # 原始数据存 json 字段
        )

    # 更新 task 统计
    archery_task.health_score = task_data.get("health_score")
    archery_task.risk_high = sum(1 for f in findings if f["severity"] == "high")
    archery_task.risk_medium = sum(1 for f in findings if f["severity"] == "medium")
    archery_task.risk_low = sum(1 for f in findings if f["severity"] == "low")
    archery_task.raccoonx_share_url = task_data.get("share_url", "")
    archery_task.save()
```

### 7.6 异步任务执行 (避免阻塞 HTTP 请求)

跟 gh-ost 任务管理一样,用后台线程跑 RaccoonX 巡检 + 轮询, 不阻塞 HTTP:

```python
# sql/extensions/sql_inspect/services/runner.py
import threading

def start_inspect_task(archery_task_id, datasource_id, template, db_name):
    """Archery 端异步调 RaccoonX (用 django_q2, 跟 v0.4.5 rebuild 一样)"""
    # 1. 调 RaccoonX 创建巡检
    raccoonx = RaccoonXClient()
    rc_result = raccoonx.trigger_inspect(datasource_id, template, db_name)

    # 2. 更新 Archery 端 task 状态
    task = InspectTask.objects.get(id=archery_task_id)
    task.raccoonx_task_id = rc_result["task_id"]
    task.status = "running"
    task.save()

    # 3. 启动 polling (后台线程)
    t = threading.Thread(
        target=_poll_raccoonx_task,
        args=(archery_task_id, rc_result["task_id"]),
        daemon=True,
    )
    t.start()

def _poll_raccoonx_task(archery_task_id, raccoonx_task_id):
    """后台轮询 RaccoonX 任务状态 (3s 间隔)"""
    import time
    raccoonx = RaccoonXClient()
    for _ in range(300):  # 最多 15 分钟
        time.sleep(3)
        result = raccoonx.get_task(raccoonx_task_id)
        if result["status"] in ("success", "failed"):
            # 解析结果存 Archery 库
            task = InspectTask.objects.get(id=archery_task_id)
            _parse_raccoonx_result(result, task)
            task.status = "success" if result["status"] == "success" else "failed"
            task.finished_at = timezone.now()
            task.save()
            return
    # 超时
    task = InspectTask.objects.get(id=archery_task_id)
    task.status = "failed"
    task.error_message = "RaccoonX 巡检超时 (15min)"
    task.save()
```

---

## 8. 实施阶段 (Phase 0~2)

```
PHASE 0          PHASE 1              PHASE 2              PHASE 3
可行性验证        巡检框架             巡检增强             工单闭环
8/20 下午        8/21~8/27            8/28~9/3             后续
半天             1 周                 1 周                 2 周
RaccoonX 跑通    菜单+列表+详情+一键    定时+趋势+钉钉通知    巡检→Archery 工单
```

### Phase 0 — 可行性验证 (8/20 下午半天)

> **关键验证 (8/19 教训)**: 拿 8/19 那条 50 万行全表扫描 SQL 走一遍。RaccoonX 报告里有没有"加索引"建议, 跟 SOAR 对比 — **SOAR 100 分 OK 没建议, RaccoonX 真给出来才算数**。如果 RaccoonX 也给不出来, 整个项目都不做, 改走 v0.4.1 慢 SQL 索引解析路线。

| 项 | 做什么 | 怎么判断 |
|---|---|---|
| 部署 | 134 dev 装 RaccoonX 源码 (Python 3.10 venv + systemd, 跟 goinception 一样) | 启动 5003 端口 |
| 数据源 | 配 1 个 Archery 已有的 MySQL (172.20.2.134:3306 / archery_dev 库) | 连接通 |
| 跑一次 | 触发全库巡检, 关 AI 模式 (跟 8/19 一样, 纯规则) | 拿到 Word 报告 |
| 业务验证 | 拿 8/19 那条 50 万行全表扫描 SQL, 看 RaccoonX 给的是不是 "建议加 idx_xxx 索引" | **如果给不出来, 后面都不做** |

### Phase 1 — 巡检框架 (8/21~8/27, 1 周)

| 模块 | 内容 | 工作量 |
|---|---|---|
| Extension 脚手架 | `sql/extensions/sql_inspect/` 目录结构 (跟 ddl_gh_ost 同) | 半天 |
| 4 张表 migration | 0001~0003 (跟 ddl_gh_ost 风格一致, 5.7/8.0 兼容) | 半天 |
| RaccoonX 客户端 | `raccoonx_client.py` + 凭据解密 helper | 半天 |
| 数据源映射脚本 | `sync_raccoonx_datasources` management command | 半天 |
| 核心 views | task_list / task_detail / task_start / task_cancel / task_rerun | 1 天 |
| 异步 runner + 轮询 | 后台线程调 RaccoonX + 解析结果存库 | 1 天 |
| 菜单 + 权限 | base.html 条件渲染 + 4 个 perm + 实例隔离 | 半天 |
| 前端模板 | 3 个 HTML (列表 / 详情 / 一键弹窗) | 1 天 |
| AJAX 轮询 | 前端 JS 3s polling task_status | 半天 |
| 5 步必做脚本补充 | 推 110 必做的 RaccoonX 装 + 数据源同步 + env 配 | 半天 |

**Phase 1 验证标准**: 业务 RD 真能用, 看到自己库健康分 + 风险。

### Phase 2 — 巡检增强 (8/28~9/3, 1 周)

| 模块 | 内容 |
|---|---|
| 定时配置 | schedule_list / new / edit / delete / run, 复用 Django Q2 schedule |
| 趋势看板 | dashboard 全公司健康总览 + 健康分分布 + Top 10 |
| 钉钉通知 | 高风险立即推 + 日报汇总, 复用 v0.2.0 dingtalk_oa driver |
| 健康分趋势 | Archery 端聚合折线图 (7 天 / 30 天) |

**Phase 2 验证标准**: DBA 配 cron 跑通, 日报真发出去。

### Phase 3 — 工单闭环 (后续, 2 周)

等 Phase 1 业务用户用起来后再评估:
- 巡检"缺失索引"建议 → 一键建 Archery DDL 工单 (走审批 + gh-ost)
- 巡检"碎片多" → 一键建 v0.4.5 rebuild 工单
- 巡检"归档建议" → 一键建 v0.4.0 归档工单

---

## 9. 风险与验证

| 风险 | 等级 | 应对 | 跟 8/19 教训对照 |
|---|---|---|---|
| **RaccoonX 跑通 ≠ 业务真用** | 🔴 高 | Phase 0 用 8/19 那条 SQL 验证报告内容 | SQLAdvisor 装上但跑不出 add index |
| **报告空洞没东西看** | 🔴 高 | RaccoonX MySQL 35+ 规则, Phase 0 验证 | 同上 |
| **RaccoonX 资源占用** | 🟡 中 | 134 dev 8GB 内存, MySQL 巡检 + Word 报告跑得动, Ollama 暂不开 | 8/19 sqladvisor 装到 `/opt/archery/bin/` 跟 SOAR 一样套路 |
| **数据出境 (云端 LLM)** | 🔴 高 | 默认 `ai_mode=disabled` | 8/19 教训 |
| **RaccoonX 快速迭代 API 崩** | 🟡 中 | 锁版本 v26.8.15.0, 推 110 时同步更新 | 8/18 教训 (1.10.0 → 1.14.0 切换) |
| **数据源双维护** | 🟡 中 | 一次性同步脚本 + 后续手动重跑 | 8/18 教训 (sqladvisor 历史 bug) |
| **跟 gh-ost 任务管理菜单冲突** | ⚪ 低 | 菜单分开 ("DBA 工具 → gh-ost 任务" / "DBA 工具 → 数据库巡检") | 8/13 拍板 |
| **Ollama 资源不够** | 🟡 中 | 暂不开 AI, 跟 8/19 一样 | 8/19 教训 |
| **DBA 误改 perm** | ⚪ 低 | 默认最小权限, 4 个 perm 4 个判定 (跟 gh-ost 任务管理一致) | 8/13 教训 |
| **Archery password 在内存明文** | ⚪ 低 | 跟 gh-ost 业务一样接受, 后续可用 Vault 兜底 | 8/12 一致 |

### 每个 Phase 验证标准

- **Phase 0**: 拿到 Word 报告, 内容非空, 有"缺失索引"卡片, **用 8/19 那条 SQL 真给出"加索引"建议**
- **Phase 1**: 业务 RD 真能用, 看到自己库健康分 + 风险; DBA 看全量; 4 个 perm 跟 8/13 gh-ost 任务管理一致
- **Phase 2**: DBA 配 cron 跑通, 日报真发出去; 趋势图渲染正常
- **Phase 3**: 业务 RD 点按钮真建工单走审批 + gh-ost

---

## 10. 跟推 110 prod 的关系

### 10.1 时间窗 (跟推 110 W3 9/1-7 并行不冲突)

```
W2 (8/18-24)        W2 末 (8/21-27)        W3 (8/28-9/3)
摸头 + Phase 0      Phase 1                Phase 2 + 推 110
W1+W2 必做摸头       Archery 端              巡检增强
RaccoonX 跑通       巡检框架                推 110 prod 包含 RaccoonX
```

### 10.2 5 步必做脚本补充 (推 110 必做)

5 步必做 (commit `035850f`, 8/17) 当前 7 个步骤, 推 RaccoonX 时补 3 条:

```bash
# 步骤 8: 装 RaccoonX 源码到 110 prod
bash scripts/deploy/install_raccoonx_110prod.sh
# - 拉代码 (跟 Archery 同 v0.5.0-alpha tag)
# - 创建 /opt/raccoonx/venv (Python 3.10)
# - systemd unit /etc/systemd/system/raccoonx.service
# - nginx 反代 /raccoonx/ → 127.0.0.1:5003
# - 验证 systemctl status raccoonx + curl 5003
# - 验证 chmod archery:archery (跟 8/19 教训, 避免 permission denied)

# 步骤 9: 同步 Archery instance → RaccoonX datasource (110 prod)
ssh 110 'cd /opt/archery && python manage.py sync_raccoonx_datasources'
# - 跑一次性同步脚本
# - 验证 ext_inspect_datasource_map 有 10 个实例
# - 验证 RaccoonX 端能连上每个实例

# 步骤 10: 配置 RACCOONX_API_URL / RACCOONX_API_KEY 环境变量
# 存 /etc/archery/.env (跟现有真凭据一致)
# RACCOONX_API_URL=http://127.0.0.1:5003
# RACCOONX_API_KEY=<RaccoonX admin API Key, 8/18 教训: 用 SysConfig().set 加密配>
```

### 10.3 110 prod 推前必做 (跟 W1+W2 摸头 8/18 一致)

> **推 110 前**: 跑 W1+W2 必做摸头 7 项 (commit `acd6345`, 8/18) + 新增 sql_inspect 4 个 migration 5.7 演练 (跟 ddl_gh_ost 8/18 演练同), 5.7/8.0 兼容性确认。Phase 1 完成后, 推 110 当天一次性跑 10 步必做。

### 10.4 5 步必做补 3 条后完整 10 步

| 步骤 | 内容 | 状态 |
|---|---|---|
| 1 | 推代码 + migration | 8/17 commit `035850f` |
| 2 | 凭据备份 (DBA 手动) | 8/17 |
| 3 | 凭据上传 (DBA 手动) | 8/17 |
| 4 | env 配 (DBA 手动) | 8/17 |
| 5 | fix_approval_flow_3level 阶段 3 | 8/17 |
| 6 | 清空 sqladvisor 配置 (8/18 教训) | 8/18 commit `25ce9b3` |
| 7 | 清空 soar 配置 (8/19 教训) | 8/19 |
| **8** | **装 RaccoonX 源码** (本次新增) | 待 Phase 0 验证后补 |
| **9** | **同步数据源** (本次新增) | 待 Phase 0 验证后补 |
| **10** | **配 RACCOONX_API_URL/API_KEY** (本次新增) | 待 Phase 0 验证后补 |

---

## 关联

- **HTML 版**: [2026-08-21_raccoonx-integration-design.html](2026-08-21_raccoonx-integration-design.html)
- **项目主页**: [README.md](../README.md) (Archery 二次开发主页)
- **踩坑速查**: [troubleshooting.md](../troubleshooting.md)
- **二次开发规范**: [customization.md](../customization.md)
- **同源设计稿**:
  - gh-ost 详设: `2026-08-10_gh-ost-detail-design.html` (80KB, 13 章节)
  - DDL 智能回滚: `2026-08-13_ddl-rollback-parse-design.html` (38KB)
  - v0.4.0 归档专题: `2026-08-10_v040-archive-rebuild-design.html` (64KB)
  - v0.4.5 ghost rebuild: `2026-08-13_v0405-ghost-rebuild-design.html` (40KB)
  - 钉钉 OA: `2026-08-10_dingtalk-oa-detail-design.html` (102KB)
