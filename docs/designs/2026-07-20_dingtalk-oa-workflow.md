# Archery 变更工单联动钉钉 OA 审批 —— 设计方案

> **状态**：v0.7（设计中，6 次迭代已完成，含自动降级 + 安全设计，待最后评审）
> **日期**：2026-07-20
> **作者**：Mavis（辅助生成）+ 项目 owner
> **目标读者**：内部 DBA 团队 + 二次开发 review 同事

---

## 0. 文档说明

本文档记录"Archery 变更工单联动钉钉 OA 审批"二次开发需求的**完整设计方案**。

- **不在本文档范围内**：钉钉后台配置步骤、UI mockup、压测报告
- **本文档固定基线**：Archery v1.14.0（commit `d303c04`）
- **本文档演进过程**：4 次迭代，从"钉钉 OA 为主"演化为"driver 可配置 + 三维策略 + 流程独立化"

---

## 1. 背景与目标

### 1.1 业务诉求

公司内部 DBA 团队希望 SQL 变更工单按风险等级走**两套审批流**：

**流程 1（普通）**：
```
研发提交 → 研发组长 → 研发负责人 → DBA → DBA 组长 → DBA 执行
```

**流程 2（重大）**：
```
研发提交 → 研发组长 → 研发负责人 → DBA → DBA 组长 → 副总 → DBA 执行
```

### 1.2 判定维度（演进后）

- **SQL 维度**（细粒度到具体类型）：INSERT / UPDATE / DELETE / ALTER / DROP / TRUNCATE / CREATE / SELECT / ...
- **业务表维度**：核心业务表清单 + 等级 L1/L2/L3
- **影响行数维度**：DML 类工单可按行数区间判定

**示例**：
- UPDATE 影响 ≤ 1 行 → 流程 1
- UPDATE 影响 2~10 行 → 流程 1
- UPDATE 影响 > 10 行 → 流程 2
- 任意 DDL（ALTER/DROP/TRUNCATE/CREATE）→ 流程 2

### 1.3 关键设计目标

1. **完全配置化**：流程 / 策略 / driver / 审批人映射都可在 admin 配置
2. **零硬编码**：未来加飞书/企微 OA 不改核心代码
3. **核心代码 0 改动**：所有功能在 `sql/extensions/dingtalk_oa/` 独立 app 内
4. **30 秒回滚**：通过 env 开关关闭，回到上游原行为

---

## 2. 现状调研

### 2.1 上游审批流结构

```
[用户在 Archery 提交] 
   → AuditV2.create_audit()  (sql/utils/workflow_audit.py:134)
   → 查 WorkflowAuditSetting(group_id, workflow_type) 拿到 audit_auth_groups
   → 创建 WorkflowAudit, current_audit = groups[0], next_audit = groups[1]
   → [用户在 Archery 页面点通过]
   → AuditV2.operate_pass() 推进 current_audit/next_audit
   → 全部走完 → WorkflowStatus.PASSED → 进入执行队列
```

**关键事实**：
- `CURRENT_AUDITOR` 是 env 注入的（settings.py:82）—— **可以替换**成自定义 auditor ✅
- `WorkflowAuditSetting` 是**单条配置**（`unique_together = (group_id, workflow_type)`）—— **不支持按 SQL 类型/表路由** ❌
- `SqlWorkflow.syntax_type` 已经有 0/1=DDL/2=DML/3=导出（models.py:331）—— **数据已有** ✅
- 通知机制已存在：`DingdingWebhookNotifier` / `DingdingPersonNotifier`，但**只是工作通知，不是 OA 审批** ⚠️
- `Users.ding_user_id` 已有，钉钉用户 ID 已存 ✅

### 2.2 现有钉钉能力

| 已实现 | 未实现 |
|--------|--------|
| 钉钉登录认证（`common/authenticate/dingding_auth.py`）| **OA 审批（智能工作流）** |
| 钉钉 access_token 缓存（`common/utils/ding_api.py`）| OA 流程实例发起/查询/回调 |
| 钉钉 webhook 群机器人通知 | 审批人 ↔ 用户/部门映射 |
| 钉钉工作通知（个人） | 审批模板管理 |
| 钉钉用户同步 |  |

### 2.3 关键约束

| 约束 | 影响 |
|------|------|
| `WorkflowAuditSetting` 单一配置 | 必须扩展为多策略路由 |
| `SqlWorkflow` 单一 `syntax_type` | 必须新增 `audit_driver` + 扩展 `audit_auth_groups` 镜像 |
| 钉钉 OA 模板变更要走钉钉后台 | process_code 需冻结，配置化 |
| 上游 `AuditV2` 是 `CURRENT_AUDITOR` 注入 | 用继承方式扩展，不动原类 |
| 单租户（Archery 默认）| 本期不考虑多租户 |

---

## 3. 关键决策演进

| # | 主题 | 决策 | 原因 |
|---|------|------|------|
| 1 | 钉钉 OA 地位 | **演进为 driver 可配置** | 用户反馈：A/B/C 三选一不够灵活 |
| 2 | SQL 判定粒度 | **细粒度到 SQL 类型** | 用户反馈：syntax_type 粗粒度不够 |
| 3 | 业务表判定 | **核心业务表 + level** | 用户反馈：需要按表判定 |
| 4 | 行数判定 | **影响行数区间** | 用户反馈：DML 类要按行数判定 |
| 5 | 流程定义 | **独立 ApprovalFlow 模型** | 用户反馈：流程也是配置项，不能写死 |

**演进原则**：每次迭代让"用户能配的更多、引擎写死的更少"。

---

## 4. 总体设计

### 4.1 架构图

```
                ┌─────────────────────────────────────┐
                │    Archery 二次开发（extensions）     │
                │                                      │
   研发提交 ───►│  ConfigurableAuditor.create_audit() │
                │     │                                │
                │     ├─► ① match_policy() 路由        │
                │     │    命中 ApprovalPolicy         │
                │     │    取出目标 ApprovalFlow        │
                │     │                                │
                │     ├─► ② 创建本地 WorkflowAudit    │
                │     │                                │
                │     └─► ③ 调 driver.start() 发起    │
                │            │                         │
                │            ▼                         │
                │     ┌────────────────┐              │
                │     │ AuditDriver    │              │
                │     └────┬───────┬───┘              │
                │          │       │                  │
                │   ArcheryDriver  DingtalkOaDriver   │
                │   (本地Group)    (钉钉OA)            │
                │          │       │                  │
                └──────────┼───────┼──────────────────┘
                           │       │
                           ▼       ▼
                  ┌─────────────┐ ┌─────────────────┐
                  │  本地        │ │  钉钉 OA 模板    │
                  │  Group 审批  │ │ (智能工作流)      │
                  │  (web UI)    │ │ (钉钉 App 审批)   │
                  └─────────────┘ └────────┬────────┘
                                           │ 回调
                                           ▼
                            ┌──────────────────────────┐
                            │ /dingtalk/oa/callback    │
                            │   验签 → 路由 → 推进     │
                            └──────────────────────────┘

                ┌─────────────────────────────────────┐
                │ 兜底：Celery Beat 定时轮询           │
                │  每 5 分钟扫未结束工单                │
                │  调 driver.get_status() 同步         │
                └─────────────────────────────────────┘
```

### 4.2 三层配置结构

```
┌────────────────────────────────────────────────────────────┐
│ 第 1 层：用户配置（全部 admin 自助）                         │
├────────────────────────────────────────────────────────────┤
│  SqlTypeRegistry    SQL 类型注册表（13 种内置 + 可扩）       │
│  CoreBusinessTable  业务表清单（instance + db + table）     │
│  ApprovalFlow       流程定义（任意多个，用户自己定义）       │
│  GroupDingtalkAuditor 审批人映射                            │
│  ApprovalPolicy     路由策略（任意多条，priority 决胜负）   │
└────────────────────────────────────────────────────────────┘
                          ↓ 触发
┌────────────────────────────────────────────────────────────┐
│ 第 2 层：路由逻辑（不可配置，是规则引擎）                    │
├────────────────────────────────────────────────────────────┤
│  ① extract_sql_types()   提取 SQL 类型集合                  │
│  ② extract_affected_tables() 提取业务表集合                 │
│  ③ extract_affected_rows()  提取影响行数                    │
│  ④ 按 priority 倒序遍历 ApprovalPolicy                      │
│  ⑤ 三维 AND 匹配 → 命中返回 flow                            │
│  ⑥ 落空 → 走默认 flow（可配）                              │
└────────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────────┐
│ 第 3 层：执行（不可配置，是系统行为）                        │
├────────────────────────────────────────────────────────────┤
│  ① 取出 flow.audit_driver                                  │
│  ② 实例化对应 driver（DRIVER_REGISTRY 查表）                │
│  ③ driver.start() 发审批                                    │
│  ④ driver 回调 → 本地 WorkflowAudit 状态推进                │
└────────────────────────────────────────────────────────────┘
```

### 4.3 核心数据流

#### 4.3.1 工单创建

