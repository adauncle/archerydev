# 8/26 周三 134 dev 完整演练清单（推 110 前一天）

> **撰写日期**: 2026-08-25
> **撰写人**: mavis
> **演练时间**: 2026-08-26 周三 9:00-12:30
> **演练人员**: mavis (远程) + DBA 值守 (现场)
> **目的**: 8/27 推 110 前一晚真演练一次, 验证所有脚本 + 修法都到位, kill master 真演练 (不是 DRY_RUN)
> **跟推 110 执行手册关系**: 详细化 `docs/runbooks/2026-08-27_push-v030-execution-manual.md` §2

---

## 0. TL;DR 一页纸

| 时间 | 演练阶段 | 关键命令 | 期望 |
|------|---------|---------|------|
| 9:00-9:15 | 前置准备 | ssh 134 dev + 看 gunicorn master 13665 | 134 dev 可达, master 在跑 |
| 9:15-10:00 | 6 drill 演练 | 跑 6 个 drill_*.py 脚本 | 全过, 无 UnboundLocalError / 500 |
| 10:00-10:30 | 5 步必做 1-12 步演练 | `bash /tmp/5step_prerequisites_110prod.sh` (跳 13 步) | 1-12 步全 OK, idempotent |
| 10:30-11:00 | 备份脚本演练 | `bash /tmp/pre_push_backup_110prod_20260827.sh` | 3 份备份 OK |
| 11:00-11:30 | 回滚脚本演练 | `DRY_RUN=1 bash /tmp/rollback_110prod_v030_20260827.sh` | 2.4 秒, SLA 余 298 秒 |
| 11:30-12:00 | 5 端点验证演练 | `bash /tmp/verify_5endpoints_110prod.sh` | 5 端点全 PASS |
| 12:00-12:30 | **kill master 真演练 (业务午休)** | 跑 5 步必做步骤 13 | 新 master 起来 + 5 端点 200 |
| 12:30-13:00 | 演练报告 + 群发 | 写 `docs/changelogs/2026-08-26_134dev-rehearsal.md` | 全过 = 推 110 准备就绪 |

**业务影响窗口**: 12:00-12:30 业务午休, kill master 真演练, 业务 RD 不可用 ≤ 30s

---

## 1. 前置准备 (9:00-9:15)

### 1.1 ssh 134 dev 验证

**跑法** (Windows PowerShell):
```powershell
ssh root@172.20.2.134
# (root password 8/24: CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW)
```

**期望**: 直接进 134 dev, 看到 `[root@archery_dev ~]#` 提示符

**失败判别**:
- "Permission denied (publickey, password)" → 密码错, 重输
- "Connection refused" → 网络/防火墙问题, 查 `Test-NetConnection 172.20.2.134 -Port 22`
- "ssh: Could not resolve hostname" → DNS 问题, 用 IP 不用 hostname

### 1.2 看 134 dev gunicorn master 状态

**跑法** (在 134 dev, root):
```bash
ps -ef | grep gunicorn | grep -v grep
```

**期望输出**:
```
root      13665     1  0 Aug17 ?        00:00:08 /opt/archery/prod/venv/bin/python3.11 /opt/archery/prod/venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 ...
archery   13700 13665  0 Aug17 ?        00:00:42 /opt/archery/prod/venv/bin/python3.11 /opt/archery/prod/venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9003 ...
...
```

**关键**: master 是 PPID=1 的那个 (第 3 列=1), pid **13665** (8/17 启动的, 推 110 演练后会变)
**失败判别**:
- 找不到 PPID=1 → master 不在跑, 演练前先 `systemctl restart archery` 拉起
- 有多个 PPID=1 → 异常, kill 老的留新的 (8/24 教训)

### 1.3 5 端点基线验证 (推 110 前快照)

