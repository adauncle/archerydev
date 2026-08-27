# 8/27 gh-ost 智能回滚 用途说明 (语义澄清)

## 背景
- 业务 RD mkq 8/27 16:58 反馈: task #6 跑成功 100% 后点"gh-ost 智能回滚"按钮报错
- DBA 阿达叔叔 8/27 17:19 问: "给我明确下这个回滚功能，具体是做什么用"
- 反思: 之前 rollback 端点 docstring 写得不够清楚, DBA 上手前可能误以为能"撤销 DDL", 实际做不到

## 核心结论 (一句话)

> **gh-ost 智能回滚 ≠ 撤销 DDL**, 它是"清残留 + 标作废"工具. 表结构变更和数据迁移在 cut-over 那一刻已经发生, 永远回不去.

## 这个端点**能**做什么

按 views.py:472-489 rollback 端点代码:
1. **DROP 残留表** (用 `DROP TABLE IF EXISTS` 防 IF NOT EXISTS 失败):
   - `_test_gho` (gh-ost 用的影子表, cut-over 后**没**被 gh-ost 自己清掉)
   - `_test_del` (业务表 rename 后的旧表, cut-over 后**没**被 gh-ost 自己清掉)
2. **task.status** 切到 `rolled_back` (DBA 主动放弃这次 DDL 的标记)
3. **workflow.status** 联动切到 `workflow_exception` (跟 failed 一样语义, 因为表已改无法回退)
4. **task.finished_at** 写当前时间
5. **task.error_message** 拼 `dropped=... errors=...` (DBA / RD 在前端能看到)

## 这个端点**不能**做什么

- ❌ **撤销 ALTER 把表结构改回原状** — gh-ost cut-over 是原子的 (`--cut-over=atomic`), 表 rename 已经发生, 永远无法回退
- ❌ **恢复原数据** — 数据迁移已经完成, 新表的内容是迁移后的版本
- ❌ **回退业务** — 业务方调用的是新表 (rename 后的主表), 不是旧表

## 适用场景 (按使用频率排序)

### 场景 1: 清理残留 (最常见) ✓
gh-ost 跑成功后, `_gho` 和 `_del` 一直堆在库里占空间. DBA 点 rollback 清理.

**8/27 实战案例**: task #6 跑完后, ghost-6.log 显示 cut-over 后只 drop 了 `_test_ghc` / `_test_ghk` 两个辅助表, **没** drop `_test_gho` 和 `_test_del`. DBA / RD 点 rollback 清理, `dropped=['_test_gho', '_test_del']` errors=[] ✓

### 场景 2: 标记"作废" (中等)
DBA 跑完 gh-ost 后发现 SQL 写错了 (比如少加字段、改错 collation), 但表结构已经改了, 无法回退. DBA 点 rollback:
- 清掉残留 `_gho` / `_del`
- 标 status=rolled_back, 业务上"这次 DDL 算不算数"由 DBA 决定
- 下次修 DDL 走新的 gh-ost 工单

### 场景 3: 清理失败 / 取消任务残留 (少见)
task 状态 `failed` / `cancelled` 时, 也可能有残留 `_gho` (gh-ost 启动后失败没清). DBA 点 rollback 清理.

## 真要"撤销 DDL"怎么办 (回退路径)

**靠前置备份, 不靠这个端点**:
1. 推 prod 前用 `mysqldump` 备份目标表 (110 prod 有专门的 backup 机制)
2. ALTER 出错时, 用 backup 恢复表结构和数据
3. rollback 端点只清残留, 不回数据

8/24 ghost-6.log 显示 110 prod ghost-6 跑前没有 mysqldump 备份 (`--no-backup` 模式? 或者走的是 Archery 自身的 backup 机制, 没在 gh-ost 跑前显式 dump). 110 prod 业务方接受"ALTER 已生效, 不能回退"这个前提, 所以 rollback 端点够用.

如果业务方要求"ALTER 失败能回退到 ALTER 前状态", 必须在 gh-ost 命令行加 `--exact-rowcount` + 推 prod 前显式 mysqldump, 这部分没在 v0.4.5 设计里.

## 关键认知 (DBA 必读)

| 操作 | 回滚端点能不能做 |
|------|----------------|
| 改完发现 SQL 错了, 撤销 ALTER | ❌ 不能, 走 backup |
| 改完想清残留 `_gho` / `_del` | ✓ 走 rollback 端点 |
| 改完但 DBA 想标"作废" | ✓ 走 rollback 端点 (但表结构没真撤销) |
| 改完想恢复原数据 | ❌ 不能, 走 backup |
| failed / cancelled 任务残留清理 | ✓ 走 rollback 端点 |

## 代码改动

### views.py:432-441 (rollback 端点 docstring)
- 加 14 行 `## CUSTOM-MODIFIED: 文档警告` 块
- 明确写: "此端点**不是**撤销 DDL"
- 列出能做 / 不能做的清单
- 提示: 真要"撤销 DDL"靠 backup, 不靠这个端点

## 验证
- 8/27 17:00 rollback 端点 import 路径 fix 后, task #6 演练 PASS
- 业务 RD mkq 在浏览器重试 task #6 rollback, `dropped=['_test_gho', '_test_del'] errors=[]` ✓
- 端点功能正常, 跟设计预期一致 (清残留)

## 教训 (跨项目可复用)
1. **产品端点 docstring 必含"能 / 不能"清单** — 不写清楚"不能撤销 ALTER", DBA 误用浪费时间. 类似 commit / rollback / drop / truncate 端点都要有"误用警告"
2. **用户问"具体做什么用" = docstring 写得不到位** — 反思: rollback 端点 8/13 拍板时只写了"drop 影子表 + 标 rolled_back", 没说清实际能力边界, 导致 DBA 上手前不知道"真撤销 DDL"做不到
3. **DDL 类操作要明确"原子性"边界** — gh-ost cut-over atomic / pt-online-schema-change swap atomic / 直接 ALTER 表锁, 三种原子边界不同, 撤销路径完全不同
4. **"回滚"这个名词歧义大** — 业务方/DBA 听到"回滚"默认是"撤销 DDL 改回原状", 但 gh-ost 的 rollback 不是这个意思. 后续可能改名叫 "cleanup_gh_ost_residuals" 或 "mark_abandoned" 更准确

## 同源 entry
- 8/27 17:00 rollback 端点 import 路径 fix (rollback 端点本身)
- 8/27 16:58 业务 RD mkq 反馈 task #6 rollback 报错 (触发本次语义澄清)
- 8/27 14:50 task #6 cut-over 成功, ghost-6.log 显示残留 `_test_gho` + `_test_del` (rollback 端点能清掉)
- 8/13 v0.4.5-alpha 拍板 3 决策 (rollback 端点 8/13 拍板写, docstring 当时写得不够细)

## 关联 commit
- 8/27 17:25 待 commit (本次)
- 8/27 17:00 commit `50122ff` rollback 端点 import 路径 fix
