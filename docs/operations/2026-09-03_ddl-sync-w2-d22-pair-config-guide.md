# DDL 跨库同步 · 库对配置操作说明 (D22)

> 适用版本: v0.5.0-alpha (commit `5f261e0` 及以后)
> 日期: 2026-09-03
> 受众: DBA 团队
> 配套 changelog: `docs/changelogs/2026-09-03_ddl-sync-w2-d22-mirror-target-group.md`

## 0. 为什么要有这个说明

D22 上线后, 库对配置页面多了一个**必填**字段: "镜像工单审批组" (target_group)。
不填会表单校验失败; 老库对没配的会有红色警示。
**镜像工单必须走历史库组审批流**, 不再走业务组。

## 1. 新建库对

### 步骤

1. 登录 Archery → 左侧菜单 "DDL 跨库同步" → "库对列表"
2. 点右上角 "新建库对" 按钮 → 进入 `/ddl_sync/pair/create/`
3. 填写字段:

| 字段 | 必填 | 说明 |
|------|------|------|
| 配对名 | 是 | DBA 自己起, 如 "accesscard 库对" |
| 业务库实例 | 是 | 业务库所在的 MySQL instance |
| 业务库名 | 是 | 业务库 schema, 如 `hly_accesscard` |
| 历史库实例 | 是 | 历史库所在的 MySQL instance |
| 历史库名 | 是 | 历史库 schema, 如 `hly_accesscard_history` |
| **镜像工单审批组** | **是** | **D22 新加, 必填, 不填表单校验失败** |
| 同步模式 | 是 | 默认 "黑名单" (业务库全同步, 显式排除) |
| 启用 | 是 | 默认勾选 |

4. 选"镜像工单审批组":

| 业务场景 | 推荐选 |
|----------|--------|
| 业务库 → 历史库 同步 | **"prod core for 历史库"** (group_id=22, DBA 单一审批) |
| 业务库 → ETL 同步 | "prod bigdata 日常" / "prod bigdata 上线" 等 (看具体情况) |
| 不确定 | 问 DBA 组长 |

5. 点 "创建库对" → 跳到库对详情页 `/ddl_sync/pair/<id>/`

### 验证

- 库对详情页能看到 "镜像工单审批组" 行, 显示 `prod core for 历史库 (group_id=22)`
- 业务库 DDL 工单审核通过后, 自动生成的镜像工单:
  - `group_id = 22` (走历史库组, 不是业务组)
  - `audit_auth_groups = '3'` (DBA 单一审批)
  - detail 页 "工单详情" tab 主表有 1 行 (D21 placeholder) + 子表可展开

## 2. 编辑库对 (新增/修改 镜像工单审批组)

### 步骤

1. 库对列表 → 点库对名 → `/ddl_sync/pair/<id>/`
2. 点 "编辑" 按钮 → `/ddl_sync/pair/<id>/edit/`
3. 改 "镜像工单审批组" 下拉 → 选新组
4. 点 "保存修改"

### 适用场景

- D22 上线时给老库对补配 target_group (3 步骤) — 必做!
- 后续想换审批组, 比如从 DBA 改到 DBA + 风控

### 验证

- 重新看库对详情页 → "镜像工单审批组" 行显示新值
- 之后业务库 DDL 走新组审批流

## 3. D22 上线时给老库对补配 (3 步骤)

D22 上线时, 老的库对 `target_group = NULL`, 详情页会显示红色警示:
> ⚠ D22 升级前的老库对, 镜像工单当前走 source_workflow.group_id (业务组), 违反设计, 需手动配

### 必须做 (3 步骤)

**步骤 1: 编辑库对补配 target_group**

- 库对详情页 → "编辑" → 选 "prod core for 历史库" → 保存
- 验证: 详情页"镜像工单审批组"行显示新值, **无红色警示**

**步骤 2: 老的镜像工单 SQL UPDATE 改 group_id + 重新 create_audit**

老的镜像工单 (D22 上线前创建的) group_id 还是业务组, 需要手动改:

```sql
-- 1. 找要改的镜像工单
SELECT id, workflow_name, group_id, group_name, audit_auth_groups
FROM sql_workflow
WHERE workflow_name LIKE '[镜像]%'
  AND group_id != <target_group_id>;

-- 2. 改 group_id + group_name
UPDATE sql_workflow
SET group_id = <target_group_id>,
    group_name = '<target_group_name>'
WHERE id IN (老镜像工单 ids);

-- 3. 删老 audit (group <target_group_id> 配的)
DELETE FROM workflow_audit
WHERE workflow_id IN (老镜像工单 ids);

-- 4. 重新走 audit_handler.create_audit() 拿新组审流
-- 走 Django shell:
```

```python
# Django shell (manage.py shell)
from sql.models import SqlWorkflow
from sql.utils.workflow_audit import get_auditor

for wf_id in [老镜像工单 ids]:
    swf = SqlWorkflow.objects.get(id=wf_id)
    swf.audit_auth_groups = ""
    swf.save(update_fields=["audit_auth_groups"])
    try:
        get_auditor(workflow=swf).create_audit()
    except Exception as e:
        print(f"wf#{wf_id} create_audit 失败: {e}")
```