**跑法** (在 134 dev, root):
```bash
# 上传 verify 脚本
ls /tmp/verify_5endpoints_110prod.sh
# 如果不存在, scp 推:
# (Windows 端) scp G:\MiniMax工作空间\archery_dev\scripts\deploy\verify_5endpoints_110prod.sh root@172.20.2.134:/tmp/

# 跑验证 (5 端点基线)
ARCHERY_URL=http://127.0.0.1:9003 SKIP_AUTH=1 bash /tmp/verify_5endpoints_110prod.sh
# (端点 4-5 输入 "OK" 模拟, 实际演练不强制)
```

**期望**:
- 端点 1-3 全 200/302 PASS
- 端点 4-5 手动验证 (可选, 演练时浏览器快看)
- 总结: `[SUMMARY] 5 endpoints: 5 OK / 0 FAIL`

**记录基线**: 拍屏或抄下来, 推 110 演练后对比 (应该跟基线一致)

---

## 2. 6 drill 端到端演练 (9:15-10:00)

> **目标**: 验证 8/13 6 commit + 8/17 dashboard 修复 + 8/24 6 bug fix 全部到位

### 2.1 6 个 drill 脚本

| # | drill 脚本 | 验证什么 | 期望时间 |
|---|-----------|---------|---------|
| A | `drill_admin_list_scope.py` | gh-ost 任务列表 perm + 角色判定 (4 Case) | 30 秒 |
| B | `drill_column_diff.py` | 字段 diff 检测 (5 Case) | 30 秒 |
| C | `drill_dashboard_graceful_degrade.py` | dashboard 优雅降级 (4 Case, 8/17 修) | 30 秒 |
| D | `drill_progress_page_perm.py` | cancel 端点 perm (3 Case, 8/13 修) | 30 秒 |
| E | `drill_ghost_task_wf_abort_sync.py` | ghost task 同步 (8/13 修) | 30 秒 |
| F | `drill_sqlsubmit_big_table.py` | SQL 提交页大表 DDL 防呆 (6 Case, 8/13 修) | 30 秒 |

### 2.2 跑法 (在 134 dev, root)

```bash
cd /opt/archery/prod

# A. gh-ost 任务列表 perm (4 Case)
sudo -u archery venv/bin/python scripts/drill_admin_list_scope.py 2>&1 | tee /tmp/drill_A.log
# 期望: 4 Case 全过, 输出类似 "Case A: archery superuser -> 200 PASS"

# B. 字段 diff (5 Case)
sudo -u archery venv/bin/python scripts/drill_column_diff.py 2>&1 | tee /tmp/drill_B.log
# 期望: 5 Case 全过

# C. dashboard 优雅降级 (4 Case, 8/17 修复)
sudo -u archery venv/bin/python scripts/drill_dashboard_graceful_degrade.py 2>&1 | tee /tmp/drill_C.log
# 期望: 4 Case 全过 (10 张图都降级成功, 无 500)

# D. cancel 端点 perm (3 Case, 8/13 修)
sudo -u archery venv/bin/python scripts/drill_progress_page_perm.py 2>&1 | tee /tmp/drill_D.log
# 期望: 3 Case 全过 (RD 看到 403 JSON / DBA 看到 200 / 异常路径 200 JSON)

# E. ghost task 同步 (8/13 修)
sudo -u archery venv/bin/python scripts/drill_ghost_task_wf_abort_sync.py 2>&1 | tee /tmp/drill_E.log
# 期望: 同步逻辑全过 (DdlGhostTask 状态跟 SqlWorkflow 终止状态联动)

# F. SQL 提交页大表 DDL 防呆 (6 Case, 8/13 修)
sudo -u archery venv/bin/python scripts/drill_sqlsubmit_big_table.py 2>&1 | tee /tmp/drill_F.log
# 期望: 6 Case 全过 (3 按钮: 启用 gh-ost / 立即执行 / 终止工单)
```

**总期望**: 6 drill 全部 PASS, 无 UnboundLocalError / 500 / ImportError / AssertionError

### 2.3 失败判别 + 应对

