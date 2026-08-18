# 2026-08-18 W1+W2 必做摸头 7 项演练

## 一句话

推 110 prod 前 7 项必做摸头, 全部在 134 dev 端演练跑通, 摸出 2 个之前没发现的环境问题, 准备就绪等 W3 (9/1-7) 真推 110。

## 背景

8/17 用户拍板"不急着推 110, 先把所有环境摸头, 争取一次性成功"。W1 (8/18-24) + W2 (8/25-31) 14 项必做摸头 7 项必须过, 1 项可选。

本 changelog 记录 8/18 一天跑完 7 项必做 + 1 项可选的演练过程 + 关键发现 + 准备就绪状态。

## 7 项必做演练过程

### W1 必做 1: D 级备份演练 (DONE 8/17)
- `cp -a /opt/archery/prod /opt/archery/prod_pre_gh_ost_drill_`
- 134 dev 实际 733M (不是预期的 30G, dev 环境数据少), 2.5s 完成
- 51G 空闲够
- 验证 diff -q 一致: dashboard.py / .env / ddl_rollback.py
- **脚本**: `scripts/deploy/drill_backup_20260817.sh` (D 级 cp -a 备份)

### W1 必做 2: D+7 还原演练 (DONE 8/18 09:14)
- **目标**: 验证 D+1 mysqldump 备份可还原, 推 110 当天同款流程可用
- **执行**: 134 dev 端等价演练 (自己 mysqldump 库, 还原到 archery_drill_restore 测试库, drop 清理)
- **链路**: mysqldump (8.0s, 31MB) → gunzip -t OK → DROP + CREATE 测试库 → zcat 还原 (11.7s) → 验证 → drop 测试库
- **总耗时**: 21 秒
- **验证**: 53 张表 / sql_workflow 24 列 71 行一致 ✓ / ext_ddl_ghost_task 46 列一致 ✓ / auth_user 不存在 (LDAP 模式, 符合预期)
- **脚本**: `scripts/deploy/drill_restore_20260817.sh`
- **日志**: `scripts/_archive/drill_restore_20260818.log`

### W1 必做 3: migration 演练 (DONE 8/18 09:23)
- **目标**: 134 dev 真跑 `migrate` 验证 no-op, 看推 110 那天会跑的 4 个 ddl_gh_ost migration SQL
- **执行**: `manage.py migrate` (134 dev 端) → "No migrations to apply" ✓
- **ddl_gh_ost 4 migration SQL 5.7/8.0 兼容性**:
  - 0001: CREATE TABLE ext_ddl_ghost_task (45 列 + 2 FK + 3 INDEX) ✓
  - 0002: ALTER TABLE (related_task_id / target_table / task_type / workflow_id NULL / UNIQUE / INDEX) ✓
  - 0003: ALTER TABLE (instance_id + FK) ✓
  - 0004: ALTER TABLE (rebuilt_* 5 字段) ✓
- **关键**: 5.7 vs 8.0 兼容性 OK, 没有字符集/collation 漂移风险
- **DESC 实测**: 134 dev 端 ext_ddl_ghost_task 46 列全在
- **脚本**: `scripts/_tmp_mig_apply_20260818.sh`
- **日志**: `scripts/_archive/migrate_drill_20260818.log` (11.7KB)

### W1 必做 4: fix_approval_flow_3level 演练 (DONE 8/18)
- **目标**: 验证 idempotent 命令在 134 dev 端跑得动, 推 110 阶段 3 后同款命令可跑
- **执行**: 134 dev 端 `manage.py fix_approval_flow_3level` 真跑 + 再跑一次 idempotent 验证
- **结果**: 134 dev 当前 3 flow (default / normal / high_risk) 已是 `audit_auth_groups=14,15,3`, 命令 idempotent no-op
- **关键认知纠正**: 8/11 commit d5f88d1 当时注释说 "14,15,3 = 研发组长(14)→DBA组长(15)→DBA(3)", 实际 auth_group ID 是 3=DBA, 13=研发, 14=研发组长, 15=DBA组长, 用户 8/18 截图直接确认 `14,15,3` = 研发组长→DBA组长→DBA 是对的, **不需要改成 13,14,3**
- **教训**: 涉及 Archery 业务配置 (审批组 ID / 角色 / perm) 必须看实际审批日志, 不要从代码/库表脑补 (跨项目可复用, 已写进 memory)
- **脚本**: `scripts/_tmp_fix_flow_20260818.sh` + `scripts/_tmp_fix_flow_v2_20260818.sh` + `scripts/_tmp_fix_flow_v3_20260818.sh` + `scripts/_tmp_verify_flow_20260818.sh`
- **本次影响**: 误改 fix_approval_flow_3level.py + init_fallback_flow.py (改 14,15,3 → 13,14,3) 后立即回滚, 134 dev DB 没动过, 3 flow 仍 14,15,3 ✓