```
SqlWorkflow(提交)
   │
   ▼
ConfigurableAuditor.create_audit()
   │
   ├── AuditV2.create_audit() (父类逻辑：创建本地 WorkflowAudit)
   │
   ├── match_policy(sql_types, affected_tables, affected_rows)
   │   └── 返回 ApprovalPolicy (或 None)
   │
   ├── 命中：取出 policy.flow (ApprovalFlow)
   │   ├── SqlWorkflow.audit_driver = flow.audit_driver
   │   ├── SqlWorkflow.audit_auth_groups = flow.audit_auth_groups
   │   └── driver = get_driver(flow.audit_driver)
   │       └── driver.start(workflow, audit, flow)
   │           ├── ArcheryDriver: 无操作（仅本地）
   │           └── DingtalkOaDriver: 调钉钉 start_process API
   │
   └── 未命中：走默认 flow（如 default）
```

#### 4.3.2 审批推进

```
[Archery 页面点通过] 或 [钉钉回调]
   │
   ▼
ConfigurableAuditor.operate_pass(actor, remark)
   │
   ├── AuditV2.operate_pass() (父类逻辑：本地推进 current_audit/next_audit)
   │
   └── driver = get_driver(workflow.audit_driver)
       ├── ArcheryDriver: 无操作
       └── DingtalkOaDriver: 同步状态到钉钉（加备注/终止流程）
```

#### 4.3.3 钉钉回调

```
[钉钉 OA 审批人操作]
   │
   ▼
POST /dingtalk/oa/callback
   │
   ├── 验签（AES 解密 + 签名校验）
   ├── 解析事件（bpms_instance_change / bpms_task_change）
   ├── 查 WorkflowAuditExternal → 拿 audit
   │
   └── 调 ConfigurableAuditor(workflow=audit.get_workflow())
       .operate_pass/reject(actor=dingtalk_user, remark=...)
```

---

## 5. 数据模型

> **全部新建模型**，不动 `sql/models.py` 现有模型。
> 仅在 `SqlWorkflow` 上加 1 个新字段（`audit_driver`），最小侵入。

### 5.1 `ApprovalFlow`（**新增核心模型**）

```python
class ApprovalFlow(models.Model):
    """审批流程定义：用户可任意创建，不受程序限制"""
    code = models.CharField(primary_key=True, max_length=32)   # "normal", "critical", "self_service"
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    audit_driver = models.CharField(
        max_length=32,
        choices=[
            ("archery", "Archery 本地 Group 审批"),
            ("dingtalk_oa", "钉钉 OA 智能工作流"),
        ],
    )
    audit_auth_groups = models.CharField(
        max_length=500,
        help_text="逗号分隔的 Group ID 列表，按审批顺序",
    )
    dingtalk_process_code = models.CharField(
        max_length=64, blank=True,
        help_text="仅 audit_driver=dingtalk_oa 时填",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "ext_approval_flow"
        verbose_name = "审批流程"
```

### 5.2 `ApprovalPolicy`（路由策略）

```python
class ApprovalPolicy(models.Model):
    """审批策略：路由规则（触发条件 → 目标流程）"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    priority = models.IntegerField(default=0)
    is_enabled = models.BooleanField(default=True)
    
    # ===== 触发条件（4 个维度）=====
    # 维度 1: SQL 类型
    sql_types = models.ManyToManyField(SqlTypeRegistry, blank=True)
    sql_type_match_mode = models.CharField(
        choices=[("any", "任一命中"), ("all", "全部命中")],
        default="any",
    )
    
    # 维度 2: 业务表
    require_core_table = models.BooleanField(default=False)
    table_levels = models.CharField(
        max_length=16, blank=True,
        help_text="L1,L2 多个用逗号分隔",
    )
    
    # 维度 3: 影响行数
    min_affected_rows = models.IntegerField(null=True, blank=True)
    max_affected_rows = models.IntegerField(null=True, blank=True)
    affected_rows_aggregate = models.CharField(
        choices=[("total", "所有 SQL 总和"), ("max", "单条 SQL 最大值")],
        default="total",
    )
    
    # 兼容层
    legacy_syntax_types = models.CharField(max_length=32, blank=True)
    
    severity = models.CharField(
        choices=[("low", "低风险"), ("medium", "中风险"), ("high", "高风险")],
        default="medium",
    )
    
    # ===== 命中目标 =====
    flow = models.ForeignKey(
        ApprovalFlow, on_delete=models.PROTECT,
        help_text="命中后跳转到哪个流程",
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "ext_approval_policy"
        ordering = ["-priority"]
```

### 5.3 `SqlTypeRegistry`（SQL 类型注册表）

```python
class SqlTypeRegistry(models.Model):
    """SQL 类型注册表：内置 + 可扩展"""
    code = models.CharField(primary_key=True, max_length=32)  # "INSERT", "DROP", ...
    category = models.CharField(max_length=16)                 # "DML" / "DDL" / "DQL" / "DCL"
    description = models.CharField(max_length=128)
    pattern = models.CharField(max_length=255)                 # 识别正则
    default_severity = models.CharField(max_length=16)         # "low" / "medium" / "high"
    has_affected_rows = models.BooleanField(
        default=True,
        help_text="DDL/DQL 类设为 False，不参与行数维度判定",
    )
    is_critical = models.BooleanField(
        default=False,
        help_text="高危类型，DROP/TRUNCATE 等",
    )
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = "ext_sql_type_registry"
```

**内置数据（首次部署 seed）**：

| code | category | severity | pattern | has_affected_rows | is_critical |
|------|----------|----------|---------|-------------------|-------------|
| SELECT | DQL | low | `^\s*SELECT\b` | False | |
| INSERT | DML | low | `^\s*INSERT\b` | True | |
| UPDATE | DML | medium | `^\s*UPDATE\b` | True | |
| DELETE | DML | high | `^\s*DELETE\b` | True | ✅ |
| REPLACE | DML | high | `^\s*REPLACE\b` | True | ✅ |
| ALTER | DDL | high | `^\s*ALTER\b` | False | ✅ |
| DROP | DDL | high | `^\s*DROP\b` | False | ✅ |
| TRUNCATE | DDL | high | `^\s*TRUNCATE\b` | False | ✅ |
| CREATE | DDL | high | `^\s*CREATE\b` | False | ✅ |
| RENAME | DDL | high | `^\s*RENAME\b` | False | ✅ |
| GRANT | DCL | high | `^\s*GRANT\b` | False | ✅ |
| REVOKE | DCL | high | `^\s*REVOKE\b` | False | ✅ |
| SET | DCL | low | `^\s*SET\b` | False | |

### 5.4 `CoreBusinessTable`（核心业务表）

```python
class CoreBusinessTable(models.Model):
    id = models.AutoField(primary_key=True)
    instance = models.ForeignKey("sql.Instance", on_delete=models.CASCADE)
    db_name = models.CharField(max_length=64)
    table_name = models.CharField(max_length=128)
    level = models.CharField(
        max_length=8, choices=[("L1", "L1"), ("L2", "L2"), ("L3", "L3")]
    )
    remark = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "ext_core_business_table"
        unique_together = ("instance", "db_name", "table_name")
        indexes = [models.Index(fields=["db_name", "table_name"])]
```

### 5.5 `GroupDingtalkAuditor`（审批人映射）

```python
class GroupDingtalkAuditor(models.Model):
    id = models.AutoField(primary_key=True)
    group = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    resource_group = models.ForeignKey(
        "sql.ResourceGroup", null=True, blank=True, on_delete=models.CASCADE
    )
    # 二选一：精确 userid 或 按部门拉
    dingtalk_user_ids = models.TextField(
        blank=True, help_text="JSON 数组，如 ['user1','user2']"
    )
    dingtalk_dept_id = models.CharField(max_length=64, blank=True)
    # 抄送
    dingtalk_cc_user_ids = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "ext_group_dingtalk_auditor"
        unique_together = ("group", "resource_group")
```

### 5.6 `WorkflowAuditExternal`（工单 ↔ 外部 OA 关联）

```python
class WorkflowAuditExternal(models.Model):
    id = models.AutoField(primary_key=True)
    audit = models.OneToOneField(
        "sql.WorkflowAudit", on_delete=models.CASCADE,
        related_name="external_audit",
    )
    source = models.CharField(max_length=32)  # "dingtalk_oa"
    external_process_instance_id = models.CharField(max_length=128, db_index=True)
    external_process_code = models.CharField(max_length=64)
    current_external_node = models.CharField(max_length=64, blank=True)
    external_status = models.CharField(max_length=32)  # RUNNING / APPROVED / REJECTED / TERMINATED
    last_synced_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    
    class Meta:
        db_table = "ext_workflow_audit_external"
```

### 5.7 `DingtalkOaEventLog`（钉钉事件流水）

```python
class DingtalkOaEventLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    audit = models.ForeignKey(
        "sql.WorkflowAudit", on_delete=models.SET_NULL, null=True
    )
    event_type = models.CharField(max_length=32)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = "ext_dingtalk_oa_event_log"
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["audit", "event_type"]),
        ]
```

