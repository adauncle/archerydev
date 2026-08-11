# 踩坑速查表

> **核心原则（用户 2026-08-11 固化）**：每个 bug / 踩坑 / 解决方式都要记录。
> 详见 `AGENTS.md` "二次开发硬规则"第 7 条。

## 文档分层

| 层 | 路径 | 写什么 | 什么时候写 |
|----|------|--------|------------|
| 1. Changelog | `docs/changelogs/YYYY-MM-DD_<bug-name>.md` | 修一个 bug 的**完整记录**：症状 / 根因 / 修法 / 验证 / 110 prod 必做 | 修代码前 |
| 2. Agent Memory | `C:\Users\hly\.minimax\agents\mavis\memory\MEMORY.md` | 通用踩坑 / 工具技巧 / 跨项目经验 | 每次踩坑 |
| 3. 项目 AGENTS.md | `AGENTS.md` | 长期规则 / 二次开发硬规范 | 固化原则时 |
| 4. 本速查表 | `docs/troubleshooting.md` | **high-level 索引**——按类别速查 | 每次加新 changelog / memory entry |

**分工**：
- changelog 写"怎么修这个具体 bug"（含代码位置 / commit hash / 验证步骤）
- memory 写"通用经验"（如"PowerShell stderr 误判" 跨项目都用）
- AGENTS.md 写"长期规则"（如"bug 必记" 原则）
- 本速查表做**反向索引**——从"现象"反查"去哪个 changelog / memory 看"

## 按现象速查

### Gh-ost 相关

| 现象 | 看哪里 |
|------|--------|
| gh-ost 启动报 `bind: address already in use` | changelog `2026-08-10_gh-ost-v030-beta-state-sync.md` §"后续修复 zombie socket 自动清理" / memory "gh-ost zombie socket 双层防御" |
| gh-ost 跑完后工单状态没同步（仍待审核） | changelog `2026-08-10_gh-ost-v030-beta-state-sync.md`（修复 2：poller 同步 wf.status）|
| 提交勾 gh-ost 后审批前能点"启用"按钮 | changelog `2026-08-11_gh-ost-approval-gating.md` |
| 详情页 500 / `UnboundLocalError: has_active_ghost_task` | memory "Django 函数内变量前向引用 UnboundLocalError" |
| cut-over 完成后"立即执行"按钮仍可见 | changelog `2026-08-10_gh-ost-v030-beta-state-sync.md` 修复 1 |
| 取消 gh-ost 后 wf.status 仍 workflow_manreviewing | changelog `2026-08-10_gh-ost-v030-beta-state-sync.md` 修复 3（cancel 不动 wf.status）|
| 演练演练工单 200 但页面裸 HTML | changelog `2026-08-10_dev-sync-static-fix.md` / memory "134 dev tarball sync 必须包含 common/static/" |
| DdlGhostTask 缺 instance 字段 | changelog `2026-08-10_gh-ost-v045-alpha-drill.md` bug #1 |

### 审批 / 钉钉 OA 相关

| 现象 | 看哪里 |
|------|--------|
| 工单走单级 DBA 审批（配置 3 级没生效）| changelog `2026-08-11_approval-flow-3level-fix.md` / memory "Archery 审批流 3 级配置生效修复" |
| workflow_audit_setting 改了没生效 | memory "Archery 审批流 优先级陷阱"（被 ext_approval_flow 覆盖）|
| 钉钉 OA 框架启用但 `ConfigurableAuditor` 报 fallback | memory "Archery 审批流 优先级陷阱"（policy 不命中 / 异常路径）|
| 110 prod 推 v0.2.0/v0.3.0 前必做 | changelog 结尾"## 110 PROD 推 v0.2.0/v0.3.0 前必做" 段 |

### Archery 老工单兼容

| 现象 | 看哪里 |
|------|--------|
| 老工单详情页 500 / `RelatedObjectDoesNotExist: sqlworkflowcontent` | changelog `2026-08-10_workflow-content-compat.md` / memory "Archery 工单 SqlWorkflowContent 缺失兼容" |
| `wf.sqlworkflowcontent.review_content` JSON 解析错 | 同上 |
| 详情页右上 `bootstrap-table` 报错 `for...of undefined` | changelog `2026-08-10_detail-html-bootstrap-table-autoinit.md`（去掉 data-toggle="table"）|
| 详情页"审批节点"无审批人信息（老工单没 audit）| changelog `2026-08-10_detail-view-audit-missing.md` |

### Archery 凭据 / 加密

| 现象 | 看哪里 |
|------|--------|
| `get_username_password()` 拿密文当明文 → 2061 caching_sha2_password 错 | memory "Archery instance user/password mirage 密文兼容" |
| goinception 报 `ValueError: invalid literal for int()` (port 字段) | memory "Archery sql_config 表 EncryptedCharField mirage 密文" |
| admin 后台改了 instance 凭据没生效 | memory "mirage 密文兼容" 段（K1≠K2 问题）|

### 134 dev 部署层

