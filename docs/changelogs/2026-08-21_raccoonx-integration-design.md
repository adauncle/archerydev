# 2026-08-21 RaccoonX 浣巡接入详细设计稿

## 摘要

Archery v0.5.0 接入开源数据库巡检平台 RaccoonX (浣巡, 原名 DBCheck), 让 Archery 平台本身具备数据库巡检能力。业务用户和 DBA 在 Archery 页面里就能一键体检, 不用跳出 Archery。

## 背景

- **业务痛点 (8/19 验证)**: 业务用户拿 SOAR 跑 `WHERE create_time >= '...'` 那条 50 万行全表扫描, SOAR 给 100 分 + OK 但没 add index 建议 — 这就是 RaccoonX 能补的"加啥索引"。
- **RaccoonX 能力**: 21+ 种数据库, 330+ 巡检规则, 270+ 基线配置, 自动生成 Word 报告, 支持 AI 诊断 (Ollama/OpenAI), eBPF 内核级监控。
- **互补关系**: Archery 把关 "SQL 审核 / 变更", RaccoonX 盯 "健康巡检 / 风险预警" — 上下游互补, 不是竞争。

## 设计稿内容

详细设计稿 10 章节, 跟之前 gh-ost / DDL 智能回滚 风格一致 (HTML 70KB + Markdown 36KB):

1. **设计原则** - 跟 5 个二次开发项目一致, 走"扩展 + 复用 + 不重写"路线
2. **业务场景** - 4 个角色 (业务 RD / DBA / 业务 leader / admin)
3. **产品界面** - 6 个核心页面 (侧边栏菜单 / 任务列表 / 巡检详情 / 一键弹窗 / 定时配置 / 趋势看板)
4. **权限模型** - 跟 8/12 gh-ost 任务管理一致, 4 个标准 perm + `_is_inspect_admin()` 判定
5. **数据模型** - 4 张表 (ext_inspect_task / ext_inspect_finding / ext_inspect_datasource_map / ext_inspect_schedule)
6. **URL 路由** - 11 个核心路由 + 2 个 AJAX 端点
7. **RaccoonX 集成** - 部署 / 数据源映射 / API 客户端 / 凭据传递 / 报告解析 / 异步执行
8. **实施阶段** - Phase 0 (半天验证) / Phase 1 (1 周框架) / Phase 2 (1 周增强) / Phase 3 (后续工单闭环)
9. **风险与验证** - 10 条风险点, 每条对应 8/19 教训
10. **跟推 110 prod 的关系** - 5 步必做补 3 条 (步骤 8~10)

## 关键拍板 (8/20 对话确认)

1. **4 个 perm 全部注册** (view/add/change/delete) - 跟 8/12 gh-ost 任务管理一致
2. **业务 RD 默认不能**, DBA 手动勾 (8/13 教训: 默认权限最小化)
3. **复用 Archery `instancepermission` 表** 做实例隔离 (跟其他业务页面一致)
4. **业务 RD 默认不勾**, DBA 手动给 (8/13 教训)
5. **AI 模式默认关** (8/19 数据出境教训, 跟 SOAR 一样纯规则先跑通)
6. **RaccoonX 装 134 dev 跟 Archery 一起**, 推 110 时同步 (跟 gh-ost 一样套路)
7. **第一阶段只支持 MySQL** (跟 Archery 业务匹配, 后面再加 PG/Oracle)
8. **核心定位调整**: Archery 平台本身具备巡检能力 (不是"用 RaccoonX 工具", 而是"Archery 多了巡检功能")

## 实施路径

| 阶段 | 时间 | 内容 | 验证标准 |
|---|---|---|---|
| **Phase 0** | 8/20 下午半天 | 134 dev 装 RaccoonX 源码 + 配 1 个 MySQL 数据源 + 跑通 1 次巡检 | 拿到 Word 报告, 内容非空, 用 8/19 那条 SQL 真给出"加索引"建议 |
| **Phase 1** | 8/21~8/27 (1 周) | Archery 端: 菜单 + 任务列表 + 详情 + 一键巡检 + 4 个 perm + 实例隔离 | 业务 RD 真能用, 看到自己库健康分 + 风险 |
| **Phase 2** | 8/28~9/3 (1 周) | 定时配置 + 趋势看板 + 钉钉通知 | DBA 配 cron 跑通, 日报真发出去 |
| **Phase 3** | 后续 (2 周) | 工单闭环: 巡检"加索引" → 一键建 Archery gh-ost 工单 | 业务 RD 点按钮真建工单走审批 |

**Phase 0 关键验证**: 拿 8/19 那条 50 万行全表扫描 SQL 走一遍。RaccoonX 报告里有没有"加索引"建议, 跟 SOAR 对比 — SOAR 100 分 OK 没建议, RaccoonX 真给出来才算数。**如果 RaccoonX 也给不出来, 整个项目都不做, 改走 v0.4.1 慢 SQL 索引解析路线**。

## 跟 8/19 教训对照

| 8/19 教训 | 本次设计应对 |
|---|---|
| SQLAdvisor 装上但跑不出 add index | Phase 0 用 8/19 那条 SQL 验证 RaccoonX 真能给出"加索引"建议 |
| SOAR 工具装到 /usr/local/bin/ 报 permission denied | RaccoonX 装 `/opt/raccoonx/` 用 `archery` user (跟 Archery 一致) |
| 业务 SQL 出境合规风险 | 默认 `ai_mode=disabled`, 纯规则先跑通 |
| 8/18 教训 1.10.0 → 1.14.0 切换历史 bug | 锁 RaccoonX 版本 v26.8.15.0, 推 110 时同步更新 |
| 8/12 gh-ost 任务管理 perm 细分 (commit c80c1ad) | 复用同一套机制, 4 个标准 perm + `{% if perms %}` 条件渲染 |
| 8/13 教训 默认权限最小化 | 业务 RD 默认不勾 perm, DBA 手动给 |
| 8/12 教训 Archery password 在内存明文 | 跟 gh-ost 业务一样接受, 后续可用 Vault 兜底 |
| 8/18 教训 django-mirage-field 加密 | RaccoonX API Key 存 RaccoonX Fernet 加密, Archery 端用 `SysConfig().set` 加密配 |

## 文件清单

- `docs/designs/2026-08-21_raccoonx-integration-design.html` (70KB, 10 章节)
- `docs/designs/2026-08-21_raccoonx-integration-design.md` (36KB, 配套 Markdown)
- `docs/changelogs/2026-08-21_raccoonx-integration-design.md` (本文件)

## 关联

- HTML 详设: [2026-08-21_raccoonx-integration-design.html](../designs/2026-08-21_raccoonx-integration-design.html)
- Markdown 详设: [2026-08-21_raccoonx-integration-design.md](../designs/2026-08-21_raccoonx-integration-design.md)
- 同源设计稿: gh-ost 详设 (80KB) / DDL 智能回滚 (38KB) / v0.4.0 归档 (64KB) / v0.4.5 rebuild (40KB) / 钉钉 OA (102KB)

## 下一步

等用户审完设计稿, 拍板后开干 Phase 0 (8/20 下午半天验证 RaccoonX 跑通)。
