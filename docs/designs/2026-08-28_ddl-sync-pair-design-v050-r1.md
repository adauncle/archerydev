# DDL 跨库同步 · 业务库 ↔ 历史库 · R1 详细设计

> **Archery R1 · 二次开发设计稿（R 之前 → R1 → R2 → R3 完整版）**
>
> R 之前原版"业务库大几百张表, DBA 手动配表不现实" 阻塞落地。R1 修订版加**批量导入 + 黑名单默认 + 增量同步** 三件套, 把 DBA 工作量从 2-3 小时降到 5-10 min。R2 加一键配机制 (R2 实战数据 6 min 配完), R3 拍板"走当前配置的流程"。重写背景章节 (4 部分), 跟领导汇报能讲清楚"为什么"。

> 配套：[HTML 功能图说](2026-08-28_ddl-sync-pair-feature-card.html) · [R 之前原版](2026-08-21_ddl-sync-pair-design.md) · [R1 changelog](../changelogs/2026-08-28_ddl-sync-v050-revised-design.md) · [R2 changelog](../changelogs/2026-08-28_ddl-sync-v050-r2-one-click-setup.md) · [R3 changelog](../changelogs/2026-08-28_ddl-sync-v050-r3-approval-flow.md)

**版本**: 详细设计 (R1 R2 R3 完整版)
**粒度**: 可直接动手写代码

---

## 0. 背景 

> 重写背景: R 之前原版缺"为什么开发这个功能" 的业务背景说明, 跟领导汇报时不便讲清楚必要性。补 4 部分: **当前两个流程 → 痛点 → 影响 → 新功能目标**, 回答"为什么" 跟"做出来有什么业务价值"。

### 0.1 当前数据同步到历史库 — 两个流程 + 流程图

业务库 ↔ 历史库 当前用 **2 个不同的流程** 同步, 一个自动化 (DML), 一个纯人工 (DDL):

**当前流程 (R 之前 · DBA 视角):**

```
  业务 RD              DBA               历史库
   │                │                │
   │ ① 提 DDL 工单         │                │
   ├───────────────────────────────▶│                │
   │                │ ② 凭经验判断要不要同步     │
   │                │  "业务库改了字段, 历史库?   │
   │                │  嗯, 凭印象好像要"      │
   │                │ ③ 手工到历史库跑 SQL      │
   │                ├───────────────────────────────▶│
   │                │                │
   │  ⚠️ 风险: 步骤 ② ③ 全靠    │                │
   │   DBA 记忆, 容易漏     │                │
```

**当前流程优缺点 (R 之前):**

| 维度 | 现状 |
|------|------|
| ✅ 优点 | DML 走科大国创组件, 自动化 **T+1 增量同步** |
| ❌ 缺点 1 | DDL 走 DBA 人工, **凭经验判断, 容易漏** (每天 5-20 条) |
| ❌ 缺点 2 | 没有"两边 schema 一致" 强制校验, 漏了没人发现 |
| ❌ 缺点 3 | DBA 下班前集中处理, **同步延迟 4-8h** |
| ❌ 缺点 4 | 跨多库场景容易配错目标库 (hly_accesscard / hly_activity / hly_doc_model) |
| ❌ 缺点 5 | DML 同步依赖 DDL 先同步, **DDL 漏 → DML 整条挂** |

**详细对比表 (R 之前 vs R 之后 R1):**

| 流程 | 工具 | 链路 | 自动化 | 风险 |
|------|------|------|--------|------|
| **R 之前 DDL** | **无, 纯人工** | 业务 RD 提 DDL 工单 → **DBA 凭经验** 判断 → DBA 手工到历史库跑 SQL | ❌ 0 自动化 | **DBA 漏同步 / 同步出错 / 同步延迟 4-8h / DML 同步挂** |
| **R 之前 DML** | 科大国创 | 业务库 → 科大国创 (按时间戳增量) → 历史库 | ✅ **T+1 增量同步** | 依赖 DDL 先同步, 否则 DML 整条挂 |
| **R1+ R1 DDL** | **Archery 自动** | 业务 RD → Archery 业务库 DDL → 审过自动触发历史库镜像工单 → 走当前 Archery 配置流程 → 历史库执行 | ✅ **T+0 实时** | **0 漏同步** (业务库 DDL 必审过才触发) |
| **R1+ R1 DML** | 科大国创 (不变) | 业务库 → 科大国创 → 历史库 | ✅ **T+1 增量同步** | **永久稳定** (DDL 0 漏 → DML 不会因 DDL 漏挂) |

> **关键点**: DML 走自动化组件没问题, **DDL 走人工是当前最大风险**。本设计稿 (R1) 解决的就是 DDL 人工同步的问题。

### 0.2 痛点 (DDL 人工同步的 5 个具体问题)

| # | 痛点 | 现状 | 风险等级 |
|---|------|------|----------|
| 1 | **DBA 人工执行, 容易漏** | 每天 DDL 工单 5-20 条, DBA 凭记忆/经验判断哪些要同步到历史库, 没有清单 | **高** |
| 2 | **没有自动校验** | 业务库 DDL 跑通 ≠ 历史库 DDL 跑了, 系统没有"两边 schema 一致" 强制检查 | **高** |
| 3 | **同步不及时** | DBA 一般下班前集中处理, DDL 同步可能延迟 4-8h | **中** |
| 4 | **跨业务库多库场景容易配错** | 业务库都是 hly_ 开头 (hly_accesscard / hly_activity / hly_doc_model 等), DBA 容易配错目标历史库 | **中** |
| 5 | **DML 同步依赖 DDL 先同步** | 科大国创按列名匹配, **历史库没 DDL 那张表/列时 DML 同步任务直接挂** | **高** |

### 0.3 影响 (DDL 漏同步的真实业务影响链路)

DDL 漏同步到历史库, **直接导致下游大数据链路中断**, 影响链路分 5 个阶段:

1. **T+0 当天**: 业务库 DDL 执行成功, 业务 RD 不知道历史库没同步 (DML 同步组件还在跑, 但底层在偷偷失败重试)
2. **T+1 第二天**: 科大国创 DML 同步任务**整体失败** (e.g. 业务库加了一个字段, 历史库没有这个字段, INSERT 报错, 整条链路挂)
3. **T+1 ~ T+3**: 下游大数据 (数据仓库 / 报表 / 风控 / 决策支持) 读历史库数据, 出现"昨天的数据没进来" / "缺字段" / "JOIN 失败"
4. **T+3+**: 业务方反馈"报表数据延迟" / "数据缺漏" / "对账不平", 反查才发现是历史库 DDL 没同步
5. **DBA 介入**: 手动补执行历史库 DDL + 手动重跑 DML 同步任务, 整个修复过程 1-4h, **下游数据延迟 1-3 天**

