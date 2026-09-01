# 9/3 DDL 跨库同步 库对详情 + 字段 diff 设计 (前端 UX) (9/3 14:30)

> **W1 设计阶段 D4 (9/3 周四)**: 库对详情页 5 按钮 UX + 业务库 DDL 工单详情页"本表已配置同步" 提示
>
> 读者: DBA 团队 (我 + 阿达叔叔), 实施用
> 来源: W1-D3 §3-§5 (R1/R2/R3 端点) + W1-D3 §8 (字段 diff 联动点) 衍生前端 UX
>
> **本文档不覆盖**:
> - 业务背景 (4 部分: 现状/痛点/影响/目标) — 看 `2026-08-31_ddl-sync-pair-design-refined.md` §0
> - 3 张表字段定义 — 看 `2026-09-01_ddl-sync-data-model.md` §2-§4
> - 后端 service 拆分 + API 契约 — 看 `2026-09-01_ddl-sync-implementation-design.md` §1-§2
> - R1/R2/R3 后端流程 — 看 `2026-09-01_ddl-sync-implementation-design.md` §3-§5

---

## 0. 概述 (跟前 3 份设计稿关系)

### 0.1 4 份设计稿分层

| 文档 | 读者 | 篇幅 | 视角 |
|---|---|---|---|
| **refined** (`2026-08-31_ddl-sync-pair-design-refined.md`) | 领导汇报 | 42KB | 业务视角 (为什么做 / 痛点 / 影响 / 目标) |
| **D2 数据模型** (`2026-09-01_ddl-sync-data-model.md`) | DBA 内部 | 14.6KB | 表结构视角 (3 张表 / ER 图 / migration) |
| **W1-D3 实施** (`2026-09-01_ddl-sync-implementation-design.md`) | DBA 实施 (后端) | 46KB | API 契约 (service 拆分 / 5 端点 / 状态机 / perm) |
| **W1-D4 本文档** (本文) | DBA 实施 (前端) | 15-20KB | 前端 UX (5 按钮 modal / 工单详情页 / 字段 diff 联动) |

### 0.2 W1-D4 跟 W1-D3 关系

```
W1-D3 (后端)              W1-D4 (前端, 本文)
§3 R1 批量导入 ──→ §1.1 📥 批量导入 modal UX
§4 R2 一键配 ──→ §1.2 🎯 一键配 modal UX
§5 R3 走当前配置 ──→ §1.4 ⚙️ 过滤规则 modal UX
§2 端点 add_table ──→ §1.3 + 添加同步表 modal UX
§8 联动点 3 字段 diff ──→ §3 字段 diff inline 联动
§6 5 status 状态机 ──→ §2.3 业务库 DDL 工单详情页 alert
```

### 0.3 W1-D4 核心目标

- 把 W1-D3 5 个端点 (compute_diff / one_click_setup / bulk_import / add_table / history_list) 落到**前端 UX 详细设计**
- 库对详情页 5 按钮 modal ASCII mockup (一键配 / 批量导入 / 添加 / schema 差集 / 过滤规则)
- 业务库 DDL 工单详情页"本表已配置同步" 提示 (detail.html 新增 alert)
- 字段 diff 端点复用 (跟 8/12 v0.3.x 联动, 避免重复造轮子)
- 前端 perm 守卫 (复用 8/13 AJAX 守卫 + 前端守卫 2 教训)

---

## 1. 库对详情页 5 按钮 UX

### 1.0 库对详情页整体布局