| 现象 | 根因 | 应对 |
|------|------|------|
| UnboundLocalError | 8/13 / 8/24 6 commit 漏了 | 排查对应 commit 是否推上 134 dev (git log) |
| 500 错误 | 端点 bug | 排查 gunicorn log `/var/log/archery/gunicorn.err` |
| ImportError | 8/13 ext_approval_flow 依赖缺 | 跑 `python manage.py migrate` |
| AssertionError | 期望值变了 | 看 drill 脚本, 改期望或改代码 |
| 134 dev ext_approval_flow 失败 | 8/11 fix_approval_flow_3level 没跑 | 跑 `python manage.py fix_approval_flow_3level` |

### 2.4 drill 演练报告

**跑完后, 写演练总结到 `/tmp/drill_summary.txt`**:
```
=== 8/26 134 dev 6 drill 演练 ===
时间: 2026-08-26 09:15-10:00
A. drill_admin_list_scope.py: PASS (4/4)
B. drill_column_diff.py: PASS (5/5)
C. drill_dashboard_graceful_degrade.py: PASS (4/4)
D. drill_progress_page_perm.py: PASS (3/3)
E. drill_ghost_task_wf_abort_sync.py: PASS (all)
F. drill_sqlsubmit_big_table.py: PASS (6/6)
总: 6/6 PASS
```

---

## 3. 5 步必做 1-12 步演练 (10:00-10:30)

> **目标**: 验证 5 步必做 13 步在 134 dev 全 idempotent, kill master 那步 (步骤 13) 单独演练

### 3.1 上传脚本

**跑法** (在 134 dev, root):
```bash
# 1. 检查脚本是否已上传
ls -la /tmp/5step_prerequisites_110prod.sh
# 如果不存在, scp 推:
# (Windows 端) scp G:\MiniMax工作空间\archery_dev\scripts\deploy\5step_prerequisites_110prod.sh root@172.20.2.134:/tmp/
```

### 3.2 跑 1-12 步 (跳 13 步)

**跑法** (在 134 dev, root):
```bash
# 备份 5 步必做日志
LOG=/var/log/archery/5step_20260826_rehearsal.log
mkdir -p $(dirname $LOG)

# 跑 1-12 步 (脚本会到步骤 13 时 kill master, 演练时让它跑, kill master 是真演练)
bash /tmp/5step_prerequisites_110prod.sh 2>&1 | tee $LOG
```

**期望输出** (1-12 步全 OK):
- 步骤 1: log dir chown archery:archery OK
- 步骤 2: sock 清理 OK (134 dev 没残留, noop)
- 步骤 3: 影子表 0 张 OK
- 步骤 4: 凭据重加密 (DBA 手动 yes, 演练 yes)
- 步骤 5: fix_approval_flow_3level 3 flow 14,15,3 OK
- 步骤 6: sqladvisor 134 dev 没配 (134 dev 演练不报, 8/18 110 prod 已修)
- 步骤 7: soar 134 dev 没配 (134 dev 演练不报, 8/19 110 prod 已修)
- 步骤 8: gh-ost / soar / sqladvisor 二进制 (134 dev 8/24 装好)
- 步骤 9: features.py 5.7 patch (134 dev 8.0 不需要)
- 步骤 10: gh-ost 4 perm (134 dev 已存在)
- 步骤 11: 8/24 6 bug fix verify (7 文件 mtime 都在 8/24)
- 步骤 12: gunicorn master pid 13665

**步骤 13 单独跑** (见 §6 kill master 真演练)

### 3.3 失败判别

| 现象 | 根因 | 应对 |
|------|------|------|
| 步骤 1 log dir chown fail | 134 dev /var/log/archery/ 不是 archery:archery | 演练时手动 chown, 推 110 时 5 步必做会修 |
| 步骤 5 fix_approval_flow_3level Unknown command | 代码没推 | `git pull` + 推 110 时确保代码到位 |
| 步骤 11 8/24 6 bug fix verify fail | 7 个文件 mtime 不在 8/24 | 看是哪个 commit 没推, `git log <file>` |

---

## 4. 备份脚本演练 (10:30-11:00)

> **目标**: 验证 3 份备份脚本 134 dev 也能跑, idempotent + JSON 格式正确

