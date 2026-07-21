# 钉钉 OA 流程配置使用说明

> **目标读者**: DBA / 运维 / 二次开发同事
> **配套文档**:
> - [设计: docs/designs/2026-07-20_dingtalk-oa-workflow.md](../designs/2026-07-20_dingtalk-oa-workflow.md)
> - [故障排查: dingtalk-oa-troubleshooting.md](./dingtalk-oa-troubleshooting.md)
> - [Changelog: 2026-07-20_coder-dingtalk-oa-driver-integration.md](../changelogs/2026-07-20_coder-dingtalk-oa-driver-integration.md)
> **代码位置**: `sql/extensions/dingtalk_oa/`
> **最后更新**: 2026-07-21

---

## 1. 功能概述

### 1.1 解决什么问题

**之前**: SQL 审核工单只能在 Archery 内部走（指定审批人 → 人工审 → 通过/拒绝）。DBA 没法用钉钉工作流看工单状态，没法在钉钉里批。

**之后**: SQL 工单**按 3D 策略自动匹配**审批驱动（archery 内审 / 钉钉 OA 外审），钉钉 OA 端**复用钉钉工作流的审批人配置、消息通知、进度同步**，DB 团队不用切到 Archery 就能批。

### 1.2 适用场景

| 场景 | 驱动 |
|---|---|
| 简单 DQL（SELECT） | archery 内审（轻量） |
| 涉及核心业务表（订单、用户）的 DML | 钉钉 OA（走钉钉工作流） |
| 高风险 DDL（DROP / TRUNCATE） | 钉钉 OA + 二次确认 |
| 失败回退 | archery 内审（兜底） |

### 1.3 不适用场景

- 紧急 SQL 审批（钉钉 OA 异步 + 5min 回调延迟，紧急场景用 Archery 内审）
- 涉及多个钉钉应用跨租户（钉钉 OA 单应用设计）
- 不在审批流模板里的操作（白名单外默认 archery 内审）

---

## 2. 架构概览

### 2.1 数据流

```
SQL 工单提交
    ↓
Archery SqlWorkflow.audit_driver = "archery" | "dingtalk_oa"   (policy 命中时锁定)
    ↓
ConfigurableAuditor.audit()  (CURRENT_AUDITOR 注入)
    ↓
┌─────────────────────┬────────────────────────┐
│  ArcheryDriver       │  DingtalkOaDriver        │
│  (内审, 现成)        │  (新)                    │
└─────────────────────┴────────────────────────┘
    ↓
approve / reject
    ↓
callback (DingTalk → Archery /dingtalk/oa/callback/)
    ↓
DingtalkOaEventLog 记录事件
    ↓
WorkflowAuditExternal 同步外部状态
    ↓
失败 3 次 → fallback → audit_driver 改 "archery" + audit_fallback_reason 记录原因
```

### 2.2 三方关系

| 角色 | 责任 |
|---|---|
| 业务用户 | 在 Archery 提交 SQL 工单 |
| 审核人 | 在钉钉 OA 审批 |
| DBA 管理员 | 在 Archery admin 配置 policy/flow/callback 凭据 |

---

## 3. 部署清单（admin 必做）

### 3.1 必填项

- [ ] 钉钉 OA 应用凭据（5 个）填到 `/opt/archery/{staging,prod}/.env`
- [ ] admin 后台改 `ext_approval_flow.audit_auth_groups` 从占位 `'1,2'` 改成实际审批组 ID
- [ ] 钉钉开放平台配回调 URL `https://<your-domain>/dingtalk/oa/callback/`
- [ ] 钉钉 OA 审批模板 ID 填到 `ext_approval_flow.dingtalk_process_code`

### 3.2 必装项（自动化已完成）

- [x] 钉钉 OA 7 张表（`makemigrations dingtalk_oa` + `migrate`）
- [x] 13 个 SQL types 种子（`seed_sql_types` command）
- [x] 默认 fallback flow（`init_fallback_flow` command）
- [x] URL 路由接入（`/dingtalk/oa/` 命名空间）
- [x] 钉钉 OA 端点（`/dingtalk/oa/audit_flow/`, `/dingtalk/oa/audit_policy/`, `/dingtalk/oa/callback/`）

---

## 4. 配置流程

### 4.1 钉钉开放平台后台（一次性配置）

#### Step 1: 创建应用

1. 登录 https://open-dev.dingtalk.com
2. 「应用开发」→「企业内部开发」→「创建应用」
3. 类型: **H5 微应用** 或 **企业内部应用**
4. 应用名: `Archery SQL 审核`（团队内能识别即可）
5. 应用描述: SQL 工单审批

