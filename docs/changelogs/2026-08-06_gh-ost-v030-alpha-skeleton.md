# gh-ost v0.3.0-alpha 骨架阶段（2026-08-06）

## 范围

v0.3.0-alpha：装 gh-ost 二进制 + 任务模型 + 预检查 5 道 + UI 骨架。**不真跑 gh-ost**，
只生成 task 记录（标记 "would use gh-ost"）。演练大表等 beta 真跑。

## 交付清单

### 后端

- `sql/extensions/ddl_gh_ost/`（Django app）
  - `apps.py` + `__init__.py` —— 标准 Django app 结构
  - `models.py` —— `DdlGhostTask` 模型，挂在 `sql_workflow` 上（一对一）
    - 状态机：`pending → queued → running → (success|failed|cancelled)`
    - 预检 5 道关固化快照（precheck_passed + precheck_report JSON）
    - 进度快照字段（progress_pct / rows_copied / speed / eta / threads_running）
    - 进程信息（ghost_pid / systemd_scope_unit）
    - 时间戳（created_at / started_at / finished_at / last_heartbeat_at）
    - cut-over 策略（immediate / low_traffic_window / manual）
    - 暂停阈值（threads_running > N）+ 超时熔断（默认 2h）
  - `migrations/0001_initial.py` —— 自动生成的建表 migration
  - `admin.py` —— DdlGhostTask admin（带进度条/状态徽章/工单跳转）
  - `views.py` —— 6 个 endpoint
    - `POST /gh_ost/precheck/<wf_id>/` —— 跑预检（不写 task）
    - `POST /gh_ost/enable/<wf_id>/` —— 预检 + 写 task
    - `POST /gh_ost/start/<wf_id>/` —— alpha 标 running，不真启进程
    - `POST /gh_ost/cancel/<wf_id>/` —— 取消
    - `GET  /gh_ost/status/<wf_id>/` —— 进度查询（前端 polling 用）
    - `GET  /gh_ost/progress/<wf_id>/` —— 进度面板页（Django template）
  - `urls.py` —— URLConf（namespace=ddl_gh_ost）
  - `services/db.py` —— PyMySQL 短连接辅助（兼容 134 dev + 110 prod）
  - `services/precheck.py` —— 预检 5 道函数
    - `check_binlog_format` —— 必须 ROW
    - `check_disk_space` —— 剩余 ≥ 1.2 × 表大小
    - `check_replication_privileges` —— REPLICATION SLAVE + CLIENT
    - `check_alter_sql` —— 是 ALTER TABLE，不改主键/全文/外键
    - `check_table_type` —— 非分区表、ENGINE=InnoDB
  - `templates/ddl_gh_ost/progress.html` —— 进度面板（Vue 风格的纯 Django template + JS polling）

### 配置

- `archery/settings.py` —— 加 4 个 env 变量
  - `CUSTOM_GH_OST_ENABLED`（默认 False，灰度开关）
  - `CUSTOM_GH_OST_BIN`（默认 `/usr/local/bin/gh-ost`）
  - `CUSTOM_GH_OST_CUT_OVER_STRATEGY`（默认 immediate）
  - `CUSTOM_GH_OST_LOG_DIR`（默认 `/var/log/archery/gh_ost`）
  - `if CUSTOM_GH_OST_ENABLED: INSTALLED_APPS += ("sql.extensions.ddl_gh_ost.apps.DdlGhOstConfig",)`
- `archery/urls.py` —— URL 路由（`if getattr(settings, "CUSTOM_GH_OST_ENABLED", False)`）
- `.env.example` —— 加 gh-ost 段示例

## 部署状态

### 134 dev（172.20.2.134）

- 2026-08-05 22:32：v1.1.10 gh-ost 二进制安装完成（`/usr/local/bin/gh-ost`）
- 2026-08-05 23:00+：演练大表 `accesscard_black_detail` 由用户迁到 archery_dev 库
- 2026-08-06 09:19：`makemigrations ddl_gh_ost` 成功生成 `0001_initial.py`
- 2026-08-06 09:19：`migrate ddl_gh_ost` 成功建表 `ext_ddl_ghost_task`
- 2026-08-06 09:25-09:31：尝试重启 gunicorn 验证端到端，**发现 .env 历史状态问题**
  - 134 dev `/opt/archery/prod/.env` 是占位文件（`SECRET_KEY=change-me-in-production` 23 字符 + `MYSQL_HOST=mysql`）
  - gunicorn 进程能 import 模型（`DdlGhostTask` 加载 37 字段）但不能连 MySQL
  - 实际原因：**134 dev .env 历史占位**（不是本次 sync 引入的，本次 sync 脚本排除了 .env）
  - 7/27 起的 gunicorn 进程 environ 里有 67 字符的真实 SK，与 .env 文件不一致
  - 推测：systemd 启动时 .env 是真值，之后某个时点被覆盖成占位
- 2026-08-06 09:32：gunicorn 已 stop，134 dev 恢复 9003 端口 inactive 状态
- **待用户决定**：提供 134 dev .env 真实值后重新部署

### 110 prod（172.20.2.110）

- 未触碰，仍在 v0.2.0 + OA 框架 published-not-enabled 状态

## 不在 alpha 范围

- 真启 gh-ost 子进程（systemd-run --scope=ghost-<id>）—— beta 阶段
- cut-over 切换逻辑（rename 阶段）—— beta 阶段
- 前端 Vue 集成（工单详情页 + admin 加组件）—— beta 阶段
- 钉钉群通知（成功/失败/取消）—— 依赖 v0.2.1+ 模板 + v0.2.2 tunnel
- 暂停阈值自动检测（threads_running 监控）—— beta 阶段
- 影子表保留 7 天（cron 清理）—— beta 阶段

## 后续（v0.3.0-beta）

1. 134 dev 演练大表真跑 gh-ost（accesscard_black_detail）
2. systemd-run --scope 实现 + 进程管理
3. stdout 解析器（Copy: 12345/100000 rows）
4. 前端 Vue 集成（工单详情页 checkbox + admin 进度组件）
5. 钉钉群通知（成功/失败/取消）
6. cut-over 策略（immediate / low_traffic_window / manual）
7. 暂停阈值自动检测
8. 演练通过后 v0.3.0 推 110 prod

## 注意事项

- alpha 阶段 `start` endpoint 只标 task.status=running，不真启 gh-ost 子进程
- 进度面板的 `progress_pct / rows_copied / speed / eta` 全部为占位 0 或 null
- 真跑请等 v0.3.0-beta 部署到 134 dev 后再勾选
- admin 看到的 8+1 ext_ 表（dingtalk_oa 7 + ddl_gh_ost 1 = 8）已确认
