# 推 110 prod v0.3.0-beta + v0.4.5 + 8/24 6 bug fix 完整执行手册

> **撰写日期**: 2026-08-25
> **撰写人**: mavis
> **状态**: 8/26 周三 9:00 演练, 8/26 周三 19:00 推 110
> **回滚 SLA**: 5 分钟 (DBA 评估, 4 触发条件)
> **值守 DBA**: 阿达叔叔 (8/26 19:00-20:00 在场)
> **本手册同步给**: DBA 值守群, 备份到 134 dev /opt/archery/prod/docs/runbooks/ + 110 prod /tmp/

---

## 0. TL;DR (一页纸, 推 110 当天照着做)

| 时间 | 谁 | 做什么 | 关键命令 |
|------|----|----|----------|
| ~~8/26 周三 9:00-12:00~~ ⚠️ | mavis + DBA | 134 dev 完整演练 — **未跑** (见 §1.5 风险) | ~~见 §2~~
| 8/26 周三 18:00 | DBA 值守群 | 群发"19:00 开始, 预计 30-40 分钟" | 模板 §6.1 |
| 8/26 周三 18:50 | DBA | **3 份备份** (代码 + schema + admin config) | `bash /tmp/pre_push_backup_110prod_20260826.sh` |
| 8/26 周三 19:00 | DBA | **5 步必做** 13 步 (log/sock/影子表/二进制/features/perm/...) | `bash /tmp/5step_prerequisites_110prod.sh` |
| 8/26 周三 19:05 | DBA | **推代码** (rsync/scp 新代码到 /dbdata/archery_v114_c9236a0) | `rsync -avz ...` 见 §3.3 |
| 8/26 周三 19:08 | DBA | **跑 migration** (建 4 个 ext_* 表 + gh-ost 4 perm) | `sudo -u archery venv/bin/python manage.py migrate` |
| 8/26 周三 19:10 | DBA | **kill master** 102228 + **nohup 拉起新 master** | 见 §3.4 |
| 8/26 周三 19:15-19:30 | DBA | **5+1 端点验证** (/login/ + /dbaprinciples/ + /admin/ + /gh_ost/admin_list/ + /sqlsubmit/ + /gh_ost/rebuild/select/) | `bash /tmp/verify_5endpoints_110prod.sh` |
| 8/26 周三 20:30 | DBA | **业务群发** "推 110 完成, 新功能上线" | 模板 §6.2 |
| 8/26 周三 20:00 | DBA | 值守结束, 交班 | (8/27 09:00 再看) |

**失败判别** (4 选 1 即回滚):
- ① migration 报错
- ② gunicorn 启动 30s 内 HTTP 502/503
- ③ 关键端点 500 (SQL 提交 / 工单详情 / gh-ost 任务)
- ④ 业务 RD 报"功能完全不可用"

**回滚命令** (5 分钟内):
```bash
bash /tmp/rollback_110prod_v030_20260826.sh
```

---

## 1. 推 110 内容清单 (要推的代码 + 配套修复)

### 1.1 这次推的内容 (8/26 17:00 用户拍板**只推 gh-ost + 字段 diff**, 17:02 拍板 detail.html 4 个 fix 跟着推)

> **8/26 17:00 用户拍板**: 推 110 范围瘦身——只推 gh-ost + 字段 diff 相关代码。
> **8/26 17:02 用户拍板**: detail.html 业务路径 4 个 fix 也要跟着推（影响 gh-ost / 字段 diff 工单 detail 页稳定性, §1.5 风险 5 解除）。
> 原计划 35+ commit → **61 commit 保留** (代码 55 + 推 110 必走物料 6), 砍掉 28 代码 commit 无关 (钉钉 OA / dashboard / dbaprinciples / sqladvisor / 通用 settings.py 修复)。

**A. 推 110 代码 commit (55)** — 进 110 prod 代码目录

| 类别 | 数量 | 关键 commit / changelog |
|------|------|-----------------------|
| gh-ost v0.3.0-beta (DBA 兜底 + 大表 DDL 防呆 + 字段 diff 检测) | 21 commit | 4f34a81, c0f42b3, 2c5a0b7, 47728bb, f87e875, 1f32976, fba0564, 70fcf47, 8ddc59a, 04ae0aa, 664058c, 2129221, 853bf6a, 461152d, 281fbeb, 36eb885, 3eb63f7, 4376553, 9eb6c9e, 14fa9f4, 374d990 |
| gh-ost v0.4.5-alpha (rebuild service + 端点 + admin UI + 演练) | 6 commit | 6412da4, e8b2cf3, 52b875b, e4a3707, a982d62, 8e40d26 |
| gh-ost v0.4.5 (DDL 智能回滚 + rebuild 3 决策落地) | 2 commit | e54a663, 4bece6a |
| **gh-ost v0.4.5 选表页面 (方案 B, 业务前端 3 步入口)** | **8 commit** | **3c00e69, 36c554e, 03c223f, 24a2498, 81a5097, 14e3007, 78ed4bb, 24200bd** |
| gh-ost 任务管理列表页 + 权限组细分 | 4 commit | c80c1ad, 727f046, 2d27a4a, eb5937b |
| gh-ost / 字段 diff bug fix (8/24 + 8/25) | 6 commit | 9d66064, e669567, 0b62856, 76d48cc, ac7e929, f76282e |
| gh-ost 业务路径灰色保留 (审批流 + cancel + 选表页面 fix) | 6 commit | a41c4d0, d5f88d1, 324a53a, eaf9853, 03c223f, 24a2498, 14e3007 |
| **detail.html 业务路径 4 个 fix (8/26 17:02 拍板跟着推)** | **4 commit** | **853cb71, d44632f, b8c0e6d, e78f758** |
| **代码总计** | **55 commit** | **强相关 44 + 灰色 7 + detail.html 4** |

> [注] 灰色 7 = 14e3007 (碎片率算法) + 03c223f (选表页 3 筛选器) + 24a2498 (筛选行挪位) + 324a53a (cancel perm) + eaf9853 (cancel 权限组) + a41c4d0 (审批流 3 级) + d5f88d1 (审批流 3 级配置)
> [注] v0.3.0-beta bug fix `14fa9f4` (DdlGhostTask 跟 SqlWorkflow 终止状态联动) + `9eb6c9e` (进度面板 perm 守卫) + `4376553` (RD 视角弹窗) 已经包含在 v0.3.0-beta 21 commit 里。

**B. 推 110 必走物料 commit (6)** — 5 步必做脚本 / 备份 / 回滚 / 演练 / 文档

| 类别 | 数量 | 关键 commit |
|------|------|-------------|
| 5 步必做脚本 (8/25 补到 13 步) | 1 | 7c2003c |
| 回滚演练 v2 DRY_RUN 模式 | 1 | 71e5b3b |
| 3 份备份 + 回滚 4 步脚本 | 1 | f1d7b49 |
| 推 110 必做补步骤 13 (8/24 教训) | 1 | ce6a364 |
| 推 110 完整执行手册 | 1 | f44c26e |
| goinception D+1 升级演练 + drill | 1 | a7ff19e |
| **物料总计** | **6 commit** | |

**推 110 总计**: 61 commit (代码 55 + 物料 6)

**❌ 砍掉 (26 commit, 不在 gh-ost / 字段 diff 范围)**:
- dashboard 优雅降级 (a16b803)
- /dbaprinciples/ 修复 (0c94576)
- 装 sqladvisor (7106be3)
- 钉钉 OA 全栈 (abe7f66, d9a5d3b, 3a850fb, 85d859e, cb5b0b5, edf7b26, 78158a3, 457590e, aaa9ecf)
- 通用 settings.py / static 修复 (1a9aea0, 5eefa3a, f366066, 982e88d, 5f6b59b, dd2d9d1, 4273a3f)
- goInception 装 + reencrypt + setup (588c7d9, a5b7a14, 052893c, 913eb5d)
- 推 110 工具 (a5471b3, 09d3cc2)
- 文档 / 计划 (d99c7bf, 8d78389, 7ab3c40, f1699bb, 5d6390c, 9c7d4ee, 0dbf21e, 151dc64, 6f2d922, 286585b, 65234fd, 360e526, a389d74, 2ccf5ea, c34ffca, f44c26e[注])

> [注] f44c26e (推 110 主手册) **保留**, 因为推 110 当天 DBA 要照着做。其他文档类 (演示稿 / 周报 / 计划) **砍** (不需要在 110 prod 上)。

