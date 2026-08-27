# 8/27 qcluster stale Redis connection (推 110 漏的第 4 个 P0)

> **时间**: 2026-08-27 09:18 (systemd disable) + 09:38 (qcluster restart)
> **作者**: mavis
> **commit**: TBD
> **严重程度**: P0 (业务执行类 — execute_sql 任务全卡死)
> **修复耗时**: 9:38 启动新 qcluster, 30s 后业务 RD 工单 #4743 自动 finish
> **关联**: 8/26 推 110 实战 4 P0 + 1 新功能 + 1 fix (SECRET_KEY / CACHE_URL / PRECHECK / **qcluster stale conn** / detail 字段 diff / detail JS fix)

---

## 症状 (8/27 09:21 业务 RD mkq 反馈)

业务 RD 提 DML 工单 #4743 (wyh 8/26 18:21 提交, 5 步审批全过, 8/27 09:19 走完最后 DBA执行), 工单状态卡在 `workflow_queuing` (即 "工单执行排队中") 19 分钟不执行。

截图: `prodarchery.ahggwl.com:9123/detail/4743/` 显示 "工单执行排队中"。

---

## 排查路径

### 第 1 步: 以为是 audit current_audit=-1 卡住 (误诊)

`workflow_audit` 表里 `audit_id 4797`:
- `current_audit=-1, next_audit=-1, current_status=1`
- `audit_auth_groups=6,4,3,15,16` (审批流配好了)

**误判** `current_audit=-1` 是 "审批没初始化" bug, 准备改 audit_id 4797。

### 第 2 步: 查 `WorkflowStatus` 实际常量 (颠覆)

`common/utils/const.py`:
```python
class WorkflowStatus(models.IntegerChoices):
    WAITING = 0, "待审核"
    PASSED = 1, "审核通过"
    REJECTED = 2, "审核不通过"
    ABORTED = 3, "审核取消"
```

**`current_status=1` = PASSED (不是 WAITING)**！且 96% 老 audit `current_audit=-1` 是"审批完成"常态, 不是异常。

### 第 3 步: 查 #4743 workflow_log (找到真审计)

`workflow_log WHERE audit_id=4797` 8 条:
1. 8/26 18:21:01 wyh 提交
2. 8/26 18:21:27 ct (研发组长) 审核通过 → 下级 研发负责人
3. 8/26 18:21:37 ljhong (研发负责人) 审核通过 → 下级 DBA审批
4. 8/26 18:22:41 mkq (DBA审批) 审核通过 → 下级 副总
5. 8/27 09:14:47 lisp (副总) 审核通过 → 下级 DBA执行
6. 8/27 09:19:15 mkq (DBA执行) 审核通过 → **无下级审批 (审批完成)**
7. 8/27 09:19:17 mkq **执行工单 / 工单执行排队中** ← 卡在这
8. 8/27 09:38:18 mkq **执行工单 / 工单开始执行** ← 新 qcluster 拉起
9. 8/27 09:38:19 系统 **执行结束 / 已正常结束** ← 1.5 秒跑完

**审批流程完整, 卡在第 7 步 (qcluster pick 任务失败)**。

### 第 4 步: 查 qcluster 进程 (找到真 P0)

`pgrep -fa "manage.py qcluster"`:
- 8 个进程全是 8/26 19:03:35 启的 nohup 老 qcluster (47537/47544/48467/48469-48473)
- **没一个新启的**

### 第 5 步: 查 redis connection (锁根因)

`ss -tnp | grep 6379`:
```
SYN-SENT  0  1  172.19.0.1:52730  →  172.19.0.4:6379  (python,pid=48467,fd=25)
```

**老 worker 48467 在尝试连 172.19.0.4:6379 (容器 redis 内网 IP)**！

### 第 6 步: qcluster.log tail (确认)

```
redis.exceptions.ConnectionError: Error 113 connecting to 172.19.0.4:6379. No route to host.
```

每 3 秒 retry 一次, 一直 fail。

---

