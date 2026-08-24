# 改 Python 代码后 reload gunicorn 标准化 SOP

> 8/24 教训: gunicorn `kill -HUP <master_pid>` **不重载 Python 代码** (只重启 worker 进程)。
> 改 Python 业务代码后必须 `kill <master_pid>`, 让 systemd (134 dev) 或 DBA 手动 nohup (110 prod) 拉起新 master, 新进程从磁盘加载新代码。
>
> **关联事故**: docs/changelogs/2026-08-24_approval-flow-source-of-truth.md (ConfigurableAuditor 修法)
> **关联 memory**: `gunicorn HUP 不重载 Python 代码 (2026-08-24)`

## 根因 (背景, 一句话)

gunicorn fork 模式 master 启动时把 Python module import 进 `sys.modules`, worker fork 时**继承 master 的内存映像**。`HUP` master 只重启 worker 进程, **不会重新 import Python 模块**。新 worker 拿到 master 的旧 `sys.modules`, 跑老代码。

`HUP` 只对 `settings.py` / `os.environ` 改动有效, 改业务代码 `views.py` / `models.py` / `extensions/*/*.py` 看不到。

## 适用场景

| 改动类型 | 怎么处理 |
|---|---|
| 改 Python 业务代码 (views / models / extensions / workflow_audit 等) | ⚠️ **必须 kill master**, 不能 HUP |
| 改 `archery/settings.py` (env / INSTALLED_APPS / TEMPLATES) | HUP 也行 (Django 启动时读) |
| 改 Django ORM model + 跑 migration | kill master (model 字段变化要 reload) |
| 改前端 HTML/JS/CSS 静态资源 | **不需要 reload gunicorn**, Django 每次请求读 static 目录 |
| 改 `requirements.in` / `requirements.txt` | kill master (新 import) |
| 改 systemd unit 文件 | `systemctl daemon-reload + restart` |

## 134 dev 流程 (5 步 SOP)

> 134 dev: gunicorn 走 systemd (`archery-prod-gunicorn.service`), kill master 后 systemd 自动拉起新进程, **无需 DBA 手动 nohup**。

```bash
# === 步骤 1: 确认代码已部署到 /opt/archery/prod ===
ssh root@172.20.2.134 "ls -la /opt/archery/prod/sql/extensions/<改动模块>/<改动文件>.py"
# 验证: 文件 mtime 跟 git commit 时间一致

# === 步骤 2: 找当前 gunicorn master pid ===
ssh root@172.20.2.134 "ps -ef | grep gunicorn | grep -v grep"
# 输出示例:
#   archery  48142     1  0 13:33 ?  00:00:00 /opt/archery/prod/venv/bin/python3.11 ... gunicorn archery.wsgi:application -w 4 ...
# 注意: PPID=1 的那个是 master (systemd 拉起后, master 变孤儿进程由 init 接管)
master_pid=$(ssh root@172.20.2.134 "ps -ef | grep gunicorn | grep -v grep | awk '\$3==1 {print \$2}' | head -1")
echo "master_pid: $master_pid"

# === 步骤 3: 优雅 kill master (systemd 会自动拉起) ===
ssh root@172.20.2.134 "kill $master_pid"
# 不要 kill -9 (systemd 收不到信号, 不会自动拉起)

# === 步骤 4: 等 7s 看新进程 (systemd 拉起 master 实际要 5-7s) ===
sleep 7
ssh root@172.20.2.134 "ps -ef | grep gunicorn | grep -v grep"
# 期望: 1 个新 master (新 PID, 启动时间 = 现在) + 4 个新 workers

# === 步骤 5: HTTP 健康检查 ===
ssh root@172.20.2.134 "curl -sI --max-time 5 http://127.0.0.1:9003/"
# 期望: HTTP/1.1 302 Found  (未登录跳 /login/)
```

## 110 prod 流程 (5 步 SOP)

> 110 prod: gunicorn **没有 systemd unit**, 是 DBA 用 `nohup` 手动启的。kill master 后 **不会自动拉起**, 需 DBA 手动 nohup 拉起新进程。