**⚠️ 灰色保留 (3 个判断, 影响 gh-ost 业务路径)**:
- `a41c4d0` ConfigurableAuditor 走上游 WorkflowAuditSetting — **保留** (gh-ost 工单 detail 页审批流必走, 8/24 重大 bug)
- `d5f88d1` 审批流 3 级配置 v0.1.4 占位修复 — **保留** (跟 a41c4d0 是一对, 不推 110 prod 审批流配置可能是占位 "3")
- `a7ff19e` goinception D+1 升级工单 — **保留** (D+1 升级是 gh-ost 走 inception 路径必走)

**8/26 17:02 用户拍板 detail.html 4 个 fix 跟着推**:
- 原本砍掉 4 个 detail.html 业务路径 fix (853cb71, d44632f, b8c0e6d, e78f758), 17:02 拍板跟着推
- 理由: gh-ost / 字段 diff 工单 detail 页也走老 detail.html / workflow 路径, 不推 110 prod 业务 RD 提的非 gh-ost 老工单 detail 页可能 500
- §1.5 风险 5 解除 (风险描述保留作为历史决策记录)

**8/25 14:00 拍板加上的 v0.4.5 选表页面 (5 commit)**:
- `3c00e69` feat: 碎片回收 选表页面 (方案 B) — 业务前端 3 步入口, 主菜单 gh-ost 任务下加"碎片回收"链接
- `36c554e` fix: progress_rebuild "查看 admin 详情" 404 — 改对 `_meta.app_label` URL
- `03c223f` feat: 选表页 3 筛选器 (库/表名/碎片率) — 前端实时过滤
- `24a2498` fix: 筛选行挪到第 1 步卡片 — 选 instance 前就能看到, 拉表后启用
- `81a5097` fix: 筛选优先级 bug — 改用 `state.filtered` 替代三目 + 优先级坑

**对应 changelog** (推 110 物料必带):
- `docs/changelogs/2026-08-25_v0405-rebuild-select-page.md`
- `docs/changelogs/2026-08-25_admin-url-404-fix.md`
- `docs/changelogs/2026-08-25_v0405-rebuild-filters.md`
- `docs/changelogs/2026-08-25_v0405-rebuild-filter-priority-bug.md`

**关键文件** (推 110 时 scp 推 /opt/archery/prod/ 同名路径):
- `sql/extensions/ddl_gh_ost/views.py` (新 view `rebuild_select_page` + 修 pct 公式)
- `sql/extensions/ddl_gh_ost/urls.py` (新路由 `rebuild/select/`)
- `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/rebuild_select.html` (新模板, 22KB, 3 步 + 3 筛选器)
- `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/progress_rebuild.html` (admin URL 修对)
- `sql/extensions/ddl_gh_ost/services/notify.py` (admin URL 修对)
- `common/templates/base.html` (主菜单加"碎片回收"链接)

### 1.2 110 prod 当前状态 (8/24 摸底基线)

| 项目 | 当前状态 |
|------|----------|
| 代码版本 | v0.2.0 + OA framework (commit d303c04) |
| 库 | `archery` (不是 `archery_prod`) |
| MySQL 版本 | 5.7.44-log |
| MySQL user | archery (8/17 .my.cnf) + root 备用 (8/25 用户补充) |
| gunicorn master pid | **102228** (8/05 启动, 跑了 19+ 天) |
| gunicorn 端口 | 9123 |
| 启动方式 | 手动 nohup (没 systemd unit) |
| 49 用户 + 14 组 | Default/研发/DBA审批/研发负责人/QA/研发组长/bn/rm/OT/bd/ht/DBA组长/副总/DBA执行 |
| ext_* 表 | ext_ddl_ghost_task 不存在 (推 110 migration 0001-0004 必建) |
| workflow_audit_setting | 28 行 (8/24 摸底) |
| gh-ost / soar / sqladvisor | 8/24-8/25 装好 (1.1.10 / 14MB / 455KB) |
| 备份目录 | /backup/ (54GB 可用, 8/05 升级用过) |

### 1.3 推 110 必走脚本 (3 份)

| 脚本 | 路径 | 跑法 | 用途 |
|------|------|------|------|
| 5 步必做 | `scripts/deploy/5step_prerequisites_110prod.sh` | 110 prod 内部 `bash /tmp/5step_prerequisites_110prod.sh` | 13 步: log/sock/影子表/凭据(手动)/fix_approval/清空 sqladvisor/清空 soar/二进制/features.py/perm/bug verify(8/24 gh-ost / 字段 diff)/master pid/configurable_auditor |
| 3 份备份 | `scripts/deploy/pre_push_backup_110prod_20260826.sh` | 110 prod 内部 `bash /tmp/pre_push_backup_110prod_20260826.sh` | 代码 + schema + admin config (8/26 18:50 跑) |
| 一键回滚 | `scripts/deploy/rollback_110prod_v030_20260826.sh` | 110 prod 内部 `bash /tmp/rollback_110prod_v030_20260826.sh` | 4 步: kill+恢复代码+恢复 schema+拉起老 master+SLA 5 分钟 |

### 1.4 ⚠️ 5.7 vs 8.0 演练差异 + 8.0 INSTANT 架构性限制 (8/25 17:30 拍板方案 A, 8/25 17:50 简化 alter)

> **关键背景** (8/25 16:50 调研): 134 dev (MySQL 8.0.22) 跑 gh-ost rebuild 看到 `status=success` 但 ibd 文件不收缩,
> 8.0.22 + gh-ost **不能清 ibd 真实碎片**。**不是 bug, 是 MySQL 8.0 INSTANT 优化的架构性限制**。
> 110 prod (MySQL 5.7.44) gh-ost rebuild **真 work**, 5.7 改 ENGINE 改自己走 COPY 触发整表物理重写。
> 8/25 17:50 用户拍板: alter 子句简化到 1 层 `ENGINE=InnoDB` (3 层防护是冗余, 8.0.22 4 种 alter 全 no-op)。

#### 1.4.1 现象 (134 dev 实测, 8/25 16:50-17:30)

| alter 子句 | MySQL 行为 | gh-ost 看到 | 实际效果 |
|------------|------------|-------------|----------|
| `ENGINE=InnoDB` (改自己) | 8.0.12+ INSTANT 跳过 | success | **无 ibd 收缩** |
| `ROW_FORMAT=DYNAMIC` (改自己) | 8.0.16+ INPLACE 跳过 | success | **无 ibd 收缩** |
| `DEFAULT CHARACTER SET=utf8mb4` (改自己) | 8.0.22 INPLACE/INSTANT 跳过 | success | **无 ibd 收缩** |
| `ENGINE=InnoDB, ALGORITHM=COPY` | 8.0.22 走 COPY 触发物理重写 | success | **ibd 收缩** ✓ (但 gh-ost cut-over 仍走 INSTANT) |