### 5.8 `SqlWorkflow` 扩展（最小侵入）

```python
# 在 sql/models.py 的 SqlWorkflow 上加 1 个字段
class SqlWorkflow(models.Model, WorkflowAuditMixin):
    # ... 现有字段不动 ...
    
    # 新增：审批驱动（工单创建时锁定）
    audit_driver = models.CharField(
        "审批驱动", max_length=32, default="archery",
        help_text="由 policy 命中时锁定，后续 policy 变更不影响历史工单",
    )
```

### 5.9 ER 图

```
┌─────────────────────┐
│   SqlWorkflow       │  (上游模型，加 1 字段)
│   + audit_driver    │
└──────────┬──────────┘
           │ 1:N
           ▼
┌─────────────────────┐
│   WorkflowAudit     │  (上游模型，不动)
└──────────┬──────────┘
           │ 1:1
           ▼
┌─────────────────────┐      ┌──────────────────┐
│WorkflowAuditExternal│─────►│DingtalkOaEventLog│
└─────────────────────┘      └──────────────────┘
           ▲
           │ (DingtalkOaDriver 写入)

┌─────────────────────┐
│  ApprovalFlow       │  ← 用户配置（任意多个）
└──────────┬──────────┘
           │ 1:N
           ▼
┌─────────────────────┐
│  ApprovalPolicy     │  ← 用户配置（任意多条）
│  - 4 维触发条件      │
│  - flow (FK)         │
└─────────────────────┘

┌─────────────────────┐    ┌──────────────────────┐
│  SqlTypeRegistry    │◄───│  ApprovalPolicy      │
└─────────────────────┘ M2M└──────────────────────┘
                                     │
                                     │ FK
                                     ▼
                            ┌─────────────────────┐
                            │  ApprovalFlow       │
                            └─────────────────────┘

┌─────────────────────┐
│  CoreBusinessTable  │  ← 用户配置（业务表清单）
└─────────────────────┘

┌─────────────────────┐    ┌──────────────────────┐
│  auth.Group         │◄───│ GroupDingtalkAuditor │
└─────────────────────┘    └──────────────────────┘
```

---

## 6. driver 抽象

### 6.1 `AuditDriver` 接口

```python
# sql/extensions/audit_drivers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Decision:
    PASS = "pass"
    REJECT = "reject"


@dataclass
class DriverStartResult:
    external_id: str
    extra: dict = None


class AuditDriver(ABC):
    """审批驱动抽象基类"""
    name: str  # driver 标识
    
    @abstractmethod
    def start(self, workflow, audit, flow: "ApprovalFlow") -> DriverStartResult:
        """发起审批，返回 driver 需要的运行时信息"""
        ...
    
    @abstractmethod
    def apply_decision(
        self, audit, decision: str, actor, remark: str
    ) -> "WorkflowAuditDetail":
        """推进一次审批结果（PASS / REJECT）"""
        ...
    
    @abstractmethod
    def terminate(self, audit, actor, remark: str):
        """终止（用户主动撤回）"""
        ...
    
    @abstractmethod
    def get_status(self, audit) -> dict:
        """查询外部状态（用于对账）"""
        ...
    
    def handle_callback(self, request) -> "HttpResponse":
        """处理 driver 自己的外部回调（archery 没有，重写可选）"""
        raise NotImplementedError("This driver has no callback")
```

### 6.2 driver 注册机制

```python
# sql/extensions/audit_drivers/registry.py
import importlib
from .base import AuditDriver

DRIVER_REGISTRY: dict = {
    "archery":     "sql.extensions.audit_drivers.archery:ArcheryDriver",
    "dingtalk_oa": "sql.extensions.dingtalk_oa.drivers.dingtalk:DingtalkOaDriver",
    # 未来加：
    # "feishu_oa":   "sql.extensions.feishu_oa.drivers.feishu:FeishuOaDriver",
    # "qywx_oa":     "sql.extensions.qywx_oa.drivers.qywx:QywxOaDriver",
}


def get_driver(name: str) -> AuditDriver:
    if name not in DRIVER_REGISTRY:
        raise ValueError(f"Unknown audit_driver: {name}")
    path = DRIVER_REGISTRY[name]
    module, cls = path.rsplit(":", 1)
    return getattr(importlib.import_module(module), cls)()
```

### 6.3 `ArcheryDriver`（默认 driver）

```python
# sql/extensions/audit_drivers/archery.py
class ArcheryDriver(AuditDriver):
    name = "archery"
    
    def start(self, workflow, audit, flow):
        # 本地 Group 审批：无需任何外部动作
        return DriverStartResult(external_id="")
    
    def apply_decision(self, audit, decision, actor, remark):
        # 直接返回，状态推进交给父类 AuditV2.operate_pass/reject
        # 这个 driver 的存在只是为了与 DingtalkOaDriver 接口对齐
        return None
    
    def terminate(self, audit, actor, remark):
        return None
    
    def get_status(self, audit):
        return {"status": "local"}
    
    def handle_callback(self, request):
        return None
```

### 6.4 `DingtalkOaDriver`（钉钉 OA driver）

```python
# sql/extensions/dingtalk_oa/drivers/dingtalk.py
class DingtalkOaDriver(AuditDriver):
    name = "dingtalk_oa"
    
    def start(self, workflow, audit, flow):
        """调钉钉 API 发起 OA 审批"""
        process_instance_id = self._call_dingtalk_api(
            "topapi.processinstance.create",
            process_code=flow.dingtalk_process_code,
            originator=workflow.engineer,
            form_components=self._build_form(workflow, audit, flow),
        )
        WorkflowAuditExternal.objects.create(
            audit=audit, source="dingtalk_oa",
            external_process_instance_id=process_instance_id,
            external_process_code=flow.dingtalk_process_code,
            external_status="RUNNING",
        )
        return DriverStartResult(external_id=process_instance_id)
    
    def apply_decision(self, audit, decision, actor, remark):
        """本地状态推进后，通知钉钉加备注或终止"""
        ext = WorkflowAuditExternal.objects.get(audit=audit)
        if decision == Decision.PASS:
            self._call_dingtalk_api(
                "topapi.processinstance.comment.add",
                process_instance_id=ext.external_process_instance_id,
                comment=f"[Archery] 节点 {actor.display} 通过：{remark}",
            )
        elif decision == Decision.REJECT:
            self._terminate_ext(ext, reason=f"[Archery] 驳回：{remark}")
            ext.external_status = "TERMINATED"
            ext.save()
        return None  # 实际 WorkflowAuditDetail 由父类 AuditV2 产生
    
    def terminate(self, audit, actor, remark):
        ext = WorkflowAuditExternal.objects.get(audit=audit)
        self._terminate_ext(ext, reason=f"[Archery] 撤回：{remark}")
        ext.external_status = "TERMINATED"
        ext.save()
    
    def get_status(self, audit):
        ext = WorkflowAuditExternal.objects.filter(audit=audit).first()
        if not ext:
            return None
        return self._call_dingtalk_api(
            "topapi.processinstance.get",
            process_instance_id=ext.external_process_instance_id,
        )
    
    def handle_callback(self, request):
        """钉钉 OA 回调处理"""
        # 1. 验签 + AES 解密
        # 2. 解析事件类型
        # 3. 调 ConfigurableAuditor.operate_pass/reject
        # 4. 记 DingtalkOaEventLog
        # 5. 返回 200 OK
        ...
```

### 6.5 `ConfigurableAuditor`（顶层路由）

```python
# sql/extensions/audit_drivers/configurable_auditor.py
from sql.utils.workflow_audit import AuditV2, AuditException, AuditSetting


class ConfigurableAuditor(AuditV2):
    """根据 ApprovalPolicy + ApprovalFlow 路由到不同 driver"""
    
    def generate_audit_setting(self) -> AuditSetting:
        """重写：根据 policy 决定审批流"""
        if not self._feature_enabled():
            return super().generate_audit_setting()
        
        # 走 policy 路由
        policy = match_policy(
            workflow=self.workflow,
            affected_tables=extract_affected_tables(self.workflow),
        )
        if not policy:
            return super().generate_audit_setting()
        
        flow = policy.flow
        return AuditSetting(
            audit_auth_groups=flow.audit_auth_groups.split(","),
            auto_pass=False,
            auto_reject=False,
        )
    
    def create_audit(self) -> str:
        result = super().create_audit()
        if not self._feature_enabled() or not self.audit:
            return result
        if self.audit.current_status != WorkflowStatus.WAITING:
            return result
        
        # 找命中的 flow
        policy = self._get_applied_policy()
        if not policy:
            return result
        flow = policy.flow
        
        # 锁定 driver 到工单
        self.workflow.audit_driver = flow.audit_driver
        self.workflow.audit_auth_groups = flow.audit_auth_groups
        self.workflow.save(update_fields=["audit_driver", "audit_auth_groups"])
        
        # 调 driver
        try:
            driver = get_driver(flow.audit_driver)
            driver.start(workflow=self.workflow, audit=self.audit, flow=flow)
        except Exception as e:
            logger.exception(f"driver {flow.audit_driver}.start() failed: {e}")
            # 降级：本地 Group 审批继续，不阻塞业务
        
        return result
    
    def operate_pass(self, actor, remark):
        detail = super().operate_pass(actor, remark)
        self._sync_to_driver(actor, remark, decision=Decision.PASS)
        return detail
    
    def operate_reject(self, actor, remark):
        detail = super().operate_reject(actor, remark)
        self._sync_to_driver(actor, remark, decision=Decision.REJECT)
        return detail
    
    def _sync_to_driver(self, actor, remark, decision):
        try:
            driver = get_driver(self.workflow.audit_driver)
            driver.apply_decision(self.audit, decision, actor, remark)
        except Exception as e:
            logger.exception(f"driver {self.workflow.audit_driver} sync failed: {e}")
            # 不阻塞本地推进；定时对账兜底
    
    def _feature_enabled(self) -> bool:
        from django.conf import settings
        return getattr(settings, "CUSTOM_DINGTALK_OA_ENABLED", False)
    
    def _get_applied_policy(self) -> Optional["ApprovalPolicy"]:
        """通过 audit_auth_groups 反查命中的 policy（首 Group + flow）"""
        # 简化：根据 syntax_type + audit_auth_groups 找最近创建的 policy
        ...
```