#### Step 2: 开通权限

1. 「权限管理」开通：
   - `OA 审批` - 用于发起审批
   - `通讯录` - 用于获取审批人信息
2. 「安全设置」配置：
   - IP 白名单: Archery 服务器公网 IP
   - 重定向 URL: `https://<your-domain>/dingtalk/oa/callback/`

#### Step 3: 创建审批模板

1. 「OA 管理」→「审批」→ 新建审批
2. 模板示例：
   ```
   审批模板名: SQL 工单审批 v1
   表单字段:
     - SQL 内容 (多行文本, 必填)
     - 数据库 (单行文本)
     - 申请人 (单行文本)
     - 申请人邮箱 (单行文本)
     - 申请单号 (单行文本)
     - 风险等级 (单选: 高/中/低)
   审批人: 流程发起人自选 / 指定审批人 / 审批组
   ```
3. 记录**审批模板 code**（`dingtalk_process_code`）

#### Step 4: 配事件订阅（callback）

1. 「应用信息」→「事件订阅」
2. 请求 URL: `https://<your-domain>/dingtalk/oa/callback/`
3. 加密方式: **AES-256-CBC**
4. 记录 **Token** + **EncodingAESKey**

#### Step 5: 拿凭据

| 凭据 | 在哪 | 填到哪 |
|---|---|---|
| AppKey | 应用信息 → 基础信息 | `DINGTALK_OA_APP_KEY` |
| AppSecret | 应用信息 → 基础信息 | `DINGTALK_OA_APP_SECRET` |
| AgentId | 应用信息 → 基础信息 | `DINGTALK_OA_AGENT_ID` |
| 回调 Token | 事件订阅 | `DINGTALK_OA_CALLBACK_TOKEN` |
| 回调 AES Key | 事件订阅 | `DINGTALK_OA_CALLBACK_AES_KEY` |
| 加密 ReceiveId | 应用信息 | `DINGTALK_OA_CALLBACK_RECEIVEID` |

### 4.2 Archery .env 配置

```bash
# 服务器上
sudo vim /opt/archery/staging/.env
```

填入（替换 `<...>` 占位）：

```bash
# 钉钉 OA 凭据
DINGTALK_OA_APP_KEY=<你的 AppKey>
DINGTALK_OA_APP_SECRET=<你的 AppSecret>
DINGTALK_OA_AGENT_ID=<你的 AgentId>
DINGTALK_OA_CALLBACK_TOKEN=<回调 Token>
DINGTALK_OA_CALLBACK_AES_KEY=<回调 AES Key>
DINGTALK_OA_CALLBACK_RECEIVEID=<加密 ReceiveId>

# 失败告警 webhook（DBA 群机器人，可选）
DINGTALK_NOTIFY_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=<机器人 token>
```

改完**重启 gunicorn**:

```bash
pkill -f gunicorn
sleep 2
sudo -Hu archery bash -c \
  'cd /opt/archery/staging && set -a && source .env && set +a && \
   /opt/archery/staging/venv/bin/gunicorn archery.wsgi:application \
     -w 2 -b 0.0.0.0:9002 \
     --access-logfile - --error-logfile - --timeout 120 \
     > /var/log/archery/staging-gunicorn.log 2>&1 &'
```

### 4.3 Archery admin 后台配置

访问 `http://<your-domain>/admin/`，登录 archery 用户。

#### 4.3.1 改默认 fallback flow

1. 左侧导航 → 「dingtalk_oa」→「Approval flows」
2. 点 code=`default` 的 flow 进入编辑
3. **Audit auth groups**: 改成实际审批组 ID（逗号分隔）:
   - 例如 `1,2,3` 表示 auth_group 表的 id=1, 2, 3 三个组
4. 保存

#### 4.3.2 建钉钉 OA ApprovalFlow

1. 左侧导航 → 「dingtalk_oa」→「Approval flows」→ 「Add approval flow」
2. 字段：

| 字段 | 值 | 说明 |
|---|---|---|
| Code | `prod_dml` | 唯一标识，policy 引用 |
| Name | 生产 DML 走钉钉 OA | 描述性 |
| Description | 生产环境 DML 走钉钉 OA 审批 | |
| Audit driver | `dingtalk_oa` | 关键：必须选这个 |
| Dingtalk process code | `<4.1 Step 3 的审批模板 code>` | |
| Is active | ✓ | 启用 |
| Audit auth groups | `1,2`（fallback 用，policy 不命中时走这里） | |