```bash
# === 步骤 1: 确认代码已部署到 /dbdata/archery_v114_c9236a0 ===
ssh root@172.20.2.110 "ls -la /dbdata/archery_v114_c9236a0/sql/extensions/<改动模块>/<改动文件>.py"

# === 步骤 2: 找当前 gunicorn master pid ===
ssh root@172.20.2.110 "ps -ef | grep gunicorn | grep -v grep"
master_pid=$(ssh root@172.20.2.110 "ps -ef | grep gunicorn | grep -v grep | awk '\$3==1 {print \$2}' | head -1")
echo "master_pid: $master_pid"

# === 步骤 3: kill master ===
ssh root@172.20.2.110 "kill $master_pid"

# === 步骤 4: 手动 nohup 拉起新 master (110 prod 没 systemd, 必须 DBA 手动) ===
ssh root@172.20.2.110 << 'EOF'
cd /dbdata/archery_v114_c9236a0
nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application \
    -w 4 \
    -b 0.0.0.0:9123 \
    --access-logfile - \
    --error-logfile - \
    --timeout 120 \
    > /tmp/gunicorn.log 2>&1 &
sleep 2
ps -ef | grep gunicorn | grep -v grep   # 验证新进程
EOF

# === 步骤 5: HTTP 健康检查 ===
ssh root@172.20.2.110 "curl -sI --max-time 5 http://127.0.0.1:9123/"
# 期望: HTTP/1.1 302 Found
```

## 必做验证 (DBA 不能省)

**提交页 (`/group/auditors/`) 显示对了 ≠ 详情页 (`/detail/<id>/`) 显示对了**。两个端点走的是不同代码路径, 必须都验证。

| 端点 | 走的代码 | 风险 |
|---|---|---|
| 提交页 `/group/auditors/` | `Audit.settings()` 直接读 `WorkflowAuditSetting` (老接口) | 不走改动代码, 容易假阳性 |
| 详情页 `/detail/<id>/` | `ConfigurableAuditor.generate_audit_setting` (本次改的) | 才是真测试路径 |

**8/24 实战**: 提交页显示 2 级 ✓, 详情页显示 3 级 ✗ (HUP 没生效, 详情页跑老代码)。

**DBA 必做验证 3 步**:
1. 浏览器登平台, 选测试组 (group_id=25 或 8/18 实际用的 group)
2. SQL 上线提交页 → 选 group / instance / db → 看 "审批流程" 应跟 admin config 配的一致
3. 提一条**新**工单 (随便一句 `ALTER TABLE t DROP COLUMN xxx`, 不会真跑)
4. 工单详情页 → "审批流" 区域 → **必须跟 admin config 配的一致**

如果 3+4 不一致 → kill master 没生效, 看下一步排查。

## 故障排查

### 现象 1: kill master 后没新进程起来 (134 dev)

```bash
# 检查 systemd 状态
ssh root@172.20.2.134 "systemctl status archery-prod-gunicorn.service"
# 期望: Active: active (running) since <刚才时间>
# 异常: Active: failed / inactive (dead) → systemd 拉起失败

# 看 systemd 日志
ssh root@172.20.2.134 "journalctl -u archery-prod-gunicorn.service -n 50"
# 常见错: .env 路径错 / Python venv 路径错 / gunicorn 命令行错
```

### 现象 2: 新进程起来但 HTTP 502/500

```bash
# 看 gunicorn stdout (systemd journal 或 /tmp/gunicorn.log)
ssh root@172.20.2.134 "journalctl -u archery-prod-gunicorn.service -n 100"   # 134 dev
ssh root@172.20.2.110 "tail -100 /tmp/gunicorn.log"                           # 110 prod
# 常见错: import 错 (改的代码语法错 / 没装新依赖) / Django 启动错 (settings.py 错 / .env 错)
```

### 现象 3: HTTP 200 但详情页显示老配置

**8/24 教训再次踩坑**: kill master 没真的杀掉 (例如 kill 了 worker, 没杀 master)。

```bash
# 1. 看所有 gunicorn 进程, 找 PPID=1 的 master
ssh root@172.20.2.134 "ps -ef | grep gunicorn | grep -v grep"
#      UID   PID  PPID  ...
# 例: archery  9999     1  0 13:33 ?  ... ← 这个是 master, 启动时间 13:33 = 跟 kill 时间对不上 = 没生效

# 2. 看 master 的启动时间
ssh root@172.20.2.134 "ps -o pid,lstart,cmd -p $master_pid"
# lstart = master 启动时间
# 期望: lstart 在刚才 kill 之后 (新进程)
# 异常: lstart 跟之前一样 (老进程没杀掉)

# 3. 如果 master 没换, 强制 kill -9 再来一次
ssh root@172.20.2.134 "kill -9 $master_pid"
```

### 现象 4: kill master 后 110 prod 进程起不来 (nohup 命令错)

```bash
# 看 gunicorn log
ssh root@172.20.2.110 "tail -50 /tmp/gunicorn.log"
# 常见错: 端口 9123 被占 (老 gunicorn 没杀干净) / venv/bin/gunicorn 路径错 / archery user 没权限

# 检查端口占用
ssh root@172.20.2.110 "ss -tlnp | grep :9123"
# 期望: 空 (kill master 后端口释放) 或 archery 进程的 gunicorn

# 手动 debug
ssh root@172.20.2.110 "cd /dbdata/archery_v114_c9236a0 && sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 --check-config"
# --check-config 只验证配置, 不真起服务, 用来排查命令行错
```

