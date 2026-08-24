# 2026-08-24 gh-ost + 字段 diff 操作手册

## 摘要

Archery v0.4.5 gh-ost 无锁 DDL 变更 + 字段 diff 检测的端到端用户操作手册 — 面向业务 RD + DBA, 从提工单、看进度、失败处理, 到 DBA 兜底操作全流程覆盖。

## 背景

gh-ost 和字段 diff 是 Archery 二次开发最复杂、用户最多的功能,经过多个 commit 迭代:
- **v0.3.0-alpha** (5 commit): gh-ost 基础 (runner / parser / poller / precheck)
- **v0.3.0-beta** (5 commit): 状态机三件套 + 审批守卫 + 端到端跑通
- **v0.3.x 字段 diff** (4 commit): 检测 + 11 条规则 + 大表防呆 + 补全 SQL
- **v0.4.5 gh-ost rebuild** (3 commit): 触发空 alter 碎片回收
- **v0.4.5 DDL 智能回滚** (commit `e54a663`): A+B 方案

但**之前只有设计稿,没有用户操作手册**。业务 RD 和 DBA 看设计稿看不到"我该点哪个按钮"。

## 操作手册内容

10 章节, 用户友好导向 (跟设计稿不同):

1. **概览: 5 分钟搞懂** - 谁该用、什么时候用、4 个功能卡片
2. **快速开始 (业务 RD)** - 6 步走完全流程
3. **业务 RD · 提工单时** - 字段 diff 自动检测 + 11 条风险规则速查 + 大表 DDL 防呆
4. **业务 RD · 提单后** - SQL 详情页 gh-ost 状态 + 进度面板 + 失败处理 + 智能回滚
5. **DBA · 任务管理列表** - 角色视角 (DBA 全量 vs RD 自己) + 取消/重试/回滚操作
6. **DBA · 字段 diff 兜底** - 业务 RD 漏勾 gh-ost 时 DBA 兜底启用
7. **DBA · v0.4.5 碎片回收** - 触发空 alter 的 3 决策 (ENGINE+ROW_FORMAT+CHARSET)
8. **权限配置** - 4 个 perm 自动注册 + admin 后台配置
9. **FAQ 10 条** - 字段 diff 没用上 / 字符集变化坑 / gh-ost 切流超时 / 智能回滚拒绝 等
10. **业务场景案例 (4 个真实)** - 8/13 字符集丢失 / DBA 兜底漏勾 / 切流超时回滚 / 碎片回收

## 11 条字段 diff 风险规则

| 规则 | 等级 | 典型场景 |
|---|---|---|
| 基础类型不兼容 | 高 | VARCHAR → TEXT / INT → BIGINT |
| 字符集变化 | 高 | utf8mb4 → utf8 / 不带 CHARSET (**生产事故根因**) |
| 排序规则变化 | 高 | utf8mb4_general_ci → utf8mb4_unicode_ci |
| 类型缩短 | 中 | VARCHAR(100) → VARCHAR(64) |
| 类型变长 | 低 | VARCHAR(64) → VARCHAR(128) |
| 整数类型兼容升级 | 低 | INT → BIGINT / SMALLINT → INT |
| nullable → NOT NULL | 中 | 字段变必填 |
| NOT NULL → nullable | 低 | 字段变可选 |
| default 变化 | 中 | DEFAULT 0 → DEFAULT NULL |
| PRIMARY KEY 变化 | 高 | 主键变更 |
| COMMENT 变化 | 低 | 注释文字变更 |

## 4 个真实业务场景案例

1. **业务 RD 提大表 DDL, 字段 diff 提示字符集丢失** - 8/13 字符集事故根因
2. **业务 RD 漏勾 gh-ost, DBA 兜底** - 紧急情况漏勾的兜底机制
3. **gh-ost 切流超时, 智能回滚兜底** - v0.4.5 DDL 智能回滚实战
4. **DBA 兜底定期碎片回收** - v0.4.5 rebuild 触发空 alter

## 设计稿 vs 操作手册的差异

| 维度 | 设计稿 | 操作手册 |
|---|---|---|
| 受众 | 开发者 (写代码的) | 最终用户 (业务 RD + DBA) |
| 粒度 | 可直接动手写代码 | 可直接动手用产品 |
| 内容 | 数据模型 / URL 路由 / 服务层 | 步骤编号 / 截图 / FAQ / 业务案例 |
| 风格 | 技术导向 (代码块多) | 用户导向 (mockup + 高亮 + 步骤) |
| 路径 | `docs/designs/` | `docs/manuals/` |
| 配套 | Markdown 双交付 | HTML 单交付 (操作手册以视觉为主) |

## 文件清单

- `docs/manuals/2026-08-24_ghost-column-diff-user-manual.html` (60KB, 10 章节)

## 关联

- HTML 操作手册: [2026-08-24_ghost-column-diff-user-manual.html](../manuals/2026-08-24_ghost-column-diff-user-manual.html)
- gh-ost 详设: [2026-08-10_gh-ost-detail-design.html](../designs/2026-08-10_gh-ost-detail-design.html) (80KB, 13 章节)
- 字段 diff mockup: [2026-08-12_gh-ost-column-diff-mockup.html](../designs/2026-08-12_gh-ost-column-diff-mockup.html) (32KB)
- DDL 智能回滚: [2026-08-13_ddl-rollback-parse-design.html](../designs/2026-08-13_ddl-rollback-parse-design.html) (38KB)
- v0.4.5 ghost rebuild: [2026-08-13_v0405-ghost-rebuild-design.html](../designs/2026-08-13_v0405-ghost-rebuild-design.html) (40KB)

## 下一步

业务 RD + DBA 拿到手册后, 跟着操作走 (重点看 §02 快速开始 + §09 FAQ)。后续补充视频教程。