3. 保存

#### 4.3.3 建 ApprovalPolicy

1. 左侧导航 → 「dingtalk_oa」→「Approval policies」→ 「Add approval policy」
2. 字段示例（高风险 DML 走钉钉）：

| 字段 | 值 |
|---|---|
| Name | 高风险 DML 走钉钉 |
| Priority | 10 |
| Is enabled | ✓ |
| Severity | high |
| Flow | 选 `prod_dml`（刚建的 flow） |
| Sql types | DELETE, UPDATE, INSERT |
| Sql type match mode | `any`（任一匹配） |
| Min affected rows | 100 |
| Max affected rows | （空 = 无上限） |
| Core business tables | （空，或选具体表） |
| Core table match mode | `any` |
| Risk level filter | `high` |

3. 保存

**3D 策略匹配规则**:
- SQL 类型 ∩ 核心表 ∩ affected_rows 范围
- 多个 policy 时，priority 数字大的优先；priority 相同按创建时间
- **policy 命中时锁定** `audit_driver` 字段，工单创建后 policy 变更不影响历史工单

#### 4.3.4 建 CoreBusinessTable（可选）

如果想"涉及某些表走钉钉 OA"，建核心业务表：

1. 左侧导航 → 「dingtalk_oa」→「Core business tables」→ 「Add core business table」
2. 字段：
   - Instance: 选目标实例
   - Db name: 库名
   - Table name: 表名（支持逗号分隔多表）
   - Level: L1=致命 / L2=重要 / L3=一般
   - Remark: 备注
   - Is active: ✓

#### 4.3.5 建 GroupDingtalkAuditor（可选）

如果想让某个资源组走不同的钉钉审批人：

1. 左侧导航 → 「dingtalk_oa」→「Group dingtalk auditors」→ 「Add group dingtalk auditor」
2. 字段：
   - Group: auth_group id
   - Resource group: resource_group id
   - Dingtalk user ids: `user1,user2`（逗号分隔）
   - Dingtalk dept id: 部门 id（钉钉侧）
   - Is active: ✓

---

## 5. 日常使用

### 5.1 业务用户提交 SQL

1. 登录 Archery → 「SQL 审核」→ 「提交工单」
2. 填 SQL + 选实例 + 选环境
3. 提交
4. 系统**自动匹配 policy**，决定 `audit_driver`：
   - `archery`（内审）→ Archery 审核人审批
   - `dingtalk_oa`（外审）→ 发起钉钉审批，钉钉里批

### 5.2 审核人审批

#### Archery 内审
- 登录 Archery → 「SQL 审核」→ 看到待审工单 → 批准/拒绝

#### 钉钉 OA 审批
- 钉钉工作通知推送 → 点开 → 钉钉 OA 审批页 → 批/拒
- 钉钉自动 callback → Archery 收到 → `DingtalkOaEventLog` 记录
- Archery 同步状态（`WorkflowAuditExternal.external_status`）

### 5.3 进度同步

- **DingTalk → Archery**: callback 每 5min 同步一次（django-q2 schedule）
- **Archery → DingTalk**: Archery 看到状态后回写到钉钉实例

---

## 6. 故障回退

### 6.1 自动回退

**触发条件**: 钉钉 OA 端**重试 3 次**失败（网络超时 / 钉钉服务端 5xx / 凭据失效）

**回退流程**:
1. `audit_driver` 改为 `archery`
2. `audit_fallback_reason` 记录失败原因
3. `DingtalkOaEventLog` 记 `event_type=failover`
4. 钉钉 webhook 告警 DBA 群

**业务无感**: 用户还是能在 Archery 看到工单，只是审批人从钉钉切到 Archery 内审

### 6.2 手工回退

紧急情况下，DBA 可以手工把 `sql_workflow.audit_driver` 从 `dingtalk_oa` 改回 `archery`：
```sql
UPDATE sql_workflow SET audit_driver='archery', audit_fallback_reason='人工回退' WHERE id=<工单 id>;
```

### 6.3 故障排查

详见: [dingtalk-oa-troubleshooting.md](./dingtalk-oa-troubleshooting.md)

常见症状速查:
- **callback 验签失败**: AES Key / Token 不对 → 检查 .env
- **policy 一直不命中**: 字段值不匹配 → 看 SQL 类型 + 表名 + affected_rows
- **driver 总是 fallback**: 钉钉服务端不通 → curl 测试网络 + 凭据

---

## 7. 监控

### 7.1 关键表