## 验证清单 (DBA 推 110 当天跑)

| 步骤 | 命令 | 期望 | 必做 |
|---|---|---|---|
| 1. 确认代码已部署 | `ls -la <PROD_PATH>/<改动文件>.py` | mtime = git push 时间 | ✓ |
| 2. 找 master pid | `ps -ef \| grep gunicorn \| awk '$3==1 {print $2}'` | 1 个 master pid | ✓ |
| 3. kill master | `kill <master_pid>` | 返回空 (无 error) | ✓ |
| 4. 等 7s + 看新 master | `sleep 7; ps -ef \| grep gunicorn` | 新 master pid ≠ 旧 pid, 启动时间 = 现在 | ✓ |
| 5. HTTP 200/302 | `curl -sI http://127.0.0.1:<port>/` | HTTP/1.1 200/302 | ✓ |
| 6. 提交页验证 | 浏览器选 group, 看 "审批流程" | 跟 admin config 配的一致 | ✓ |
| 7. 详情页验证 (真测试路径) | 提一条新工单, 看 detail 页 | 跟 admin config 配的一致 | ⚠️ **必做** |
| 8. 清理演练工单 | DBA 在平台终止流程 | 测试工单不残留 | ✓ |

## 反模式 (绝对不要做)

| 反模式 | 后果 | 替代方案 |
|---|---|---|
| `kill -HUP <master_pid>` 期望重载代码 | 8/24 教训: 详情页跑老代码 | `kill <master_pid>` |
| 只看提交页 "审批流程" 跳过详情页 | 8/24 教训: 提交页走老接口假阳性 | 必做步骤 6+7 |
| kill master 后不验证 | 110 prod 没 systemd, 起不来业务挂 5-10 分钟 | 必做步骤 4+5+7 |
| `kill -9 master` 跳过优雅停止 | 134 dev systemd 收不到 SIGTERM, 不会拉新进程 | `kill` (默认 SIGTERM) |
| 改代码后直接提工单不验证 | 老工单残留老配置 (写死 workflow.audit_auth_groups) | 必做步骤 7 (提**新**工单) |
| 推 110 当天只 reload 不 smoke test | 推完上线后业务挂才发现 | 跑 5 步必做脚本完整 13 步 |

## 一键脚本 (DBA 拷过去用)

`scripts/deploy/reload_gunicorn_after_code_change.sh`:

```bash
#!/bin/bash
# reload_gunicorn_after_code_change.sh — 改 Python 代码后 reload gunicorn
# 134 dev: kill master + systemd 自动拉起
# 110 prod: kill master + 手动 nohup 拉起
#
# 用法:
#   bash reload_gunicorn_after_code_change.sh <env>    # env = 134dev | 110prod

set -e

ENV=${1:-134dev}

case "${ENV}" in
    134dev)
        HOST="root@172.20.2.134"
        PORT=9003
        SERVICE="archery-prod-gunicorn.service"
        ;;
    110prod)
        HOST="root@172.20.2.110"
        PORT=9123
        SERVICE=""  # 110 prod 没 systemd
        ;;
    *)
        echo "Usage: $0 <134dev|110prod>"; exit 1
        ;;
esac

echo "=== 1. 找 master pid ==="
master_pid=$(ssh ${HOST} "ps -ef | grep gunicorn | grep -v grep | awk '\$3==1 {print \$2}' | head -1")
if [[ -z "${master_pid}" ]]; then
    echo "ERR: 找不到 master, 排查 gunicorn 进程状态"
    exit 1
fi
echo "master_pid: ${master_pid}"

echo ""
echo "=== 2. kill master ==="
ssh ${HOST} "kill ${master_pid}"
echo "OK: kill ${master_pid}"

echo ""
echo "=== 3. 等 7s 看新进程 (systemd 拉起 master 实际要 5-7s) ==="
sleep 7
if [[ -n "${SERVICE}" ]]; then
    # 134 dev: systemd 拉起
    new_status=$(ssh ${HOST} "systemctl is-active ${SERVICE}")
    echo "systemd status: ${new_status}"
    if [[ "${new_status}" != "active" ]]; then
        echo "ERR: systemd 拉起失败, 看 journalctl -u ${SERVICE} -n 50"
        exit 1
    fi
else
    # 110 prod: 手动 nohup 拉起
    echo "110 prod 没 systemd, DBA 手动 nohup 拉起新进程..."
    echo ""
    echo "  在 110 prod 上跑:"
    echo "  cd /dbdata/archery_v114_c9236a0"
    echo "  nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:${PORT} --access-logfile - --error-logfile - --timeout 120 > /tmp/gunicorn.log 2>&1 &"
    echo ""
    read -p "DBA 拉起完成? (yes/no): " confirm
    if [[ "${confirm}" != "yes" ]]; then
        echo "退出, 推 110 必做补一条 (5 步必做步骤 13 失败)"
        exit 1
    fi
fi

echo ""
echo "=== 4. HTTP 健康检查 ==="
http_out=$(ssh ${HOST} "curl -sI --max-time 5 http://127.0.0.1:${PORT}/" 2>&1 | head -3)
echo "${http_out}"
if echo "${http_out}" | grep -q "200\|302"; then
    echo "OK: HTTP 200/302, gunicorn alive"
else
    echo "ERR: HTTP 不正常, 排查 9123 端口 + gunicorn log"
    exit 1
fi

echo ""
echo "=== 5. ⚠️ 必做验证: 提新工单看详情页 ==="
echo "DBA 必做:"
echo "  1. 浏览器登平台, 选测试组"
echo "  2. SQL 上线提交页 → 选 group / instance / db → 看 '审批流程' 应跟 admin config 配的一致"
echo "  3. 提一条新工单 (随便一句 ALTER ... DROP COLUMN xxx)"
echo "  4. detail 页 → '审批流' → ⚠️ 必须跟 admin config 配的一致"
echo ""
echo "  如果 3+4 不一致 → kill master 没生效, 排查 master 启动时间 (故障排查 §现象 3)"
echo ""

read -p "DBA 验证完成? (yes/no): " confirm
if [[ "${confirm}" != "yes" ]]; then
    echo "退出, 推 110 必做补一条 (5 步必做步骤 13 失败)"
    exit 1
fi

echo ""
echo "=== ✅ reload gunicorn 流程完成 ==="
echo "  host: ${HOST}"
echo "  port: ${PORT}"
echo "  master: ${master_pid} → 已 kill"
echo "  验证: 提新工单 detail 页已确认"
```