```
┌─────────────────────────────────────────────────────────────┐
│  库对详情: hly_accesscard 库对                                 │
│  (业务库 hly_accesscard 1589 张 ↔ 历史库 hly_activity 1289 张) │
├─────────────────────────────────────────────────────────────┤
│  [基本信息] [同步表清单] [同步历史] [操作日志]                  │
├─────────────────────────────────────────────────────────────┤
│  同步表清单 (1589 张 · 1289 白名单 + 300 黑名单)              │
│                                                              │
│  [🎯 一键配]  [📥 批量导入]  [+ 添加同步表]  [🔍 schema 差集] [⚙️ 过滤规则] │  ← 5 按钮
│                                                              │
│  搜索: [_______]  过滤: [全部 ▼] [白名单 ▼] [黑名单 ▼]        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 表名         类型      来源        大小      创建时间 │  │
│  ├──────────────────────────────────────────────────────┤  │
│  │ accesscard_  白名单    手动         243MB    09-01   │  │
│  │   black_detail                                       │  │
│  │ accesscard_  白名单    一键配       50MB     09-01   │  │
│  │   account                                           │  │
│  │ dict_config  黑名单    一键配       100KB    09-01   │  │
│  │ ... (分页 50/页)                                    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 📥 批量导入 modal (复用 W1-D3 §3)

> 详细流程 + 后端见 W1-D3 §3 R1 批量导入 UX 流程

```
┌──────────────────────────────────────────────────────────┐
│  📥 批量导入同步表                                          │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  扫描源库 hly_accesscard: 1589 张, 过滤后 1200 张            │
│                                                            │
│  过滤规则:                                                  │
│  [✓] 排除前缀 _log _bak _tmp _test (300 张)                │
│  [✓] 排除后缀 _history _archive (50 张)                    │
│  [✓] 排除 ENGINE MEMORY BLACKHOLE (10 张)                  │
│  [✓] 排除空表 (29 张)                                       │
│                                                            │
│  搜索: [_______]                                            │
│  ☐ 全选  ☐ 反选  选中: 0 / 1200                             │
│                                                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │ ☐ 表名                            已存在  大小      │  │
│  ├────────────────────────────────────────────────────┤  │
│  │ ☐ accesscard_black_detail            否    243MB    │  │
│  │ ☐ accesscard_account                否    50MB     │  │
│  │ ☐ dict_config                       是    100KB    │  │
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

### 1.2 🎯 一键配 modal (复用 W1-D3 §4)

> 详细流程 + 后端见 W1-D3 §4 R2 一键配 UX 流程

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
│       [预览前 20 张] [全选] [反选]                          │
│                                                            │
│  [✓] 黑名单 (业务库 - 历史库)  300 张 ✅ 推荐全选            │
│       [预览前 20 张] [全选] [反选]                          │
│                                                            │
│  [ ] 孤儿 (历史库 - 业务库)  0 张                            │
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

### 1.3 + 添加同步表 modal (单张加, 兜底)

```
┌──────────────────────────────────────────────────────────┐
│  + 添加同步表                                                │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  表名: [_______________________]                            │
│       (业务库 hly_accesscard 下的表名)                       │
│       [🔍 自动补全] (扫源库 1589 张, 模糊匹配)              │
│                                                            │
│  同步类型:                                                  │
│       (●) 白名单 (要同步)  ( ) 黑名单 (不同步)              │
│                                                            │
│  字段级调整规则 (可选, Phase 3 用):                          │
│       跳过列 (csv): [_____________]                        │
│       重命名列 (JSON): [_________________]                  │
│       {                                                     │
│         "skip_columns": ["create_time", "update_time"],   │
│         "rename_columns": {"old": "new"}                   │
│       }                                                     │
│                                                            │
│  预览: 添加 1 张白名单表 (bulk_create 1 条记录)              │
│                                                            │
│              [取消]              [确认添加]                  │
└──────────────────────────────────────────────────────────┘
```

### 1.4 ⚙️ 过滤规则 modal (Phase 3, R3 加 filter_rule JSONField)

> **避坑**: D2 §2 DdlSyncPair.filter_rule 是 R3 Phase 3 加的 JSONField, Phase 1 可先建好字段, 不实现前端配置 UI. Phase 3 上线时再启用此 modal.

```
┌──────────────────────────────────────────────────────────┐
│  ⚙️ 过滤规则 (Phase 3 · 增量同步配置)                        │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  业务库新增表自动入"待确认" 列表, 过滤规则自动匹配             │
│                                                            │
│  排除前缀 (csv): [_______]   排除后缀 (csv): [_______]      │
│  示例: _log,_bak,_tmp,_test       _history,_archive         │
│                                                            │
│  排除 ENGINE (csv): [_______]   排除空表 (✓)                │
│  示例: MEMORY,BLACKHOLE                                    │
│                                                            │
│  最小表大小 (bytes): [_______]                              │
│  示例: 0 (不限制) / 1048576 (1MB)                          │
│                                                            │
│  匹配规则: 排除规则 OR 命中 + 最小大小过滤 = 跳过同步         │
│  命中规则: 排除规则 NOT 命中 = 自动入白名单                  │
│                                                            │
│  当前生效规则: (R3 加后存到 DdlSyncPair.filter_rule)         │
│  {                                                          │
│    "exclude_prefix": ["_log", "_bak", "_tmp", "_test"],    │
│    "exclude_suffix": ["_history", "_archive"],             │
│    "exclude_engine": ["MEMORY", "BLACKHOLE"],              │
│    "min_size_bytes": 0                                     │
│  }                                                          │
│                                                            │
│              [取消]              [保存规则]                  │
└──────────────────────────────────────────────────────────┘
```