**步骤 3: 验证**

- `/detail/<wf_id>/` 看 audit_auth_groups 是否走新组
- 比如期望 `audit_auth_groups = '3'` (DBA 单一审批)

## 4. 常见问题

### Q1: 业务库 DDL PASSED 后, 镜像工单没生成?

**A**: 看 `ext_ddl_sync_history.sync_status`:
- `failed` + `error_message` 含 "没配 target_group" → D22 老库对没配, 走步骤 3
- `failed` + 其他 → 看 `error_message` 详细原因
- `syncing` → 等业务方审核执行
- 查不到 record → DdlSyncPair.source_instance 跟 source_workflow.instance 不匹配, 或 pair.enabled=False

### Q2: 镜像工单 audit_auth_groups 是空的?

**A**: WorkflowAuditSetting 没配, 走 DBA 兜底:

```sql
-- 1. 查 group 22 (prod core for 历史库) 配的审流
SELECT * FROM workflow_audit_setting
WHERE group_id = 22 AND workflow_type = 2;  -- 2 = SQL_REVIEW

-- 2. 没配就补 (DBA 单一审批)
INSERT INTO workflow_audit_setting
  (group_id, group_name, workflow_type, audit_auth_groups)
VALUES
  (22, 'prod core for 历史库', 2, '3');
```

### Q3: 怎么验证镜像工单走历史库组?

```python
# Django shell
from sql.models import SqlWorkflow

# 找最新的 [镜像] 工单
swf = SqlWorkflow.objects.filter(workflow_name__startswith="[镜像]").order_by("-id").first()
print(f"wf#{swf.id} group_id={swf.group_id} group_name={swf.group_name}")
print(f"audit_auth_groups={swf.audit_auth_groups}")

# 期望: group_id=22, audit_auth_groups='3'
```

### Q4: 想换审批组, 比如从 DBA 单一改成 DBA+风控双审?

**A**: 两个入口二选一:
1. 改 `workflow_audit_setting.audit_auth_groups` (只改审流, 不动 group_id) — 不推荐, 影响所有用这个组的工单
2. 改 DdlSyncPair.target_group 指向新组 (推荐, 只影响这一个库对) — 走步骤 2

## 5. 关键路径

| 页面 | URL | 用途 |
|------|-----|------|
| 库对列表 | `/ddl_sync/pair/` | 看所有库对 |
| 新建库对 | `/ddl_sync/pair/create/` | 配新库对, 必填 target_group |
| 编辑库对 | `/ddl_sync/pair/<id>/edit/` | 改库对配置, 含 target_group |
| 库对详情 | `/ddl_sync/pair/<id>/` | 看库对配置 + 同步表清单 + 同步历史 |
| 工单详情 | `/detail/<wf_id>/` | 看镜像工单, 自动跑 v0.3.x 字段 diff |

## 6. 关键术语

| 术语 | 解释 |
|------|------|
| 业务库 | 业务方跑的库, 提 DDL 工单的库 |
| 历史库 | 业务库的归档库, 同步目标 |
| 镜像工单 | 业务库 DDL PASSED 后自动生成到历史库的工单 |
| 库对 | 业务库 + 历史库 的对应关系 (DdlSyncPair) |
| target_group | 镜像工单审批组, D22 新加, DBA 显式选 (库对 → ResourceGroup) |
| WorkflowAuditSetting | Archery 审流配置表, 跟 group_id + workflow_type 关联 |
| audit_auth_groups | 审流配置, 格式 `'3'` (DBA) 或 `'14,3'` (风控+DBA) |

## 7. 紧急回滚

D22 上线后出问题想回滚:

```sql
-- 1. 找 target_group 字段, 看哪些库对已配
SELECT id, name, target_group_id, target_group_name
FROM ext_ddl_sync_pair;

-- 2. 临时回滚 D22: 把 sync_trigger.py 改回 source_workflow.group_id
--    (改 134 dev + 110 prod 2 处, gunicorn 重启)
--    sync_trigger.py:
--      group_id=source_workflow.group_id,
--      group_name=source_workflow.group_name,

-- 3. 镜像工单 group_id 已经在创建时定, 改不了, 老的工单保留新流程
```

**回滚 D22 不是简单回滚 commit**, 因为 D22 涉及到:
- 新加 migration 0002 (target_group + target_group_name 字段) — 不能回滚
- sync_trigger.py 改用 pair.target_group — 可回滚代码, 但 D22 后创建的镜像工单已经是新 group
- 老镜像工单 group_id 已 SQL UPDATE 改过 — 不能回滚

**所以 D22 上线前必先 134 dev 演练通 + 业务方确认无异常**。

## 8. 联系

- 文档作者: mavis
- 关联 commit: `5f261e0`
- 关联 changelog: `docs/changelogs/2026-09-03_ddl-sync-w2-d22-mirror-target-group.md`
- 紧急 issue: 找 DBA 组长