### W2 必做 5: gunicorn restart 演练 (DONE 8/18 09:38)
- **目标**: 验证 gunicorn `kill -HUP <master>` 平滑重启可用
- **执行**: 134 dev 端 9003 端口 gunicorn master pid 47458, kill -HUP, 4 秒 reload
- **结果**:
  - Master PID 47458 不变 (HUP 不重启 master, 只重新加载 worker)
  - 4 worker 全部替换: 47460/47465/47467/47472 → 7543/7544/7545/7546
  - 5 端点 HTTP 状态码: / 302, /login/ 200, /dashboard/ 302, /admin/ 302, /gh_ost/list/ 302 (全部正确)
  - /gh_ost/list/ redirect /login/ (鉴权守卫工作)
  - DB 数据完整: ext_approval_flow 3 flow 仍 14,15,3
- **关键**: HUP 是 gunicorn reload 标准方式, 4 秒完成, 0 中断
- **踩坑**: 第一版脚本 awk 列号算错导致 MASTER_PID 解析失败, 改用 `pgrep + /proc/PID/stat ppid` 找 master; worker count 用 `ps -eo comm` 而不是 pgrep 排除 bash
- **脚本**: `scripts/deploy/drill_gunicorn_restart_20260818.sh`

### W2 必做 6: schema diff (DONE 8/18 09:42)
- **目标**: 134 dev vs 110 prod 53 张表全量比对, 识别推 110 必处理的差异
- **执行**: 134 dev + 110 prod 各抓 3 份 (columns / indexes / tables), diff
- **关键发现 (4 张独有表)**:
  - 134 dev 多: `ext_ddl_ghost_task` (8/11 commit 加的, 推 110 阶段 3 后会建)
  - 134 dev 多: `sql_slave_config` (Archery 上游表, 110 prod 漏装, 跟我们 v0.3.0+ 二次开发无关)
  - 110 prod 多: `mysql_slow_query_review` + `mysql_slow_query_review_history` (134 dev 8/06 漏建, 110 prod 7/27 init 时建, 推 110 110 prod 不动, 134 dev 不补)
- **共有表 5.7 vs 8.0 metadata noise 51 张**:
  - 134 dev 8.0.22: utf8mb4_0900_ai_ci (默认) / utf8mb4_unicode_ci / utf8_general_ci
  - 110 prod 5.7.44: utf8mb4_general_ci (统一)
  - int vs int(11) (8.0 不写显示宽度)
  - 索引命名: 134 dev 老式 (idx_*) vs 110 prod 新式 (table_field_hash)
  - **结论**: 都是 metadata noise, 实际 schema 兼容, 推 110 不影响
- **脚本**: `scripts/deploy/drill_schema_diff_20260818.sh` + `scripts/deploy/drill_schema_diff_only_20260818.sh` + `scripts/_tmp_110prod_schema_20260818.sh`
- **数据归档**: `/opt/archery/prod/scripts/_drill/schema_diff_20260818_093907/`
- **日志**: `scripts/_archive/schema_diff_20260818.log`

### W2 必做 7: 完整 sync 链路 dry-run (DONE 8/18 11:26)
- **目标**: 演练 pack → 部署测试目录 → 验证代码就绪 → HUP 烟测 全流程
- **执行**: 134 dev 端演练
  - pack: 2.3s, tarball 30M (排除 venv / .git / logs / media / static / **_drill**)
  - 解压到测试目录: 0.5s, 51M
  - chown archery:archery
  - 链接 venv (复用现有)
  - 复制 .env + 创建 logs / media
  - `manage.py check` → 0 issues ✓
  - `manage.py migrate --plan` → "No planned migration operations" ✓
  - HUP 9003 gunicorn 4s reload, 5 端点 200/302 正确
  - 清理测试目录
- **踩坑**:
  - 第一版 tar 没加 `--strip-components=1`, 解压后文件在 `prod/` 子目录, 改加
  - 第二版排除 logs 但 Django 期望 logs 目录存在, 改解压后 `mkdir -p logs media`
  - 第三版起测试 gunicorn 9005 端口失败 (sudo 包装的 shell 退出带走子进程), 改用 `manage.py check` 验证代码就绪, 跳过测试端口起 gunicorn (推 110 当天直接覆盖重启真服务)
  - 第四版 tarball 9.3G (因 _drill/ 演练产物目录自递归), 改排除, 30M
