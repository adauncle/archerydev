# 钉钉 OA 联动变更工单 —— 基础架构（第一阶段）

**日期**：2026-07-20
**作者**：Mavis (coder agent)
**影响范围**：`sql/extensions/dingtalk_oa/`、`sql/extensions/audit_drivers/`
**风险等级**：低
**关联设计**：[docs/designs/2026-07-20_dingtalk-oa-workflow.md v0.7](../designs/2026-07-20_dingtalk-oa-workflow.md)

## 背景

按 v0.7 设计文档 §9 阶段化实施，本阶段（阶段 1）交付"基础架构"：
扩展 app 脚手架 + 7 个新模型 + driver 抽象 + 路由引擎骨架。
**未触碰**任何上游文件，**未写**DingtalkOaDriver（属于阶段 4）。
**未修改**`sql/models.py` 现有模型（`SqlWorkflow.audit_driver` 字段属于阶段 5"接入"）。

## 改动内容

### 目录与脚手架
- 新建 `sql/extensions/dingtalk_oa/` —— 钉钉 OA 二次开发独立 app
  - `__init__.py` / `apps.py` —— Django app 配置（`DingtalkOaConfig`，`name="sql.extensions.dingtalk_oa"`）
  - `models.py` —— 7 个新模型（详见下）
  - `admin.py` —— 7 个模型的 Django admin 注册
  - `services/` —— 业务服务（policy 路由 + sql_type_detect）
  - `migrations/` —— 占位（首次接入时跑 `makemigrations dingtalk_oa`）
  - `tests/` —— 3 个测试文件

- 新建 `sql/extensions/audit_drivers/` —— driver 抽象层（跨 feature 共用）
  - `base.py` —— `AuditDriver` 抽象基类 + `DriverStartResult` / `Decision`
  - `registry.py` —— `DRIVER_REGISTRY` 注册表 + `get_driver` / `register_driver`
  - `archery.py` —— `ArcheryDriver`（默认本地 driver，占位实现）
  - `configurable_auditor.py` —— `ConfigurableAuditor`（继承 `AuditV2`，重写 `generate_audit_setting`）

### 7 个新模型（`sql/extensions/dingtalk_oa/models.py`）

| # | 模型 | 关键字段 | db_table |
|---|------|----------|----------|
| 1 | `SqlTypeRegistry` | `code` (PK) / `category` / `pattern` / `default_severity` / `is_critical` / `is_active` | `ext_sql_type_registry` |
| 2 | `CoreBusinessTable` | `instance` (FK) / `db_name` / `table_name` / `level` (L1/L2/L3) | `ext_core_business_table` |
| 3 | `ApprovalFlow` | `code` (PK) / `audit_driver` / `audit_auth_groups` / `dingtalk_process_code` | `ext_approval_flow` |
| 4 | `ApprovalPolicy` | `priority` / `sql_types` (M2M) / `require_core_table` / `min_affected_rows` / `flow` (FK PROTECT) | `ext_approval_policy` |
| 5 | `GroupDingtalkAuditor` | `group` (FK auth.Group) / `resource_group` (FK 可空) / `dingtalk_user_ids` / `dingtalk_dept_id` | `ext_group_dingtalk_auditor` |
| 6 | `WorkflowAuditExternal` | `audit` (OneToOne) / `external_process_instance_id` / `external_status` / `payload` (JSON) | `ext_workflow_audit_external` |
| 7 | `DingtalkOaEventLog` | `audit` (FK SET_NULL) / `event_id` (幂等) / `payload` / `processed` / `error` | `ext_dingtalk_oa_event_log` |

### driver 抽象
- `AuditDriver` —— 4 个抽象方法：`start` / `apply_decision` / `terminate` / `get_status`，1 个可选 `handle_callback`
- `DRIVER_REGISTRY` —— `archery` 已注册；`dingtalk_oa` 在阶段 4 接入
- `get_driver(name)` —— 抛 `ValueError`（未注册）或 `ImportError`（路径写错）
- `ConfigurableAuditor._feature_enabled()` —— 默认 False（`CUSTOM_DINGTALK_OA_ENABLED` 未设置时）
  - False 时 `generate_audit_setting` 完全走父类 `AuditV2`，零侵入
  - True 时调 `services.policy.match_policy(workflow=self.workflow)`

### 路由引擎（`sql/extensions/dingtalk_oa/services/policy.py`）
- `match_policy(workflow, affected_tables=None)` —— 三维 AND 匹配
  - 维度 1：SQL 类型集合（`any` / `all` 模式）
  - 维度 2：核心业务表（按 `db_name + table_name` 命中 `CoreBusinessTable`，可指定 level）
  - 维度 3：影响行数区间（`min_affected_rows` / `max_affected_rows`，`None` 时不参与判定）
- 按 `priority` 倒序遍历 `is_enabled=True` 的策略
- 防御：`sql_types` 为空的策略永远不命中