## 根因 (1 行总结)

**8/26 19:03 启的 nohup qcluster worker 48467 内存里 redis connection 仍指 172.19.0.4:6379 (容器 redis, 8/26 K2 修复时已 kill), K2 修复改 .env (REDIS_HOST=127.0.0.1) 时没 reload qcluster, 老 worker 一直 BLPOP 失败, task 卡在 redis 队列没人执行**。

---

## 推 110 时间线 (还原事故)

| 时间 | 事件 | qcluster 状态 |
|------|------|---------------|
| **8/26 19:03:35** | nohup 启 qcluster (DBA 推 110 之前手起) | 读 .env REDIS_HOST=172.19.0.4 → 走 172.19.0.4 |
| 8/26 19:00+ | 推 110 启动 | (qcluster 在跑, 没影响) |
| 8/26 20:11 | K1 SECRET_KEY 修复 | (qcluster 不影响 SECRET_KEY) |
| 8/26 20:43 | K2 CACHE_URL 修复 + .env REDIS_HOST=127.0.0.1 | **❌ qcluster 没 reload, 老 worker 仍连 172.19.0.4** |
| 8/26 20:55 | K3 PRECHECK 修复 | (qcluster 不影响 PRECHECK) |
| 8/26 21:34 | 字段 diff 新功能 | (qcluster 不影响) |
| 8/26 21:57 | 字段 diff JS 修复 | (qcluster 不影响) |
| 8/26 23:10 | perm 拆分 7 min 收尾 | (qcluster 不影响) |
| 8/27 09:14-09:19 | 业务 RD mkq 审批 #4743 最后 2 步 | (qcluster 应该 pick 但 pick 不到) |
| 8/27 09:19:17 | mkq "工单执行排队中" (入队 task 卡死) | 老 worker 48467 BLPOP 172.19.0.4 持续 fail |
| 8/27 09:21 | mkq 浏览器截图反馈 | qcluster 持续 crash 172.19.0.4 |
| 8/27 09:38 | **本次修复: pkill 老 qcluster + nohup 拉新** | 新 worker 走 127.0.0.1:6379, 30s 后 #4743 finish |

**业务 RD mkq 之前没提 execute_sql 类的工单 (推 110 后演练都是 abort), 所以没人触发这个 bug**。

---

## 修复 (8/27 09:38)

### 操作

```bash
# 1. 备份老 qcluster log (跟 8/27 09:18 systemd disable 教训一致)
cp /var/log/archery/qcluster.log /var/log/archery/qcluster.log.bak_20260827_0938

# 2. pkill -9 老 qcluster 8 进程 (8/26 19:03 启的)
pkill -9 -f 'manage.py qcluster'

# 3. nohup 拉新 (走 c9236a0 新 .env)
cd /dbdata/archery_v114_c9236a0
setsid nohup sudo -u archery venv/bin/python manage.py qcluster \
  </dev/null >/var/log/archery/qcluster.log 2>&1 &
```

### 验证

| 检查 | 结果 |
|------|------|
| 新 qcluster 8 进程稳定 | ✓ (48092 sudo + 48094 master + 48694 worker + 5 sub-workers 48696-48701) |
| redis connection 走 127.0.0.1:6379 | ✓ (4 个 ESTAB 127.0.0.1:54850/54868/54852/54880) |
| 无 172.19.0.4 错 | ✓ (grep -c = 0) |
| gunicorn 没被误杀 | ✓ (6 进程 + /login/ 200) |
| #4743 状态 | ✓ `workflow_finish, finish_time=2026-08-27 09:38:19.098818` |
| 5+1 端点 + Django test client | ✓ 全过 |

### 修复到恢复时间

- 9:38 启动新 qcluster
- 9:38:18 新 worker BLPOP 拿 #4743 task
- 9:38:19 task finish (1.5 秒执行)
- **30 秒恢复**！

---

## 教训 (跨项目可复用, 4 条)

### 1. **Python qcluster 进程不 reload .env, 改 .env 必重启 qcluster** (核心)