```sql
-- 看最近回退的工单
SELECT id, workflow_name, audit_driver, audit_fallback_reason, status, update_time
FROM sql_workflow
WHERE audit_fallback_reason != ''
ORDER BY update_time DESC
LIMIT 20;

-- 看钉钉事件日志
SELECT id, event_type, audit_id, processed, error, created_at
FROM ext_dingtalk_oa_event_log
ORDER BY id DESC
LIMIT 50;

-- 看未同步的外部状态
SELECT id, audit_id, source, external_status, last_synced_at
FROM ext_workflow_audit_external
WHERE external_status NOT IN ('approved', 'rejected')
ORDER BY id DESC
LIMIT 20;
```

### 7.2 关键日志

```bash
# gunicorn stdout（access log + error log 合并）
tail -f /var/log/archery/staging-gunicorn.log

# django-q2 调度日志（钉钉同步任务）
sudo -Hu archery -H bash -lc \
  "cd /opt/archery/staging && set -a && source .env && set +a && \
   venv/bin/python manage.py qmonitor"
```

### 7.3 告警

`DINGTALK_NOTIFY_WEBHOOK` 触发条件:
- 钉钉 driver 失败 3 次 → fallback 触发 → 通知 DBA
- callback 验签失败 → 通知 DBA
- 同步任务超时 → 通知 DBA

---

## 8. 角色 + 权限

| 操作 | 需要 |
|---|---|
| 查看 SQL 工单 | 业务用户（auth_user.is_active） |
| 提交 SQL 工单 | 业务用户 + auth_group 权限 |
| 审批 SQL 工单 | audit_auth_groups 里的人 |
| 配置钉钉 OA 凭据 | DBA（root 权限，.env） |
| 配置 ApprovalFlow/Policy | superuser（admin 后台） |
| 修改 audit_auth_groups | superuser（admin 后台） |

---

## 9. 常见问题

### Q1: 工单提交后一直在「待审核」状态

- 检查 `audit_driver` 字段：是不是 `archery`（不是 `dingtalk_oa`）？
- 如果是 `dingtalk_oa`：看 `ext_dingtalk_oa_event_log` 有没有 error
- 看 `DINGTALK_NOTIFY_WEBHOOK` 有没有 fallback 告警

### Q2: 钉钉里看到审批了，但 Archery 状态没更新

- 检查 `/dingtalk/oa/callback/` 端点是否 200（看 `ext_dingtalk_oa_event_log`）
- 检查钉钉开放平台的事件订阅 URL 是否正确（必须 HTTPS）
- 检查 AES Key / Token 是否一致

### Q3: 修改了 policy 但历史工单没变

- **设计如此**：`audit_driver` 字段在 policy 命中时锁定，后续 policy 变更不影响
- 如需修改：直接改 `sql_workflow.audit_driver`

### Q4: 想临时关掉钉钉 OA，所有工单回内审

```bash
# 服务器上
sudo vim /opt/archery/staging/.env
# 改：CUSTOM_DINGTALK_OA_ENABLED=False
pkill -f gunicorn
sudo -Hu archery bash -c \
  'cd /opt/archery/staging && set -a && source .env && set +a && \
   /opt/archery/staging/venv/bin/gunicorn archery.wsgi:application ...'
```

或者 SQL 一键：
```sql
UPDATE sql_workflow SET audit_driver='archery', audit_fallback_reason='DBA 临时关停' WHERE audit_driver='dingtalk_oa';
```

### Q5: 钉钉 OA 怎么走 callback？服务端主动 push 还是 Archery 拉？

**钉钉主动 push**（推荐）: 钉钉审批状态变更 → POST 到 `/dingtalk/oa/callback/` → Archery 处理

**Archery 兜底拉取** (5min 一次): 用 `WorkflowAuditExternal.last_synced_at` + django-q2 schedule 任务，万一 push 漏了也能 sync

---

## 10. 变更历史

| 日期 | 变更 | 负责人 |
|---|---|---|
| 2026-07-20 | 初始设计文档 v0.5 | Mavis |
| 2026-07-20 | driver 集成 commit cb5b0b5 / 85d859e / 342b494 | coder-agent |
| 2026-07-21 | 部署到 staging (b99dbda) | Mavis |
| 2026-07-21 | 补全 missing 环节（migrations / URL / seed）| Mavis |

---

**有问题先看**: [dingtalk-oa-troubleshooting.md](./dingtalk-oa-troubleshooting.md)
**没找到再找**: DBA 团队（联系开发同事）
