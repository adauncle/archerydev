# 2026-08-11 · v0.3.0-beta gh-ost DBA 兜底 + 大表 DDL 防呆

> **作者**: mavis  · **面向 DBA 验收 + 后续 110 PROD 推 v0.3.0 参考**

## 一句话

修一个真生产风险：**RD 提交大表 DDL 没勾 gh-ost → 3 级审批通过 → DBA 在原路径"立即执行" → 锁表 → 生产事故**。本次把"DBA 是兜底角色"产品定位落到代码，3 个修复全做完。

## 触发场景

8/11 用户浏览器验证：
- 流程 1（RD 勾 gh-ost）→ 全 OK
- **流程 2（RD 没勾 gh-ost）→ 研发组长通过 → DBA组长通过 → DBA 通过 → DBA 看不到"启用 gh-ost"按钮，只能点"立即执行"**

这是真生产事故风险——大表 DDL 走原路径会锁表（业务阻塞几秒到几分钟）。

## 根因

`can_enable_ghost` 守卫（`sql/views.py`）：
```python
can_enable_ghost = (
    (user.is_superuser or is_dba_group or is_submitter)
    and workflow_detail.status in ("workflow_review_pass", ...)
    and not has_ghost_task
)

is_dba_group = user.groups.filter(name__in=["DBA", "DBA组长"]).exists()
```

`is_dba_group` 查 Django **auth_group**（权限组）——但 134 dev / 110 prod 的 DBA user 关联的是 **resource_group**（资源组），不是 auth_group。**DBA user 实际上拿不到"启用 gh-ost"按钮**（除非是 superuser）。

## 修法（DBA 兜底 + 大表 DDL 防呆）

### 修复 1：can_enable_ghost 守卫放宽

`sql/views.py`：
```python
can_enable_ghost = (
    (user.is_superuser
     or user.has_perm("sql.sql_review")  # 新增：DBA 兜底 (有审阅 perm 就能启用)
     or is_dba_group                      # 兼容老路径 (auth_group 是 DBA/DBA组长)
     or is_submitter)
    and workflow_detail.status in ("workflow_review_pass", "workflow_timingtask")
    and not has_ghost_task
)
```

业务意义：**DBA 是兜底角色，RD 漏勾 gh-ost 时 DBA 必须能启用**。改用 `has_perm("sql.sql_review")` 兜底（不依赖 auth_group 绑定）。

### 修复 2：大表 DDL 红色 alert

`sql/views.py` 加 `_get_table_size_info` helper：
- 解析首条 ALTER → 拿表名 → 查 `information_schema.tables` 拿行数 + 大小
- 阈值：**行数 ≥ 10w 或 大小 ≥ 100MB** 视为大表
- 阈值走 env vars `CUSTOM_BIG_TABLE_ROW_THRESHOLD` / `CUSTOM_BIG_TABLE_SIZE_THRESHOLD_MB`，可调

`detail.html` 加红色 alert 块 + 三按钮：
```
⚠️ 检测到 [accesscard_black_detail] 是大表 DDL
   行数 241558 / 数据大小 53 MB
   强烈建议启用 gh-ost 无锁 DDL，避免锁表

   [启用 gh-ost（DBA 兜底）]  [立即执行（确认锁表）]  [终止工单（让 RD 重提）]
```

### 修复 3：立即执行按钮双层 confirm（大表时）

`detail.html` 加 JS：点大表 alert 的"立即执行"按钮 → 弹 2 次 confirm：
1. 第一次："确认要走原路径执行大表 DDL 吗？会锁表..." → 取消
2. 第二次："再次确认：已评估锁表风险？..." → 取消

防止 DBA 一时手快点了立即执行，强制走"二次确认"流程。

### 修复 4：DBA 兜底启用 gh-ost 按钮

大表 alert 的"启用 gh-ost（DBA 兜底）"按钮 → 调 precheck + enable 端点（跟 RD 勾的流程一样）→ 创建 DdlGhostTask → 走 cut-over success → wf.status 自动切 workflow_finish。

这让 **DBA 在详情页一键兜底启用 gh-ost**，不需要后端命令。

### 修复 5：终止工单按钮

大表 alert 的"终止工单（让 RD 重提）"按钮 → 走 `/cancel/` 端点（已有）：
- `wf.status=workflow_abort`
- 任何挂的 DdlGhostTask 标 cancelled
- 跟之前 v0.3.0-beta 状态机修复的拒绝清理逻辑一致

## 端到端验证（134 dev 5 Case）

演练表 `archery_dev.accesscard_black_detail`（24w 行 / 53MB，触发大表 alert）

| Case | 验证 | 结果 |
|------|------|------|
| A | RD 勾 gh-ost + 3 级通过 → 走 gh-ost (基础流程) | ✅ wf 自动启用 task |
| B | RD 没勾 + **小表** → 无 alert, 立即执行按钮正常 (无 confirm) | ✅ |
| C | RD 没勾 + **大表** → 红色 alert + 三按钮全在 | ✅ |
| D | DBA 走"终止工单" → wf.status=workflow_abort | ✅ |
| E | DBA 走"启用 gh-ost" 兜底 → task 创建 + cut-over success + wf.finish 同步 | ✅ |

5 Case 全过。

## 变更文件清单

| 文件 | 变更 |
|------|------|
| `sql/views.py` | can_enable_ghost 放宽 + 大表 alert 检测 + `_get_table_size_info` / `_parse_first_alter` / `_workflow_sql_text` helper |
| `sql/templates/detail.html` | 大表红色 alert + 三按钮 + JS 双层 confirm + 启用 gh-ost 兜底按钮 |
| `archery/settings.py` | 加 `CUSTOM_BIG_TABLE_ROW_THRESHOLD` / `CUSTOM_BIG_TABLE_SIZE_THRESHOLD_MB` |
| `docs/changelogs/2026-08-11_gh-ost-dba-fallback.md` | 本 changelog |
| `scripts/drill_v030b_dba_fallback.py` | 5 Case 端到端演练 |
| `scripts/pack_v030b_dba_fallback.py` | 打包脚本 |

## 110 PROD 推 v0.3.0 前必做

1. ✅ 之前的 5 步必做（log dir chown / sock 清理 / 影子表 / 凭据重加密 / DBA 重新保存）
2. ⚠️ **新增**：`CUSTOM_BIG_TABLE_ROW_THRESHOLD` / `CUSTOM_BIG_TABLE_SIZE_THRESHOLD_MB` 环境变量（如不设，默认 10w 行 / 100MB）
3. ⚠️ **生产阈值建议调高**（如 50w 行 / 500MB），取决于业务规模
4. ⚠️ **DBA 培训**：在详情页看到红色 alert + 三按钮 = DBA 兜底流程

## 关联

- `docs/changelogs/2026-08-11_gh-ost-approval-gating.md`（v0.3.0-beta 审批守卫）
- `docs/changelogs/2026-08-11_approval-flow-3level-fix.md`（OA 3 级审批）
- `docs/designs/2026-08-10_gh-ost-detail-design.html` §7.3 状态机
- `docs/designs/2026-08-05_gh-ost-product-design.html` §启用 gh-ost