---

## 7. 路由引擎

### 7.1 `match_policy` 算法

```python
# sql/extensions/dingtalk_oa/service/policy.py
def match_policy(workflow: SqlWorkflow, affected_tables: list) -> Optional[ApprovalPolicy]:
    """多维 AND 匹配，按 priority 倒序遍历"""
    sql_types = extract_sql_types(workflow.sqlworkflowcontent.sql_content)
    affected_rows = extract_affected_rows(workflow, mode="total")
    
    policies = ApprovalPolicy.objects.filter(
        workflow_type=2,  # SQL_REVIEW
        is_enabled=True,
    ).order_by("-priority")
    
    for policy in policies:
        if not _match_sql_types(policy, sql_types):
            continue
        if policy.require_core_table and not _has_core_table(affected_tables, policy.table_levels):
            continue
        if not _match_affected_rows(policy, affected_rows):
            continue
        return policy
    return None
```

### 7.2 维度判定

```python
def _match_sql_types(policy, sql_types: set) -> bool:
    policy_types = set(policy.sql_types.values_list("code", flat=True))
    if not policy_types:
        return False
    if policy.sql_type_match_mode == "all":
        return policy_types.issubset(sql_types)
    return bool(policy_types & sql_types)  # any


def _has_core_table(affected_tables, levels: str) -> bool:
    qs = CoreBusinessTable.objects.filter(
        db_name__in=[t["db"] for t in affected_tables],
        table_name__in=[t["table"] for t in affected_tables],
        is_active=True,
    )
    if levels:
        qs = qs.filter(level__in=levels.split(","))
    return qs.exists()


def _match_affected_rows(policy, rows: int) -> bool:
    if policy.min_affected_rows is None and policy.max_affected_rows is None:
        return True
    if policy.min_affected_rows is not None and rows < policy.min_affected_rows:
        return False
    if policy.max_affected_rows is not None and rows > policy.max_affected_rows:
        return False
    return True
```

### 7.3 SQL 解析

```python
# service/sql_type_detect.py
import sqlparse
import re
from ..models import SqlTypeRegistry

_registry_cache = None


def _get_registry():
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = {
            r.code: re.compile(r.pattern, re.I)
            for r in SqlTypeRegistry.objects.filter(is_active=True)
        }
    return _registry_cache


def extract_sql_types(sql_content: str) -> set:
    types = set()
    registry = _get_registry()
    
    for stmt in sqlparse.split(sql_content):
        stmt = stmt.strip()
        if not stmt or stmt.startswith("--"):
            continue
        for code, pattern in registry.items():
            if pattern.search(stmt):
                types.add(code)
                break
    return types


def extract_affected_rows(workflow: SqlWorkflow, mode: str = "total") -> int:
    review_content = workflow.sqlworkflowcontent.review_content or "[]"
    rows = []
    for r in json.loads(review_content):
        try:
            rows.append(int(r.get("affected_rows", 0)))
        except (ValueError, TypeError):
            rows.append(0)
    if not rows:
        return 0
    return sum(rows) if mode == "total" else max(rows)


def extract_affected_tables(workflow: SqlWorkflow) -> list:
    """复用上游 sql/utils/extract_tables.py 的解析逻辑"""
    from sql.utils.extract_tables import extract_tables  # 上游
    sql_content = workflow.sqlworkflowcontent.sql_content
    return extract_tables(sql_content, db_name=workflow.db_name)
```

### 7.4 边界场景

| 场景 | 处理 |
|------|------|
| 多条 SQL 混合类型（INSERT + DROP）| priority 高的胜出 |
| 解析不出任何 SQL 类型 | 降级到 `legacy_syntax_types` |
| 仍未命中 | 走默认 flow（可配） |
| DDL 配了行数区间 | 忽略行数维度（`has_affected_rows=False`）|
| 用户配的 sql_types 为空 | 该 policy 永远不命中（防御）|
| 多条 policy 命中同一工单 | priority 高的胜出 |
| 多个 SQL 都有 affected_rows | 用 `total` 聚合（默认）或 `max` |
| 业务表跨实例 | 不会命中（CoreBusinessTable 按 instance+db+table）|

---

## 8. 配置示例

### 8.1 流程定义（`ApprovalFlow`）

| code | name | audit_driver | audit_auth_groups | dingtalk_process_code |
|------|------|--------------|-------------------|----------------------|
| `normal` | 普通变更 | `archery` | 研发组长, 研发负责人, DBA, DBA 组长 | - |
| `critical` | 重大变更 | `dingtalk_oa` | 研发组长, 研发负责人, DBA, DBA 组长, 副总 | `PROC_CRITICAL` |
| `self_service` | 自助变更 | `archery` | DBA | - |
| `data_export` | 数据导出 | `dingtalk_oa` | DBA, DBA 组长, 法务 | `PROC_EXPORT` |
| `default` | 默认兜底 | `archery` | DBA, DBA 组长 | - |

### 8.2 策略定义（`ApprovalPolicy`）

| 策略名 | sql_types | require_core_table | min_rows | max_rows | aggregate | priority | flow |
|--------|-----------|---------------------|----------|----------|-----------|----------|------|
| 极小变更 | UPDATE, INSERT | - | 0 | 1 | total | 5 | `self_service` |
| 普通 DML | UPDATE, INSERT, DELETE | - | 2 | 10 | total | 10 | `normal` |
| 核心表 DML | UPDATE, INSERT, DELETE | L1, L2 | - | - | total | 30 | `normal` |
| 大量 UPDATE | UPDATE | - | 11 | - | total | 50 | `critical` |
| DDL 强制 | ALTER, DROP, TRUNCATE, CREATE | - | - | - | - | 80 | `critical` |
| DELETE 必审 | DELETE | - | - | - | - | 100 | `critical` |
| 兜底 | - | - | - | - | - | 0 | `default` |

### 8.3 审批人映射（`GroupDingtalkAuditor`）

| group | resource_group | dingtalk_user_ids | dingtalk_dept_id |
|-------|----------------|-------------------|------------------|
| 研发组长 | - | `["u001","u002"]` | - |
| 研发负责人 | - | - | `D001` |
| DBA | - | - | `D002` |
| DBA 组长 | - | `["u010"]` | - |
| 副总 | - | `["vp001"]` | - |

### 8.4 SQL 类型 seed

13 种内置（详见 5.3），管理员可调整 pattern、新增方言。

### 8.5 核心业务表示例

| instance | db | table | level | remark |
|----------|----|----|----|--------|
| `prod-mysql-01` | `hly_accesscard` | `user` | L1 | 用户主表 |
| `prod-mysql-01` | `hly_accesscard` | `card` | L1 | 卡片主表 |
| `prod-mysql-01` | `hly_accesscard` | `access_log` | L2 | 门禁日志 |
| `prod-mysql-01` | `hly_accesscard` | `temp_table` | L3 | 临时表 |

---

## 9. 阶段化实施

