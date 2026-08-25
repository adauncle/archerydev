# v0.4.5 碎片回收 选表页面 (方案 B) — 2026-08-25

## 症状 / 背景

设计稿 [`docs/designs/2026-08-13_v0405-ghost-rebuild-design.md` §6.3](../designs/2026-08-13_v0405-ghost-rebuild-design.md) 计划
建一个"DBA 选表页面" — 业务前端 3 步流程（选 instance → 看 top 碎片表 → 点开始），
原计划 8/12 写但被 gh-ost 任务管理列表页 + 字段 diff 等优先级挤掉，8/13 v0.4.5 拍板 3
决策时只补了 admin 后台 batch_rebuild action（方案 A，独立选表页面方案 B 留到 8/25）。

DBA 反馈：进 admin 后台操作有 3 不便：
1. 不知道 admin URL（`/admin/ddl_gh_ost/ddlghosttask/`）
2. admin 后台 batch_rebuild 看不到碎片率排序（要自己看 DATA_FREE）
3. admin 后台触发完要切到 admin_list 看进度，不直观

**8/25 11:00 用户拍板走方案 B**：DBA 走业务前端菜单（主菜单）入口一气呵成。

## 拍板方案 B 流程

| 步骤 | 动作 | 页面表现 |
|------|------|---------|
| ① 选 instance | 顶部下拉选一个 MySQL 实例（DBA 有权限的所有 instance） | 选完自动 AJAX 拉表 |
| ② 看 top 碎片表 | 中部表格按 **DATA_FREE 倒序** 列 top 200 InnoDB 表 | 列：库名 / 表名 / DATA_FREE (MB) / 总大小 (MB) / 碎片率% / 复选框 |
| ③ 点开始 | 勾 1~N 张表 → 点 **"开始回收"** | 跳进度页 `/gh_ost/rebuild/progress/<task_id>/`，3s 一次 polling |

**特殊设计**：
- 碎片率 < 5% 的表**默认灰显**（可不选，避免无效操作）
- 同表已有 running 任务时**后端拒**（FIFO 排队，跟 ghost 一致）
- 点"开始"后**不阻塞**——异步写 task + 启 gh-ost，页面立刻跳进度
- 进度页复用 ghost 进度页（同一套 polling / 终态 reload / 钉钉通知）

## 实施内容

### 1. 后端 view — `views.py`

**新 view** `rebuild_select_page` (DBA 专属入口)
- URL: `GET /gh_ost/rebuild/select/`
- 守卫: `_is_admin_or_dba(request.user)` (走 group 角色守卫，**不是 perm 守卫**)
  - 比 admin_list 的 `view_ddlghosttask` perm 更严：碎霸回收是 DBA 专属工具
  - 即使用户有 `view_ddlghosttask` perm, 只要不在 DBA / DBA组长 组, 一律 403
- 渲染 `rebuild_select.html` 模板
- 传可用 instance 列表（按 instance_name 排序）

**修** `rebuild_list` 端点（pct 计算公式）
- 原公式: `pct = (data_free / (data_len + 1)) * 100` — 小表畸形 (19199%)
- 新公式: `pct = data_free / (data_free + data_len + idx_len) * 100`
- 范围 0~100%, 一般表 0~30%, >50% 才建议 rebuild
- 演练验证: `workflow_log` 99.3%, `django_q_task` 4.6%, `workflow_audit` 99.4%

### 2. URL 路由 — `urls.py`

```python
path("rebuild/select/", views.rebuild_select_page, name="rebuild_select"),
```

### 3. 模板 — `templates/ddl_gh_ost/rebuild_select.html` (~16KB)

3 步指示器 + 3 卡片 (选 instance / 看表 / 勾表 + 开始)：
- Element UI 风格, 跟 task_list.html 视觉统一
- 步骤指示器: 灰色 → 蓝色 (active) → 绿色 (done)
- 表 checkbox 多选 + 碎片率颜色 (high red / mid orange / low gray)
- AJAX fetch `/gh_ost/rebuild/list/` + `/gh_ost/rebuild/start/` (复用现有端点)
- 串行触发: 每张表一个 POST, 任一失败就停, 全部完成后跳进度页

### 4. 主菜单 — `common/templates/base.html`

在 gh-ost 任务下拉子菜单内 (跟"任务管理"同级) 加"碎片回收"链接：
- 守卫: `user.is_superuser` 或属于 DBA / DBA组长 组 (跟 view 守卫一致)
- 图标: `fa-magic` (碎片回收的"魔法"语义)

### 5. 演练 — `scripts/_archive/_drill_rebuild_select_test_client.py`

Django test client (避开 Archery 启用的 2FA, 直接 force_login superuser):
```
1. GET /gh_ost/rebuild/select/  200  9/9 PASS (页面 9 项元素全对)
2. instance list                0 (HTML 占位 option, AJAX 拉真实)
3. GET /gh_ost/rebuild/list/    200  142 张表, 3 张 top 演示
4. POST /gh_ost/rebuild/start/  200  task_id=76 status=running pid=42723
5. status polling               8s 内 success
6. GET /gh_ost/rebuild/progress/76/  200
7. RD guard (oa_tester_1)       403  PermissionDenied 触发
```

## 验证

✅ 134 dev 后端演练全 PASS (Django test client, 8/25 14:30)
✅ 端到端真触发 (task #76 workflow_log rebuild 5s 内 success)
✅ RD 守卫 403 正确 (oa_tester_1 触发 PermissionDenied)
✅ pct 公式合理化 (99.3% / 4.6% / 99.4%)

## 推 110 检查

- 推 110 物料: views.py / urls.py / rebuild_select.html / base.html (4 文件)
- 推 110 后必做: 浏览器手动验证 admin 视角能进 / 业务 RD 视角 403
- 8/27 推 110 范围 包含本 commit (v0.3.0-beta + v0.4.5 全部)

## 教训 (跨项目可复用)

1. **DBA 工具要"找得到"**：admin 后台虽能配但 DBA 不知道 URL，主菜单入口降低使用门槛
2. **碎片率公式要合理**：`DATA_FREE / DATA_LENGTH` 跟 `DATA_FREE / (DATA_FREE + DATA_LENGTH + INDEX_LENGTH)` 差异巨大
3. **DBA 专属工具用 group 守卫，不用 perm**：perm 可以开放给 RD（看 ghost 任务），但碎霸回收是 DBA 专属，必须更严
4. **AngularJS 2FA 不能用 curl 模拟登录**：演练必须用 Django test client 或浏览器手动

## 关联

- 设计稿: `docs/designs/2026-08-13_v0405-ghost-rebuild-design.md` §6.3
- v0.4.5 拍板 3 决策: `docs/changelogs/2026-08-13_v0405-rebuilt-fields.md`
- gh-ost 任务管理列表页: `docs/changelogs/2026-08-12_gh-ost-task-list-page.md`
- 推 110 准备: `docs/runbooks/2026-08-27_push-v030-execution-manual.md`