跟 8/24 教训 "gunicorn HUP 不重载 Python 代码" 同源, 但更隐蔽:
- gunicorn HUP 不 reload 是因为 gunicorn 自身不监听 HUP 触发 reload
- qcluster **没有 HUP 接口**, 只能重启整个进程才能 reload .env
- 推 110 改 .env (REDIS_HOST, CACHE_URL, REDIS_PASSWORD, SECRET_KEY) 后, 必查 "哪些 long-running python 进程读了这个 .env"
- 110 prod 长寿 python 进程: gunicorn (4 worker) + qcluster (1 master + 6 workers) + 后台 cron (django_q schedule)
- gunicorn 重启 = kill master + nohup 拉新 (8/24 教训应用)
- **qcluster 重启 = pkill -9 -f 'manage.py qcluster' + nohup 拉新** (本次新加)

### 2. **audit_id `current_audit=-1` + `current_status=1` 是"审批完成"常态, 不是异常**

96% 老 audit 都是这个模式 (4638/4803 条), 是 c9236a0 新 audit 引擎在审批流走完时正常设置的值:
- `current_audit=-1`: 没人再等审批
- `next_audit=-1`: 没有下级审批
- `current_status=1 (PASSED)`: 审计已通过

**如果看到 `current_audit=-1` 配合 `sql_workflow.status=workflow_queuing`, 真正要看 `workflow_log` 走了几步, 不是 audit 表**.

### 3. **业务 RD "工单执行排队中" 状态 = audit PASSED + 等 qcluster pick**

截图里 "工单执行排队中" 是 `workflow_log.operation_info` 字段, 出现一次在 `operation_type=5 (EXECUTE_START)` 阶段, 表示:
- 审计通过 (current_status=PASSED)
- 走 audit 引擎入队 `sql.utils.execute_sql.execute` (via django_q_task + redis 队列)
- 等 qcluster BLPOP `django_q` 列表 + 跑 task

**真正卡死要看 qcluster log 跟 redis connection**, 不看 audit 表。

### 4. **.env 改完必做 5+1 检查**

每次推 prod 改 .env 必做:
1. `pkill -9 -f 'manage.py qcluster'` + nohup 拉新
2. `ss -tnp | grep 6379` 看 connection 走新 IP
3. `tail qcluster.log` 看无旧 IP 错
4. `ps -o pid,lstart` 看 qcluster 启动时间是"现在"
5. `mysql ... django_q_task` 看有新 task 入队
6. (可选) 提一个测试 DML 工单, 验证 30s 内 finish

---

## 同源 entry

- 8/27 09:18 110 prod systemd 双 unit 清理实战 (推 prod 后清理 idempotent 操作)
- 8/27 08:12 cron 推 110 收尾验证 (systemd ghost restart 风暴发现)
- 8/26 23:11 推 110 perm 拆分 7 min 收尾
- 8/26 21:57 8/26 推 110 实战收尾 (3 P0 + 1 新功能 + 1 fix)

---

## 下次推 prod 必做 (强化, 5 条)

1. 推完 .env 改后必 `pkill -9 -f 'manage.py qcluster' && nohup 拉新` (8/27 P4 新加)
2. 推完必 `systemctl disable --now <svc>-gunicorn.service <svc>-qcluster.service` (8/27 09:18 已加)
3. 推前 check 脚本必用 `Model._meta.db_table` 拿真表名 (8/27 08:12 已加)
4. cron 异步 check 期望 pid 必带 `pgrep -fa 'gunicorn.*<svc>'` fallback (8/27 08:12 已加)
5. 推 prod 后必 verify 110 prod `.env` 跟 systemd `EnvironmentFile=` 路径一致 (8/27 08:12 已加)

**这次要写进 `5step_prerequisites_110prod.sh` 作为"步骤 14: 重启 qcluster + verify redis connection"** (idempotent, 推前 qcluster 已是新启也再 restart 一次, 0 风险)。