| 现象 | 看哪里 |
|------|--------|
| 启动后 systemctl is-active 报 active 但页面 404 | memory "134 dev gunicorn 启动检查 SOP"（必须 curl 9003）|
| 静态资源 302 / text/html 而非 200 | memory "134 dev tarball sync 必须包含 common/static/" |
| gh-ost log 报 `Permission denied` | changelog `2026-08-10_gh-ost-log-dir-permission.md`（chown archery:archery）|
| 134 dev gunicorn 反复重启 | memory "134 dev gunicorn 启动检查 SOP"（看 journalctl）|

### Django 视图层

| 现象 | 看哪里 |
|------|--------|
| 详情页 500 / `UnboundLocalError` 跟变量前向引用有关 | memory "Django 函数内变量前向引用 UnboundLocalError" |
| 视图报 `FieldError: Cannot resolve keyword 'is_terminal'` | memory "Archery 演练环境踩坑"（is_terminal 是 @property）|
| 视图报 `DisallowedHost: 'testserver'` | drill 脚本加 `settings.ALLOWED_HOSTS += ["testserver"]` |

### 演练脚本 / 工具

| 现象 | 看哪里 |
|------|--------|
| 走 `/api/v1/workflow/` 报 "你所在组未关联该实例" | memory "Archery 演练环境踩坑"（走 instance id=2 / group 8 / archery M2M）|
| 走 `/cancel/` 报 404 | memory "Archery 演练环境踩坑"（POST 字段是 `cancel_remark` 不是 `audit_remark`）|
| `submit` API 报 `'workflow' 是必填项` | memory "Archery 演练环境踩坑"（嵌套结构 `workflow: {...}`）|
| `submit` API 报 `KeyError 'is_offline_export'` | 补 `is_offline_export=0` |
| `is_auto_review` 返 False 但 generate 出错 | memory "Archery 审批流优先级陷阱" |

### Windows / PowerShell 工具链

| 现象 | 看哪里 |
|------|--------|
| `ssh ... "cmd1; cmd2"` 即使成功 PowerShell 报 code 1 | memory "PowerShell ssh 链式 stderr 误判" |
| `pkill -9 -f xxx` 没找到匹配返回 1 链式断 | memory "PowerShell ssh 链式 stderr 误判"（用 `|| true` 兜底）|
| PowerShell `cat` / `grep` / `bash` not on PATH | 改用 Python subprocess / ripgrep |
| Windows tar 同步漏 `ddl_gh_ost/` 前缀 | memory "gh-ost 部署工程经验"（用 `arcname = f"ddl_gh_ost/{rel}"`）|
| Excel `.xlsx` 被 Excel 进程占用 | `record_feature.py` 自动 fallback 到时间戳副本 |
| `Remove-Item` 本地 `.xlsx` 被 PowerShell 拦 | 副本 + `Copy-Item` 覆盖 |
| `echo > file` 写 UTF-16 LE 含 NUL byte | 用 Python `write` 工具写 UTF-8 无 BOM |

## 按时间索引（changelog）

| 日期 | 标题 | 状态 |
|------|------|------|
| 2026-07-22 | `2026-07-22_v0.1.4-submitsql-audit-setting.md` | 已合 |
| 2026-08-05 | `2026-08-05_gh-ost-product-design.html` | 已合 |
| 2026-08-06 | `2026-08-06_gh-ost-v030-alpha-skeleton.md` | 已合 |
| 2026-08-06 | `2026-08-06_gh-ost-v045-alpha-skeleton.md` | 已合 |
| 2026-08-10 | `2026-08-10_dev-sync-static-fix.md` | 已合 `be4d6fb` |
| 2026-08-10 | `2026-08-10_detail-html-bootstrap-table-autoinit.md` | 已合 `d44632f` |
| 2026-08-10 | `2026-08-10_detail-view-audit-missing.md` | 已合 `b8c0e6d` |
| 2026-08-10 | `2026-08-10_workflow-content-compat.md` | 已合 `e78f758` |
| 2026-08-10 | `2026-08-10_gh-ost-log-dir-permission.md` | 已合 `042dee3` |
| 2026-08-10 | `2026-08-10_gh-ost-v030-beta-state-sync.md` | 已合 `04ae0aa` + `8ddc59a` |
| 2026-08-10 | `2026-08-10_gh-ost-v045-alpha-drill.md` | 已合 `8e40d26` |
| 2026-08-10 | `2026-08-10_sqlcheck-mirage-config-fix.md` | 已合 `b429f28` |
| 2026-08-10 | `2026-08-10_gh-ost-v030-beta-e2e-drill.md` | 已合 `cd2ce88` |
| 2026-08-11 | `2026-08-11_gh-ost-approval-gating.md` | 已合 `664058c` |
| 2026-08-11 | `2026-08-11_approval-flow-3level-fix.md` | 已合 `d5f88d1` |

## 维护规则

- 每次加新 changelog **必须更新本表** "按时间索引"
- 每次新增 memory entry 决定**是否要加到"按现象速查"**
- AGENTS.md 改"二次开发硬规则"要同步更新本表原则段
- 4 个文件有冲突时以**最新 commit** 为准

## 详细参考

- AGENTS.md（项目硬规范）
- docs/changelogs/（每次修 bug 的完整记录）
- C:\Users\hly\.minimax\agents\mavis\memory\MEMORY.md（agent 跨项目踩坑经验）