| 阶段 | 内容 | 验证方式 | 预估 |
|------|------|----------|------|
| **0. 钉钉后台准备** | 申请 OA 应用、创建 2 个模板、配置回调 URL、申请发布 | 钉钉后台能跑通模板 | 1 天 |
| **1. 基础架构** | `sql/extensions/dingtalk_oa/` 脚手架 + 7 个模型 + migration + `ApprovalFlow`/`ApprovalPolicy` admin | `makemigrations` 干净，能进 admin 增删改查 | 1.5 天 |
| **2. 路由引擎** | `match_policy` + SQL 类型提取 + 业务表识别 + 行数提取 + seed 命令 | 单测覆盖各分支 | 2 天 |
| **3. driver 抽象** | `AuditDriver` 接口 + `DRIVER_REGISTRY` + `ArcheryDriver` | 默认行为完全等同上游 | 1 天 |
| **4. 钉钉 driver** | `DingtalkOaDriver`（start/decision/terminate/get_status/handle_callback）| 单元测试 + 联调 | 2.5 天 |
| **5. ConfigurableAuditor** | 替换 `CURRENT_AUDITOR` 默认值，`generate_audit_setting` 路由 | 提交一个工单看日志，命中正确 flow | 1.5 天 |
| **6. 回调 endpoint** | `/dingtalk/oa/callback` 验签 + 解析 + 路由 + 调 auditor | mock 钉钉回调测试 | 1 天 |
| **7. 兜底 + 监控** | Celery 轮询对账、`DingtalkOaEventLog`、metric 接入 | 杀掉 webhook 后能自愈 | 1 天 |
| **8. UI 增强** | 详情页显示命中规则 + 催办按钮 | 手工测试 | 1 天 |

**总计**：约 12-15 个工作日（不含钉钉后台配置和联调）

---

## 10. 风险与回滚

### 10.1 主要风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 钉钉 OA 模板变更 | 模板改了 `process_code` 失效 | 模板冻结 + process_code 写 ApprovalFlow |
| 钉钉回调丢失/延迟 | 审批卡住 | 5 分钟轮询兜底（`Celery Beat`）|
| 钉钉 API 限流 | 提交/回调 429 | 重试 + 限流 + 监控 |
| 双入口审批不一致 | 状态错乱 | **本期不开放 Archery 网页对钉钉 OA 工单的手动审批**（详情页只读 + 催办）|
| 审批人离职/转岗 | OA 找不到审批人 | `GroupDingtalkAuditor` 按部门拉，每天同步 |
| 升级上游时冲突 | merge 冲突 | 改动只在 `extensions/dingtalk_oa/` 和 `settings.py` 1 段 |
| 历史工单 | 老工单无 OA 关联 | 只对接新工单；老工单继续走原流程 |

### 10.2 回滚方案

```bash
# env 关掉开关
CUSTOM_DINGTALK_OA_ENABLED=False
# 重启 gunicorn
systemctl restart archery-gunicorn archery-celery-worker
# 此时所有工单回到纯本地 Group 审批
```

**回滚是设计层面的"安全网"**，不是事后补救：
- `ConfigurableAuditor._feature_enabled() = False` 时，直接 `super().generate_audit_setting()` 走上游
- `SqlWorkflow.audit_driver` 字段默认 `archery`，不影响老数据

### 10.3 灰度策略

```bash
# 阶段 1：仅 DBA 自用
ApprovalFlow.objects.filter(code="critical").update(is_active=False)
# 仅 admin 提交时走重大流程

# 阶段 2：扩大范围
# 改 ApprovalPolicy 的 priority 让普通用户也能命中
```

### 10.4 自动降级策略

**核心原则**：业务优先。钉钉任何环节异常时，自动回退到 Archery 本地 Group 审批，不阻塞业务。

#### 10.4.1 兜底场景矩阵

| 场景 | 检测方式 | 兜底动作 |
|------|----------|----------|
| **A. start() 调用失败** | API 异常 / 超时 / 429 | 记日志 → 标记 `oa_failed=True` → 走 archery 本地 → 工单页提示"OA 启动失败已降级" |
| **B. 钉钉回调延迟/丢失** | 定时轮询发现 status=超时未变 | Celery 调 `get_status()` → 同步本地 → 仍超时 30min → 降级 |
| **C. 钉钉模板被禁用** | start 时返回错误码 | 同 A |
| **D. access_token 失效** | API 返回 401 | 自动刷新 token + 重试 1 次，仍失败 → 降级 |
| **E. 钉钉侧审批人找不到** | start 报错 | 降级 + 通知管理员 |
| **F. 钉钉侧流程被手动撤回** | 回调 bpms_instance_change | 同步本地 `WorkflowStatus.ABORTED` |
| **G. 网络分区（API 整体不通）** | 全部调用超时 | 启动重试 3 次 → 降级 + 告警 |

#### 10.4.2 降级状态机

```
[工单提交]
   │
   ▼
[ConfigurableAuditor.create_audit()]
   │
   ├── policy 命中 → flow.audit_driver = "dingtalk_oa"
   │
   └── driver.start() 尝试
        │
        ├── 成功 → 正常走 OA
        │         │
        │         ▼
        │     [WorkflowAuditExternal.oa_status = "RUNNING"]
        │         │
        │         ├── 钉钉回调 → 推进本地 → 正常结束
        │         │
        │         └── Celery 轮询：超时未变 → 触发场景 B 兜底
        │
        └── 失败（任何异常）
            │
            ▼
        [WorkflowAuditExternal.oa_status = "FALLBACK"]
        [WorkflowAuditExternal.oa_failure_reason = "..."]
        [WorkflowAuditExternal.fallback_at = now()]
            │
            ▼
        [工单状态 = 待审批，走 archery 本地 Group]
        [DingtalkOaEventLog 记 fallback 事件]
        [DingtalkOaEventLog.error = 详细堆栈]
            │
            ▼
        [工单详情页：⚠️ "钉钉OA启动失败，已降级到本地审批" 横幅]
```

#### 10.4.3 降级实现细节

##### 1) `DingtalkOaDriver.start()` 降级

```python
def start(self, workflow, audit, flow):
    """调钉钉 API 发起 OA 审批；失败时降级"""
    start_result = None
    fallback_reason = None
    
    for attempt in range(1, OA_RETRY_TIMES + 1):
        try:
            process_instance_id = self._call_dingtalk_api(
                "topapi.processinstance.create",
                process_code=flow.dingtalk_process_code,
                originator=workflow.engineer,
                form_components=self._build_form(workflow, audit, flow),
                timeout=OA_TIMEOUT_SECONDS,
            )
            start_result = DriverStartResult(external_id=process_instance_id)
            break
        except DingtalkApiError as e:
            fallback_reason = f"attempt {attempt}: {e}"
            logger.warning(f"dingtalk OA start failed (attempt {attempt}): {e}")
            if attempt >= OA_RETRY_TIMES:
                # 重试耗尽，降级
                return self._fallback(workflow, audit, flow, fallback_reason)
        except Exception as e:
            # 不可恢复错误，立即降级
            fallback_reason = f"unexpected: {e}"
            logger.exception(f"dingtalk OA start unexpected error: {e}")
            return self._fallback(workflow, audit, flow, fallback_reason)
    
    if start_result:
        WorkflowAuditExternal.objects.create(
            audit=audit, source="dingtalk_oa",
            external_process_instance_id=start_result.external_id,
            external_process_code=flow.dingtalk_process_code,
            external_status="RUNNING",
        )
    return start_result


def _fallback(self, workflow, audit, flow, reason):
    """降级：写特殊标记，强制走本地 Group 审批"""
    WorkflowAuditExternal.objects.create(
        audit=audit, source="dingtalk_oa",
        external_process_instance_id="",
        external_process_code=flow.dingtalk_process_code or "",
        external_status="FALLBACK",
        oa_failure_reason=reason[:500],
    )
    workflow.audit_driver = "archery"  # 强制回退到本地
    workflow.audit_fallback_reason = reason[:255]
    workflow.save(update_fields=["audit_driver", "audit_fallback_reason"])
    
    DingtalkOaEventLog.objects.create(
        audit=audit,
        event_type="FALLBACK_AT_START",
        payload={"flow": flow.code, "reason": reason},
        processed=True,
        error=reason[:1000],
    )
    
    notify_admin_fallback(workflow, reason)
    return DriverStartResult(external_id="", extra={"fallback": True, "reason": reason})
```

##### 2) `SqlWorkflow` 扩展字段

```python
# 在 sql/models.py 的 SqlWorkflow 上加 1 个字段（最小侵入）
class SqlWorkflow(models.Model, WorkflowAuditMixin):
    # ... 现有字段不动 ...
    
    # 兜底标记
    audit_fallback_reason = models.CharField(
        "审批驱动降级原因（钉钉 OA 失败时回退本地）",
        max_length=255, blank=True,
    )
```

##### 3) `WorkflowAuditExternal` 扩展字段

```python
class WorkflowAuditExternal(models.Model):
    # ... 现有字段 ...
    
    # 兜底相关（v0.6 新增）
    oa_status = models.CharField(
        "钉钉 OA 状态：RUNNING / DONE / FALLBACK",
        max_length=32, default="RUNNING",
    )
    oa_failure_reason = models.CharField(max_length=500, blank=True)
    fallback_at = models.DateTimeField(null=True, blank=True)
    reconcile_failed_count = models.IntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)
```

##### 4) Celery 兜底对账

