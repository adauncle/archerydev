# 8/27 15:15 poller zombie + 终态显示 双重修复

## 症状
- 业务 RD mkq 8/27 15:07 反馈：工单 #4752 (task #4) 状态显示"执行有异常"，但 gh-ost 状态显示"执行中 0% 重试中"
- task #4 ghost 进程 14:11 报 1064 SQL syntax 错误后死掉，task.status 一直卡在 `running` 不联动
- 业务 RD 浏览器刷 30 分钟，进度面板一直显示"轮询中 · 3s 刷新"和"执行中 0%"
- 同一工单业务 RD 8/27 14:40 重新提的 task #6 已 100% 成功（9m53s 跑完 hly_doc_model.test 7.28M rows）

## 根因
1. **is_alive 用 `os.kill(pid, 0)` 对 zombie 返 True** — gh-ost 子进程报 1064 后立即死掉，父进程 (gunicorn worker 39719) 没 wait() reap，进程变 zombie。`os.kill(pid, 0)` 对 zombie 返 0 (PID 存在)
2. **poller 死循环** — poller `is_alive` 返 True (zombie 误判 alive) + log 空 (gh-ost 死太快没机会写 log) → 永远 sleep 3s 不到 `_finalize_task` 分支
3. **前端 progress.html 终态判断缺 `rolled_back`** — status 映射只有 success/failed/cancelled，rolled_back 显示原始 status 字符串
4. **前端 JS polling 终态判断缺 `rolled_back`** — 终态判断 `["success", "failed", "cancelled"]` 漏 rolled_back，rolled_back 后还继续 polling

## 修法

### A. 后端 poller 改进
1. **runner.py is_alive 区分 zombie** — 在 `os.kill(pid, 0)` 基础上加 `/proc/<pid>/status` 检查 `State:` 字段，`Z` (zombie) 视为已死：
   ```python
   def is_alive(pid: int) -> bool:
       if not pid: return False
       try: os.kill(pid, 0)
       except (ProcessLookupError, PermissionError): return False
       try:
           with open(f"/proc/{pid}/status", "r") as f:
               for line in f:
                   if line.startswith("State:"):
                       if "Z" in line.split()[1]:
                           return False
                       return True
       except (FileNotFoundError, ProcessLookupError): return False
       return True
   ```
2. **poller.py 加 staleness 检测** — 进程 alive 但 log mtime > 60s 没更新视为卡死，task 标 failed（双保险，防 gh-ost 卡死场景）：
   ```python
   STALENESS_THRESHOLD = 60  # 秒
   # log 文件存在但 mtime 超过阈值秒没变 → failed
   # log 文件压根没生成 (gh-ost 启动失败没写 log) + started_at > 60s → failed
   ```

### B. 前端 progress.html 改进
1. **Django template 终态文字加 `rolled_back`** — line 114-118 增 "已回滚" 分支
2. **终态 pct 强制 100%** — progress-pct 数字 + progress-bar-fill 宽度在 `task.is_terminal` 时 100%（避免 0% + 终态矛盾显示）
3. **JS 终态判断用 is_terminal 全集** — `TERMINAL_STATUSES = ["success", "failed", "cancelled", "rolled_back"]`，终态时 setTimeout reload 而非继续 polling
4. **JS status 映射加 `rolled_back`** — 渲染 "已回滚" 中文

## 验证
- **134 dev** 演练 (待 commit + deploy):
  - 启动 task 模拟 gh-ost zombie 场景: 拿一个 task 改 ghost_pid=已死 PID, 观察 poller 3s 内切到 failed
  - 演练 build_ghost_command + 真实 task #1 alter 提取
- **110 prod** 部署 (待 commit + deploy):
  - 推 runner.py + poller.py + progress.html
  - 5 端点 HTTP 全过
  - 真实 task #4 状态保持 failed (不复活), task #6 状态保持 success

## 教训（跨项目可复用）
1. **`os.kill(pid, 0)` 不能区分 zombie 和 alive** — 任何用 `os.kill(pid, 0)` 做存活检测的代码, 都要加 `/proc/<pid>/status` State 字段判断 zombie, 否则僵尸进程永远"活着"
2. **Linux zombie 进程需要父进程 wait() reap** — gunicorn worker 没注册 SIGCHLD handler 时, 子进程死后变 zombie 占 PID. 强杀父进程或加 `signal.signal(SIGCHLD, SIG_IGN)` 让 init 接管 reap
3. **poller 必须有 staleness 检测** — 仅"进程活着"不够, 还要"log 末尾 N 秒有更新". alive + no log update = 卡死, 视为 failed
4. **前端终态判断必须跟 model 终态一致** — 任何 hardcode 的 `["success", "failed", "cancelled"]` 都会漏新加的 rolled_back, 用 `task.is_terminal` (model property) 单一来源

## 关联 commit
- 8/27 15:30 待 commit
- 8/27 15:35 134 dev 部署
- 8/27 15:40 推 110 prod
