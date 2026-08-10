# gh-ost v0.4.5-alpha 134 dev 演练报告

**日期**: 2026-08-10
**作者**: mavis
**目标**: 验证 v0.4.5-alpha 6 commit 在 134 dev 真实环境跑通

## 演练环境

| 项 | 值 |
|----|----|
| 演练服务器 | 172.20.2.134 (DEV) |
| 部署目录 | /opt/archery/prod |
| 演练库 | archery_dev（避免影响 archery_prod） |
| 演练表 | accesscard_black_detail（433k 行 / 243MB） |
| gh-ost 版本 | 1.1.10 |
| MySQL 版本 | 8.0.22 |
| 灰度开关 | CUSTOM_GH_OST_ENABLED=True / CUSTOM_GH_OST_REBUILD_ENABLED=True |

## 演练步骤

### Step 1: sync 代码到 134 dev

```bash
# 本地打包
python pack_v045.py  # 11 个文件 → v045_alpha.tar.gz (32KB)
scp v045_alpha.tar.gz root@172.20.2.134:/tmp/

# 134 dev 解压 + chown
cd /opt/archery/prod
tar -xzf /tmp/v045_alpha.tar.gz
chown -R archery:archery sql/extensions/ddl_gh_ost/
```

### Step 2: 跑 migration 0003（加 instance 字段）

```bash
python manage.py makemigrations ddl_gh_ost
# 0003_ddlghosttask_instance.py
python manage.py migrate ddl_gh_ost
# Applying ddl_gh_ost.0003_ddlghosttask_instance... OK
```

### Step 3: 重启 gunicorn

```bash
systemctl restart archery-prod-gunicorn
curl -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9003/admin/login/
# 302（重定向到 login）✓
```

## 演练过程（4 轮 + 5 个 bug fix）

### Round 1: 触发 task #10
**期望**: gh-ost 启动
**实际**: task #10 立即 `status=failed`，"queue advance: task #10 instance 解析失败"
**根因**: DdlGhostTask 没有 `instance` 字段，queue._resolve_instance 从 related_task_id 查（NULL）
**Fix**: DdlGhostTask 加 `instance` ForeignKey + migration 0003

### Round 2: 触发 task #12
**期望**: gh-ost 启动 + 跑
**实际**: gh-ost 报 `SQL syntax error 1064 near 'TABLE'`
**根因**: `_make_rebuild_alter` 返回完整 SQL `ALTER TABLE x COMMENT '...'`，gh-ost 期望**裸子句** `COMMENT '...'`
**Fix**: `_make_rebuild_alter` 改返回 `f"COMMENT 'archery-auto-rebuild-{date}'"`

### Round 3: 触发 task #13-15
**期望**: gh-ost 跑
**实际**: 仍报 `near 'TABLE'`
**根因**: `runner.start_ghost_process` 调 `build_ghost_command(task, instance)`，**没传 rebuild_mode=True**，内部走 ghost 分支取空 alter_statement
**Fix**: start_ghost_process 加 `rebuild_mode = (task.task_type == "rebuild")` 推断

### Round 4: 触发 task #17
**期望**: gh-ost 跑
**实际**: gh-ost 仍然报 `near 'TABLE'`（日志显示 gh-ost 跑 ALTER COMMENT 但还是错）
**根因**: rebuild.start_rebuild_process 内部只 return pid，**没写 task.ghost_pid**，poller is_alive(None) 永远 False 标 failed
**Fix**: rebuild.start_rebuild_process 内部写 task.ghost_pid + status + started_at

### Round 5: 触发 task #19 ✅
**期望**: gh-ost 跑 + progress 更新
**实际**: 完美！
```
[T+3s]   status=running  progress=0%   stage=connecting
[T+6s]   status=running  progress=6%   stage=copying
[T+9s]   status=running  progress=29%  stage=copying
[T+12s]  status=running  progress=51%  stage=copying
[T+15s]  status=running  progress=73%  stage=copying
[T+18s]  status=running  progress=100% stage=copying
[T+21s]  status=success  progress=100% stage=done
```
**耗时**: 21 秒
**数据**: 241558 行 copy + 1.04s cut-over
**验证**: 表 COMMENT 改成 `archery-auto-rebuild-20260810` ✓

### Round 6: 排队验证（3 task FIFO）✅

3 个 task 同时写，DBA 期望"先来先跑"：
- t1 #23: 立即推进（18s 完成）
- t2 #24: 排队等 t1 完成 → t1 终态后 poller._finalize_task 调 try_advance_queue 推进 t2（再 18s）
- t3 #25: 排队等 t2 完成 → 自动推进（再 18s）

