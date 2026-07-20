# 架构与模块说明

> 基于 Archery v1.14.0。详细 API/模型以代码为准。

## 1. 整体架构

```
┌──────────────────────────────────────────────────────┐
│                       Browser                        │
│                  (Vue + Element UI)                  │
└────────────────────────┬─────────────────────────────┘
                         │ HTTP
┌────────────────────────▼─────────────────────────────┐
│                      Nginx                           │
└────────────────────────┬─────────────────────────────┘
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
│   Web       │   │  Celery     │   │  Celery     │
│ (gunicorn)  │   │  Worker     │   │  Beat       │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       │                 │                 │
       └────────┬────────┴─────────┬───────┘
                │                  │
        ┌───────▼──────┐    ┌──────▼──────┐
        │    MySQL     │    │    Redis    │
        │ (元数据库)    │    │ (缓存/队列) │
        └──────────────┘    └─────────────┘
                │
                │  通过 SQLAlchemy/sqlparse
                │  访问业务数据库
                ▼
        ┌──────────────────────┐
        │  业务 MySQL 实例集群  │
        │  (被管理的目标库)      │
        └──────────────────────┘
```

## 2. Django Apps

| App | 职责 | 是否可改 |
|-----|------|----------|
| `archery` | Django 配置、URLConf、WSGI | 极慎重 |
| `sql` | SQL 审核/执行/查询/工单 主模块 | 二次开发主战场 |
| `sql_api` | 内部 REST API | 优先扩展 |
| `common` | 公共组件：认证/菜单/权限 | 改动全局影响 |
| `dashboard` | 仪表板/统计 | 独立 |

## 3. sql 模块核心模型（参考）

- `Users` —— 用户
- `ResourceGroup` / `ResourceInstance` / `DataSource` —— 资源管理
- `Workflow` / `WorkflowLog` —— 工单
- `SqlWorkflow` / `SqlWorkflowContent` —— SQL 工单
- `QueryLog` / `QueryAudit` —— 查询日志与审计
- `AuditConfig` / `AuditRule` —— 审核规则
- `Instance` —— 数据库实例元信息

> 具体字段以合入上游后的 `sql/models.py` 为准。

## 4. SQL 审核流程

```
用户提交 SQL
   ↓
[1] 语法解析 (sqlparse)
   ↓
[2] 实例 / 库 / 表元信息收集
   ↓
[3] 规则匹配（本地规则 + soar/sqladvisor 等可选）
   ↓
[4] 生成审核结果（高危/中危/低危/建议）
   ↓
[5] 工单审批流转
   ↓
[6] 执行（goInception/Yearning-client/直连）
   ↓
[7] 执行结果回写 + 审计日志
```

## 5. 二次开发常见切入点

| 需求 | 切入点 |
|------|--------|
| 新增审核规则 | `sql/sqlreview/` + `AuditRule` 模型 |
| 自定义工单审批流 | `sql/workflow.py` + `Workflow` 状态机 |
| 数据脱敏 | `sql/query.py` + 中间件 |
| 通知渠道（飞书/钉钉/企微） | `sql/notify.py` |
| 权限细分 | `common/permissions.py` + `ResourceGroup` |
| 资源拓扑 | `sql/resource_group.py` + `Instance` |
| 审计增强 | `sql/query_audit.py` + Celery 任务 |

## 6. 异步任务（Celery）

主要队列：

- `default` —— 通用
- `sql` —— SQL 执行、查询
- `audit` —— 审核相关

主要任务：

- `sql.tasks.execute_workflow` —— 执行工单
- `sql.tasks.sync_instance_schema` —— 同步实例元数据
- `dashboard.tasks.refresh_stats` —— 刷新统计
- `common.tasks.send_notify` —— 发送通知

## 7. 扩展点清单

1. **自定义审核规则**：注册到 `AUDIT_RULE_REGISTRY`
2. **自定义数据库引擎**：实现 `BaseEngine` 接口
3. **自定义通知渠道**：实现 `BaseNotifier` 接口
4. **自定义认证后端**：实现 Django `auth_backends`
5. **自定义权限**：注册到 `PERMISSION_REGISTRY`

> 合入上游代码后请同步更新本文件。