```python
# sql/extensions/dingtalk_oa/tasks.py
@shared_task
def reconcile_pending_oa_workflows():
    """每 5 分钟扫一次 RUNNING 中超时的工单"""
    threshold = timezone.now() - timedelta(minutes=OA_RECONCILE_TIMEOUT_MIN)
    pending = WorkflowAuditExternal.objects.filter(
        oa_status="RUNNING",
        last_synced_at__lt=threshold,
    )
    
    for ext in pending:
        audit = ext.audit
        if audit.current_status != WorkflowStatus.WAITING:
            ext.oa_status = "DONE"
            ext.save()
            continue
        
        driver = get_driver("dingtalk_oa")
        try:
            status = driver.get_status(audit)
            if status.get("status") == "COMPLETED":
                ext.oa_status = "DONE"
                ext.save()
            elif status.get("status") == "RUNNING":
                ext.last_synced_at = timezone.now()
                ext.save()
        except Exception as e:
            logger.warning(f"reconcile {ext.audit.audit_id} failed: {e}")
            ext.reconcile_failed_count += 1
            ext.save()
            if ext.reconcile_failed_count >= 3:
                _force_fallback(ext, reason=f"reconcile failed 3 times: {e}")


def _force_fallback(ext, reason):
    """强制降级：把工单回退到本地 Group 审批"""
    audit = ext.audit
    workflow = audit.get_workflow()
    
    workflow.audit_driver = "archery"
    workflow.audit_fallback_reason = f"对账失败降级：{reason}"[:255]
    workflow.save()
    
    ext.oa_status = "FALLBACK"
    ext.oa_failure_reason = reason[:500]
    ext.fallback_at = timezone.now()
    ext.save()
    
    DingtalkOaEventLog.objects.create(
        audit=audit,
        event_type="FALLBACK_AT_RECONCILE",
        payload={"reason": reason},
        processed=True,
        error=reason[:1000],
    )
    notify_admin_fallback(workflow, reason)
```

##### 5) 兜底工单详情页横幅

```html
<!-- templates/sqlworkflow.html 扩展 -->
{% if workflow.audit_fallback_reason %}
<div class="alert alert-warning">
  ⚠️ 钉钉 OA 启动失败，已降级到本地 Group 审批
  <br>
  原因：{{ workflow.audit_fallback_reason }}
  <br>
  <small>该工单继续走本地审批，不影响业务</small>
  {% if perms.sql.audit_user %}
  <form method="post" action="{% url 'sql:retry_oa' workflow.id %}" style="margin-top:8px">
    {% csrf_token %}
    <button type="submit" class="btn btn-sm btn-primary">重试钉钉 OA</button>
  </form>
  {% endif %}
</div>
{% endif %}
```

#### 10.4.4 降级开关与可配置项

```ini
# .env.example 新增
# ====== 钉钉 OA 兜底策略 ======
CUSTOM_DINGTALK_OA_RETRY_TIMES=3              # 启动 OA 时的重试次数
CUSTOM_DINGTALK_OA_TIMEOUT_SECONDS=10         # 单次 API 调用超时
CUSTOM_DINGTALK_OA_RECONCILE_INTERVAL_MIN=5    # 轮询间隔
CUSTOM_DINGTALK_OA_RECONCILE_TIMEOUT_MIN=30    # 多久无回调触发对账
CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=True      # 兜底总开关（False=钉钉失败就阻塞）
```

`CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=False` 时：
- `driver.start()` 失败 → **不降级**，抛出异常阻塞业务
- 适合对一致性要求极高、不接受本地 Group 审批的场景

#### 10.4.5 降级后的告警与监控

- **实时告警**：每次 fallback 触发 `notify_admin_fallback()`，通过 `DingdingWebhookNotifier` 推送到 DBA 群
- **每日报告**：Celery 每日生成"昨日降级工单列表"
- **Dashboard 指标**：
  - `oa_fallback_count_24h` —— 24h 降级次数
  - `oa_reconcile_failure_count` —— 对账失败次数
  - `oa_avg_response_time` —— API 响应时间

#### 10.4.6 降级恢复

降级是**单工单级**的：
- 钉钉恢复后，**新工单**自动恢复正常走 OA
- **已降级工单**继续走本地 Group 审批，不回切
- 管理员可手动"重试 OA"：在工单详情页点按钮，调用 `DingtalkOaDriver.start()` 重新发起

```python
# sql/extensions/dingtalk_oa/views.py
@permission_required("sql.audit_user")
def retry_oa(request, workflow_id):
    workflow = get_object_or_404(SqlWorkflow, pk=workflow_id)
    audit = workflow.get_audit()
    policy = match_policy(workflow, extract_affected_tables(workflow))
    if not policy or policy.flow.audit_driver != "dingtalk_oa":
        messages.error(request, "当前工单策略不要求钉钉 OA")
        return redirect("sql:detail", workflow_id)
    
    try:
        driver = get_driver("dingtalk_oa")
        driver.start(workflow, audit, policy.flow)
        workflow.audit_fallback_reason = ""
        workflow.audit_driver = "dingtalk_oa"
        workflow.save()
        messages.success(request, "已重新发起钉钉 OA")
    except Exception as e:
        messages.error(request, f"重试失败：{e}")
    return redirect("sql:detail", workflow_id)
```

#### 10.4.7 测试用例

- [ ] Mock 钉钉 API 返回 500 → 应 fallback，本地 Group 审批继续
- [ ] Mock 钉钉 API 第一次 401，第二次成功 → 应重试 1 次后正常
- [ ] Mock 钉钉 API 连续 3 次 500 → 应 fallback
- [ ] 钉钉回调丢失 30 分钟 → 应对账后推进本地
- [ ] 钉钉回调丢失 3 次对账 → 强制 fallback
- [ ] 降级后 admin 手动重试 → 应恢复正常
- [ ] `CUSTOM_DINGTALK_OA_FALLBACK_ENABLED=False` → start 失败阻塞业务
- [ ] access_token 401 → 自动刷新重试

### 10.5 钉钉安全设计

**核心原则**：钉钉 OA 回调是**最敏感的攻击面**——没做签名校验意味着任何人都能伪造"审批通过"事件。本节覆盖所有安全设计点。

#### 10.5.1 回调签名验证（核心）

钉钉 OA 回调采用**加密 + 签名**双重保护：

```python
# sql/extensions/dingtalk_oa/security/crypto.py
import base64
import hashlib
import hmac
import json
import struct
from Crypto.Cipher import AES


class DingtalkCrypto:
    """钉钉 OA 回调加密/解密 + 签名校验"""

    def __init__(self, token: str, aes_key: str, receiveid: str = ""):
        if len(aes_key) != 43:
            raise ValueError("aes_key must be 43 chars (base64 without padding)")
        self.token = token
        self.receiveid = receiveid
        # aes_key 补 "=" 后 base64 解码，取前 32 字节
        self.aes_key = base64.b64decode(aes_key + "=")
        self.block_size = 32

    def verify_signature(self, timestamp: str, nonce: str,
                         encrypted_b64: str, signature: str) -> bool:
        """
        钉钉签名规则（v2.0）：
        1) 把 token、timestamp、nonce、encrypted_body 排序
        2) 拼接后 SHA1
        3) 与 URL 参数 signature 比较
        """
        params = sorted([self.token, timestamp, nonce, encrypted_b64])
        expected = hashlib.sha1("".join(params).encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, signature)

    def decrypt(self, encrypted_b64: str) -> dict:
        """
        AES-256-CBC 解密
        密文结构：random(16B) + msg_len(4B, 大端) + msg + receiveid
        """
        ciphertext = base64.b64decode(encrypted_b64)
        if len(ciphertext) < 32:
            raise ValueError("ciphertext too short")
        # IV 取 aes_key 前 16 字节
        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        plain = cipher.decrypt(ciphertext)
        # 跳过前面 16 字节 random
        plain = plain[16:]
        # msg_len 是 4 字节大端无符号整数
        msg_len = struct.unpack(">I", plain[:4])[0]
        msg = plain[4:4 + msg_len]
        # 校验尾部 receiveid
        tail = plain[4 + msg_len:4 + msg_len + len(self.receiveid)]
        expected = self.receiveid.encode("utf-8") if isinstance(self.receiveid, str) else self.receiveid
        if tail != expected:
            raise ValueError("receiveid mismatch")
        return json.loads(msg.decode("utf-8"))

    def encrypt(self, msg: dict) -> str:
        """加密（用于回调返回）"""
        msg_bytes = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        msg_len = struct.pack(">I", len(msg_bytes))
        random_bytes = os.urandom(16)
        plain = random_bytes + msg_len + msg_bytes + self.receiveid.encode("utf-8")
        # PKCS7 padding
        pad = self.block_size - len(plain) % self.block_size
        plain += bytes([pad] * pad)
        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        return base64.b64encode(cipher.encrypt(plain)).decode("utf-8")
```

回调入口完整流程：