### 1.5 🔍 schema 差集 modal (compute_diff 端点 + 联动字段 diff)

> **联动 8/12 字段 diff**: 复用 v0.3.x 字段 diff 端点 (`POST /gh_ost/column_diff/`), W1-D3 §8 联动点 3 展开

```
┌──────────────────────────────────────────────────────────┐
│  🔍 schema 差集 (业务库 vs 历史库 · 字段 diff 联动)          │
├──────────────────────────────────────────────────────────┤
│                                                            │
│  自动扫双库, 对比字段差异 + 字段 diff 风险规则                │
│                                                            │
│  对比维度: 8 维 (类型 / 字符集 / 排序规则 / NULL /          │
│         DEFAULT / COMMENT / 索引 / 字符长度)               │
│                                                            │
│  ━━━ 库对扫表结果 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                            │
│  业务库 hly_accesscard: 1589 张表                          │
│  历史库 hly_activity:   1289 张表                          │
│                                                            │
│  缺失表 (业务库有, 历史库没): 300 张 (不同步)               │
│  字段差异表 (有字段差异的表): 45 张 ⚠️ 需要 DBA 关注        │
│  完全一致表: 1244 张 ✓                                     │
│                                                            │
│  ━━━ 字段差异详情 (前 20 张, 点查看全部) ━━━━━━━━━━━━━━━  │
│                                                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │ 表名                  差异列   风险等级  详情        │  │
│  ├────────────────────────────────────────────────────┤  │
│  │ accesscard_account   status  高       字符集丢失  │  │
│  │                                       (8/27 实战)  │  │
│  │ accesscard_user      phone   中       长度缩短    │  │
│  │ accesscard_black_    remark  低       COMMENT 变  │  │
│  │   detail                                        │  │
│  │ ... (前 20 张)                                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                            │
│  跳转: [📋 查看全部 45 张字段差异表]                        │
│                                                            │
│              [取消]      [导出 CSV 报告]                    │
└──────────────────────────────────────────────────────────┘
```

**避坑 8/12 字段 diff 实战**: 复用时前端 JS 变量要 `json.dumps + |safe` (Django 4.0+ 没 escapejs filter)

---

## 2. 业务库 DDL 工单详情页"本表已配置同步" 提示

### 2.1 入口 (业务库 DDL 工单 detail.html)

> **核心联动**: 业务 RD 提 DDL 工单, 在工单详情页看到"本表已配置跨库同步", 让业务 RD 知道"DDL 提完会自动同步到历史库"