### 4.1 跑法 (在 134 dev, root)

```bash
# 1. 上传脚本 (如果没有)
ls -la /tmp/pre_push_backup_110prod_20260827.sh

# 2. 跑备份 (134 dev 演练用, 时间戳改 20260826)
# 注意: 134 dev 演练会真产生备份文件, 推 110 当天要在 110 prod 跑真备份
cd /opt/archery/prod
TS="20260826_rehearsal"
BACKUP_DIR="/tmp/backup_134dev_rehearsal"
mkdir -p $BACKUP_DIR

# ⚠️ 134 dev 演练改 PROD_PATH + 备份目录, 不要覆盖 /backup/
# (脚本默认 /dbdata/archery_v114_c9236a0 是 110 prod 路径, 134 dev 用 /opt/archery/prod)
sed -i "s|/dbdata/archery_v114_c9236a0|/opt/archery/prod|g; s|/backup|${BACKUP_DIR}|g; s|20260827_2050|${TS}|g" /tmp/pre_push_backup_110prod_20260827.sh

# 跑
bash /tmp/pre_push_backup_110prod_20260827.sh 2>&1 | tee /var/log/archery/pre_push_backup_${TS}.log
```

### 4.2 期望输出

```
[3 份备份完成]
  1. 代码:    /tmp/backup_134dev_rehearsal/archery_v030_${TS}_code.tar.gz (~50MB)
  2. Schema:  /tmp/backup_134dev_rehearsal/archery_v030_${TS}_schema.sql (~10MB)
  3. Admin:   /tmp/backup_134dev_rehearsal/archery_v030_${TS}_admin.json (~5MB)
  备份状态: code=OK schema=OK admin=OK
```

### 4.3 失败判别

| 现象 | 根因 | 应对 |
|------|------|------|
| code FAIL | 磁盘 < 5GB | `df -BG /tmp` |
| schema FAIL header 不像 mysqldump | 134 dev 走 my.cnf 缺 | 演练时手动加 `mysqldump --defaults-file=...` |
| admin FAIL JSON 损坏 | Archery settings print 污染 | 8/25 修法已经处理, 演练时看 log |

### 4.4 134 dev 演练限制

- **134 dev 走 my.cnf 没配** (8/06 教训), 演练时需要传 env var 或修改脚本
- 推 110 110 prod 走 .my.cnf 没这问题
- 演练只要验证备份流程跑通 + JSON 格式对, 不强求 schema 跟 110 prod 一致

---

## 5. 回滚脚本 DRY_RUN=1 演练 (11:00-11:30)

> **目标**: 验证一键回滚 DRY_RUN=1 模式演练 (不真改文件, 只演练逻辑), 跟 8/25 v2 演练一致

### 5.1 跑法 (在 134 dev, root)

```bash
# 1. 确认 DRY_RUN=1 模式 (脚本默认行为, 演练时强制)
# 2. 演练时跑 3 份备份 (跟 §4 一样, 演练时间戳)
# 3. 跑回滚 DRY_RUN=1
DRY_RUN=1 bash /tmp/rollback_110prod_v030_20260827.sh 2>&1 | tee /var/log/archery/rollback_${TS}.log
```

### 5.2 期望输出

```
[回滚完成]
  时间: 2026-08-26 ...
  状态:
    - 代码: 演练模式, 没真改 (DRY_RUN=1)
    - Schema: 演练模式, 没真改
    - gunicorn: 演练模式, 没真改
    - 日志: /var/log/archery/rollback_${TS}.log
总耗时: 2-3 秒
SLA 余: 297-298 秒
```

### 5.3 失败判别

| 现象 | 根因 | 应对 |
|------|------|------|
| 总耗时 > 30s | 备份 tarball 太大 / 134 dev I/O 慢 | 正常, 推 110 110 prod 备份更快 |
| DRY_RUN=1 还改了文件 | 8/25 教训没修干净 | 检查脚本 mv / tar / DROP / nohup 是否都包了 `if DRY_RUN` |

---