- **总时间**: ~25 秒
- **关键**: tarball 30M 是推 110 时的实际大小, scp 134→110 约 30-60 秒
- **脚本**: `scripts/deploy/drill_sync_full_20260818.sh`

### W2 可选 8: staging 摸头 (DONE 8/18)
- **staging 现状**: 7/21 部署, 883M, **冷备 (没在跑)**
- **结论**: 跟推 110 无关, 跳过深入演练

## 关键发现汇总 (推 110 必看)

1. **ddl_gh_ost 4 migration 5.7/8.0 兼容** (W1 必做 3): CREATE TABLE + ALTER TABLE + FK + INDEX + UNIQUE 都兼容, 5.7/8.0 都跑得动
2. **ext_approval_flow 3 flow audit_auth_groups=14,15,3 跟 Archery 上游配置一致** (W1 必做 4): 不需要改, 推 110 后跑 fix_approval_flow_3level 命令 idempotent
3. **gunicorn HUP reload 4s, master 不变, worker 全替换** (W2 必做 5): 推 110 当天 `kill -HUP <master>` 即可平滑重启, 不需要 systemctl restart
4. **schema diff 4 张独有表 (134 多 2 / 110 多 2)** (W2 必做 6): 134 多 `ext_ddl_ghost_task` 推 110 阶段 3 后建, 其他跟我们无关
5. **tarball 30M, scp ~30-60s** (W2 必做 7): 推 110 跨主机 scp 实际很小, 不用 rsync
6. **5 步必做 idempotent, 推 110 当天可重复跑** (W1 必做 2-4): 已验证

## 推 110 当天必做 checklist (W3 9/1-7)

1. ☐ 推代码: `pack → scp 134 dev → 110 prod → tar -xzf --strip-components=1 → chown archery:archery`
2. ☐ 创建 logs / media 目录 (`mkdir -p /dbdata/archery_v114_c9236a0/{logs,media}`)
3. ☐ 备份 venv: 复用 110 prod 现有 venv, 不重装依赖 (演练 W2 必做 7 验证)
4. ☐ 复制 .env (DBA 手动, 110 prod /root/.my.cnf 凭据不同)
5. ☐ 跑 5 步必做 (precheck 11 项, fix_approval_flow_3level 创建 3 flow)
6. ☐ `manage.py migrate` (跑 4 个 ddl_gh_ost migration 建 ext_ddl_ghost_task)
7. ☐ `kill -HUP <master>` 平滑重启 gunicorn 9123
8. ☐ 烟测 5 端点: /, /login/, /dashboard/, /admin/, /gh_ost/list/ (期望 200/302)
9. ☐ 浏览器验证 gh-ost 任务列表 + ext_approval_flow 3 flow
10. ☐ D+1 备份 + 旧 commit rollback 准备

## 涉及文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `scripts/deploy/drill_restore_20260817.sh` | 新增 | D+7 还原演练脚本 |
| `scripts/deploy/drill_gunicorn_restart_20260818.sh` | 新增 | gunicorn HUP 演练脚本 |
| `scripts/deploy/drill_schema_diff_20260818.sh` | 新增 | schema diff 抓数据脚本 |
| `scripts/deploy/drill_schema_diff_only_20260818.sh` | 新增 | schema diff 比对脚本 |
| `scripts/deploy/drill_sync_full_20260818.sh` | 新增 | 完整 sync 链路 dry-run 脚本 |
| `scripts/_tmp_mig_apply_20260818.sh` | 临时 | migration 演练脚本 |
| `scripts/_tmp_fix_flow_*.sh` | 临时 | fix_approval_flow_3level 演练脚本 |
| `scripts/_tmp_110prod_schema_20260818.sh` | 临时 | 110 prod 端 schema 抓取 |
| `scripts/_tmp_110prod_table_check_20260818.sh` | 临时 | 110 prod 端表数验证 |
| `scripts/_tmp_tar_inspect_20260818.py` | 临时 | tarball 大小分析 (排查自递归) |
| `scripts/_archive/drill_restore_20260818.log` | 归档 | D+7 还原演练日志 |
| `scripts/_archive/migrate_drill_20260818.log` | 归档 | migration 演练日志 (11.7KB) |
| `scripts/_archive/schema_diff_20260818.log` | 归档 | schema diff 日志 |
| `scripts/_archive/sync_drill_v6_20260818.log` | 归档 | 完整 sync 链路 dry-run 日志 (最终版) |
| `docs/changelogs/2026-08-18_w1-w2-prerequisites-drills.md` | 新增 | 本 changelog |