**accesscard_black_detail 实战** (8/25 16:40 反馈):
- 134 dev (8.0.22) rebuild 8+ 次 (task #70-72/87-89/94/95/96), 全部 status=success
- ibd 物理大小不变 (128KB / 144MB), DATA_FREE 报 9MB
- 真碎片率 (FILE_SIZE 算法) = 6.7%, 跟 rebuild 前一致

#### 1.4.2 用户拍板 (8/25 17:30 方案 A)

> "生产环境没有 mysql 5.7 的版本, 110 虽然是 mysql 5.7 但仅供 archery 使用。所以方案 A 即可"

**方案 A 含义**:
1. **接受架构性限制**, 不在 gh-ost 层面修 INSTANT 跳过
2. **134 dev 演练验收改标准**:
   - ✅ task `status=success`
   - ✅ gh-ost log 显示 "migrating `<table>`", "Copy: N/M", "All-OK" → "Cut-over" → "completed"
   - ❌ ~~不依赖 ibd 收缩验证 (8.0 预期 no-op)~~
3. **110 prod 5.7.44 gh-ost rebuild 真 work**:
   - 5.7 改 ENGINE 改自己走 **COPY** 触发整表物理重写
   - 推 110 后, DBA 跑 rebuild 看到 ibd **真收缩** (5.7 行为)
4. **9 月 5.7→8.0 升级后需要架构性修法** (不在 8/26 推 110 范围):
   - 方案 a: gh-ost cut-over 强制 `ALGORITHM=COPY` (改 gh-ost, 跨工具, 需立项)
   - 方案 b: 不用 gh-ost, 直接 `ALTER TABLE ... ENGINE=InnoDB, ALGORITHM=COPY` (锁表, 大表不可接受)
   - 方案 c: 5.7 继续用, 8.0 走 gh-ost + DBA 手动验证 (现状)
   - 推 110 后, 跟 DBA 单独约 9 月升级时间表

#### 1.4.3 8/25 17:50 用户拍板简化 alter 子句 (1 层 ENGINE=InnoDB)

> "碎片回收命令明确下,只需要 alter table xx engine=innodb;"

**简化历史**:
- **8/13 拍板**: 3 层防护 `ENGINE+ROW_FORMAT+CHARSET` (当时以为能让 8.0 触发物理重写)
- **8/25 16:50 调研**: 8.0.22 4 种 alter 全 no-op, 3 层防护对 8.0 是没用的 metadata change
- **8/25 17:50 用户拍板**: 简化到 1 层 `ENGINE=InnoDB`

**简化版 alter** (8/25 17:50 后代码):
```python
# 8/13 3 层防护
return (
    f"ENGINE={table_info['engine']}, "
    f"ROW_FORMAT={table_info['row_format']}, "
    f"DEFAULT CHARACTER SET={table_info['charset']} "
    f"COLLATE={table_info['collation']}"
)
# 8/25 1 层简化
return f"ENGINE={table_info['engine']}"
```

**5.7 / 8.0 行为**:
- **5.7.44**: 改 ENGINE 改自己走 **COPY 触发整表物理重写**, ibd 真收缩 ✓
- **8.0.22**: 改 ENGINE 改自己走 INSTANT 跳过, **不重写** (架构性限制, 接受)

**8/25 18:01 134 dev 真演练验证** (task #103):
- `rebuilt_alter_full = [ENGINE=InnoDB]` ✓
- gh-ost log: "Table found. Engine=InnoDB" + "Ghost table altered" + "Done migrating"
- status: success (18s, 18:01:12 → 18:01:28)
- 表结构: ENGINE=InnoDB, ROW_FORMAT=Dynamic, TABLE_COLLATION=utf8mb4_bin (不漂)
- 8.0.22 ibd 仍 144MB (预期, INSTANT no-op)

**字段保留** (rebuilt_charset/row_format/collation/alter_full/at):
- 仍存"原表属性" + "实际用的 alter" (现在就是 `ENGINE=InnoDB`)
- 5 字段 zero risk, 推 110 migration 不变

#### 1.4.4 8.0.22 DATA_FREE 虚高问题 (8/25 16:55 顺手修, 已 commit `14e3007`)

| 老算法 (DATA_FREE 虚高) | 新算法 (FILE_SIZE 真实) |
|------------------------|------------------------|
| 128KB ibd 报 9MB DATA_FREE (虚高 70 倍) | FILE_SIZE = 128KB (真实) |
| `pct = DATA_FREE / (DATA_FREE + DATA + INDEX)` | `pct = (FILE_SIZE - DATA - INDEX) / FILE_SIZE` |
| workflow_log 99.3% (误报) | workflow_log 50.0% (真) |
| archive_log 4.5% (漏报 16 倍) | archive_log 74.7% (真) |

**修法**: `rebuild_list` 端点 SQL 改 `LEFT JOIN INNODB_TABLESPACES` 拿 `FILE_SIZE`。
**5.7 / 8.0 都用 FILE_SIZE 算法**, 不依赖 MySQL 版本。

#### 1.4.5 推 110 / 8.0 升级 影响

| 阶段 | MySQL 版本 | gh-ost rebuild 行为 | 验收标准 |
|------|-----------|---------------------|----------|
| 8/26 推 110 后 | 110 prod 5.7.44 | **真物理重写**, ibd 收缩 | task success + ibd 缩小 |
| 8/26 134 dev 演练 | 134 dev 8.0.22 | **INSTANT no-op**, ibd 不收缩 | task success + log cut-over |
| 9 月 5.7→8.0 升级 (计划) | 110 prod 8.0.22 | **INSTANT no-op** (待解决) | 待立项, 走 ALGORITHM=COPY |

#### 1.4.6 为什么不动 gh-ost 代码

- gh-ost 1.1.x 走 **binlog 异步重写 + cut-over 切表**, 不依赖 MySQL 原生 DDL
- 但 cut-over 阶段会改原表 metadata, 8.0 走 INSTANT 跳过导致 gh-ost 看不到要重写的子句而空转
- 改 gh-ost 让 cut-over 强制 `ALGORITHM=COPY` 涉及 gh-ost 内部 binlog + 影子表切换逻辑, **跨工具范围**
- 110 prod 5.7 不受影响, **8/26 推 110 业务可用**

#### 1.4.7 推 110 后 DBA 必看 (碎片回收功能 in 8.0.22 业务库架构性限制) — 8/26 推完后 DBA 30 分钟内必过目

> **关键认知 (8/26 09:00 用户拍板)**: 110 prod (5.7.44) 只是 Archery 自己的元数据 DB, **业务库全 8.0.22**。
> 也就是说 gh-ost rebuild 在业务 RD 实际使用场景(8.0.22 业务库) = **INSTANT no-op = 看不到 ibd 收缩**。
> 8/25 16:50-18:01 134 dev task #103 真演练验证过 (8.0.22 INSTANT 跳过 4 种 alter)。
> **业务 RD 用了会看不到效果**, DBA 走 OPTIMIZE TABLE ALGORITHM=COPY 兜底 (锁表, 小表 OK)。

##### 1.4.7.1 真实环境拓扑 (8/26 09:00 厘清)

| 组件 | 版本 | 库 | 角色 |
|------|------|------|------|
| 110 prod (Archery 平台) | MySQL 5.7.44 | archery (元数据) | Archery 自己的 DB, 没业务表 |
| 业务库 (RD 实际使用) | MySQL 8.0.22 | 业务库 (hly_accesscard 等) | 业务 RD 提单 SQL 实际执行目标 |
| 134 dev (演练 + 业务库) | MySQL 8.0.22 | archery_dev + archery_prod | DEV 演练 + 业务库实例 |

**关键含义**:
- Archery 5.7 (110 prod) **不会触发 gh-ost rebuild**, 5.7 只是 Archery 自己的元数据
- 业务 RD 提单 → 110 prod Archery 转发 → 业务库 (8.0.22) 执行
- gh-ost rebuild 实际跑在 8.0.22 业务库上 = **INSTANT no-op**
- 110 prod Archery 元库(5.7.44)本身没几张大表, 没碎片回收需求

##### 1.4.7.2 推 110 后 DBA 必做 (15 分钟过目, 不再 "真 work 验证")

**目的**: 不是验证 gh-ost rebuild 实际效果(已知 8.0.22 no-op), 而是验证 v0.4.5 功能链路正常 + DBA 知道 8.0.22 兜底方案。

**Pre-conditions 必查 (推 110 后, 验证前 5 分钟)**:

```bash
# 1. 5 步必做步骤 9 跑过 (5.7 features.py patch 5,7 行)
#    跑法: bash /tmp/5step_prerequisites_110prod.sh 看 log, 步骤 9 要 PASS
#    注: 这是 Archery 5.7 元库走 gh-ost 需要, 5.7 + gh-ost 真 work 用

# 2. gh-ost 二进制在 /opt/archery/bin/ (archery user 写得了)
ssh root@172.20.2.110 'ls -la /opt/archery/bin/gh-ost'
# 期望: -rwxr-xr-x 1 archery archery ... gh-ost
# 异常: 没有或 root owned → 8/18 教训, 110 prod 装到 /opt/archery/bin/ 不是 /usr/local/bin/

# 3. instance 凭据 (走 .my.cnf 验证)
ssh root@172.20.2.110 'cat /root/.my.cnf'
# 期望: user=archery, password=ldlAaBDXqKmycI6cJdDlcRgVWchsC8, host=127.0.0.1
# 注: 5.7 Archery 元库 + 8.0.22 业务库 instance 都靠这个 .my.cnf

# 4. 5+1 端点验证全 PASS (推 110 阶段 5 必跑)
bash /tmp/verify_5endpoints_110prod.sh
# 期望: 端点 1-3 200/302, 端点 4-6 DBA 浏览器手动验证 OK
# 特别: 端点 6 /gh_ost/rebuild/select/ 选 instance 时, 既能看到 5.7 Archery 元库也能看到 8.0.22 业务库
```

**架构性限制确认 (DBA 必看 5 分钟)**:

```bash
# 5. 确认 8.0.22 业务库 FILE_SIZE 算法 + gh-ost 走通
#    (5+1 端点验证时, 端点 6 已经在浏览器看到 8.0.22 业务库的 top 碎片表)
#    推 110 后这个表应该已经显示出来 (FILE_SIZE 真实算法, 8/25 16:55 修法)

# 6. DBA 心算: 业务 RD 提单后 gh-ost rebuild 实际行为
#    - 业务库 8.0.22: INSTANT no-op, 看到 success 但 ibd 不收缩
#    - Archery 5.7 元库 (没业务表): 5.7 走 COPY 真 work, 但没表可 rebuild
#    结论: 业务 RD 看到 success 后会问"为什么 ibd 没小" → DBA 提前知道走兜底

# 7. 8.0.22 兜底方案 (DBA 手动 OPTIMIZE TABLE ALGORITHM=COPY)
#    走 8.0.22 业务库 (走 .my.cnf 凭据)
ssh root@172.20.2.110 "mysql -h<业务库 host> -uroot -p'8k3pWGC2gxs2SsnelQtPg9Acti6fYD' -e \"
SELECT t.TABLE_SCHEMA, t.TABLE_NAME,
       ROUND(its.FILE_SIZE/1024/1024, 2) AS ibd_size_mb,
       ROUND((its.FILE_SIZE - t.DATA_LENGTH - t.INDEX_LENGTH) / 1024 / 1024, 2) AS free_mb,
       ROUND((its.FILE_SIZE - t.DATA_LENGTH - t.INDEX_LENGTH) / its.FILE_SIZE * 100, 1) AS pct
FROM INFORMATION_SCHEMA.TABLES t
LEFT JOIN INFORMATION_SCHEMA.INNODB_TABLESPACES its
  ON its.NAME = CONCAT(t.TABLE_SCHEMA, '/', t.TABLE_NAME)
WHERE t.TABLE_SCHEMA='hly_accesscard' AND t.TABLE_NAME='accesscard_black_detail'
ORDER BY pct DESC LIMIT 5;
\""
# 期望: 8.0.22 业务库的 top 碎片表 (FILE_SIZE 算法)
# 后续: 走 OPTIMIZE TABLE t ALGORITHM=COPY 锁表清碎片 (小表 OK, 大表 DBA 评估)
```

**功能链路确认 (10 分钟, 不真触发业务表 rebuild)**:

```bash
# 8. Archery 5.7 元库真走一遍 rebuild (5.7 真 work, 没业务表也能验)
#    浏览器走 /gh_ost/rebuild/select/ (DBA admin 登录)
#    步骤: 选 5.7 Archery 元库 instance → 拉表 → 勾一张小表 (workflow_log / archive_log) → 触发

# 9. 跳到 /gh_ost/rebuild/progress/<task_id>/ 看进度
#    期望: status queued → running → success (5-30 分钟, 取决于表大小)
#    注: 5.7 走 COPY 真物理重写, FILE_SIZE 应该真收缩 (对比 §1.4.7.3 验证)

# 10. 看 gh-ost log 显示 "Copying rows" 真拷贝 (5.7 行为)
ssh root@172.20.2.110 "tail -30 /var/log/archery/gh_ost/<task_id>.log | grep -E 'Copy:|Copying|cut-over|renamed|Done'"
# 期望: "Copy: N/M" + "Cut-over" + "Tables renamed" + "Done migrating"
```

##### 1.4.7.3 Archery 5.7 元库 rebuild 验证 (FILE_SIZE 真收缩, 5.7 真 work 核心证据)

```bash
# 11. 查 FILE_SIZE 后值 (跟前值对比, 验证 5.7 真物理重写)
ssh root@172.20.2.110 "mysql -uroot -p'8k3pWGC2gxs2SsnelQtPg9Acti6fYD' -e \"
SELECT t.TABLE_SCHEMA, t.TABLE_NAME,
       ROUND(its.FILE_SIZE/1024/1024, 2) AS ibd_size_mb,
       ROUND((its.FILE_SIZE - t.DATA_LENGTH - t.INDEX_LENGTH) / 1024 / 1024, 2) AS free_mb,
       ROUND((its.FILE_SIZE - t.DATA_LENGTH - t.INDEX_LENGTH) / its.FILE_SIZE * 100, 1) AS pct
FROM INFORMATION_SCHEMA.TABLES t
LEFT JOIN INFORMATION_SCHEMA.INNODB_TABLESPACES its
  ON its.NAME = CONCAT(t.TABLE_SCHEMA, '/', t.TABLE_NAME)
WHERE t.TABLE_SCHEMA='archery' AND t.TABLE_NAME='workflow_log';
\""
# 期望: FILE_SIZE 显著下降 (5.7 走 COPY 真物理重写)
# 异常: FILE_SIZE 不变 → 5.7 features.py patch 漏了, 看 5 步必做步骤 9

# 12. 验证表结构不漂 (跟 pre-验证对比)
ssh root@172.20.2.110 "mysql -uroot -p'8k3pWGC2gxs2SsnelQtPg9Acti6fYD' -e \"
SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE, ROW_FORMAT, TABLE_COLLATION
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA='archery' AND t.TABLE_NAME='workflow_log';
\""
# 期望: 跟 pre-验证完全一致 (CHARSET/ROW_FORMAT/COLLATION 都没变)
# 异常: CHARSET/ROW_FORMAT 变了 → alter 子句拼错, 立刻回滚推 110 (SLA 5 分钟)
```

##### 1.4.7.4 8.0.22 业务库兜底 (DBA 手动 OPTIMIZE TABLE ALGORITHM=COPY)

**业务 RD 报"rebuild 没效果"时, DBA 走这个**:

```bash
# 13. 8.0.22 业务库真清碎片 (锁表, 小表 OK, 大表评估)
ssh root@172.20.2.110 "mysql -h<业务库 host> -uroot -p'8k3pWGC2gxs2SsnelQtPg9Acti6fYD' -e \"
OPTIMIZE TABLE hly_accesscard.accesscard_black_detail ALGORITHM=COPY;
\""
# 期望: 锁表 ~1-5 分钟 (取决于表大小), ibd 真收缩
# 警告: 大表 (10GB+) 锁表时间 1 小时+, 业务不可接受, 改用其他方案
# 替代方案: pt-online-schema-change / 备份+恢复 / 接受 8.0 碎片限制

# 14. 验证 FILE_SIZE 真收缩
ssh root@172.20.2.110 "mysql -h<业务库 host> -uroot -p'8k3pWGC2gxs2SsnelQtPg9Acti6fYD' -e \"
SELECT t.TABLE_SCHEMA, t.TABLE_NAME,
       ROUND(its.FILE_SIZE/1024/1024, 2) AS ibd_size_mb,
       ROUND((its.FILE_SIZE - t.DATA_LENGTH - t.INDEX_LENGTH) / its.FILE_SIZE * 100, 1) AS pct
FROM INFORMATION_SCHEMA.TABLES t
LEFT JOIN INFORMATION_SCHEMA.INNODB_TABLESPACES its
  ON its.NAME = CONCAT(t.TABLE_SCHEMA, '/', t.TABLE_NAME)
WHERE t.TABLE_SCHEMA='hly_accesscard' AND t.TABLE_NAME='accesscard_black_detail';
\""
# 期望: FILE_SIZE 显著下降 (8.0.22 + ALGORITHM=COPY 走 COPY 真物理重写)
```

**验证清单 (DBA 打勾)**:

- [ ] Pre-conditions 4 项全 OK (§1.4.7.2 步骤 1-4)
- [ ] 架构性限制认知对齐 (§1.4.7.2 步骤 5-7, 知道 8.0.22 业务库 gh-ost no-op)
- [ ] Archery 5.7 元库 rebuild 成功 (§1.4.7.2 步骤 8-10 + §1.4.7.3 步骤 11-12, FILE_SIZE 真收缩, 表结构 0 漂移)
- [ ] 8.0.22 业务库兜底方案准备 (§1.4.7.4 步骤 13-14, OPTIMIZE TABLE ALGORITHM=COPY 锁表)
- [ ] 业务群发通知 (见下方模板)

**异常处理**:

| 异常 | 原因 | 应对 |
|------|------|------|
| §1.4.7.2 步骤 9 task status=failed | gh-ost 连不上 MySQL 或权限不够 | 看 gh-ost log `/var/log/archery/gh_ost/<task_id>.log`, 排查 instance 凭据 / binlog 权限 |
| §1.4.7.3 步骤 11 FILE_SIZE 不变 (5.7 元库) | 5.7 features.py patch 漏了 | 重跑 5 步必做步骤 9, 再触发 rebuild |
| §1.4.7.3 步骤 12 CHARSET/ROW_FORMAT 变了 | alter 子句拼错 | **立刻回滚推 110** (SLA 5 分钟), 看 §5.2 |
| §1.4.7.2 步骤 8 浏览器返 403 | rebuild 端点 perm 守卫 (8/25 加) | 检查 admin 后台 /admin/auth/user/<id>/change/ 勾 `add_ddlghosttask` perm |
| 业务 RD 报"业务库 rebuild 没效果" | 8.0.22 架构性限制 (INSTANT no-op), **预期内** | DBA 走 §1.4.7.4 兜底 (OPTIMIZE TABLE ALGORITHM=COPY 锁表) |
| §1.4.7.4 步骤 13 锁表时间过长 | 大表 (10GB+) 锁表 1 小时+ | 改用 pt-online-schema-change / 备份+恢复 / 接受 8.0 碎片限制 |

**关联命令模板** (推 110 后业务群发, 8.0.22 业务库架构性限制已知 + 5.7 元库验证通过后):

```
[推 110 完成 @ 20:30 + Archery 5.7 元库 gh-ost 验证 @ 21:00]
gh-ost 无锁 DDL + 字段 diff 检测 + DDL 智能回滚 + 大表 DDL 防呆 + 碎片回收 上线
5+1 端点验证 200, 无 5xx
推完后跑 Archery 5.7 元库 rebuild (workflow_log 真碎片表) 验证:
  - FILE_SIZE 显著下降 (5.7 走 COPY 触发整表物理重写) ✓
  - 表结构 0 漂移 (CHARSET/ROW_FORMAT/COLLATION 都没变) ✓
⚠️ 注意: 业务库 (8.0.22) 走 gh-ost rebuild 因 MySQL 8.0 INSTANT 优化是 no-op (ibd 不收缩)
  业务 RD 看到 success 但 ibd 没小是预期内, 真要清碎片联系 DBA 走 OPTIMIZE TABLE ALGORITHM=COPY 锁表兜底
DBA 19:00-20:00 值守
8/27 09:00 再看 1 日观察
```

**关联**:
- changelog: `docs/changelogs/2026-08-25_v0405-fragmentation-algorithm-fix.md` (FILE_SIZE 算法修法)
- changelog: `docs/changelogs/2026-08-25_v0405-rebuild-8p0-instant-caveat.md` (8.0 INSTANT 架构性限制 + 8/25 17:50 简化 alter)
- changelog: `docs/changelogs/2026-08-13_v0405-rebuilt-fields.md` (3 决策拍板 → 8/25 简化)
- 演练脚本: `scripts/_archive/_drill_frag_algorithm.py` (新算法 16/16 PASS)
- 演练脚本: `scripts/_archive/_rebuild_e2e_v3.py` (8/25 18:01 task #103 真演练)
- 5 步必做: 步骤 9 (features.py patch 5.7) + 步骤 13 (验证 8.0/5.7 兼容性)

---

## 1.5 ⚠️ 8/26 推 110 风险清单 (用户 16:34 拍板提前)

> **8/26 16:34 用户拍板**: 推 110 时间从 8/27 21:00 提前到 8/26 19:00 (今晚 7 点)。
> 时间紧, 8/26 原计划 9:00-12:30 完整演练**未跑**,DBA 推 110 时需要警觉以下 4 点:

### 风险 1:134 dev 完整演练未跑(最关键)

- **现状**: 8/26 9:00-12:30 完整演练 (6 drill + 5 步必做 + kill master 真演练) **未跑**
- **已完成的部分**:
  - ✅ qcluster hang 修复 (8/26 11:24 杀 7/27 老 qcluster + nohup 拉新 + Q worker 1s 内收任务验证)
  - ✅ workflow #102 修复 (is_backup=False, status 重置为 workflow_review_pass, 业务 RD 重新点"立即执行"链路通)
  - ✅ gh-ost task #103/#104 实战 (8/25 演练结果, 已在 master)
- **未做的部分**:
  - ❌ drill_admin_list_scope / drill_column_diff / drill_dashboard_graceful_degrade / drill_progress_page_perm / drill_ghost_task_wf_abort_sync / drill_sqlsubmit_big_table (6 drill 全部)
  - ❌ 5 步必做 13 步 (110 prod 内执行, 演练过 DRY_RUN 模式, 但没在 134 dev 真演练)
  - ❌ kill master 真演练 (134 dev 演练过, 但 8/26 没演练; 推 110 前无法验证 gunicorn 启停)
- **应对**: 推 110 阶段 5 (5+1 端点验证) **必跑全**, 任一端点 fail 立即回滚 (SLA 5 分钟)

### 风险 2:5.7 features.py patch 漏了

- **现状**: 8/24 摸底发现 110 prod MySQL 5.7.44 client lib 跟 gh-ost 不兼容, **必须打 features.py patch 第 5、7 行**
- **应对**: 5 步必做**步骤 9** 跑过 + 看 log, 漏了立刻回滚 (gh-ost 跑起来会触发 5.7 client lib 兼容 bug)

### 风险 3:8.0.22 业务库 gh-ost rebuild no-op

- **现状**: 110 prod 业务库 (hly_accesscard 等) 全是 8.0.22, gh-ost rebuild 在 8.0.22 走 INSTANT 跳过 (4 种 alter 全 no-op)
- **影响**: 业务 RD 用了 rebuild 看到 success 但 ibd 不收缩
- **应对**: §1.4.7 已知 + 业务群发消息 disclaimer, DBA 走 OPTIMIZE TABLE ALGORITHM=COPY 锁表兜底

### 风险 4:qcluster 30 天没重启历史

- **现状**: 8/26 11:24 修了 134 dev qcluster hang 问题, 但 110 prod qcluster 也跑了 30+ 天没重启
- **应对**: 推 110 阶段 1 (3 份备份) 之前, **DBA 手动重启 110 prod qcluster** (跟 134 dev 一样 `pkill + nohup`)

### 风险 5: ~~detail.html 业务路径 4 个 fix 砍掉, gh-ost / 字段 diff 工单 detail 页偶发 500~~ (8/26 17:02 用户拍板解除, 4 个 fix 跟着推)

- **原风险** (8/26 17:00 拍板时引入): 用户 17:00 拍板推 110 范围瘦身到"只推 gh-ost + 字段 diff", 砍掉 4 个 detail.html / workflow 通用业务路径 fix, gh-ost / 字段 diff 工单 detail 页也走老 detail.html / workflow 路径, 4 个边缘 case 可能 500。
- **8/26 17:02 用户拍板**: detail.html 4 个 fix 跟着推, 风险解除。
- **现在保留**: `853cb71` `d44632f` `b8c0e6d` `e78f758` 4 个 fix 全部进推 110 物料 (见 §1.1 范围表)。
- **5+1 端点验证** (DBA 推 110 阶段 5 必跑): 不需要额外加端点, 端点 5 = `/sqlsubmit/` 走业务 RD 账号, 已经覆盖 detail 页路径。

### 风险 6:推 110 范围瘦身到 61 commit, 5 步必做 13 步同步瘦身后是否够用

- **现状**: 5 步必做 13 步是按"35+ commit 推 110"写的, 61 commit 略多但 13 步仍全跑
- **应对**: 13 步不动, 只是推的代码范围小了; 步骤 11 (8/24 6 bug fix verify) 改为"8/24 gh-ost / 字段 diff bug fix verify (4 个 detail.html fix + 6 个 gh-ost / 字段 diff fix)", 步骤 12 (master pid 102228) 不变

### 8/26 19:00 推 110 决策点

> 如果 8/26 19:00 推之前 DBA 觉得演练不够, 可以选择:
> - **A. 按计划推 110 (19:00 准时)** — 接受 4 个风险, DBA 推 110 时警觉
> - **B. 推迟到 8/27 21:00** — 留 26 小时做 134 dev 完整演练 + 8/27 上午 9:00-12:00 kill master 真演练
> - **C. 8/26 18:00-19:00 紧急演练 1 小时** — 只跑核心 3 个 drill + kill master 真演练 (压缩演练)
> **用户 16:34 拍板 A, 现在按 A 走, DBA 警觉 + 5+1 端点必跑全**。

---

## 2. T-1 准备 (8/26 演练 status: 部分, 见 §1.5) — 134 dev 完整演练

> **目标**: 验证 8/25 3 份脚本 + 8/24 6 bug fix 都在 134 dev 真实跑通, kill master 真演练 (不是 DRY_RUN)

### 2.1 134 dev 端到端演练 7 drill (8/25 加 drill G 选表页面)

**跑法** (在 134 dev, root):
```bash
cd /opt/archery/prod

# A. gh-ost 任务列表 perm (4 Case)
sudo -u archery venv/bin/python scripts/drill_admin_list_scope.py 2>&1 | tail -30

# B. 字段 diff (5 Case)
sudo -u archery venv/bin/python scripts/drill_column_diff.py 2>&1 | tail -30

# C. dashboard 优雅降级 (4 Case, 8/17 修复)
sudo -u archery venv/bin/python scripts/drill_dashboard_graceful_degrade.py 2>&1 | tail -30

# D. cancel 端点 perm (3 Case, 8/13 修)
sudo -u archery venv/bin/python scripts/drill_progress_page_perm.py 2>&1 | tail -30

# E. ghost task 同步 (8/13 修)
sudo -u archery venv/bin/python scripts/drill_ghost_task_wf_abort_sync.py 2>&1 | tail -30

# F. SQL 提交页大表 DDL 防呆 (6 Case, 8/13 修)
sudo -u archery venv/bin/python scripts/drill_sqlsubmit_big_table.py 2>&1 | tail -30
```

**期望**: 全部 7 个 drill 通过 (含 drill G 选表页面), 无 UnboundLocalError / 500 / ImportError / AssertionError

### 2.2 kill master 真演练 (8/26 12:00-12:30, 业务午休)

> ⚠️ **必须在 134 dev 跑, 推 110 当天 110 prod 才敢 kill**

**跑法** (在 134 dev, root):
```bash
# 1. 看 master
ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1
# 期望: 13665 (134 dev 当前 master)

# 2. 跑 5 步必做步骤 13 (会自动 kill + verify)
cd /opt/archery/prod
bash scripts/deploy/5step_prerequisites_110prod.sh 2>&1 | tail -50
# 只跑 1-12 步 (在 12 步交互提示时 ctrl+c 退出, 或跳到 13 步)
# 重点是步骤 13: configurable_auditor + kill master + verify

# 3. 5 端点验证 (跟 110 prod 推完后用同一个脚本)
bash scripts/_archive/verify_5endpoints_134dev.py 2>&1 | tail -30
# 期望: 5 端点 200/302, admin 登录后 5 端点全 200

# 4. 看 gunicorn log 有没有 5xx
tail -50 /var/log/archery/gunicorn.err 2>&1 | grep -E ' 5[0-9][0-9] ' | head -5
# 期望: 0 条

# 5. 提一条新工单 (从浏览器), 验证 detail 页审批流跟 config/ 配一致
# 期望: detail 页审批级别 == 提交页显示的 (8/24 修法生效)
```

### 2.3 演练失败判别 + 应对

| 现象 | 原因 | 应对 |
|------|------|------|
| drill 脚本 UnboundLocalError | 8/24 6 bug fix 漏了 | 排查对应 commit 是否推上 134 dev |
| drill 脚本 500 | 8/13 大表 DDL 防呆或字段 diff 缺 | 排查 commit `f87e875` / `1f32976` |
| 5 端点验证有 5xx | 8/24 6 bug fix 引入新问题 | 排查 gunicorn log, 8/24 内回滚对应 commit |
| kill master 后 30s 没新进程 | 134 dev 有 systemd 5-7s 自动拉, 110 prod 没 systemd 需手动 | 134 dev 是真演练, 110 prod 推 110 那天手动 nohup 拉起 |

### 2.4 演练后发"演练通过"消息

> 群发 DBA 值守群 + 业务群:
> "[演练报告] 134 dev 6 drill 全过 + kill master 演练完成 + 5 端点 200 + 无 5xx. 8/26 推 110 准备就绪, 19:00 准时开始."

---

## 3. T 推 110 (8/26 周三 19:00-19:30)

### 3.1 推前 5 分钟 (18:55) — 通知业务群

**群发业务群** (模板):
```
[公告] 今晚 19:00-19:30 推 110 prod v0.3.0-beta, 期间会有 1-2 分钟 SQL 提交页不可用
新功能: gh-ost 无锁 DDL / 字段 diff 检测 / DDL 智能回滚 / 大表 DDL 防呆
回滚 SLA 5 分钟, DBA 19:00-20:00 值守
如有紧急 DDL 需求, 请 19:00 前提交, 或 19:30 后提
```

### 3.2 阶段 1: 3 份备份 (18:50-19:00, 10 分钟)

**跑法** (在 110 prod, root):
```bash
# 1. 脚本先 scp 到 110 prod /tmp/
scp scripts/deploy/pre_push_backup_110prod_20260826.sh root@172.20.2.110:/tmp/

# 2. ssh 登 110 prod
ssh root@172.20.2.110
# (root password 8/24: lAqfb8uEmQYsnGNQwIHtGPwukjCz6J)

# 3. 跑备份
bash /tmp/pre_push_backup_110prod_20260826.sh 2>&1 | tee /var/log/archery/pre_push_backup_20260826_1850.log
```

**期望输出**:
```
[3 份备份完成]
  1. 代码:    /backup/archery_v030_20260826_1850_code.tar.gz (35M)
  2. Schema:  /backup/archery_v030_20260826_1850_schema.sql (52K, 1319 行)
  3. Admin:   /backup/archery_v030_20260826_1850_admin.json (20K, 921 行)
  备份状态: code=OK schema=OK admin=OK
```

**失败处理**:
- code FAIL → 必看 log, **阻塞推 110** (没代码备份没法回滚)
- schema / admin FAIL → 提示 DBA 评估, DBA 评估可继续推

### 3.3 阶段 2: 推代码 (19:05-19:08, 3 分钟)

**跑法** (在 110 prod, root):
```bash
# 1. 备份当前 (跟 8/17 摸底 runbook 一致, 在 /dbdata/ 留一份)
cd /dbdata
cp -a archery_v114_c9236a0 archery_v114_pre_gh_ost_20260826.bak
# 留作保险, 推失败时回滚用

# 2. rsync 新代码 (从 134 dev 拉, 或 git tarball)
# 方案 A: rsync 走 134 dev
rsync -avz --delete \
  --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' --exclude='static/dist' --exclude='node_modules' \
  root@172.20.2.134:/opt/archery/prod/ /dbdata/archery_v114_c9236a0/

# 方案 B: git tarball (134 dev 端打包 + 110 prod 端解压)
# 134 dev: cd /opt/archery/prod && tar -czf /tmp/archery_v030_20260826.tar.gz --exclude='venv' --exclude='__pycache__' .
# 110 prod: rsync -avz root@172.20.2.134:/tmp/archery_v030_20260826.tar.gz /tmp/
# 110 prod: cd /dbdata/archery_v114_c9236a0 && tar -xzf /tmp/archery_v030_20260826.tar.gz

# 3. chown 恢复 (rsync/tar 解压后可能 root 拥有)
chown -R archery:archery /dbdata/archery_v114_c9236a0

# 4. 验证关键文件 mtime (跟 134 dev 一致)
stat -c '%y %n' /dbdata/archery_v114_c9236a0/sql/extensions/audit_drivers/configurable_auditor.py
# 期望: 2026-08-24 (8/24 修法版)
```

### 3.4 阶段 3: 跑 5 步必做 (19:08-19:12, 4 分钟)

**跑法** (在 110 prod, root):
```bash
scp scripts/deploy/5step_prerequisites_110prod.sh root@172.20.2.110:/tmp/
bash /tmp/5step_prerequisites_110prod.sh 2>&1 | tee /var/log/archery/5step_20260826_1900.log
```

**期望输出** (13 步全 OK):
- 步骤 1-3: log dir chown / sock 清理 / 影子表 (0 张)
- 步骤 4: 凭据重加密 (DBA 手动 yes/no 确认)
- 步骤 5: fix_approval_flow_3level (3 flow 14,15,3)
- 步骤 6-7: 清空 sqladvisor / soar (8/18-8/19 已修, idempotent)
- 步骤 8: gh-ost / soar / sqladvisor 二进制 (8/24 装好)
- 步骤 9: features.py 5.7 patch (8/17 已打, 5.7 patch 命中)
- 步骤 10: gh-ost 4 perm (migrate 后 idempotent 重建)
- 步骤 11: 8/24 6 bug fix verify (7 个文件 mtime 都在 8/24)
- 步骤 12: gunicorn master pid 102228 (110 prod 当前)
- 步骤 13: configurable_auditor 8/24 修法 + kill master + nohup 拉起

**步骤 13 关键** (8/24 教训):
- **不要 HUP master** (HUP 不重载 Python 代码)
- 必须 `kill <master_pid>` + 手动 `nohup sudo -u archery venv/bin/gunicorn ...` 拉起
- 新 master pid 会变 (8/24 教训: 134 dev master 13665 → 13199, 7s 内)

### 3.5 阶段 4: 跑 migration (19:12-19:14, 2 分钟)

**跑法** (在 110 prod, archery user):
```bash
cd /dbdata/archery_v114_c9236a0
sudo -u archery venv/bin/python manage.py migrate 2>&1 | tee /var/log/archery/migrate_20260826.log
```

**期望输出**:
```
Running migrations:
  Applying ddl_gh_ost.0001_initial... OK
  Applying ddl_gh_ost.0002_ddlghosttask_related_task_id_and_more... OK
  Applying ddl_gh_ost.0003_ddlghosttask_instance... OK
  Applying ddl_gh_ost.0004_ddlghosttask_rebuilt_fields... OK
```

**失败处理**: 任意 migration 失败 → 立刻回滚 (见 §5)

### 3.6 阶段 5: 5 端点验证 (19:15-19:30, 15 分钟)

**跑法** (在 110 prod, root, 或 134 dev 端 curl 110 prod):
```bash
# 脚本在 134 dev 端验证, 也可上传到 110 prod
bash /tmp/verify_5endpoints_110prod.sh 2>&1
# (脚本跟 8/25 134 dev 演练用的 verify_5endpoints_134dev.py 配套, 改 host/port 即可)
```

**5+1 端点** (期望全 200/302):
| # | 端点 | 期望 | 验证什么 |
|---|------|------|----------|
| 1 | `/login/` | 200 | gunicorn alive + Django 启动 OK |
| 2 | `/dbaprinciples/` | 302 (跳登录) | 8/24 修法生效, 不再 500 |
| 3 | `/admin/` | 302 (跳登录) | Django admin 后台 OK |
| 4 | `/gh_ost/admin_list/` (admin 登录) | 200 | gh-ost 任务管理列表 + 4 perm 守卫 |
| 5 | `/sqlsubmit/` (DBA 登录) | 200 | SQL 提交页 + 大表 DDL 防呆 + detail.html 4 个 fix 生效 |
| 6 | `/gh_ost/rebuild/select/` (DBA 登录) | 200 | v0.4.5 选表页面 + 3 筛选器 + FILE_SIZE 算法 |

**额外验证** (DBA 必做):
```bash
# 6. gunicorn log 看有没有 5xx
tail -100 /tmp/gunicorn.log 2>&1 | grep -E ' 5[0-9][0-9] ' | head -5
# 期望: 0 条

# 7. /var/log/archery/ 看 gh-ost 目录可写
ls -ld /var/log/archery/gh_ost/
# 期望: drwxr-xr-x archery archery

# 8. 提一条新 SQL 上线工单 (浏览器, 任一 DBA)
# 期望: detail 页审批流 == 提交页审批流 (8/24 修法生效, 不走 ext_approval_flow 旧配)
```

### 3.7 阶段 6: 业务群通知 (20:30)

**群发业务群** (模板):
```
[推 110 完成 @ 20:30] gh-ost 无锁 DDL + 字段 diff 检测 + DDL 智能回滚 + 大表 DDL 防呆 上线
5 端点验证 200, 无 5xx
DBA 19:00-20:00 值守
8/27 09:00 再看 1 日观察
```

---

## 4. T+1 观察 (8/27 周四 9:00) — 1 日观察清单

### 4.1 关键指标

| 指标 | 期望 | 排查 |
|------|------|------|
| gunicorn master pid | 跟 19:10 拉起的 pid 一致 | 不一致 = 中途 crash 过, 看 log |
| gunicorn log 5xx 数 | 0 (推 110 后 12 小时) | 有 5xx = 业务受影响, 排查 |
| gh-ost 任务数 | 跟 8/26 19:00 后提交数一致 | 缺失 = 推 110 过程中有人提单失败 |
| admin 后台 login 数 | 跟 8/26 19:00 后登录数一致 | 缺失 = 推 110 影响登录 |
| 业务 RD 工单状态 | 全部正常流转 | 有卡住 = 审批流 3 级有问题 |

### 4.2 日志检查命令

```bash
# 8/26 19:00 后的所有 gunicorn log
tail -1000 /tmp/gunicorn.log | grep -E ' 5[0-9][0-9] ' | head -20
tail -1000 /tmp/gunicorn.log | grep -E 'gh-ost|column_diff|approval' | head -20

# 推 110 后 1 日 (8/27 09:00 看) 业务用户登录
grep 'login\|POST /login' /var/log/archery/access.log 2>&1 | tail -30

# gh-ost 任务 (DBA 运维入口)
/admin/ddl_gh_ost/ddlghosttask/ 看 task 列表, 有没有异常 status
```

### 4.3 1 日观察报告

DBA 8/27 09:00 写 1 日观察报告到 `docs/changelogs/2026-08-27_push-v030-day1-observation.md`:
- gunicorn log 5xx 数
- 业务 RD 提单数 (推 110 前后对比)
- gh-ost 任务数
- 任何异常

---

## 5. 失败判别 + 回滚 (SLA 5 分钟)

### 5.1 4 触发条件 (DBA 拍板, 4 选 1 即回滚)

1. **数据库 migration 报错** (任何 ddl_gh_ost migration 失败)
2. **gunicorn 启动 30s 内 HTTP 502/503** (gunicorn 起不来)
3. **关键端点 500** (SQL 提交 / 工单详情 / gh-ost 任务任一返 500)
4. **业务 RD 报"功能完全不可用"** (用户主观判定)

### 5.2 回滚命令 (一键)

**跑法** (在 110 prod, root):
```bash
bash /tmp/rollback_110prod_v030_20260826.sh 2>&1 | tee /var/log/archery/rollback_20260826.log
```

**回滚 4 步** (脚本自动):
1. 停 gunicorn (kill master 102228, 5s)
2. 恢复代码 (rsync 从 /backup/archery_v030_20260826_1850_code.tar.gz, 30s)
3. 恢复 schema (DBA yes/no 二次确认, 10s)
4. 拉起老 gunicorn (nohup, 5s)
5. 验证 HTTP 200 (10s)

**总耗时**: 30-60s (SLA 5 分钟 = 300s, 余 240s)

### 5.3 回滚后业务群发

```
[110 prod 回滚完成 @ <新 master pid>]
/login/=200, /dbaprinciples/=302
回滚原因: <填, 例: 关键端点 500 / migration 失败>
业务影响: 8/26 19:00 后新功能不可用, 基础功能正常
推 110 重试时间: <待定, 修复问题后>
```

### 5.4 演练模式 (DRY_RUN=1, 8/25 教训)

> ⚠️ 推 110 当天**绝对不要**用 DRY_RUN=1, DRY_RUN=1 是演练模式, 跳过所有破坏性操作
> 演练模式只用于 8/26 134 dev 演练, 推 110 当天 110 prod 必须真跑

```bash
# 错误示范 (8/26 演练用)
DRY_RUN=1 bash /tmp/rollback_110prod_v030_20260826.sh

# 正确示范 (8/26 推 110 用, 推 110 失败时)
bash /tmp/rollback_110prod_v030_20260826.sh
```

---

## 6. 消息模板 (群发用)

### 6.1 推 110 前 5 分钟通知 (8/26 18:55)

**业务群 + DBA 群**:
```
[公告] 今晚 19:00-19:30 推 110 prod v0.3.0-beta, 期间会有 1-2 分钟 SQL 提交页不可用
新功能: gh-ost 无锁 DDL / 字段 diff 检测 / DDL 智能回滚 / 大表 DDL 防呆
回滚 SLA 5 分钟, DBA 19:00-20:00 值守
如有紧急 DDL 需求, 请 19:00 前提交, 或 19:30 后提
```

### 6.2 推 110 完成后通知 (8/26 20:30)

**业务群**:
```
[推 110 完成 @ 20:30] gh-ost 无锁 DDL + 字段 diff 检测 + DDL 智能回滚 + 大表 DDL 防呆 上线
5 端点验证 200, 无 5xx
DBA 19:00-20:00 值守
8/27 09:00 再看 1 日观察
```

### 6.3 回滚通知 (回滚完成后 30 秒内)

**业务群 + DBA 群**:
```
[110 prod 回滚完成 @ <新 master pid>]
/login/=200, /dbaprinciples/=302
回滚原因: <填>
业务影响: 8/26 19:00 后新功能不可用, 基础功能正常
推 110 重试时间: <待定>
```

---

## 7. 关键命令 cheat sheet

### 7.1 110 prod 登录 + 基础信息

```bash
# 1. ssh 登 110 prod
ssh root@172.20.2.110
# (root password: lAqfb8uEmQYsnGNQwIHtGPwukjCz6J)

# 2. 看当前 gunicorn master
ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1
# 推 110 前期望: 102228
# 推 110 后期望: 新 pid (kill + nohup 后变)

# 3. 看 110 prod 基础信息
mysql --defaults-file=/root/.my.cnf -e "SELECT VERSION();"
# 期望: 5.7.44-log
mysql --defaults-file=/root/.my.cnf -e "SELECT DATABASE();"
# 期望: archery
df -BG /backup
# 期望: >5GB

# 4. 看 5 端点
for ep in /login/ /dbaprinciples/ /admin/; do
  echo "== $ep =="
  curl -sI --max-time 5 http://127.0.0.1:9123$ep | head -1
done
```

### 7.2 推 110 关键命令

```bash
# 1. 3 份备份
bash /tmp/pre_push_backup_110prod_20260826.sh

# 2. 推代码 (rsync)
rsync -avz --delete \
  --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' --exclude='static/dist' --exclude='node_modules' \
  root@172.20.2.134:/opt/archery/prod/ /dbdata/archery_v114_c9236a0/
chown -R archery:archery /dbdata/archery_v114_c9236a0

# 3. 5 步必做
bash /tmp/5step_prerequisites_110prod.sh

# 4. migration
cd /dbdata/archery_v114_c9236a0
sudo -u archery venv/bin/python manage.py migrate

# 5. kill master + nohup 拉起
kill <master_pid>  # 推 110 前 102228, 推完后是新 pid
cd /dbdata/archery_v114_c9236a0
nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application \
  -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 \
  > /tmp/gunicorn.log 2>&1 &

# 6. 5 端点验证
bash /tmp/verify_5endpoints_110prod.sh
```

### 7.3 回滚命令

```bash
# 1. 一键回滚
bash /tmp/rollback_110prod_v030_20260826.sh

# 2. 手动回滚 (如果脚本有问题)
# 2.1 停 gunicorn
kill <master_pid>
sleep 5
# 2.2 恢复代码
cd /dbdata
cp -a archery_v114_pre_gh_ost_20260826.bak/* archery_v114_c9236a0/ 2>&1 | tail -3
# (或 tar -xzf /backup/archery_v030_20260826_1850_code.tar.gz)
# 2.3 恢复 schema (DBA yes/no 二次确认)
mysql --defaults-file=/root/.my.cnf -e "DROP DATABASE IF EXISTS archery;"
mysql --defaults-file=/root/.my.cnf -e "CREATE DATABASE archery DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_general_ci;"
mysql --defaults-file=/root/.my.cnf archery < /backup/archery_v030_20260826_1850_schema.sql
# 2.4 拉起老 gunicorn
cd /dbdata/archery_v114_c9236a0
nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application \
  -w 4 -b 0.0.0.0:9123 --access-logfile - --error-logfile - --timeout 120 \
  > /tmp/gunicorn.log 2>&1 &

# 3. 验证 HTTP
curl -sI --max-time 5 http://127.0.0.1:9123/login/
```

### 7.4 应急联系

| 角色 | 联系 | 何时联系 |
|------|------|----------|
| DBA 值守 (阿达叔叔) | (现场) | 推 110 19:00-20:00 |
| mavis | (远程) | 推 110 期间 任何代码 / 脚本问题 |
| 业务 RD 群 | (群) | 推 110 期间 业务 RD 报功能不可用 |

---

## 8. 推 110 推前 checklist (DBA 8/26 18:45 自查)

- [ ] 134 dev 演练报告 (8/26 演练) 已写到 docs/changelogs/, 6 drill 全过
- [ ] 业务群 / DBA 群已发推 110 通知 (8/26 18:55)
- [ ] 3 份备份脚本已 scp 到 110 prod /tmp/
- [ ] 5 步必做脚本已 scp 到 110 prod /tmp/
- [ ] 回滚脚本已 scp 到 110 prod /tmp/
- [ ] 验证 5 端点脚本 (verify_5endpoints_110prod.sh) 已 scp 到 110 prod /tmp/
- [ ] 110 prod .my.cnf 可用 (mysql --defaults-file=/root/.my.cnf -e "SELECT 1" OK)
- [ ] 110 prod 备份目录 /backup/ > 5GB
- [ ] 110 prod /dbdata/archery_v114_c9236a0 当前 commit == d303c04 (推 110 前基线)
- [ ] 110 prod gunicorn master pid 102228 在跑 (没自动退出)
- [ ] 8/24 教训 必看: kill master (不是 HUP) + 推完后提新工单验证

---

## 9. 关联文档

- **5 步必做脚本**: `scripts/deploy/5step_prerequisites_110prod.sh` (1-13 步)
- **3 份备份脚本**: `scripts/deploy/pre_push_backup_110prod_20260826.sh`
- **一键回滚脚本**: `scripts/deploy/rollback_110prod_v030_20260826.sh`
- **8/17 推 110 摸底 runbook**: `docs/runbooks/2026-08-17_push-v030b-to-110prod.md`
- **8/24 reload gunicorn SOP runbook**: `docs/runbooks/2026-08-24_gunicorn-reload-after-code-change.md`
- **8/25 演练报告**: `docs/changelogs/2026-08-25_110prod-pre-push-drill.md` + `2026-08-25_rollback-drill-and-incident.md`
- **设计稿**: `docs/designs/2026-08-27_push-v030-rollback-plan.md` (8/25 写, 跟本手册配套)

---

## 10. 8/26 推 110 关键时间点 (DBA 值守时间线)

| 时间 | DBA 动作 | 备注 |
|------|----------|------|
| 18:00 | DBA 群发"19:00 开始" | 提前 1 小时预警 |
| 18:45 | DBA 自查 checklist (§8) | 推前 9 项检查 |
| 18:50 | DBA 跑 3 份备份 | ~10 分钟, 备份日志 /var/log/archery/pre_push_backup_20260826_1850.log |
| 19:00 | DBA 跑 5 步必做 (13 步) | ~4 分钟, 含 1 次 DBA yes/no (步骤 4 凭据重加密) |
| 19:05 | DBA 推代码 (rsync) | ~3 分钟, chown 恢复 |
| 19:08 | DBA 跑 migration | ~2 分钟, 4 个 ddl_gh_ost migration |
| 19:10 | DBA kill master 102228 + nohup 拉起 | ~10 秒, 步骤 13 包含 |
| 19:15 | DBA 跑 5 端点验证 | ~5 分钟, 业务群发通知 |
| 19:20 | DBA 提一条新工单, 验证 detail 页审批流 | 8/24 修法生效, ~3 分钟 |
| 19:25 | DBA 看 gunicorn log 5xx + gh-ost 任务列表 | ~3 分钟, 业务群发"推 110 完成" |
| 19:30 | DBA 群发业务群 | 推 110 完成通知 |
| 19:30-20:00 | DBA 值守 | 观察业务用户 |
| 20:00 | DBA 交班 | 8/27 09:00 再看 1 日观察 |

---

**DBA 值守重要提醒**:
1. 推 110 期间**不要 HUP master** (8/24 教训: HUP 不重载 Python 代码)
2. 推 110 期间**不要动 .env** (8/06 教训: .env 占位事故)
3. 推 110 期间**不要直接 SQL UPDATE admin 配置** (8/18 教训: 走 SysConfig().set 走 mirage 加密, 不能 SQL 直塞)
4. 推 110 期间**任何报错先看 log, 不懂问 mavis, 别瞎试**
5. 推 110 失败**立刻回滚** (5 分钟 SLA, 不恋战)

**推 110 失败 ≠ 推 110 失败重试 = 推 110 推迟**: 第一次失败立刻回滚, 分析问题, 第二天或下周再推