## 6. kill master 真演练 (12:00-12:30, 业务午休)

> **目标**: 验证 5 步必做步骤 13 走 kill master 路径, systemd 自动拉起新 master + 5 端点 200
> **8/24 教训固化**: 永远 `kill master` (不是 HUP), 134 dev 有 systemd, 110 prod 没有 (手动 nohup)

### 6.1 演练前 5 分钟 (11:55) — 通知业务群

**群发业务群** (模板):
```
[演练通知] 12:00-12:30 134 dev 演练 kill master (业务午休时段, 业务 RD 不可用 ≤ 30s)
演练完后 5 端点验证 200, 业务 RD 12:30 后正常使用
跟 8/27 推 110 一样的演练, 提前 1 天真跑一次
```

### 6.2 跑步骤 13 (在 134 dev, root)

```bash
# 1. 跑 5 步必做脚本, 跳到步骤 13
bash /tmp/5step_prerequisites_110prod.sh
# 步骤 1-12 已经跑过, 步骤 13 才开始

# 2. 步骤 13 实际跑 (脚本会):
#    2.1 确认代码已更新 (grep "走父类, 用 Archery 上游 WorkflowAuditSetting")
#    2.2 找 master pid (PPID=1, 期望 13665)
#    2.3 kill 13665
#    2.4 sleep 3
#    2.5 找新 master (systemd 自动拉, 134 dev 有 systemd)
#    2.6 HTTP curl 验证 200
#    2.7 提示 DBA 提新工单验证 detail 页审批流
```

### 6.3 期望输出

```
=== 步骤 13: configurable_auditor 8/24 修法 + kill master 重启 ===
[10:50:30] OK  configurable_auditor.py 已是 8/24 修法版
[10:50:30]  当前 master pid: 13665
[10:50:30]  kill 13665 ...
[10:50:33] OK  新 master pid: 14523 (旧 master 13665 已退出)
[10:50:33] OK  HTTP 200/302, gunicorn alive
```

### 6.4 134 dev systemd 自动拉 vs 110 prod 手动

| 环境 | kill master 后 | 应对 |
|------|----------------|------|
| 134 dev (有 systemd) | 5-7s 自动拉起新 master | 等 sleep 3 后, ps 看新 pid |
| 110 prod (无 systemd) | **不会自动拉起**, 业务全挂 | DBA 手动 `nohup sudo -u archery venv/bin/gunicorn ...` 拉起 |

**8/24 教训**: 推 110 110 prod 当天 kill master 后, 必须 DBA 立即 nohup 拉起, 不能等 (业务全挂 5s 也算 SLA 违规)

### 6.5 kill master 后验证 (DBA 必做, 跟推 110 一样)

**跑法** (在 134 dev, root):
```bash
# 1. 5 端点验证
ARCHERY_URL=http://127.0.0.1:9003 SKIP_AUTH=1 bash /tmp/verify_5endpoints_110prod.sh
# 期望: 5 端点全 PASS

# 2. gunicorn log 看有没有 5xx
tail -100 /var/log/archery/gunicorn.err 2>&1 | grep -E ' 5[0-9][0-9] ' | head -5
# 期望: 0 条

# 3. 浏览器提一条新工单 (任意 DBA, 134 dev 演练)
# 期望: detail 页审批流 == 提交页显示的 (8/24 修法生效)
```

### 6.6 演练结束通知 (12:30)

**群发业务群**:
```
[演练完成] 12:00-12:30 134 dev kill master 真演练完成
- 5 端点验证全 PASS
- gunicorn log 无 5xx
- 新 master pid 14523, 业务 RD 可正常使用
演练结果: 8/27 推 110 准备就绪, 21:00 准时推
```

---

## 7. 演练报告 (12:30-13:00)

### 7.1 写演练报告

**位置**: `docs/changelogs/2026-08-26_134dev-rehearsal.md` (134 dev 端, 推 github)