### SQL 特征提取（`sql/extensions/dingtalk_oa/services/sql_type_detect.py`）
- `extract_sql_types(sql_content)` —— 基于 `SqlTypeRegistry.pattern` 编译缓存（`RLock` 线程安全）
- `extract_affected_rows(workflow, mode="total")` —— `total` / `max` 聚合
- `extract_affected_tables(workflow)` —— 复用上游 `sql.utils.extract_tables.extract_tables`
- `reset_registry_cache()` —— admin 修改注册表后由调用方显式触发

### 测试（pytest-django）
- `tests/test_models.py` —— 9 个用例（创建 / 默认值 / 唯一约束 / PROTECT / M2M / 顺序）
- `tests/test_audit_drivers.py` —— 14 个用例（driver 行为 / 注册表 / 特性开关 / 抽象类不可实例化）
- `tests/test_policy_match.py` —— 26 个用例（SQL 类型提取 / 行数聚合 / 表提取 / 三维匹配 / match_policy 端到端）

## 涉及文件

### 新建（不修改任何已有文件）
- `sql/extensions/dingtalk_oa/__init__.py`
- `sql/extensions/dingtalk_oa/apps.py`
- `sql/extensions/dingtalk_oa/models.py`
- `sql/extensions/dingtalk_oa/admin.py`
- `sql/extensions/dingtalk_oa/services/__init__.py`
- `sql/extensions/dingtalk_oa/services/policy.py`
- `sql/extensions/dingtalk_oa/services/sql_type_detect.py`
- `sql/extensions/dingtalk_oa/migrations/__init__.py`
- `sql/extensions/dingtalk_oa/tests/__init__.py`
- `sql/extensions/dingtalk_oa/tests/test_models.py`
- `sql/extensions/dingtalk_oa/tests/test_audit_drivers.py`
- `sql/extensions/dingtalk_oa/tests/test_policy_match.py`
- `sql/extensions/audit_drivers/__init__.py`
- `sql/extensions/audit_drivers/base.py`
- `sql/extensions/audit_drivers/registry.py`
- `sql/extensions/audit_drivers/archery.py`
- `sql/extensions/audit_drivers/configurable_auditor.py`
- `docs/changelogs/2026-07-20_coder-dingtalk-oa-foundation.md` —— 本文件

### 未触碰（按设计要求）
- `sql/models.py` —— `SqlWorkflow.audit_driver` 字段属于阶段 5，本阶段不加
- `archery/settings.py` —— `CURRENT_AUDITOR` 默认值仍为 `AuditV2`
- `archery/urls.py` —— 路由属阶段 6
- `common/`、`dashboard/`、`sql_api/` —— 与本阶段无关

## 验证清单

- [x] 所有 .py 文件 UTF-8 中文注释正常
- [x] 模型字段与 v0.7 §5 1:1 对应
- [x] `AuditDriver` 抽象类不可直接实例化（`test_audit_drivers.py::test_abstract_audit_driver_cannot_be_instantiated`）
- [x] `ConfigurableAuditor._feature_enabled()` 默认 False，不影响上游行为
- [x] 路由算法符合 v0.7 §7（priority 倒序 + 三维 AND + 防御空 sql_types）
- [x] 49+ 个 pytest 用例覆盖主要模型和 driver
- [ ] `pytest sql/extensions/dingtalk_oa/tests/ -v` —— **未运行**（本地无 Python/Django 环境；CI 或 dev 容器内首跑）
- [ ] `python manage.py check sql.extensions.dingtalk_oa` —— **未运行**（同上）

## 第二阶段（driver 接入）所需

- 在 `sql/extensions/dingtalk_oa/drivers/dingtalk.py` 写 `DingtalkOaDriver`（v0.7 §6.4）
- 在 `registry.DRIVER_REGISTRY` 注册 `"dingtalk_oa"`
- 在 `sql/models.py:SqlWorkflow` 加 1 个字段 `audit_driver`（v0.7 §5.8）
- 在 `archery/settings.py:INSTALLED_APPS` 加 `"sql.extensions.dingtalk_oa.apps.DingtalkOaConfig"`
- 通过 env `CUSTOM_DINGTALK_OA_AUDITOR` 替换 `CURRENT_AUDITOR`
- 写 seed 命令灌 13 个内置 `SqlTypeRegistry`

## 回滚方案

```bash
# 本阶段全部新建文件，未改动任何已有代码
git reset --hard HEAD~1
```

或：
```bash
# 仅移除本 app（无需数据库迁移，因 migrations 是空）
rm -rf sql/extensions/dingtalk_oa/ sql/extensions/audit_drivers/
rm docs/changelogs/2026-07-20_coder-dingtalk-oa-foundation.md
```

`migrations/0001_initial.py` 占位是空 operations，**不**会执行任何 DDL。
真实建表 DDL 由第二阶段跑 `makemigrations dingtalk_oa` 生成。
