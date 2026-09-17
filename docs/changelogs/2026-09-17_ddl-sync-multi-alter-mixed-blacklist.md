# DDL-Sync 多 ALTER 工单 + 混合黑/白名单修复

> **变更日期**：2026-09-17 16:45
> **修复者**：mavis
> **影响范围**：DBA 团队的 DDL 跨库自动同步 (`sql/extensions/ddl_sync/`)
> **关联**：
> - 实战工单：wf#4841 形态（4 CREATE + 4 ALTER，9/16 实战触发）
> - 用户拍板：9/17 13:58 阿达叔叔确认
> - changelog: 本文件

## 业务背景

DBA 配 DdlSyncPair 黑/白名单后，业务方提交工单含**多条 ALTER** 时，需要每个 ALTER **独立判定**白/黑名单：
- 名单外的表 → 写 DdlSyncHistory(`skipped`) 留 DBA 排查
- 名单内的表 → 拼成镜像工单的 SQL（含全部 kept 的 ALTER）

修复前的 Bug：
- `_extract_table_name()` 只返**第一个** ALTER 的表名，整个工单只用第一个表去判定白/黑名单
  - 多 ALTER 工单里其他表被忽略
  - 第一表在黑名单 → 整个工单不触发镜像（其他白名单的表也丢同步）
  - 第一表不在白名单 → 整个工单不触发镜像
- 即使触发镜像工单，`ddl_text = sql_content` **全文**不过滤，把不该同步的 ALTER 也带上

## 修复方案

### 1. 新增 `_extract_all_alters()`

```python
def _extract_all_alters(sql_content: str) -> list:
    """提取 SQL 里所有 ALTER TABLE 的 table_name + 完整语句 (扫所有, 不只是第一个).

    Returns:
        list of {"db": str|None, "table": str|None, "full": str}
        空 SQL / 没 ALTER 返 []
    """
```

特性：
- 按 `;` 分割 SQL
- 跳过 `use xxx;` 前缀（9/11 DBA-bug-1 实战踩坑）
- 跳过 `--` 注释行 + 空行
- 用 `_ALTER_PATTERN` (已 9/12 DBA-bug-5a 修反引号 schema) 匹配
- `db_raw.replace("`", "")` + `rstrip(".")` 处理反引号边界（9/17 实战新发现）
- 返 `[{"db", "table", "full"}]` list

### 2. 改造 `workflow_passed_handler`

```python
all_alters = _extract_all_alters(sql_content)
if not all_alters:
    return  # 没 ALTER, 不触发 (Phase 2 加 CREATE/DROP/RENAME)

for pair in pairs:
    kept_alters = []
    skipped_alters = []

    # 5.1 对每个 ALTER 独立判定白/黑名单
    for alter in all_alters:
        if _should_sync(pair, alter["table"]):
            kept_alters.append(alter)
        else:
            skipped_alters.append(alter)

    # 5.2 写 skipped history (每个 skipped ALTER 一条, DBA 排查用)
    for alter in skipped_alters:
        DdlSyncHistory.objects.create(
            pair=pair,
            source_workflow=instance,
            table_name=alter["table"],
            ddl_text=alter["full"],
            sync_status="skipped",
            error_message="白/黑名单不匹配 (orphan) - 9/17 DDL-Sync-Bug-A 多 ALTER split",
            finished_at=timezone.now(),
        )

    # 5.3 没 kept ALTER → 不创建镜像工单
    if not kept_alters:
        continue

    # 5.4 拼 kept 的 sql_content (只含通过名单的 ALTER, 不是全文)
    kept_sql = "\n".join([alter["full"] for alter in kept_alters])

    # 5.5 应用 transform_rule
    transformed_ddl = _apply_transform_rule(kept_sql, pair, kept_alters[0]["table"])

    # 5.6 创建镜像工单 + 走 audit_setting
    try:
        target_workflow = create_target_workflow(instance, pair, transformed_ddl)
    except Exception as e:
        # 失败标 failed 不阻塞主流程
        ...

    # 5.7 写 syncing history (每个 kept 一条, target_workflow 共享)
    for alter in kept_alters:
        DdlSyncHistory.objects.create(
            pair=pair,
            source_workflow=instance,
            target_workflow=target_workflow,
            table_name=alter["table"],
            ddl_text=alter["full"],
            transformed_ddl_text=transformed_ddl,
            sync_status="syncing",
        )
```