```python
# sql/extensions/dingtalk_oa/callback.py
import time
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit


@csrf_exempt
@require_http_methods(["POST"])
@ratelimit(key="ip", rate="60/m", method="POST", block=True)  # 单 IP 限流
def dingtalk_oa_callback(request):
    """
    钉钉 OA 回调入口
    URL: /dingtalk/oa/callback
    """
    client_ip = _get_client_ip(request)

    # 0) IP 黑名单检查（防刷）
    if is_banned(client_ip):
        logger.warning(f"dingtalk callback from banned IP: {client_ip}")
        return HttpResponse("banned", status=403)

    # 1) timestamp 校验（防重放，5 分钟窗口）
    timestamp = request.GET.get("timestamp", "")
    nonce = request.GET.get("nonce", "")
    signature = request.GET.get("signature", "")
    try:
        ts_ms = int(timestamp)
    except (ValueError, TypeError):
        return HttpResponse("invalid timestamp", status=400)
    if abs(time.time() * 1000 - ts_ms) > 5 * 60 * 1000:
        logger.warning(f"dingtalk callback timestamp out of range: {timestamp}")
        return HttpResponse("timestamp expired", status=400)

    # 2) 验签
    crypto = get_crypto()
    encrypted_b64 = request.body.decode("utf-8")
    if not crypto.verify_signature(timestamp, nonce, encrypted_b64, signature):
        # 告警 + 累计失败计数（防暴力破解）
        notify_security_alert("signature_failed", {"ip": client_ip})
        record_signature_failure(client_ip)
        return HttpResponse("signature invalid", status=403)

    # 3) AES 解密
    try:
        event = crypto.decrypt(encrypted_b64)
    except Exception as e:
        logger.exception(f"dingtalk callback decrypt failed: {e}")
        return HttpResponse("decrypt failed", status=400)

    # 4) 幂等性检查（防重发）
    event_id = event.get("EventId") or _generate_event_id(event)
    if DingtalkOaEventLog.objects.filter(event_id=event_id, processed=True).exists():
        logger.info(f"dingtalk callback duplicate event_id={event_id}, skip")
        return _make_encrypted_response("success")

    # 5) 业务处理（路由到 ConfigurableAuditor）
    try:
        _handle_event(event, raw_encrypted=encrypted_b64, signature=signature)
    except Exception as e:
        logger.exception(f"handle dingtalk event failed: {e}")
        # 记失败事件，供人工排查
        DingtalkOaEventLog.objects.create(
            event_id=event_id, event_type=event.get("EventType", "unknown"),
            payload=sanitize_payload(event), processed=False, error=str(e),
        )
        return HttpResponse("internal error", status=500)

    # 6) 记成功日志
    DingtalkOaEventLog.objects.create(
        event_id=event_id, event_type=event.get("EventType"),
        payload=sanitize_payload(event), processed=True,
        raw_payload_encrypted=encrypted_b64[:1000],  # 密文留存，便于排查
    )
    return _make_encrypted_response("success")


def _make_encrypted_response(text: str) -> HttpResponse:
    """把响应也加密（钉钉要求）"""
    crypto = get_crypto()
    encrypted = crypto.encrypt({"errcode": 0, "errmsg": text})
    return HttpResponse(encrypted, content_type="text/plain")
```

#### 10.5.2 回调幂等性（防重放 + 防重发）

**`DingtalkOaEventLog` 新增字段**：

```python
class DingtalkOaEventLog(models.Model):
    # ... 现有字段 ...
    event_id = models.CharField(max_length=64, db_index=True, unique=True)  # 钉钉 EventId
    signature = models.CharField(max_length=128, blank=True)
    raw_payload_encrypted = models.TextField(blank=True)  # 密文留存，便于排查
```

幂等保证：
- 钉钉可能因网络原因**重发**相同回调
- `event_id` unique 约束，DB 层强制去重
- 重复事件**直接返回成功响应**（不报错，让钉钉停止重试），不重复处理

#### 10.5.3 操作员权限校验

钉钉推送的"审批人"必须在 `GroupDingtalkAuditor` 中，否则视为**未授权**：

```python
def verify_auditor_permission(audit, dingtalk_userid: str, decision: str):
    """钉钉推送的审批人必须在 GroupDingtalkAuditor 中"""
    current_group_id = int(audit.current_audit)
    try:
        auditor = GroupDingtalkAuditor.objects.get(
            group_id=current_group_id,
            is_active=True,
        )
    except GroupDingtalkAuditor.DoesNotExist:
        raise PermissionDenied(f"当前审批节点 {current_group_id} 未配置钉钉审批人")

    # 精确 userid 白名单
    allowed_userids = set(json.loads(auditor.dingtalk_user_ids or "[]"))
    # 按部门拉（动态）
    if auditor.dingtalk_dept_id:
        allowed_userids.update(get_dept_users_from_dingtalk(auditor.dingtalk_dept_id))

    if dingtalk_userid not in allowed_userids:
        # 钉钉里非配置的审批人点了通过/拒绝 → 严重事件
        notify_security_alert(
            "unauthorized_auditor",
            {
                "dingtalk_userid": dingtalk_userid,
                "audit_id": audit.audit_id,
                "decision": decision,
            },
            severity="critical",
        )
        raise PermissionDenied(f"钉钉用户 {dingtalk_userid} 无审批权限")


def get_dept_users_from_dingtalk(dept_id: str) -> set:
    """从钉钉拉部门下所有成员 userid（缓存 1 小时）"""
    cache_key = f"dingtalk_dept_users:{dept_id}"
    cached = cache.get(cache_key)
    if cached:
        return set(cached)
    # 调钉钉 API
    token = get_dingtalk_access_token()
    resp = requests.get(
        f"https://oapi.dingtalk.com/user/getDeptMember?access_token={token}&deptId={dept_id}",
        timeout=10,
    ).json()
    userids = resp.get("userIds", [])
    cache.set(cache_key, userids, timeout=3600)
    return set(userids)
```

#### 10.5.4 敏感字段脱敏

**原则**：SQL 全文、数据库密码等敏感信息**绝不**通过钉钉表单传递。

```python
def _build_form(workflow, audit, flow) -> list:
    """
    构建钉钉 OA 表单组件
    原则：只传工单摘要 + SQL 摘要 + 命中规则，SQL 全文不上传
    """
    return [
        {"name": "工单号", "value": str(workflow.id)},
        {"name": "提交人", "value": workflow.engineer_display},
        {"name": "目标库", "value": f"{workflow.instance.instance_name}/{workflow.db_name}"},
        {"name": "SQL 摘要", "value": _sql_summary(workflow.sqlworkflowcontent.sql_content)},
        {"name": "影响行数", "value": str(extract_affected_rows(workflow))},
        {"name": "命中规则", "value": _get_applied_policy_name(workflow)},
        {"name": "Archery 链接", "value": f"{settings.ARCHERY_BASE_URL}/sql/detail/{workflow.id}/"},
        # 完整 SQL 通过"详情"链接在 Archery 内查看（需要登录态）
    ]


def _sql_summary(sql: str, max_len: int = 200) -> str:
    """SQL 摘要：去注释 + 截断"""
    from sql.utils.sql_utils import remove_comments
    cleaned = remove_comments(sql).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "..."
    return cleaned
```

`DingtalkOaEventLog.payload` 入库前脱敏：

```python
SENSITIVE_KEYS = {"password", "passwd", "secret", "token", "access_key", "api_key"}


def sanitize_payload(payload: dict) -> dict:
    """事件 payload 脱敏后入库"""
    sanitized = json.loads(json.dumps(payload))  # 深拷贝
    for key in list(sanitized.keys()):
        if key.lower() in SENSITIVE_KEYS:
            sanitized[key] = "***REDACTED***"
    for key in ("sql_content", "sql_full", "raw_sql"):
        if key in sanitized:
            sanitized[key] = _sql_summary(sanitized[key])
    return sanitized
```

#### 10.5.5 IP 白名单与限流

**Nginx 层 IP 白名单**（钉钉回调服务器固定 IP）：

```nginx
# docker/nginx/nginx.conf 钉钉回调专属 location
location /dingtalk/oa/callback {
    # 钉钉回调服务器固定 IP（以钉钉官方文档为准）
    # 钉钉杭州
    allow 101.37.79.0/24;
    # 钉钉上海
    allow 140.205.94.0/24;
    # 钉钉深圳
    allow 203.119.214.0/24;
    # 钉钉北京
    allow 59.110.0.0/16;
    deny all;

    proxy_pass http://archery_app;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

**应用层限流**（Django 装饰器）：

```python
from django_ratelimit.decorators import ratelimit

@ratelimit(key="ip", rate="60/m", method="POST", block=True)
def dingtalk_oa_callback(request):
    ...