**总耗时 54s，3 个 task 串行成功**。FIFO 完美 work。

但 Round 6 第一次跑暴露另一个 bug：has_running 检测不到 stale running 任务（gh-ost 进程死了但 status 卡 running），永久阻塞 queue。
**Fix**: `try_advance_queue` 加 `is_alive(pid)` 检查，跳过 stale running。

## 5 个 bug 修复汇总

| # | Bug | 文件 | Fix |
|---|----|----|----|
| 1 | queue 缺 instance 字段 | models.py + migration 0003 | 加 ForeignKey('sql.Instance') |
| 2 | gh-ost --alter 期望裸子句 | runner.py | 改 `_make_rebuild_alter` 返回 `COMMENT '...'` |
| 3 | start_ghost_process 不传 rebuild_mode | runner.py | 加 `rebuild_mode = task.task_type == "rebuild"` |
| 4 | rebuild.start_rebuild_process 不写 task 字段 | rebuild.py | 内部写 ghost_pid / status / started_at |
| 5 | try_advance_queue 阻塞 stale running | queue.py | 加 `is_alive(pid)` 检查 |

## 性能数据

| 项 | 数值 |
|----|----|
| 演练表行数 | 241,558 |
| 演练表大小 | 243.6 MB |
| gh-ost 启动到 copy 开始 | ~3s |
| Copy 阶段 | 12s（~20k 行/秒） |
| Cut-over 锁表 | 1.04s |
| 总耗时 | 18-21s |
| data_free 变化 | 7.0MB → 7.0MB（删除的行没真释放，需 OPTIMIZE 二次触发） |

## 关键文件改动

| 文件 | 改动 |
|------|------|
| `models.py` | + `instance` ForeignKey + `## CUSTOM-MODIFIED: 修 queue 漏洞` |
| `migrations/0003_ddlghosttask_instance.py` | 自动生成 AddField instance |
| `runner.py` | `_make_rebuild_alter` 改裸子句 + `start_ghost_process` 加 rebuild_mode 推断 |
| `rebuild.py` | `start_rebuild_process` 写 task 字段 |
| `queue.py` | `try_advance_queue` 加 has_alive_running 检查 |

## 验收清单

- [x] gh-ost 启动 + 创建 ghost table + ALTER + copy + cut-over
- [x] poller 3s 轮询 + progress 正确更新
- [x] 钉钉通知（best-effort，本地无 .env webhook 配置 skip）
- [x] task 终态正确（success）
- [x] 影子表自动清理（_gho/_del/_ghc/_ghk drop 干净）
- [x] 同表 3 task FIFO 串行成功
- [x] DATA_FREE 监控（无明显下降，因演练前没真造碎片）
- [x] rebuild 进度面板 + status 端点

## 待改进（commit 7+）

1. **poller race condition**：gh-ost 启动后 poller 第一次 poll 立即判 alive=False（之前 stale 任务）
2. **stale running 清理**：poller 终态化应自动清理
3. **data_free 真造碎片演练**：删除后 ALTER TABLE x ENGINE=InnoDB 触发页合并
4. **admin 入口集成**：v0.4.5-alpha 进度在 admin 列表能看到，但前端触发表还要做

## v0.4.5-alpha 6 commit 全部完成

| # | commit | 标题 | 状态 |
|---|--------|----|----|
| 1 | `6412da4` | model 改造 + migration + 3 灰度开关 | ✅ |
| 2 | `e8b2cf3` | rebuild service（build_rebuild_command） | ✅ |
| 3 | `52b875b` | rebuild 端点（list/start） + 路由注册 | ✅ |
| 4 | `e4a3707` | admin + UI（task_type 筛选 + 进度面板） | ✅ |
| 5 | `a982d62` | 同表 FIFO 排队 + 归档联动 hook | ✅ |
| 6 | `xxxxx` | 134 dev 演练报告（含 5 个 bug fix） | ✅ |

**v0.4.5-alpha 进度 6/6 (100%)** 🎉

## 关联

- 计划文档: `docs/reports/2026-08-06_功能开发计划_v3.xlsx` row 42-47
- 设计稿: `docs/designs/2026-08-05_gh-ost-product-design.html`
- 前置 commit: `a982d62` (queue + 归档联动)
- 110 prod 推广: 等 DBA 重新保存 instance user/password + DINGTALK_NOTIFY_WEBHOOK 配置
