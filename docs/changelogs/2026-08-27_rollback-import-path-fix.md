# 8/27 17:00 rollback 端点 import 路径 fix

## 症状
- 业务 RD mkq 8/27 16:58 反馈: 工单 #4757 (task #6) 跑成功 100% 后, 点 "gh-ost 智能回滚" 按钮报错
- 错误信息: `[rollback] dropped=[] errors=["connect: No module named 'sql.extensions.ddl_gh_ost.db'"]`
- task #6 status 被错标 'rolled_back' (rollback 没真成功, 是 import 错误)
- 业务 RD 浏览器 task #6 详情页显示 "100% 已回滚" (rolled_back 蓝色 badge) + 错误信息卡片

## 根因
- `sql/extensions/ddl_gh_ost/views.py:461` rollback 端点写错 import 路径:
  ```python
  from .db import _get_creds  # 错误: views.py 在 ddl_gh_ost/ 目录, 指 ddl_gh_ost/db.py 不存在
  ```
- 实际 `db.py` 在 `sql/extensions/ddl_gh_ost/services/db.py` 子目录
- 同根因: `admin.py:197` (Django admin action rollback) 同样写错
- services/runner.py / services/precheck.py / services/poller.py 写的 `from .db` 正确 (它们在 services/ 目录, 相对 .db 指 services/db.py)

## 为什么 8/13 v0.4.0 + 8/24 v0.4.5 演练没暴露
- 8/13 fix 写这两个端点时, 业务 RD 还没点过 rollback (rollback 按钮只在 status=success 显示)
- 8/24 演练 16/16 PASS 全是 gh-ost 跑通场景, rollback 端点没真触发
- 8/25 8 阶段演练同样没真调 rollback 端点 (演练任务 status 没 success)
- 8/27 14:40 业务 RD 提的 task #6 是第一个真跑成功 100% 的 task, 也是第一个真点 rollback 按钮的

## 修法
- `views.py:461` 改: `from .db import _get_creds` → `from .services.db import _get_creds`
- `admin.py:197` 改: `from .db import _get_creds` → `from .services.db import _get_creds`

## 验证
- **110 prod 部署** (17:02):
  - scp views.py + admin.py → /dbdata/archery_v114_c9236a0/
  - 备份 .bak_20260827_1702
  - kill 真常驻 master 121336 (跑 89min) → nohup 拉新 126412 (跑 3min+) + 3 workers 跑新代码
- **演练 import 路径**:
  - `from sql.extensions.ddl_gh_ost.services.db import _get_creds` OK ✓
  - 旧路径 `from sql.extensions.ddl_gh_ost.db` 失败 (符合预期, 验证 bug 存在)
- **演练 _get_creds 真跑**:
  - task #6 (instance 27 prod core for history 变更) → user=archery host=172.20.2.108:6446 OK ✓
- **5 端点 HTTP 全过**: login 200 + admin/dbaprinciples/gh_ost/admin_list 302
- **DBA 干预**: task #6 status rolled_back → success, error_message 写 "[DBA 干预 2026-08-27 17:05] 原 rollback 因 import 错误没真成功, 改回 success 让业务 RD 重试"

## 业务 RD 后续
- 业务 RD mkq 浏览器刷新工单 #4757 / task #6 页面
- 现在 status=success, "回滚" 按钮可点
- 点 "回滚" 按钮 (新代码), 应该真回滚 (drop _test_gho + _test_del, 都不存在, dropped=[]), errors=[]
- status 切到 rolled_back, 业务 RD 看到完整成功

## 教训 (跨项目可复用)
1. **Django app 多层目录, 相对 import 容易写错** — `from .db` 在 services/ 子目录 OK, 在 app/ 顶层 (views.py / admin.py) 错. 写代码时要看清楚"自己在哪一层", 跨层级 import 加注释.
2. **rollback / cancel / retry 端点必须有"真演练"** — 不能只演练 gh-ost 跑通就完事, 还要演练"成功 → 回滚"链路. 这次业务 RD 第一个真点 rollback 才暴露 bug, 8/24 演练没覆盖.
3. **演练 checklist 必含"全生命周期"** — 8/24 + 8/25 演练只跑"提交 → 启动 → 成功"路径, 漏了"成功 → 回滚"路径. 任何新功能上线前必演"全生命周期" 至少 1 次.
4. **端点返错时 error_message 字段塞详细** — rollback 端点 line 485 把 errors 拼进 error_message, 业务 RD 能在前端看到完整堆栈, 不用 ssh 查 log

## 同源 entry
- 8/27 15:15 poller zombie 检测 (rollback 端点返回的 task 状态联动)
- 8/27 14:18 runner.py alter 子句提取 (rollback 端点用的 _get_creds 跟 start 端点共享)
- 8/13 v0.4.5-alpha 拍板 3 决策 (rollback 端点 8/13 拍板写)

## 关联 commit
- 8/27 17:08 待 commit
- 8/27 17:02 推 110 prod