```
┌─────────────────────────────────────────────────────────────┐
│  DDL 工单详情 #100                                             │
│  (业务库 hly_accesscard.accesscard_black_detail)              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  状态: workflow_manreviewing (审批中)                          │
│  发起人: mkq (业务 RD)                                         │
│  SQL: ALTER TABLE accesscard_black_detail ADD COLUMN ...     │
│                                                              │
│  ━━━ 本表已配置跨库同步 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │  ← 新增 alert
│                                                              │
│  ⚠️ 此 DDL 审批通过后会自动同步到历史库                         │
│                                                              │
│  库对: hly_accesscard 库对 (业务库 1589 张 ↔ 历史库 1289 张)   │
│  同步模式: blacklist (默认)                                   │
│  同步状态: pending (审批通过后生成历史库镜像工单)               │
│  联动: v0.4.5 智能回滚 (失败时自动 drop 残留 _gho/_del)        │
│                                                              │
│  📋 [查看同步历史]  🔗 [跳转到库对详情]                        │  ← 2 跳转链接
│                                                              │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                              │
│  字段 diff 检测:                                              │
│  ⚠️ 字符集丢失 (高风险)  ⚠️ 长度缩短 (中风险)                │  ← 复用 8/26 21:34 字段 diff inline
│  [📋 查看字段 diff 详情]                                      │
│                                                              │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │
│                                                              │
│  审批流程:                                                    │
│  [✓] 研发组长 (id=14) 已审批                                  │
│  [ ] DBA 组长 (id=15) 待审批                                  │
│  [ ] DBA (id=3) 待审批                                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 alert 块实现 (Django template)

```django
{# templates/sql/detail.html (业务库 DDL 工单详情页) #}
{% if sync_pair_alert %}
<div class="alert alert-warning" role="alert">
  <h4 class="alert-heading">⚠️ 本表已配置跨库同步</h4>
  <p>
    此 DDL 审批通过后会自动同步到历史库
    {% if sync_pair_alert.target_db %}
      ({{ sync_pair_alert.target_db }})
    {% endif %}
  </p>
  <hr>
  <p class="mb-1">
    <strong>库对:</strong>
    {{ sync_pair_alert.pair_name }}
    (业务库 {{ sync_pair_alert.source_db_size }} 张
    ↔ 历史库 {{ sync_pair_alert.target_db_size }} 张)
  </p>
  <p class="mb-1">
    <strong>同步模式:</strong>
    {{ sync_pair_alert.get_sync_mode_display }}
  </p>
  <p class="mb-1">
    <strong>同步状态:</strong>
    {{ sync_pair_alert.sync_status }} (审批通过后生成历史库镜像工单)
  </p>
  <p class="mb-1">
    <strong>联动:</strong> 智能回滚 (失败时自动 drop 残留 _gho/_del)
  </p>
  <hr>
  <a href="{% url 'ddl_sync:pair_detail' sync_pair_alert.pair_id %}" class="btn btn-sm btn-primary">
    🔗 跳转到库对详情
  </a>
  <a href="{% url 'ddl_sync:history_list' %}?pair={{ sync_pair_alert.pair_id }}" class="btn btn-sm btn-info">
    📋 查看同步历史
  </a>
</div>
{% endif %}
```

### 2.3 view 端构建 sync_pair_alert context (views.py)

```python
# views.py
def detail(request, workflow_id):
    workflow = get_object_or_404(SqlWorkflow, pk=workflow_id)
    
    # 联动: 查 DdlSyncPair 是否覆盖此表
    sync_pair_alert = None
    if workflow.instance and workflow.db_name:
        try:
            pair = DdlSyncPair.objects.filter(
                source_instance=workflow.instance,
                source_db=workflow.db_name,
                enabled=True,
            ).first()
            if pair:
                # 解析 sql_content 提取表名
                table_name = _extract_table_name(workflow.sql_content)
                if table_name:
                    # 判定白/黑名单
                    should_sync = _should_sync(pair, table_name)
                    sync_pair_alert = {
                        "pair_id": pair.id,
                        "pair_name": pair.name,
                        "target_db": pair.target_db,
                        "source_db_size": pair._count_source_tables(),
                        "target_db_size": pair._count_target_tables(),
                        "sync_mode": pair.sync_mode,
                        "sync_status": "pending" if should_sync else "skipped",
                    }
        except Exception:
            logger.exception("查 DdlSyncPair 失败, 跳过 alert")
            sync_pair_alert = None
    
    context = {
        "workflow": workflow,
        "sync_pair_alert": sync_pair_alert,  # 新增
        ...
    }
    return render(request, "detail.html", context)
```

### 2.4 异常处理 (alert 块)

| 异常 | 处理 | 用户提示 |
|------|------|----------|
| `DdlSyncPair` 找不到 | sync_pair_alert = None, 不显示 alert | 无 (DBA 没配库对) |
| `workflow.instance` 为空 | 不显示 alert | 无 (新工单, 还没选 instance) |
| `table_name` 解析失败 | 不显示 alert | 无 (DDL 不是 CREATE/ALTER/DROP) |
| 黑名单含此表 | sync_pair_alert.sync_status = "skipped" | "本表已配置黑名单, 不同步" |
| 白名单不含此表 (orphan) | sync_pair_alert.sync_status = "skipped" | "本表不在白名单, 不自动同步, 需 DBA 手动同步" |
| 库对禁用 (enabled=False) | 不显示 alert | 无 (DBA 暂停库对) |

---

## 3. 字段 diff 端点复用 (跟 8/12 v0.3.x 联动)

### 3.1 复用场景

> **W1-D3 §8 联动点 3**: 8/12 字段 diff — 复用 column_diff 端点 (前端 JS 变量要 json.dumps + |safe, Django 4.0+ 没 escapejs)

**3 个复用场景**:

| 场景 | 入口 | 端点 | 输出 |
|------|------|------|------|
| 1. 库对详情页 字段 diff 联动 | detail.html 字段 diff inline 区域 (8/26 21:34 落地) | `POST /gh_ost/column_diff/` | 11 风险点 + 8 维对比 |
| 2. 业务库 DDL 工单详情页 字段 diff | W1-D4 §2.1 alert 块内 "查看字段 diff 详情" 链接 | 同上 | 同上 |
| 3. 库对详情页 🔍 schema 差集 modal | W1-D4 §1.5 schema 差集 | 同上 + 库对扫表批处理 | 45 张字段差异表 + CSV 导出 |

### 3.2 复用实现 (避免重复造轮子)

**复用 8/12 字段 diff service**:

```python
# services/column_diff.py (v0.3.x 已有, 8/12 落地)
def fetch_column_diff(instance, db_name, table_name) -> dict:
    """
    复用 8/12 字段 diff 端点, 库对详情页直接调
    """
    ...

# 库对详情页 (新功能) - 复用方式 1
def schema_diff_view(request, pair_id):
    pair = DdlSyncPair.objects.get(id=pair_id)
    diffs = []
    for table in pair._get_synced_tables()[:20]:  # 前 20 张
        diff = fetch_column_diff(
            pair.source_instance, pair.source_db, table
        )
        if diff["high_risk_count"] > 0 or diff["mid_risk_count"] > 0:
            diffs.append({"table": table, "diff": diff})
    return JsonResponse({"ok": True, "data": {"diffs": diffs}})
```

**避坑 8/26 21:57**: 复用时前端 JS 变量要 `json.dumps + |safe` (Django 4.0+ 没 escapejs filter)

```django
{# pair_detail.html - 复用字段 diff inline #}
{% if field_diffs_json %}
<script>
  const fieldDiffs = {{ field_diffs_json|safe }};
  // ... 复用 sqlsubmit.html 同样 fetchColumnDiff / renderColumnDiff 函数
</script>
{% endif %}
```

### 3.3 库对扫表批处理 (性能预算)

> 1589 张表全部跑字段 diff, 单端点串行 = 1589 × 2s = 53min, 太慢. 必用批量优化.

**批量优化方案**:

```python
# services/schema_diff.py (W1-D4 新加)
def batch_schema_diff(pair: DdlSyncPair, table_names: list[str]) -> dict:
    """
    批量字段 diff - 走 information_schema 一次拿所有列, 内存比对
    性能: 1589 张表 < 30s (单 SQL 拿所有列, 内存比对比单端点快 100x)
    """
    source_columns = _fetch_all_columns(pair.source_instance, pair.source_db)
    target_columns = _fetch_all_columns(pair.target_instance, pair.target_db)
    diffs = []
    for table in table_names:
        diff = _compare_columns(
            source_columns.get(table, []),
            target_columns.get(table, []),
        )
        if diff["high_risk_count"] > 0:
            diffs.append({"table": table, "diff": diff})
    return {"ok": True, "data": {"diffs": diffs, "total": len(diffs)}}


def _fetch_all_columns(instance, db_name) -> dict[str, list[dict]]:
    """
    一次 SQL 拿所有列, 性能预算 1589 张表 < 5s
    SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
           EXTRA, COLUMN_COMMENT, CHARACTER_SET_NAME, COLLATION_NAME
    FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s
    """
    conn = pymysql.connect(...)
    with conn.cursor() as cur:
        cur.execute(SQL, (db_name,))
        rows = cur.fetchall()
    # 按 TABLE_NAME 分组
    result = defaultdict(list)
    for row in rows:
        result[row[0]].append({...})
    return dict(result)
```

**性能预算**:

| 库对规模 | 扫源库列 | 扫目标库列 | 比对 | 总耗时 |
|----------|----------|------------|------|--------|
| 1589 张表 (hly_accesscard) | 3.2s | 2.8s | 0.5s | **6.5s** |
| 1289 张表 (hly_activity) | 2.5s | 2.2s | 0.4s | **5.1s** |
| 1589 + 1289 双库扫 | 5.7s | 5.0s | 0.9s | **11.6s** |

**前端 spinner 30s 超时**, 性能预算 < 15s 留足 buffer.

### 3.4 复用 vs 重复的取舍 (避坑 8/12 实战)

| 维度 | 复用 8/12 字段 diff | 重新写 W1-D4 字段 diff |
|------|---------------------|------------------------|
| 优点 | 0 重复代码, 11 风险规则 + 8 维对比 都复用 | 独立维护, 不影响 v0.3.x |
| 缺点 | 8/12 bug 会同步影响 (e.g. 8/26 21:57 JS ReferenceError) | 重复造轮子, 2 份代码要同步修 |
| 性能 | 8/12 端点单表串行, 大库对慢 | W1-D4 批量优化, 库对全表快 |
| 结论 | ✅ **复用 8/12 端点 + W1-D4 加批量优化** | ❌ 重复造轮子 |

**最终决定**: 复用 8/12 `column_diff.py` + W1-D4 加 `batch_schema_diff()` 批量优化, 库对全表用批量, 单表用 8/12 端点.

---

## 4. 异常处理 (前端 perm 守卫 + modal 错误 UX)

### 4.1 前端 perm 守卫 (复用 8/13 AJAX 守卫教训)

> **避坑 8/13**: Django AJAX 端点 perm 守卫不能 raise PermissionDenied (返 HTML 错误页), 必用 JsonResponse(403) 返 JSON. 前端守卫要覆盖所有页面, 改一处忘改另一处.

```django
{# pair_detail.html - 5 按钮 perm 守卫 #}
<div class="btn-group" role="group">
  {% if perms.ddl_sync.change_ddlsyncpair %}
    <button id="btn-bulk-import" class="btn btn-primary">📥 批量导入</button>
    <button id="btn-one-click-setup" class="btn btn-success">🎯 一键配</button>
  {% endif %}

  {% if perms.ddl_sync.add_ddlsynctable %}
    <button id="btn-add-table" class="btn btn-info">+ 添加同步表</button>
  {% endif %}

  {% if perms.ddl_sync.view_ddlsyncpair %}
    <button id="btn-schema-diff" class="btn btn-warning">🔍 schema 差集</button>
  {% endif %}

  {% if perms.ddl_sync.change_ddlsyncpair %}
    <button id="btn-filter-rule" class="btn btn-secondary">⚙️ 过滤规则</button>
  {% endif %}
</div>

{# JS 块也要包同一个守卫 (8/13 教训) #}
{% if perms.ddl_sync.change_ddlsyncpair %}
<script>
  $("#btn-bulk-import").click(() => openBulkImportModal());
  $("#btn-one-click-setup").click(() => openOneClickSetupModal());
  // ... 其他 2 按钮
</script>
{% endif %}
```

### 4.2 4 角色 4 判定 (前端守卫覆盖)

| 角色 | 可见 5 按钮 | 可操作 | 业务库 DDL 工单 alert |
|------|--------------|--------|---------------------|
| **业务 RD** | (无, 默认隐藏) | 只看自己的同步历史 (跳转到 history_list) | ✅ 可见 (自己提的工单) |
| **DBA 组长** | 全部 5 按钮 (view + change + add) | 全部 4 perm | ✅ 可见 (所有工单) |
| **DBA 执行** | 4 按钮 (批量导入 / 一键配 / 添加 / schema 差集, view + change) | 4 perm (不能 delete) | ✅ 可见 (所有工单) |
| **副总 / superuser** | 全部 5 按钮 | 全部 4 perm (含 delete) | ✅ 可见 (所有工单) |

**审计清单 (改 perm 守卫时必走)**:

```bash
grep -rn "btn-bulk-import\|btn-one-click-setup\|btn-add-table\|btn-schema-diff\|btn-filter-rule" sql/extensions/ddl_sync/templates/
grep -rn "{% if.*ddl_sync\." sql/extensions/ddl_sync/templates/
```

### 4.3 modal 异常 UX (前端错误处理)

**统一错误处理 pattern**:

```javascript
// pair_detail.js - 统一错误处理
function handleAjaxError(xhr, defaultMsg) {
  let msg = defaultMsg;
  try {
    const data = JSON.parse(xhr.responseText);
    if (data.error) msg = data.error;
  } catch (e) {
    // 非 JSON 响应 (8/13 教训: PermissionDenied 返 HTML)
    msg = "服务异常, 请联系 DBA (HTTP " + xhr.status + ")";
  }
  showErrorToast(msg);  // Element UI notification
}

function showErrorToast(msg) {
  this.$notify.error({ title: "操作失败", message: msg, duration: 5000 });
}

// 各端点调用
$("#btn-bulk-import").click(() => {
  $.ajax({
    url: `/ddl_sync/pair/${pairId}/bulk_import/`,
    method: "POST",
    data: { table_names: selectedTables, sync_type: "whitelist" },
    success: (data) => {
      if (data.ok) {
        this.$message.success(`批量导入 ${data.data.imported_count} 张完成`);
        location.reload();
      } else {
        showErrorToast(data.msg || "批量导入失败");
      }
    },
    error: (xhr) => handleAjaxError(xhr, "批量导入失败"),
  });
});
```

### 4.4 5 类异常 + 用户提示

| 类别 | 后端处理 | 前端 UX |
|------|----------|---------|
| **用户输入错** (table_names 空 / sync_type 错) | 返 400 + `{"ok": false, "error": "..."}` | Element UI notification 红色 toast 5s |
| **库对配置错** (pair.disabled / source_instance 不存在) | 返 400 + `{"ok": false, "error": "..."}` | toast 提示 + 按钮置灰 |
| **库连接错** (1045 / connection refused) | 返 500 + `{"ok": false, "error": "..."}` | toast 提示 + 通知 DBA 群 |
| **DDL 转换错** (transform_rule 错) | 返 400 + `{"ok": false, "error": "..."}` | toast 提示 + 跳转修复 transform_rule |
| **target_workflow 执行错** (语法 / 权限) | 联动 v0.4.5 rollback + history failed | toast 提示 + 跳转 history_list 看详情 |

---

## 5. 性能预算 + 134 dev 演练 5 Case

### 5.1 性能预算 (前端 UX 加载 + 后端 API)

| 场景 | 前端加载 | 后端 API | 总耗时 | 性能预算 |
|------|----------|----------|--------|----------|
| pair_detail 页面加载 | 0.5s | 1.2s (4 tab query) | 1.7s | < 2s |
| 批量导入 modal 打开 (扫源库 1589 张) | 0.3s | 3.2s | 3.5s | < 5s |
| 一键配 modal 打开 (compute_diff 1589+1289) | 0.3s | 12.3s | 12.6s | < 15s |
| schema 差集 modal (批量字段 diff) | 0.3s | 11.6s | 11.9s | < 15s |
| 业务库 DDL 工单详情 (查 DdlSyncPair + 字段 diff) | 0.5s | 2.5s | 3.0s | < 5s |
| 库对详情页 5 按钮 perm 守卫 | 0.1s | 0.1s | 0.2s | < 0.5s |

### 5.2 134 dev 端到端演练 5 Case (W1-D4 前端 UX 部分)

| Case | 场景 | 预期结果 | 验证点 |
|------|------|----------|--------|
| **A** | 库对详情页加载, 5 按钮显示 (DBA 角色) | 5 按钮全部可见, 顺序正确 | 截图 / curl 200 |
| **B** | 业务 RD 角色访问库对详情 | 5 按钮全部隐藏, 跳转到 history_list | curl 200 + 按钮不可见 |
| **C** | 一键配 modal 打开 (hly_accesscard 1589 张) | 12.3s 内出结果, 3 集合显示 | 截图 + 响应时间 |
| **D** | 业务库 DDL 工单详情 (hly_accesscard.test) | alert 块显示"本表已配置跨库同步" | 截图 + 跳转链接 |
| **E** | schema 差集 modal 打开 (1589 张扫表) | 11.6s 内出结果, 45 张字段差异 | 截图 + CSV 导出 |

### 5.3 业务 RD mkq 浏览器实测 (8/26 教训应用)

**避坑 8/26**: 5+1 端点验证深度不够, 必走"业务 RD 浏览器真业务工单流"

- 必含特殊场景: 库名含 `use hly_xxx;` 多行 SQL / 大表 ALTER / 失败工单 retry / 孤儿表 skipped
- 必测 4 perm 守卫: 业务 RD 点一键配 403 / DBA 成功 / 副总兜底
- 必测 alert 块: 业务 RD 提单 → 审批中看到 alert → 审批通过后看同步历史更新

### 5.4 推 110 prod checklist 补充 (W1-D4 前端部分)

```bash
# W1-D4 新加前端文件
- sql/extensions/ddl_sync/templates/pair_list.html
- sql/extensions/ddl_sync/templates/pair_detail.html  ← 含 5 按钮 + 4 tab
- sql/extensions/ddl_sync/templates/partials/_bulk_import_modal.html
- sql/extensions/ddl_sync/templates/partials/_one_click_modal.html
- sql/extensions/ddl_sync/templates/partials/_add_table_modal.html
- sql/extensions/ddl_sync/templates/partials/_schema_diff_modal.html
- sql/extensions/ddl_sync/templates/partials/_filter_rule_modal.html
- sql/extensions/ddl_sync/static/ddl_sync/pair_detail.js  ← 含 5 modal JS
- sql/extensions/ddl_sync/static/ddl_sync/column_diff_reuse.js  ← 复用 8/12

# 跟 v0.3.x 字段 diff 联动
- sql/templates/sql/detail.html  ← 业务库 DDL 工单详情页加 alert 块

# 跟 common base.html 侧边栏联动
- common/templates/base.html  ← 加"DDL 跨库同步" 菜单
```

---

## 附录 A: 9/3 W1-D4 拍板记录

**DBA 拍板 (9/3 14:30, 假设)**:
1. ✅ 命名/路径 `docs/designs/2026-09-03_ddl-sync-detail-ux-design.md`
2. ✅ 5 章节结构 (库对详情 5 按钮 + 业务库 DDL 工单详情 + 字段 diff 复用 + 异常处理 + 性能预算)
3. ✅ 跟 W1-D3 互相引用不覆盖 (D3 后端 / D4 前端)
4. ✅ 复用 8/12 字段 diff 端点 + W1-D4 加 batch_schema_diff() 批量优化

**9/1 W1-D3 拍板引用**: 本文 §1 库对详情 5 按钮 modal 引用 W1-D3 §3 §4 §5 端点契约.

**8/12 字段 diff 实战引用**: 本文 §3 复用 8/12 `column_diff.py` + W1-D4 加批量优化 (避坑 8/26 21:57 JS ReferenceError).

**8/13 AJAX 守卫教训引用**: 本文 §4.1 复用 8/13 perm 守卫 (JsonResponse 403 不 raise PermissionDenied) + §4.2 前端守卫覆盖全 5 按钮.

---

## 附录 B: 跟 W2 实施的接口契约

W1-D4 拍板后, W2 开发 (9/7-9/11) 直接按本文 §1-§5 落地:

- **§1 库对详情 5 按钮 modal** → 9/7-9/8 写 5 个 modal HTML + JS
- **§2 业务库 DDL 工单详情 alert** → 9/9 改 detail.html + views.py 加 sync_pair_alert context
- **§3 字段 diff 端点复用** → 9/10 复用 8/12 column_diff + 新加 batch_schema_diff 批量优化
- **§4 前端 perm 守卫** → 9/10 全 5 按钮 perm 守卫 + modal 错误 UX
- **§5 134 dev 端到端演练 5 Case** → 9/11 演练

W3 提测上线 (9/14-9/18) 按本文 §5.3 业务 RD mkq 浏览器实测 + §5.4 推 110 前端文件清单.

---

**版本**: W1-D4 v1.0 (9/3 14:30 落地, 提前 9/1 下午)
**作者**: mavis
**审核**: 阿达叔叔 (待)
**配套**:
- 业务背景: `2026-08-31_ddl-sync-pair-design-refined.md` §0
- 数据模型: `2026-09-01_ddl-sync-data-model.md` §2-§4
- 后端 service + 端点: `2026-09-01_ddl-sync-implementation-design.md` §1-§2
- 实施计划: `2026-08-31_r1-implementation-plan.md`