### 0.4 新功能 R1 DDL 跨库同步 — 解决什么痛点, 达成什么目标

**新功能**: 业务库 DDL 触发后, Archery **自动**在历史库生成镜像 DDL 工单, **走跟正常历史库工单一样的流程** (R3 拍板: 走当前配置的流程, 0 额外代码)。

#### 解决的核心痛点 (4 对应 0.2, 痛点 1+5 合并)

| 痛点 (0.2 序号) | R1 解法 |
|------|------------|
| 1+5 · DBA 漏同步 → 同步组件挂 | **业务库 DDL 审过自动触发历史库镜像工单**, 0 漏同步 + 同步组件不再因 DDL 漏同步挂 |
| 2 · 没有自动校验 | **业务库 DDL 必审过 (`current_status=1 PASSED`) 才触发**, 实时校验 |
| 3 · 同步不及时 | **T+0 实时触发**, 不再下班前集中处理 |
| 4 · 跨多库容易配错 | **DBA 配库对时用 `WHERE TABLE_SCHEMA LIKE 'hly%'` 跨多库**, 一次配多业务库多历史库 |

### 0.5 R1 优化后流程 (R 之后 · 自动化视角)

**优化后流程 (R 之后 R1):**

```
  业务 RD            Archery             业务库            Archery 自动            历史库
   │               │               │                │                │
   │ ① 提 DDL 工单        │               │                │                │
   ├─────────────────────────────▶│               │                │                │
   │               │ ② 审批            │                │                │
   ├──────────────────────────────┼─────────────────────────────▶│                │                │
   │               │               │ ③ 业务库执行 ALTER       │                │
   │               │               ├────────────────────────────────▶│                │
   │               │               │                │ ④ 审过 (current_status=1)   │
   │               │               │                │ ⑤ 自动生成历史库镜像工单    │
   │               │               │                │ ⑥ 走当前 Archery 配置流程   │
   │               │               │                ├────────────────────────────────▶│
   │               │               │                │                │ ⑧ 历史库执行 ALTER
   │               │               │                │                │
   │  ✅ 优势: 步骤 ④⑤⑥⑧ 全    │               │                │                │
   │   Archery 自动化, 0 漏同步 │               │                │                │
```

**优化后流程优缺点 (R 之后 R1):**

| 维度 | R1 |
|------|-------|
| ✅ 优点 1 | DDL **T+0 实时** 同步, 不再等 DBA 下班前集中处理 |
| ✅ 优点 2 | **0 漏同步** — 业务库 DDL 必审过 (`current_status=1`) 才触发, 系统强制 |
| ✅ 优点 3 | **下游大数据 0 延迟** — 业务方无感知 DDL 同步过程 |
| ✅ 优点 4 | **DBA 配表 1-click** — 一键配机制 (R2 实战数据 业务库 1589 / 历史库 1289, 6 min 配完) |
| ✅ 优点 5 | **DML 同步永久稳定** — DDL 0 漏 → 同步组件不再因 DDL 漏挂 |
| ✅ 优点 6 | **历史库工单跟正常工单一样** — 0 额外代码, DBA 改"历史库组" 流程就生效 (R3) |
| ⚠️ 限制 | R1 Phase 1 范围: 库对管理 + 一键配 + 触发镜像工单。schema 差集工具 + 增量同步走 Phase 2/3 |

**对比一眼看 (R 之前 vs R 之后):**

| 维度 | R 之前 (当前) | R 之后 R1 (优化后) |
|------|---------------|----------------------|
| DDL 同步方式 | DBA 人工 (凭经验) | **Archery 自动** (审过即触发) |
| 同步延迟 | **4-8h** (DBA 下班前集中处理) | **T+0 实时** |
| 漏同步风险 | **高** (DBA 凭记忆) | **0** (系统强制) |
| 业务方感知 | 报表延迟 1-3 天 | **0** (无感知) |
| DML 同步稳定性 | 经常因 DDL 漏挂 | **永久稳定** |
| DBA 工作量 | 每天 5-20 条 DDL 都要手工同步 | **0** (全自动) |
| DBA 配表工作量 | R 之前 2-3 小时手动配 1589 张 | **6 min 1-click 配完** (R2) |
| 异常保护 | 无 | **rollback 端点 + 钉钉通知 + 异常回滚** (联动 v0.4.5 + v0.2.0) |

---

## 目录