### 3. deprecate `_extract_table_name()` 兼容老代码

```python
def _extract_table_name(sql_content: str) -> str:
    """提取 ALTER TABLE 的 table_name (DEPRECATED, 保留兼容老代码)."""
    alt = _extract_all_alters(sql_content)
    return alt[0]["table"] if alt else ""
```

保留函数兼容老测试代码 + 9/17 之前的脚本。

## 演练验证 (7/7 PASS)

**脚本**：`scripts/_w3_ddlsync_bug_verify.py`（_extract_all_alters 单元测试）

| Case | 输入 | 期望 | 实际 |
|------|------|------|------|
| 1 | `ALTER TABLE t1 ADD COLUMN c int;` | 1 条 | ✅ table=t1 |
| 2 | 多 ALTER 混合名单 `t_blacklist + t_whitelist` | 2 条 | ✅ tables=[t_blacklist, t_whitelist] |
| 3 | `use xx;\n-- 注释\nALTER TABLE a ADD COLUMN c int;\nALTER TABLE b ADD COLUMN c int;` | 2 条 | ✅ |
| 4 | 反引号 schema `` ALTER TABLE `hly_billing`.`consume_flow` ADD INDEX ...`` | 1 条 | ✅（9/12 DBA-bug-5a 修过） |
| 5 | 空 SQL `""` | 0 条 | ✅ |
| 6 | 只有 CREATE 没 ALTER `CREATE TABLE t (id int);` | 0 条 | ✅ |
| 7 | wf#4841 实战 4 ALTER (`accesscard_licensefront_info` / `vehicle_info_verify` / `accesscard_vehicle_review` / `accesscard_opendcardapply`) | 4 条 | ✅ |

## 端到端演练 (e2e PASS)

**脚本**：`scripts/_w3_ddlsync_e2e_drill.py`

配置：
- pair id=1 (blacklist 模式)
- 配 `DdlSyncTable(sync_type=blacklist, table_name=v0_ddlsync_test_blacklist)`

模拟工单 sql_content：
```sql
ALTER TABLE v0_ddlsync_test_blacklist ADD COLUMN c1 int;
ALTER TABLE v0_ddlsync_test_whitelist ADD COLUMN c2 int;
```

实际跑通结果（134 dev + 110 prod 双向 PASS）：
- `history_blacklist.sync_status = 'skipped'` ✅
- `history_whitelist.sync_status = 'syncing'` ✅
- 镜像工单 `sql_content` = `'ALTER TABLE v0_ddlsync_test_whitelist ADD COLUMN c2 int;'` ✅
  - **不含 blacklist 表的 ALTER**，过滤生效
- `transaction.savepoint_rollback` 干净，db 未污染 ✅

## 部署 (DBA 一条龙)

### 134 dev (9/17 14:55)
- 推 1 个文件（`sql/extensions/ddl_sync/services/sync_trigger.py`）
- 推 2 个演练脚本（`_w3_ddlsync_bug_verify.py` + `_w3_ddlsync_e2e_drill.py`）
- `systemctl restart archery-prod-gunicorn.service`（业务中断 ~10 秒）
- HTTP 200 + 7/7 + e2e PASS ✅

### 110 prod (9/17 16:42)
**踩坑 (9/17 实战新发现)**：
- memory 里 110 prod 路径 `/dbdata/archery_v114_c9236a0/` 实际是对的，但**真实跑的是 c9236a0 目录**
- systemd 服务 (`archery-v114-gunicorn.service`) 9/8 就 failed 了，之后都是手动跑的
- pkill gunicorn + 用 `--daemon --pid /tmp/gunicorn_110.pid` 启动
- 需要 source `.env` + export `CAS_SERVER_URL/CAS_SERVER_PORT/CAS_REALM/CAS_LOGIN_URL/CAS_VALIDATE_URL/CAS_LOGOUT_URL/CAS_VERSION` 占位 env vars（settings.py:493 env() 没 default）
- HTTP 200 + 7/7 + e2e PASS ✅