**模板**:
```markdown
# 2026-08-26 134 dev 完整演练报告 (推 110 前一天)

## 演练时间
2026-08-26 9:00-13:00 (mavis 远程 + DBA 现场)

## 6 drill 演练结果
| # | drill 脚本 | 验证什么 | 期望 | 实测 |
|---|-----------|---------|------|------|
| A | drill_admin_list_scope.py | gh-ost 任务列表 perm | PASS (4/4) | ✓ |
| B | drill_column_diff.py | 字段 diff 检测 | PASS (5/5) | ✓ |
| C | drill_dashboard_graceful_degrade.py | dashboard 优雅降级 | PASS (4/4) | ✓ |
| D | drill_progress_page_perm.py | cancel 端点 perm | PASS (3/3) | ✓ |
| E | drill_ghost_task_wf_abort_sync.py | ghost task 同步 | PASS | ✓ |
| F | drill_sqlsubmit_big_table.py | 大表 DDL 防呆 | PASS (6/6) | ✓ |

## 5 步必做 1-12 步演练
1-12 步全 OK, idempotent 验证通过

## 备份脚本演练
3 份备份 OK (代码 + schema + admin config)

## 回滚脚本 DRY_RUN=1 演练
2.4 秒, SLA 余 298 秒, 0 破坏性操作

## kill master 真演练 (12:00-12:30 业务午休)
- 旧 master 13665 kill OK
- 新 master 14523 起来 OK (systemd 自动拉)
- 5 端点验证全 PASS
- gunicorn log 无 5xx
- 业务 RD 12:30 后正常使用

## 8/27 推 110 准备就绪
- 4 脚本全部演练通过
- 1 手册 (docs/runbooks/2026-08-27_push-v030-execution-manual.md) 已就绪
- 推 110 阶段 1-6 步骤都演练过

## 8/27 推 110 关键时间节点
- 20:55 业务群发"21:00 开始"
- 20:50 备份 (3 份)
- 21:00 推 110 (6 阶段)
- 21:30 业务群发"推 110 完成"
- 22:00 值守结束
```

### 7.2 8/27 推 110 准备 checklist (再确认一次)

- [ ] 4 脚本全部 scp 到 110 prod /tmp/ (8/27 20:30 前)
- [ ] verify_5endpoints_110prod.sh 也 scp 到 110 prod /tmp/
- [ ] 5 步必做 + 备份 + 回滚 + 验证 4 脚本 8/26 演练全过
- [ ] kill master 真演练 8/26 演练过 (systemd 自动拉)
- [ ] 8/24 教训固化到手册 (kill 不是 HUP, 提新工单验证)
- [ ] 业务群通知模板准备好
- [ ] DBA 值守确认 8/27 21:00-22:00 在场

---

## 8. 关键命令 cheat sheet (8/26 演练用)

### 8.1 134 dev 登录

```bash
# Windows PowerShell
ssh root@172.20.2.134
# (root password 8/24: CXUsQvOHMUYc_xjFWLnoy54Jv4JmShQW)
```

### 8.2 看 master pid

```bash
ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1
# 期望 8/26 演练前: 13665
# 期望 8/26 演练后 (kill): 14523 (systemd 自动拉的新 pid)
```

### 8.3 跑 6 drill

```bash
cd /opt/archery/prod
for drill in drill_admin_list_scope drill_column_diff drill_dashboard_graceful_degrade drill_progress_page_perm drill_ghost_task_wf_abort_sync drill_sqlsubmit_big_table; do
    echo "=== $drill ==="
    sudo -u archery venv/bin/python scripts/$drill.py 2>&1 | tail -5
done
```

### 8.4 跑 5 步必做

```bash
# 1-12 步 (跳 13 步)
bash /tmp/5step_prerequisites_110prod.sh 2>&1 | tee /var/log/archery/5step_20260826.log
# 步骤 13 kill master (12:00 演练时跑, 业务午休)
# 步骤 13 跑过 = 全流程演练完
```

### 8.5 跑 3 份备份