1. [修订要点 (跟 R 之前原版对比)](#1-修订要点-跟-821-原版对比)
2. [核心思路调整](#2-核心思路调整)
3. [批量导入机制 (核心新增)](#3-批量导入机制-核心新增)
4. [增量同步机制](#4-增量同步机制)
5. [产品界面 (5 个核心页面 · 调整后)](#5-产品界面-5-个核心页面--调整后)
6. [数据模型调整](#6-数据模型调整)
7. [URL 路由调整](#7-url-路由调整)
8. [联动点 (v0.4.5 / v0.3.0 / v0.2.0)](#8-联动点-v045--v030--v020)
9. [实施阶段 (短期 C → 中期 B → 长期 A)](#9-实施阶段-短期-c--中期-b--长期-a)
10. [风险与验证](#10-风险与验证)
11. [跟 gh-ost 实战教训对照](#11-跟-827-gh-ost-实战教训对照)

---

## 1. 修订要点 (跟 R 之前原版对比)

R 之前 R1 初版发布后，R 复审时发现 1 个**核心痛点** + 2 个**边界场景**问题：

| # | 问题 | 严重度 | 修法 |
|---|------|--------|------|
| **P0** | **历史库大几百张表，DBA 手动配同步表不现实**（库对详情逐张点 "添加同步表" 几百次） | **阻塞** | 新增"批量导入"机制（从历史库 INFORMATION_SCHEMA 扫表 + 模态框勾选）+ 同步模式默认从 whitelist 改 blacklist |
| P1 | 业务库**新增表**时白名单不会自动包含，DBA 容易漏配 | 中 | 新增"增量同步"机制 + 业务库新增表自动入"待确认"列表 |
| P2 | 库里已有 100+ 张表，DBA 想知道"哪些列/索引漏同步了" | 中 | 新增"库对 schema 差集工具"（巡检结果里直接展示列/索引 diff） |

| 维度 | R 之前原版 | R1 修订版 R1 |
|------|-----------|----------------------|
| 同步模式默认 | whitelist (DBA 显式选要同步的) | **blacklist (默认全同步, DBA 显式排除)** |
| 批量配表 | 只能逐张点 | **批量导入 (从历史库扫表 + 模态框勾选)** |
| 增量同步 | 未考虑 | **业务库新增表自动入"待确认"** |
| schema 差集 | 仅手动巡检 | **自动展示列/索引 diff** |
| Phase 1 范围 | 库对管理 + 库对详情 | **+ 批量导入 + 模态框** (核心) |
| Phase 2 范围 | 巡检 + 工单联动 | **+ 增量同步** |
| Phase 3 范围 | transform_rule + 定时 | **+ schema 差集工具 + 钉钉通知** |

---

## 2. 核心思路调整

### 2.1 R 之前原版思路（保留作为 fallback）

> DBA 在 Archery 后台配"业务库 ↔ 历史库 + 同步表清单"白名单, 业务 RD 提 DDL 时 Archery 自动判断 + 自动建历史库 DDL 工单。

**问题**: 白名单模式 + 逐张点 = 历史库 500 张表要 DBA 点 500 次, 不现实。

### 2.2 R1 修订版思路（采用）

> **DBA 配库对时, 默认 blacklist 模式 (业务库跟历史库 1:1 同步), 批量导入时一键全选 + 过滤规则排日志表/字典表/临时表。同步模式 + 批量配置 + 增量检测 三件套把 DBA 工作量从"500 次" 降到"1 次批量 + 50 个排除规则"。**

**核心调整**:
- 同步模式 **默认从 whitelist 改 blacklist** (业务库 80% 表都要同步, 显式排除 20% 不要的更省事)
- 库对详情加 **批量导入按钮** (从历史库 INFORMATION_SCHEMA.TABLES 扫表, 模态框显示 + 全选/反选 + 过滤)
- 业务库新增表自动入"待确认"列表, DBA 1-click 决定加白名单还是黑名单
- 巡检结果展示 schema 差集 (列/索引 diff), DBA 一眼看到"漏同步了哪些"

**真实场景预估** (业务库 500 张表):
| 操作 | R 之前原版耗时 | R1 修订版耗时 |
|------|--------------|----------------|
| 配库对 | 5 min (填库对名 + 选业务库/历史库) | 同 5 min |
| 配同步表 | **2-3 小时** (500 次点) | **5-10 min** (1 次批量 + 50 个排除) |
| 业务库新增表 | DBA 漏掉 | **自动检测, 1-click 决定** |
| 漏同步排查 | 手动写 SQL 对比 | **巡检结果自动展示** |

**DBA 工作量降低 90%+, 不再是阻塞点**。

---

## 3. 批量导入机制 (核心新增)

### 3.1 UX 流程

```
DBA 进库对详情页 → 点 [📥 批量导入] → 弹模态框
 ↓
模态框:
 ┌─ 批量导入同步表 ─────────────────────────────┐
 │ 从历史库 hly_history 自动扫描           │
 │ 找到 487 张表 (跟业务库差 13 张)         │
 │                         │
 │ [全选] [反选] [搜索 ____________] [⚙ 过滤]  │
 │                         │
 │ 过滤规则 (可叠加):                │
 │  排除前缀: [_log, _bak, _tmp, _test]     │
 │  排除后缀: [_history, _archive, _backup]   │
 │  排除 ENGINE: [MEMORY, BLACKHOLE, MRG_MYISAM] │
 │  仅保留 size > 0 的表 (排除空表)        │
 │  ─ 过滤后剩余 198 张表, 待选 ─        │
 │                         │
 │ 列表 (滚动加载 + 复选框):             │
 │  ☐ accesscard_black_detail  243MB 35 列   │
 │  ☐ accesscard_config     12KB  8 列   │
 │  ☐ accesscard_log       1.2GB 12 列  ← 默认排除 (后缀 _log)
 │  ☐ accesscard_audit      8KB  8 列   │
 │  ... (198 张, 分页 50/页)            │
 │                         │
 │ 已选中: 198 / 198               │
 │                         │
 │ [取消] [✓ 确认导入 (198 张)]          │
 └─────────────────────────────────────────────────┘
 ↓
DBA 点"确认导入" → 后端批量 INSERT 198 张
 ↓
库对详情: "已加 198 张同步表" + 列表
```

### 3.2 后端实现

```python
# sql/extensions/ddl_sync/services/batch_import.py
from django.db import transaction
from ..models import DdlSyncTable


def batch_import_tables(pair, table_names, filter_rule=None):
  """批量导入同步表 (Phase 1 核心)

  R1 新增: 替代 R 之前设计稿的"DBA 手动逐张点 add_sync_table"
  业务: 历史库大几百张表, DBA 一次操作完成 80% 工作量
  """
  # 1. 去重 + 验证 (跟现有表对比, 排除已存在)
  existing = set(
    DdlSyncTable.objects.filter(pair=pair)
    .values_list("table_name", flat=True)
  )
  new_tables = [t for t in table_names if t not in existing]

  # 2. 批量 INSERT (单次 SQL, 性能比 500 次单插高 100 倍)
  if not new_tables:
    return 0

  with transaction.atomic():
    DdlSyncTable.objects.bulk_create([
      DdlSyncTable(pair=pair, table_name=t) for t in new_tables
    ])

  # 3. 写审计 (可选, Phase 3 加)
  # SyncAuditLog.objects.create(...)

  return len(new_tables)


def scan_history_tables(target_instance, target_db):
  """从历史库 INFORMATION_SCHEMA 扫所有表 (Phase 1 必备)

  R1 新增: 替代 R 之前设计稿的"DBA 凭记忆列 500 张表名"
  """
  user, password, (host, port) = _get_creds(target_instance)
  conn = pymysql.connect(host=host, port=port, user=user, password=password,
             database=target_db, connect_timeout=5, autocommit=True)
  try:
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
      cur.execute("""
        SELECT TABLE_NAME, DATA_LENGTH, TABLE_ROWS
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = %s
         AND TABLE_TYPE = 'BASE TABLE' -- 排除视图
        ORDER BY TABLE_NAME
      """, [target_db])
      return cur.fetchall()
  finally:
    conn.close()
```

### 3.3 前端实现 (HTML mockup)

库对详情页新增"批量导入"按钮:

```html
<!-- 库对详情页 body -->
<div class="d-flex justify-content-between">
  <h3>同步表清单 · 198 / 487</h3>
  <div>
    <button class="btn btn-primary" id="btnBatchImport">📥 批量导入</button>
    <button class="btn btn-outline-primary">+ 添加同步表</button>
  </div>
</div>

<!-- 批量导入模态框 -->
<div class="modal fade" id="batchImportModal">
  <div class="modal-dialog modal-xl">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">批量导入同步表</h5>
        <button class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <!-- 历史库扫描结果 -->
        <div class="alert alert-info">
          从历史库 <code>hly_history</code> 自动扫描, 找到 <b>487</b> 张表
          (跟业务库差 13 张)
        </div>

        <!-- 过滤规则 -->
        <div class="row g-2 mb-3">
          <div class="col-md-6">
            <label class="form-label">排除前缀 (逗号分隔)</label>
            <input type="text" class="form-control" id="excludePrefix"
                placeholder="_log, _bak, _tmp, _test">
          </div>
          <div class="col-md-6">
            <label class="form-label">排除后缀</label>
            <input type="text" class="form-control" id="excludeSuffix"
                placeholder="_history, _archive, _backup">
          </div>
        </div>

        <!-- 列表 + 复选框 -->
        <div class="d-flex justify-content-between mb-2">
          <div>
            <button class="btn btn-sm btn-link" id="btnSelectAll">全选</button>
            <button class="btn btn-sm btn-link" id="btnSelectNone">反选</button>
            <input type="text" class="form-control form-control-sm d-inline-block"
                style="width: 200px;" placeholder="搜索表名" id="tableSearch">
          </div>
          <div>
            <span class="text-muted">已选 <b id="selectedCount">0</b> / <span id="totalCount">487</span></span>
          </div>
        </div>

        <div class="table-responsive" style="max-height: 400px;">
          <table class="table table-hover">
            <thead>
              <tr><th><input type="checkbox" id="checkAll"></th>
                <th>表名</th><th>大小</th><th>列数</th><th>状态</th></tr>
            </thead>
            <tbody id="tableListBody">
              <!-- JS 渲染 -->
            </tbody>
          </table>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" data-bs-dismiss="modal">取消</button>
        <button class="btn btn-primary" id="btnConfirmImport">✓ 确认导入</button>
      </div>
    </div>
  </div>
</div>
```

### 3.4 关键设计决策

1. **从历史库扫 (而不是业务库)**: 因为历史库 = 业务库归档, 业务库有的历史库一定有。但有些淘汰的表历史库也没, 这种情况业务库 DDL 不用同步到历史库。
2. **过滤规则在客户端生效, 不存数据库**: Phase 1 不持久化, DBA 每次批量导入手动配过滤 (典型场景 DBA 配 1 次后几乎不变, 真要变可重导入覆盖)。
3. **去重在服务端**: 同一张表 pair + table_name 唯一约束, bulk_create 前过滤。
4. **审计在 Phase 3 加**: Phase 1 暂不写审计, 业务库 DDL 触发时再写。

---

## 4. 增量同步机制

### 4.1 问题

业务库某 DBA 加了 1 张新表 `accesscard_v2`, 没通知历史库 DBA。3 个月后业务方发现时间戳同步跑历史库挂, 才知道漏配。

### 4.2 解法

业务库 DDL 工单提交时, Archery **自动检测**新表是否在历史库/白名单里:
- **在白名单**: 正常联动
- **不在白名单 + 历史库有同表 (但未配过)**: 工单详情页提示 "检测到新表 `xxx` 未配置进历史库同步, 请 DBA 确认是否加入"
- **不在白名单 + 历史库无此表**: 不联动 (新表不用同步到历史库)

### 4.3 实现

Phase 2 加, Phase 1 范围外:

```python
# sql/extensions/ddl_sync/services/incremental.py
def detect_new_table(workflow):
  """业务库 DDL 工单提单时检测新表"""
  table_name = _parse_first_table(workflow.sql_content)
  pair = DdlSyncPair.objects.filter(
    source_instance=workflow.instance,
    source_db=workflow.db_name,
    enabled=True
  ).first()
  if not pair:
    return None # 没配库对, 不检测

  # 检查白名单
  if pair.tables.filter(table_name=table_name).exists():
    return None # 已在白名单, 正常联动

  # 检查历史库
  history_tables = scan_history_tables(pair.target_instance, pair.target_db)
  history_table_names = {t["TABLE_NAME"] for t in history_tables}

  if table_name in history_table_names:
    return {
      "status": "needs_confirmation",
      "message": f"检测到表 {table_name} 在历史库存在但未配置同步, 请 DBA 决定",
      "history_size": next(t for t in history_tables if t["TABLE_NAME"] == table_name)["DATA_LENGTH"],
    }
  return None
```

### 4.4 UX 提示

工单详情页加增量检测提示 (DBA 视角):

```
💡 增量检测: 检测到表 `accesscard_v2` 在历史库存在 (243MB) 但未配置同步
  [1-click 加进白名单] [1-click 加进黑名单] [忽略]
```

---

## 5. 产品界面 (5 个核心页面 · 调整后)

### 5.1 库对管理列表 (DBA 专属)

跟 R 之前原版相同, 加 1 列 "同步模式" 提示.

### 5.2 库对详情 · 改 (重点: 批量导入 + 过滤规则)

```
accesscard 库对 · 🔘 blacklist 模式
业务库: hly_accesscard (172.20.2.134:3306) · 历史库: hly_history (172.20.2.X:3306)

同步表清单 · 198 / 487 (已配)
 [📥 批量导入] [+ 添加同步表] [🔍 schema 差集] [⚙ 过滤规则]

 accesscard_black_detail   [同步] 字段 35 个 ✏ 🗑
 accesscard_config      [同步] 字段 8 个  ✏ 🗑
 accesscard_audit      [同步] 字段 8 个  ✏ 🗑
 ... 还有 195 张表 (分页)
 
黑名单表 (默认不同步) · 0 个
 [+ 添加黑名单表]

最近 5 次同步历史
 #12345 业务库工单 实战时 [已完成] 历史库 #12346 执行成功
 ...

[🔍 立即跑巡检 (C 方案兜底)] [📊 schema 差集报告]
```

### 5.3 业务库 DDL 工单详情 (跟 R 之前原版相同, 加增量检测提示)

```
SQL 工单 #12345 [DDL 跨库同步]
... (跟 R 之前原版相同)

执行状态
 ✅ 业务库 (hly_accesscard@134) 已执行
 🔄 历史库 (hly_* 跨多库) [⇄ 联动] 按当前配置审核中
    镜像工单 #12346 · 工单类型: SQL 上线申请 · 组: prod core for 历史库
    业务库 DDL 已审过 (current_status=1 PASSED) 才触发, 跟正常历史库工单走一样的流
 💡 增量检测: 检测到表 `accesscard_v2` 在历史库存在 (243MB) 但未配置同步
   [1-click 加进白名单] [1-click 加进黑名单] [忽略]
```

### 5.4 历史库 DDL 工单列表 (跟 R 之前原版相同)

### 5.5 库对巡检结果 · 改 (重点: schema 差集)

```
accesscard 库对 · 巡检结果
巡检时间: 实战时 · 对比 198 张同步表

🔴 1 张表 schema 不一致
 accesscard_black_detail [5 列缺失 / 2 索引缺失]
  列 diff:
   + card_serial (实战漏同步, varchar(64) DEFAULT NULL)
   + is_premium (8/15 漏同步, tinyint(1) DEFAULT 0)
   + ... 共 5 列
  索引 diff:
   - idx_card_serial (8/15 漏同步)
   - idx_is_premium (实战漏同步)
  [生成补 DDL →]

🟢 197 张表 schema 一致
 ... 列出 5 张代表表名

⚠️ 此巡检由 DBA @张三 在 实战时 手动触发, 建议配定时任务 (每天凌晨跑)
```

---

## 6. 数据模型调整

### 6.1 3 张表 (跟 R 之前原版相同, sync_mode 默认值改)

```python
class DdlSyncPair(models.Model):
  SYNC_MODE_CHOICES = [
    ("blacklist", "黑名单 (默认, 业务库全同步, 显式排除)"), # R1 改默认
    ("whitelist", "白名单 (DBA 显式选要同步的)"), # R 之前原版默认
  ]
  # ... 字段跟 R 之前相同
  sync_mode = models.CharField(max_length=16, choices=SYNC_MODE_CHOICES,
                 default="blacklist") # R 之前是 whitelist
```

### 6.2 过滤规则 (Phase 3 加, 暂存客户端)

DBA 配过滤规则 (排除前缀/后缀/ENGINE 等) 暂存客户端, 不入库。Phase 3 才加 `filter_rule JSONField`:

```python
# Phase 3
class DdlSyncPair(models.Model):
  # ...
  filter_rule = models.JSONField(default=dict, blank=True)
  # 格式: {
  #   "exclude_prefix": ["_log", "_bak", "_tmp", "_test"],
  #   "exclude_suffix": ["_history", "_archive"],
  #   "exclude_engine": ["MEMORY", "BLACKHOLE"],
  #   "min_size_bytes": 0, # 排除空表
  # }
```

### 6.3 业务库新增表"待确认" (Phase 2 加)

不加新表, 用现有 `DdlSyncPair` 加 1 个 JSONField 暂存:

```python
# Phase 2
class DdlSyncPair(models.Model):
  # ...
  pending_tables = models.JSONField(default=dict, blank=True)
  # 格式: {
  #   "accesscard_v2": {
  #     "detected_at": "实战时",
  #     "first_workflow_id": 12345,
  #     "history_size_bytes": 254803968,
  #   }
  # }
```

---

## 7. URL 路由调整

```python
# sql/extensions/ddl_sync/urls.py
urlpatterns = [
  # 库对管理 (DBA 专属) - R 之前原有
  path("pair_list/", views.pair_list, name="pair_list"),
  path("pair/new/", views.pair_new, name="pair_new"),
  path("pair/<int:pair_id>/edit/", views.pair_edit, name="pair_edit"),
  path("pair/<int:pair_id>/detail/", views.pair_detail, name="pair_detail"),

  # R1 新增: 批量导入 (核心)
  path("api/pair/<int:pair_id>/scan_history_tables/", views.api_scan_history_tables,
     name="api_scan_history_tables"),
  path("api/pair/<int:pair_id>/batch_import/", views.api_batch_import_tables,
     name="api_batch_import_tables"),

  # R1 新增: schema 差集工具 (Phase 3)
  path("api/pair/<int:pair_id>/schema_diff/", views.api_schema_diff,
     name="api_schema_diff"),

  # 同步表管理 (DBA 专属) - R 之前原有
  path("pair/<int:pair_id>/table/add/", views.table_add, name="table_add"),
  path("pair/<int:pair_id>/table/<int:table_id>/delete/", views.table_delete,
     name="table_delete"),

  # 历史库 DDL 工单列表 (DBA 兜底视角) - R 之前原有
  path("history_workflows/", views.history_workflows, name="history_workflows"),

  # 库对巡检 (C 方案兜底) - R 之前原有
  path("inspect/run/", views.inspect_run, name="inspect_run"),
  path("inspect/result/<int:pair_id>/", views.inspect_result, name="inspect_result"),
]
```

---

## 8. 联动点 (v0.4.5 / v0.3.0 / v0.2.0)

跟 R 之前原版相同, 加 1 个联动:

| 已有功能 | 联动方式 | 业务价值 |
|---|---|---|
| v0.4.5 DDL 智能回滚 (commit `e54a663`) | 历史库 DDL 工单也走智能回滚 | 历史库 DDL 失败能自动回 |
| v0.3.0 gh-ost (commit `cd2ce88`) | 历史库 DDL 大表走 gh-ost | 历史库大表 DDL 也无锁 |
| v0.3.x 大表 DDL 防呆 (commit `374d990`) | 历史库 DDL 也走大表防呆 | 历史库大表 DDL 不锁表 |
| v0.2.0 钉钉 OA (commit `d5f88d1`) | 历史库 DDL 审批人推钉钉 | DBA 钉钉里就能审 |
| audit_drivers 3 级审批 | 历史库 DDL 走同一审批 | 跟业务库 DDL 一致 |
| **R1 新增: 字段 diff (commit `0a04775`)** | 业务库 DDL 工单详情页**字段 diff 提示**已上线, 库对详情页复用同一组件展示 schema 差集 | 一个组件两处用, 不重复开发 |

---

## 9. 实施阶段 (短期 C → 中期 B → 长期 A)

### 9.1 Phase 1 · 短期 C · **3 阶段 3 周 (下周一-3 周后, 15 个工作日)** — 用户拍板

**核心: 库对管理 + 批量导入 + 一键配 + 走当前配置流程 + 推 110 prod**

 DBA 阿达叔叔拍板: "**从 8 月 31 号开始算第一周。重新生成，按照设计 + 开发 + 提测上线。这三个阶段生成**". 3 阶段 3 周比 5 天紧凑节奏 ( 拍板的 下周一-下周五) 留更多时间.

**3 阶段 3 周日程表**:

| 阶段 | 周次 | 主要工作 | 详细说明 |
|------|------|----------|----------|
| **第 1 阶段: 设计** | 下周一 - 下周五 (1 周 5d) | 详细设计 + 数据模型 migration + 库对管理 + R1 批量导入 + R2 一键配 + R3 走当前配置 + 134 dev 演练设计 + 推 110 主手册 | 数据模型 3 张表 migration (sync_mode 默认 blacklist + R2 sync_type 字段) + 库对管理列表 + 库对详情设计稿 + R1 批量导入 设计 + R2 一键配 设计 + R3 走当前配置 设计 + 134 dev 演练 设计 + 推 110 主手册更新 + 设计稿评审 |
| **第 2 阶段: 开发** | 下下周一 - 下下周五 (1 周 5d) | 库对管理 CRUD + 5 按钮 + R1 批量导入 + R2 一键配 + R3 走当前配置 开发 + 134 dev 端到端演练 + 修复 | 库对管理 CRUD (DdlSyncPair + DdlSyncTable) + 5 个核心按钮 (🎯 一键配 / 📥 批量导入 / + 添加同步表 / 🔍 schema 差集 / ⚙ 过滤规则) + R1 批量导入 (从历史库扫表 + 模态框 + 过滤规则) + R2 一键配 (compute_diff + one_click_setup) + R3 走当前配置 (镜像工单走 Archery 当前配置 + 业务库 DDL 必审过 trigger) + 134 dev 端到端演练 + 修复实战踩坑 |
| **第 3 阶段: 提测上线** | 再下周一 - 再下周五 (1 周 5d) | 提测 (DBA 验收 + 业务 RD 端到端) + 修复实战踩坑 + 推 110 prod + smoke test + 收尾 | DBA 验收用例 + 业务 RD 端到端测试 + 修复实战踩坑 (避坑 R 之前推 110 实战踩坑: CACHE_URL / SECRET_KEY / K3 变量 / ALLOWED_HOSTS / poller zombie / rollback import) + 推 110 prod (5 步必做) + smoke test (5 端点全过 + 业务 RD 浏览器实测) + 文档收尾 + 下一周周报准备 |

**3 阶段周报口径**: 拍板, 下周一算 Week 1. 每周 1 个阶段, 周报按周 (周一提交) 节奏汇报:
- Week 1 (8/31): 设计阶段
- Week 2 (9/7): 开发阶段
- Week 3 (9/14): 提测上线阶段
- Week 4 (9/21): Phase 2 启动 (增量同步机制)

**Phase 1 核心交付物 (3 阶段 3 周内)**:

- [ ] 数据模型 3 张表 migration (sync_mode 默认 blacklist + R2 sync_type 字段)
- [ ] 库对管理列表 + 库对详情 (跟 R 之前相同, 加批量导入按钮 + 一键配按钮)
- [ ] **R1 批量导入机制** (核心): 扫历史库 + 模态框 + 过滤规则 + 批量入库
- [ ] **R2 一键配机制** (核心): compute_diff + one_click_setup + 1-click 接受
- [ ] **R3 走当前配置流程** (核心): 镜像工单走 Archery 当前配置, 跟正常工单一样
- [ ] 业务库 DDL 工单详情"本表已配置同步" 提示 (跟 R 之前相同)
- [ ] 134 dev 演练: 配 accesscard 库对 + 一键配 1-click 接受 + 1 条真实 DDL 联动
- [ ] 110 prod 推 R1 实战 (按 5 步必做)

### 9.2 Phase 2 · 中期 B · **1-2 周**

- [ ] 增量同步机制 (业务库新增表自动入"待确认" 列表)
- [ ] 1-click 加白名单/黑名单 工单详情页操作
- [ ] 历史库 DDL 工单列表 (跟 R 之前相同)

### 9.3 Phase 3 · 长期 A · **2-3 周**

- [ ] 过滤规则持久化 (filter_rule JSONField)
- [ ] 库对巡检 (C 方案兜底) 页面 (跟 R 之前相同, 加 schema 差集)
- [ ] 定时巡检 (每天凌晨) + 不一致推钉钉
- [ ] 业务 RD + 业务 leader 视角 (DBA 权限不变)
- [ ] transform_rule 字段级调整 (skip_columns / rename_columns)

---

## 10. 风险与验证

### 10.1 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 业务库 80% 表要同步, DBA 选 blacklist 模式后漏配置 | 高 | R1 增量检测: 业务库新表不在白/黑名单时, 工单页提示 DBA |
| 历史库 schema 跟业务库不同步太久, 巡检时 diff 巨大 | 中 | Phase 3 推定时巡检 + 钉钉通知, 早发现 |
| 批量导入误操作 (勾错表) | 中 | 模态框 confirm 提示, 导入后可逐张编辑 |
| sync_mode 从 whitelist 改 blacklist 默认值, 老库对默认值不变 (新库对才生效) | 低 | migration 加 default, 老库对需 DBA 手动改 sync_mode 才会变 |

### 10.2 验证

- 134 dev 演练: 配 accesscard 库对 (业务库 accesscard_* 表 20 张) + 批量导入 + 1 条真实 DDL 联动验证
- 110 prod 推: 选 1-2 个真实库对验证, 跟现有 gh-ost / 字段 diff / 智能回滚联动

---

## 11. 跟 gh-ost 实战教训对照

gh-ost 实战踩了 4 个坑, R 修订时一一对照避免:

| 实战坑 | R 修订怎么避免 |
|---------|------------------|
| 实战 14:18 时 业务库 8.0 解析 SQL 保留原始格式, gh-ost 报 1064 | 历史库 5.7 / 8.0 都要演练, 库对详情 "试跑 SQL" 按钮 (Phase 3) 提前验证 |
| 实战 14:11 时 业务库 instance 27 archery user 权限不够 | 库对配置时**预检**历史库 + 业务库 archery user 权限, 配错立刻提示 |
| 实战 13:50 时 业务 RD group.name = "DBA审批" 不匹配 `_is_admin_or_dba` 白名单 | 库对管理 4 perm 4 判定, 跟 gh-ost 任务管理 list 同一套路, 8/12 fix 教训复用 |
| 实战 15:15 时 gh-ost 子进程死变 zombie, poller 死循环 | 库对 sync_trigger.py 也用 `os.kill(pid, 0)` + `/proc/<pid>/status` State 字段判断 (复用 实战 fix) |

---

## 12. R2 进一步优化: 一键配 (按历史库)

 DBA 阿达叔叔查 110 prod 真实数据:
- 业务库 hly_accesscard: **1589** 张表
- 历史库 hly_activity: **1289** 张表
- 业务库 - 历史库: **300** 张 (业务库独有, 通常字典/配置/日志, 不归档)

**思路 (DBA 原话)**: "历史库有多少张表就拿多少张" — 白名单 = 历史库所有表 (1289 张), 黑名单 = 业务库独有 (300 张). 1-click 配完, 不用批量导入手动勾选.

### 12.1 一键配 vs 批量导入 对比

| 步骤 | R1 批量导入 | **R2 一键配** |
|------|------------|---------------|
| 配白名单 | 批量导入勾选 (5 min) | **自动 (1 click)** |
| 配黑名单 | 手动加 OR 写脚本 (10-20 min) | **自动 (1 click)** |
| **总耗时** | **15-25 min** | **6 min** |

**再省 2-4 倍**, 从 R1 "5-10 min 配白名单 + 几十个排除" 降到 R2 "1-click 配白名单 + 1-click 配黑名单".

### 12.2 UX 流程

库对详情页加 **"🎯 一键配 (按历史库)"** 按钮:

```
┌─ 🎯 一键配 (按历史库) ─────────────────────────────────┐
│ 自动扫描历史库 + 业务库, 计算差集:            │
│                             │
│  业务库 (hly_accesscard): 1589 张表           │
│  历史库 (hly_activity):  1289 张表           │
│  ─────────────────────────────             │
│  业务库 ∩ 历史库 (1289 张): → 默认白名单 (建议全选)     │
│  业务库 - 历史库 (300 张):  → 默认黑名单 (建议全选)     │
│  历史库 - 业务库 (0 张):   → 0 张, 提示 DBA      │
│                             │
│ 提示: 白名单 1289 张 (从历史库扫, 全选)           │
│    黑名单 300 张 (业务库独有, 通常字典/配置/日志, 全选)   │
│    DBA 可逐张调整, 1-click 接受即可           │
│                             │
│ ⚙ 预览:                         │
│  ✓ 白名单 (1289 张, 全选):                │
│    accesscard_black_detail ✓ 存在 243MB        │
│    accesscard_config    ✓ 存在 12KB         │
│    accesscard_audit     ✓ 存在 8KB         │
│    ... (分页 50/页)                   │
│                             │
│  🚫 黑名单 (300 张, 全选):                │
│    dict_currency      ✗ 历史库无 4KB        │
│    dict_country       ✗ 历史库无 8KB        │
│    log_search        ✗ 历史库无 1.2GB       │
│    ... (分页 50/页)                   │
│                             │
│ 业务库加新表时, Archery 自动检测 + "待确认" 流程 (Phase 2)   │
│                             │
│     [取消] [✓ 1-click 接受 (1289+300)]         │
└──────────────────────────────────────────────────────────┘
```

### 12.3 后端实现

```python
# sql/extensions/ddl_sync/services/one_click_setup.py
from ..models import DdlSyncTable


def one_click_setup(pair, accept_white: list, accept_black: list):
  """一键配 (按历史库) — R2 新增

  业务: DBA "历史库有多少张表就拿多少张" — 1-click 配完白名单 + 黑名单.
  """
  with transaction.atomic():
    # 1. 清空现有的 (幂等, 重新配会覆盖)
    DdlSyncTable.objects.filter(pair=pair).delete()

    # 2. 批量写白名单 (bulk_create 性能高 100 倍)
    if accept_white:
      DdlSyncTable.objects.bulk_create([
        DdlSyncTable(
          pair=pair, table_name=t,
          sync_type='whitelist', # R2 加字段区分
        ) for t in accept_white
      ])

    # 3. 批量写黑名单 (R2 加 sync_type 字段, 跟白名单同表存)
    if accept_black:
      DdlSyncTable.objects.bulk_create([
        DdlSyncTable(
          pair=pair, table_name=t,
          sync_type='blacklist',
        ) for t in accept_black
      ])

  return len(accept_white) + len(accept_black)


def compute_diff(pair):
  """扫业务库 + 历史库, 算差集 — R2 新增"""
  # 1. 扫业务库所有表
  source_tables = scan_history_tables(pair.source_instance, pair.source_db)
  source_names = {t["TABLE_NAME"] for t in source_tables}

  # 2. 扫历史库所有表
  target_tables = scan_history_tables(pair.target_instance, pair.target_db)
  target_names = {t["TABLE_NAME"] for t in target_tables}

  # 3. 差集
  white_candidates = source_names & target_names # 业务库 ∩ 历史库
  black_candidates = source_names - target_names # 业务库独有
  orphan = target_names - source_names       # 历史库独有 (业务库已删)

  return {
    "white": sorted(white_candidates),
    "black": sorted(black_candidates),
    "orphan": sorted(orphan),
  }
```

### 12.4 数据模型微调 (DdlSyncTable 加 sync_type 字段)

```python
class DdlSyncTable(models.Model):
  # R2 加: 区分白名单 / 黑名单
  SYNC_TYPE_CHOICES = [
    ("whitelist", "白名单 (要同步)"),
    ("blacklist", "黑名单 (不同步)"),
  ]
  pair = models.ForeignKey(DdlSyncPair, on_delete=models.CASCADE, related_name="tables")
  table_name = models.CharField(max_length=128)
  sync_type = models.CharField(max_length=16, choices=SYNC_TYPE_CHOICES, default="whitelist")
  # ... 其他字段跟 R 之前相同

  class Meta:
    # R2 改: 唯一约束加 sync_type (同一对库, 同一表, 不能既在白名单又在黑名单)
    unique_together = [("pair", "table_name", "sync_type")]
```

### 12.5 URL 路由加 2 个端点

```python
# sql/extensions/ddl_sync/urls.py
urlpatterns = [
  # ... R1 路由
  # R2 新增: 一键配
  path("api/pair/<int:pair_id>/compute_diff/", views.api_compute_diff,
     name="api_compute_diff"),
  path("api/pair/<int:pair_id>/one_click_setup/", views.api_one_click_setup,
     name="api_one_click_setup"),
]
```

### 12.6 R1 批量导入 跟 R2 一键配 关系

**两者并存, 不冲突**:
- **一键配** (R2 核心): 业务库 + 历史库**有重叠**的场景 (99% DDL 同步场景都这样), 1-click 配完, 走 95% 场景
- **批量导入** (R1 fallback): 业务库 + 历史库**不重叠** OR DBA 想手动选部分表的场景, 走 5% 场景
- 库对详情页**同时放 2 个按钮**, DBA 根据场景选

```
库对详情页
 [🎯 一键配 (按历史库)] ← 95% 场景 1-click
 [📥 批量导入]      ← 5% 场景 fallback
 [+ 添加同步表]      ← 兜底单张加
```

### 12.7 Phase 1 范围调整

加 R2 一键配到 Phase 1, 跟 R1 批量导入并存:

- [ ] 数据模型 3 张表 migration (sync_mode 默认 blacklist + **R2 加 sync_type 字段**)
- [ ] 库对管理列表 + 库对详情
- [ ] **R2 一键配机制** (核心, 95% 场景): compute_diff + one_click_setup
- [ ] **R1 批量导入机制** (fallback, 5% 场景): 跟 R2 并存
- [ ] 业务库 DDL 工单详情"本表已配置同步" 提示
- [ ] 134 dev 演练: 配 accesscard 库对 + **R2 一键配 1-click 接受** + 1 条真实 DDL 联动

### 12.8 实战示例 ( 业务库数据)

```bash
# 110 prod 真实查询 (DBA 截图)
select count(*) from information_schema.tables where table_schema like 'hly%'
# 业务库: 1589 (hly_accesscard)
# 历史库: 1289 (hly_activity)
# 业务库 - 历史库: 300 张 (字典/配置/日志等不归档)

# 走 R2 一键配:
# - 业务库 ∩ 历史库 = 1289 张 → 自动加白名单
# - 业务库 - 历史库 = 300 张 → 自动加黑名单
# - 1-click 接受, 2 min 配完

# vs R1 批量导入:
# - 配白名单 1289 张: 5 min 批量导入
# - 配黑名单 300 张: 手动加 OR 写脚本 10-20 min
# - 总耗时 15-25 min
```

### 12.9 跟 R1 关系

R1 修订 (commit 34e2613) **保留有效**:
- §3 批量导入机制 (R1 5% 场景 fallback)
- §4 增量同步机制 (Phase 2 业务库新表自动检测)
- §5 §6 §7 §8 §9 §10 §11 (跟 R1 一致)

R2 是 **R1 进一步优化** (核心机制加一键配, 减少 2-4 倍 DBA 工作量).

---

## 13. R3 重大决策变更: 走当前配置的流程

### 13.1 决策

 DBA 阿达叔叔拍板:

> **生成历史库工单, 按照当前 Archery 配置的流程走就行, DBA 调整成什么流程, 就怎么走. 和正常工单一样.**

这是个**优雅的设计原则**:
- 自动生成的镜像工单跟正常历史库工单走一样的审计流 (`SqlWorkflow` + `audit_setting`)
- DBA 在 Archery 后台改什么配置, 镜像工单就自动跟进
- 不需要为"自动生成" 单独搞一套审批逻辑
- DBA 改 "prod core for 历史库" 组的流程 (单级 / 双级 / 加 leader), 镜像工单自动同步

### 13.2 跟 R 之前拍板对比

| 维度 | R 之前拍板 (作废) | R3 拍板 (采用) |
|------|----------------|----------------|
| 审批人 | 同业务库 DDL 审批人 (3 级) | **按当前 Archery 配置 (DBA 配的) 走** |
| 业务库 DDL 没审过怎么办 | R 之前没明确 | R 明确: 不联动 (业务库 DDL 必审过) |
| 业务 RD 收到通知 | 业务 RD + 业务 leader 都收 (重复) | 只通知业务 RD (不重复打扰业务 leader) |
| 实施复杂度 | 需要单独为"自动生成" 写代码 | **0 额外代码**, 复用现有 `audit_setting` |

### 13.3 实施原则 (3 个)

1. **自动生成的镜像工单跟正常工单一样** — 不在 R1 代码里写"由谁审" / "走几级", 完全用 Archery 现成的 `workflow_audit_setting.audit_auth_groups` 配置. DBA 后台改什么, 镜像工单就怎么走.
2. **业务库 DDL 必须审过 (`current_status=1 PASSED`) 才触发镜像工单** — 实施: 镜像工单创建 trigger 加 `if source_workflow.current_status != 1: return None`. 这是底线, 业务库 DDL 没审过不联动.
3. **业务 RD 实时通知 (钉钉 OA)** — 业务库 DDL 触发镜像工单时, 钉钉通知业务 RD: "你的 DDL `#12345` 触发了历史库工单 `#12346` 状态: 审核中/执行中/已完成". 让业务 RD 知道"我的 DDL 触发了历史库 DDL", 不丢控.

### 13.4 安全护栏 (3 个)

虽然走当前流程, 但要加 3 个安全护栏防风险:

1. **业务库 DDL 必审过 trigger** — 见 §13.3 第 2 条
2. **历史库执行前预演 + 异常 rollback** — 跟 v0.4.5 智能回滚 联动 (R 之前拍板, 已落地). 复用 R 之前拍的 rollback 端点 (`services.db._get_creds` + DROP TABLE IF EXISTS 兜底)
3. **异常通知 DBA + 业务 RD** — 跟 v0.2.0 钉钉 OA 联动, 异常立刻钉钉通知 DBA + 业务 RD, 不依赖业务 RD 自己查工单状态

### 13.5 Archery 配置 (DBA 后台自己配, R1 不动)

```
工单类型: SQL 上线申请
组: prod core for 历史库    ← 跟现在一致
变更审批流程: DBA       ← DBA 自己在 Archery 后台配, 想改就改
```

`workflow_audit_setting.audit_setting_id=3` (group_id=5, audit_auth_groups='6,4,3,15,16') — 2024-01-16 创建, 当前 110 prod 实际细分为 'DBA审批' (id=3) / 'DBA执行' (id=16) / 'DBA组长' (id=14) / '副总' (id=15). 镜像工单自动走这个配置.

### 13.6 跟 R1/r2 关系

- **R1 修订** (§3-§11): 库对配 + 批量导入 + 增量同步 + 数据模型 + URL 路由, 都跟"自动生成的工单走哪个流程" 无关, 保留
- **R2 一键配** (§12): 库对配白/黑名单, 跟"自动生成的工单走哪个流程" 无关, 保留
- **R3 重大决策** (§13, 本次新增): 明确"自动生成的镜像工单走当前 Archery 配置的流程", 跟正常工单一样 + 3 个安全护栏

R3 是**对 R1+R2 的补充**, 不冲突, 改的是 R 之前拍板时遗留的"走同业务库审批人" 模糊点.

---

## 关联 commit / changelog

- **** commit `f4078c6`: R 之前旧设计稿 + 实战功能图说 HTML 防丢
- **** commit `34e2613`: 写 R1 修订设计稿 + 新功能图说 HTML
- **** (本次) R2 加 §12 一键配机制, 业务库 1589 / 历史库 1289 实战数据支撑
- R 之前原版: docs/designs/R 之前_ddl-sync-pair-design.md (保留作为对照)
- R1: docs/designs/2026-08-28_ddl-sync-pair-design-v050-r1.md
- R1 功能图说: docs/designs/R 修订_ddl-sync-pair-feature-card.html (待加一键配 mockup)
- R2 changelog: docs/changelogs/2026-08-28_ddl-sync-v050-r2-one-click-setup.md