```

#### 10.5.6 密钥管理

```ini
# .env.example（已有，禁止提交到 git）
DINGTALK_OA_CALLBACK_TOKEN=        # 43+ 字符随机，钉钉后台生成
DINGTALK_OA_CALLBACK_AES_KEY=       # 43 字符 base64，钉钉后台生成
DINGTALK_OA_APP_KEY=                # 钉钉应用 AppKey
DINGTALK_OA_APP_SECRET=             # 钉钉应用 AppSecret
```

**密钥轮换流程**：

1. 钉钉后台 → 应用 → 事件订阅 → 修改 Token/AES Key
2. 旧密钥保留 5 分钟（双密钥并行）
3. 更新 `.env` 文件
4. 重启 gunicorn
5. 验证回调仍能解密
6. 钉钉后台移除旧密钥

**启动时密钥检查**：

```python
# scripts/check_dingtalk_secrets.py
def check_secrets():
    """启动前跑：检查密钥强度、是否使用默认值"""
    token = os.environ.get("DINGTALK_OA_CALLBACK_TOKEN", "")
    aes_key = os.environ.get("DINGTALK_OA_CALLBACK_AES_KEY", "")
    
    issues = []
    if len(token) < 32:
        issues.append("DINGTALK_OA_CALLBACK_TOKEN 太短")
    if len(aes_key) != 43:
        issues.append("DINGTALK_OA_CALLBACK_AES_KEY 长度必须为 43")
    if "example" in token.lower() or "test" in token.lower():
        issues.append("DINGTALK_OA_CALLBACK_TOKEN 像是默认值")
    
    if issues:
        raise RuntimeError(f"钉钉密钥配置有问题：{issues}")
```

**不同环境不同密钥**：

| 环境 | AppKey | AppSecret | Callback Token/AES |
|------|--------|-----------|-------------------|
| dev | dev_app | dev_secret | dev_random |
| staging | staging_app | staging_secret | staging_random |
| prod | prod_app | prod_secret | prod_random（**至少 90 天轮换一次**）|

#### 10.5.7 异常告警与封禁

```python
# sql/extensions/dingtalk_oa/security/guard.py
from django.core.cache import cache

SIGNATURE_FAIL_THRESHOLD = 10   # 连续失败次数
SIGNATURE_BAN_MINUTES = 60      # 封禁时长


def record_signature_failure(ip: str):
    """签名失败计数 + 自动封禁"""
    key = f"dingtalk_sig_fail:{ip}"
    count = cache.get(key, 0) + 1
    cache.set(key, count, timeout=SIGNATURE_BAN_MINUTES * 60)

    if count == SIGNATURE_FAIL_THRESHOLD:
        # 达到阈值，触发封禁
        ban_key = f"dingtalk_banned:{ip}"
        cache.set(ban_key, True, timeout=SIGNATURE_BAN_MINUTES * 60)
        notify_security_alert(
            "ip_banned_after_repeated_signature_failure",
            {"ip": ip, "failure_count": count, "ban_minutes": SIGNATURE_BAN_MINUTES},
            severity="critical",
        )
    elif count >= 3:
        # 累计失败 3 次就告警（防暴力破解）
        notify_security_alert(
            "repeated_signature_failure",
            {"ip": ip, "failure_count": count},
            severity="warning",
        )


def is_banned(ip: str) -> bool:
    return bool(cache.get(f"dingtalk_banned:{ip}", False))


def notify_security_alert(event_type: str, payload: dict, severity: str = "warning"):
    """安全告警：推到 DBA 群 + 邮件"""
    # 1) DBA 群 webhook
    from common.config import SysConfig
    from common.utils.sendmsg import MsgSender
    sys_config = SysConfig()
    webhook = sys_config.get("ding_security_webhook")
    if webhook:
        msg = f"[{severity.upper()}] 钉钉安全事件：{event_type}\n详情：{payload}"
        MsgSender().send_ding(webhook, msg)
    # 2) 邮件（重要事件）
    if severity == "critical":
        send_email_to_admins(subject=f"钉钉安全告警 {event_type}", body=str(payload))
    # 3) 记日志
    logger.warning(f"security alert [{severity}] {event_type}: {payload}")
```

#### 10.5.8 安全测试用例

- [ ] 伪造 timestamp（5 分钟外）→ 应拒绝 400
- [ ] 伪造 signature（错误 token）→ 应拒绝 403 + 计数
- [ ] 伪造 signature（错误 body）→ 应拒绝 403
- [ ] 重放攻击（同一 timestamp+nonce 重发）→ 应幂等返回成功
- [ ] AES 解密失败（密文损坏）→ 应拒绝 400
- [ ] 越界 msg_len → 应拒绝（防止 OOM）
- [ ] 钉钉用户非 GroupDingtalkAuditor → 应拒绝 + 告警
- [ ] 同一工单已 REJECTED，再收"通过"→ 应拒绝
- [ ] 敏感字段（密码/token）在 payload → 应脱敏
- [ ] IP 白名单外访问 → nginx 拒绝
- [ ] 单 IP 1 分钟 > 60 次 → 限流 429
- [ ] 连续签名失败 3 次 → 告警
- [ ] 连续签名失败 10 次 → 封禁 1 小时
- [ ] access_token 401 → 自动刷新重试
- [ ] 钉钉回调 URL 是 HTTP（非 HTTPS）→ 钉钉后台拒绝
- [ ] aes_key 长度 != 43 → 启动失败
- [ ] token 包含"example"或"test" → 启动告警

---

## 11. 待拍板子决策

> 这些是设计落地前需要 owner 决定的子决策。

1. **示例 flow seed**：启动时预置 `normal`/`critical` 2 个示例 flow？**推荐要**（开箱即用）
2. **fallback 流程**：所有 policy 都不命中时走哪个 flow？**推荐建 `default` flow 兜底**
3. **flow 删除保护**：被引用的 flow 允许删除？**推荐 PROTECT**（DB 强制）
4. **driver 删除保护**：被引用的 driver 允许从 registry 移除？**推荐不允许**（注册时校验）
5. **聚合方式**：用 `total`（总和）还是 `max`（单条最大）？**推荐 total**
6. **DDL 行数判定**：DDL 类不参与行数维度？**推荐是**（`has_affected_rows=False`）
7. **UI 提示**：工单详情页显示"命中规则"？**推荐要**（透明化、可解释）
8. **affected_rows 来源**：用审核阶段估算值（SQL 一提交就拿到）？**推荐估算即可**（审批在前执行在后）
9. **是否禁用 Archery 网页手动审批**（OA 流程）：**推荐禁用**（避免双入口不一致）
10. **钉钉应用**：新建独立 OA 应用还是复用 `AUTH_DINGDING`？**推荐独立**（更安全）

---

## 12. 待办事项

- [ ] Owner 拍板 §11 的 1-10 子决策
- [ ] 钉钉后台申请 OA 应用（阶段 0）
- [ ] 创建 2 个 OA 审批模板（普通/重大）
- [ ] 配置回调 URL（公网域名 + HTTPS）
- [ ] 输出第一阶段（阶段 1-2）任务清单
- [ ] 阶段评审：每完成 1 个阶段 review 一次

---

## 13. 附录

### 13.1 关键上游文件位置

| 文件 | 行数 | 作用 |
|------|------|------|
| `archery/settings.py` | 514 | Django 配置，含 `CURRENT_AUDITOR` |
| `sql/models.py` | 1387 | WorkflowAudit/Setting/Detail/Log/SqlWorkflow |
| `sql/utils/workflow_audit.py` | 800+ | `AuditV2` 核心审批引擎 |
| `sql/sql_workflow.py` | 522 | 工单视图（submit/pass/reject/cancel/execute）|
| `sql/notify.py` | 546 | 通知机制（已有 DingdingWebhookNotifier 等）|
| `common/utils/ding_api.py` | 129 | 钉钉 access_token 缓存 |
| `common/authenticate/dingding_auth.py` | - | 钉钉认证 |
| `common/config.py` | 100+ | `SysConfig`（从 sql_config 表读配置）|

### 13.2 二次开发规范

- 所有新功能在 `sql/extensions/dingtalk_oa/` 下
- 核心文件（`sql/`、`common/`、`archery/settings.py`）只做最小接入
- 每次 commit 带 changelog（`docs/changelogs/YYYY-MM-DD_<short>.md`）
- 配置走环境变量（`.env` + `archery/settings.py` 读 env）

### 13.3 配置项清单

```ini
# .env.example 新增
# ====== 钉钉 OA 审批（内部定制）======
CUSTOM_DINGTALK_OA_ENABLED=False
CUSTOM_DINGTALK_OA_AUDITOR=sql.extensions.audit_drivers.configurable_auditor:ConfigurableAuditor

# 钉钉智能工作流应用
DINGTALK_OA_APP_KEY=
DINGTALK_OA_APP_SECRET=
DINGTALK_OA_AGENT_ID=

# 回调地址（公网域名 + HTTPS）
ARCHERY_BASE_URL=https://archery.example.com
DINGTALK_OA_CALLBACK_PATH=/dingtalk/oa/callback
DINGTALK_OA_CALLBACK_TOKEN=
DINGTALK_OA_CALLBACK_AES_KEY=
```

### 13.4 参考资料

- [钉钉开放平台 - 智能工作流（OA 审批）](https://open.dingtalk.com/document/orgapp/approval-process)
- [Archery 官方文档](https://github.com/hhyo/Archery/wiki)
- [Archery v1.14.0 release](https://github.com/hhyo/Archery/releases/tag/v1.14.0)

---

**文档版本**：v0.7
**最后更新**：2026-07-20（新增 §10.5 钉钉安全设计）