## 实战新发现 (跨项目可复用)

### 1. ddl_sync 多 ALTER 处理规则 (跨项目 ddl_sync 通用)
跨项目写 DDL 同步 / 镜像工单系统，处理**多 ALTER 工单** + **混合白/黑名单**时：
- 用 `_extract_all_alters` 返 `list[{db, table, full}]`
- `workflow_passed_handler` 循环每个 ALTER **独立判定**白/黑名单
- skipped ALTER 写 `DdlSyncHistory(sync_status='skipped', error_message='9/17 DDL-Sync-Bug-A 多 ALTER split')`，DBA 排查
- kept ALTER 拼**新 sql_content** 创建镜像工单（只含 kept 的 ALTER，不再是全文）

### 2. db_raw 反引号边界处理 (跨项目 regex 实战)
- 老 `strip("`")` 处理 `\`.\`反引号\`边界不彻底
- 修法: `db_raw.replace("`", "").rstrip(".")` 先去掉所有反引号再 split

### 3. 110 prod 真实跑路径是 `archery_v114_c9236a0/` (9/17 实战新发现, 跨环境部署教训)
- memory 里旧版 "110 prod 路径 = `/dbdata/archery_v114/`" 是错的
- systemd service `WorkingDirectory=/dbdata/archery_v114_c9236a0`
- 实际生产跑的代码在 c9236a0 目录
- 推文件必须推 c9236a0，否则同步崩

### 4. 110 prod systemd 服务已 failed (9/17 实战新发现)
- `archery-v114-gunicorn.service` 9/8 就 failed (代码问题)
- 之后都是手动 `kill + setsid nohup` 启动
- 手动启动必须 source `.env` + export CAS 占位 env vars，否则 worker boot failed

### 5. e2e 演练 mock audit.get_audit (跨项目 e2e 测试通用)
演练 signal handler 触发的逻辑时：
- `post_save` 会触发但 handler 第一行就检查 `audit.current_status == PASSED`
- 没有真实 audit 记录 → handler 直接 return，演练失败
- 修法：`patch.object(wf, "get_audit")` 返 `MagicMock(current_status="3")` 绕过

### 6. 演练脚本 sys.path 用 os.getcwd() 不要写死 (跨项目通用)
- 老写死 `sys.path.insert(0, "/opt/archery/prod")` → 110 prod 跑就 ModuleNotFoundError
- 修法：`sys.path.insert(0, os.getcwd())` 通用于任何部署路径

### 7. gunicorn --daemon + .pid + source .env (跨项目 systemd 故障应急)
- systemd failed 时手动启动 gunicorn 必须:
  - `set -a && source .env && set +a` 把 .env 里变量全部 export
  - 加 CAS_SERVER_URL 等占位（settings.py 里 env() 没 default 的）
  - `--daemon --pid /tmp/gunicorn_xxx.pid` 后台跑
  - `--workers 5 --bind 0.0.0.0:9123 --access-logfile ./logs/access.log --error-logfile ./logs/error.log --capture-output archery.wsgi:application`

### 8. e2e drill savepoint_rollback 干净退出 (跨项目 e2e 通用)
演练 signal handler 触发的逻辑后,清理 db 状态:
- `with transaction.atomic(): sid = transaction.savepoint()`
- 演练 assert 全 PASS
- `transaction.savepoint_rollback(sid)` 回滚,不污染 db

## commit

```bash
# 文件清单
# M: sql/extensions/ddl_sync/services/sync_trigger.py (+118 lines _extract_all_alters + workflow_passed_handler 改造)
# A: scripts/_w3_ddlsync_bug_verify.py (7/7 PASS)
# A: scripts/_w3_ddlsync_e2e_drill.py (e2e PASS)
# A: docs/changelogs/2026-09-17_ddl-sync-multi-alter-mixed-blacklist.md (本文件)
```