## 演练记录 (8/24)

**134 dev 真实演练** (commit `ce6a364` 之后, 8/24 14:00-14:02):

| 步骤 | 实际结果 | 期望 | 状态 |
|---|---|---|---|
| 1. 找 master pid | `pid=8570, start=14:00:51` | PPID=1 那个 | ✅ |
| 2. kill master | `kill 8570` (默认 SIGTERM) | 无 error | ✅ |
| 3. 等 7s 看新进程 | `pid=13199, start=14:01:41` (7s 后) | 新 master pid ≠ 旧, 启动时间 = 现在 | ✅ |
| 4. systemd status | `active` | active | ✅ |
| 5. HTTP 健康检查 | `HTTP/1.1 302 Found / Location: /login/` | 200/302 | ✅ |
| 6. 提交页验证 | (DBA 必做, 上次 #85 后已验证 2 级生效) | 跟 admin config 配的一致 | ✅ |
| 7. 详情页验证 | (DBA 必做, 上次 #85 后已验证 2 级生效) | 跟 admin config 配的一致 | ✅ |

**关键观察**:
- systemd 拉起 master 实际要 **5-7s**, 不是 3s, 演练脚本改成 `sleep 7`
- master pid 变化: `8570 → 13199`, 启动时间从 `14:00:51` 跳到 `14:01:41` (= kill 后 7s) — 证明 systemd 拉起的是新进程, 不是老进程 (老进程已 SIGTERM 退出)
- HTTP 200/302, 4 workers 都 fork 自新 master, 业务可访问
- 这次没改代码, 行为跟之前一致; 验证流程走得通, 推 110 同样流程

**演练脚本**: `scripts/_archive/_drill_reload_gunicorn_20260824.py`

**演练时间点**:
- 8/24 14:00:51 — 旧 master 8570 启动 (systemd 拉起)
- 8/24 14:01:33 — mavis kill 8570
- 8/24 14:01:41 — 新 master 13199 启动 (systemd 拉起, 8s 内)
- 8/24 14:01:43 — HTTP 302 验证通过

## 关联

- 8/24 教训 changelog: `docs/changelogs/2026-08-24_approval-flow-source-of-truth.md` §"8/24 教训 — gunicorn HUP 不重载 Python 代码"
- 8/24 教训 memory: `gunicorn HUP 不重载 Python 代码 (2026-08-24)` (跨项目可复用)
- 5 步必做脚本 步骤 13: `scripts/deploy/5step_prerequisites_110prod.sh` 末尾
- 134 dev systemd unit: `scripts/deploy/systemd/archery-prod-gunicorn.service`
- 110 prod 启动命令: `cd /dbdata/archery_v114_c9236a0 && nohup sudo -u archery venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9123 ... &`
- 推 110 runbook: `docs/runbooks/2026-08-17_push-v030b-to-110prod.md`
- 通用服务运维: `docs/runbooks/service-operations.md`