```bash
# 134 dev 演练用 (改 PROD_PATH + 备份目录)
TS="20260826_rehearsal"
sed -i "s|/dbdata/archery_v114_c9236a0|/opt/archery/prod|g; s|/backup|/tmp/backup_134dev_rehearsal|g; s|20260827_2050|${TS}|g" /tmp/pre_push_backup_110prod_20260827.sh
mkdir -p /tmp/backup_134dev_rehearsal
bash /tmp/pre_push_backup_110prod_20260827.sh
```

### 8.6 跑回滚 DRY_RUN=1

```bash
DRY_RUN=1 bash /tmp/rollback_110prod_v030_20260827.sh
# 期望 2.4 秒, SLA 余 298 秒
```

### 8.7 跑 5 端点验证

```bash
ARCHERY_URL=http://127.0.0.1:9003 SKIP_AUTH=1 bash /tmp/verify_5endpoints_110prod.sh
# 端点 1-3 自动测, 端点 4-5 手动浏览器验证 (演练可选)
```

### 8.8 kill master 真演练

```bash
# 演练 12:00 跑, 业务午休
master_pid=$(ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1)
echo "旧 master: $master_pid"
kill $master_pid
sleep 5
new_master=$(ps -ef | grep gunicorn | grep -v grep | awk '$3==1 {print $2}' | head -1)
echo "新 master: $new_master"
curl -sI http://127.0.0.1:9003/login/ | head -1
# 期望: HTTP/1.1 200 OK
```

---

## 9. 8/26 演练失败应对

### 9.1 演练失败 ≠ 推 110 失败

**关键判断**:
- 8/26 演练失败 = 8/27 推 110 前修
- 8/27 推 110 失败 = 一键回滚 SLA 5 分钟

**演练失败应对**:
1. 排查 8/26 演练问题, 修代码/脚本
2. 重跑演练
3. 演练通过才能推 110

**演练失败典型场景**:
- 6 drill 有 1 个 fail → 排查对应 commit, 重跑
- kill master 后 systemd 没拉起 → 看 gunicorn log, 手动 nohup 拉
- 5 端点验证 fail → 看 gunicorn log, 排查哪个端点 500

### 9.2 演练推迟决策

**8/26 演练如果 13:00 前没通过**:
- 选项 A: 8/26 下午修, 8/26 晚上再演练
- 选项 B: 8/27 推 110 推迟到 8/28 / 下周
- 选项 C: 8/27 推 110 但只推 "已经演练通过" 的部分 (5 步必做 + 备份 + 回滚 + verify 5 端点 4 脚本演练过, 部分 drill 演练失败的 commit 暂不推)

**8/24 拍板**: 回滚 SLA 5 分钟, 推 110 推迟是可接受选项 (业务不中断 > 推 110 准时)

---

## 10. 关联文档

- **推 110 完整执行手册**: `docs/runbooks/2026-08-27_push-v030-execution-manual.md` (DBA 值守)
- **5 步必做脚本**: `scripts/deploy/5step_prerequisites_110prod.sh` (1-13 步)
- **3 份备份脚本**: `scripts/deploy/pre_push_backup_110prod_20260827.sh`
- **一键回滚脚本**: `scripts/deploy/rollback_110prod_v030_20260827.sh`
- **5 端点验证脚本**: `scripts/deploy/verify_5endpoints_110prod.sh`
- **8/25 演练报告**: `docs/changelogs/2026-08-25_110prod-pre-push-drill.md` + `2026-08-25_rollback-drill-and-incident.md`

---

**8/26 演练重要提醒**:
1. **kill master 真演练必须在业务午休 (12:00-12:30)**, 不要在 9:00-10:00 业务高峰演练
2. **演练前 5 分钟通知业务群**, 演练完通知业务群
3. **演练失败不要硬推 110**, 修问题重演练
4. **演练报告 8/26 12:30 前写完**, 给 DBA 推 110 信心

**8/27 推 110 必走**:
1. **永远 `kill master` (不是 HUP)** — 8/24 教训
2. **推完后提新工单验证 detail 页** — 不是只看提交页
3. **不要动 .env** — 8/06 教训
4. **不要直接 SQL UPDATE admin 配置** — 8/18 教训
