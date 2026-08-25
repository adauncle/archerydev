# v0.4.5 rebuild — 8.0.22 INSTANT 架构性限制 + accesscard_black_detail 验收 (8/25 17:30)

> **类型**: docs (架构性限制说明 + 拍板记录)
> **状态**: 8/25 17:30 拍板方案 A (用户 11 字回复: "生产环境没有 mysql 5.7 的版本, 110 虽然是 mysql 5.7 但仅供 archery 使用. 所以方案 A 即可")
> **关联**: `2026-08-25_v0405-fragmentation-algorithm-fix.md` (FILE_SIZE 算法修法)
> **关联**: `2026-08-25_v0405-rebuild-select-page.md` (选表页面)
> **目的**: 8.0.22 (134 dev) + gh-ost rebuild 看不到 ibd 收缩, 不是 bug, 是 MySQL 8.0 INSTANT 优化导致。
>         110 prod (5.7.44) 不受影响, 8/27 推 110 业务可用。

## 背景

8/25 14:00 用户拍板上 v0.4.5 选表页面 (业务前端 3 步入口), 8/25 16:00 拍板 perm 守卫统一。
8/25 16:50 用户反馈 "accesscard_black_detail 执行碎片回收后, 刷新页面碎片率没有变化",
8/25 17:00 排查发现 8.0.22 INSTANT 坑 + DATA_FREE 虚高双重问题。

## 现象 (134 dev 实测)

### 1. 多次 rebuild 看不到 ibd 收缩

| task # | 时刻 | 状态 | gh-ost log 关键节点 |
|--------|------|------|---------------------|
| #70 | 8/25 11:38:23 | success | Copy: 200000/200000 → cut-over OK |
| #71 | 8/25 12:42:11 | success | Copy: 200000/200000 → cut-over OK |
| #72 | 8/25 12:58:47 | success | Copy: 200000/200000 → cut-over OK |
| #87-89 | 8/25 14:xx | success | 同上 |
| #94-96 | 8/25 15:xx | success | 同上 |
| #100 | 8/25 17:26:45 | success | 同上 |

**8+ 次 rebuild 全 success, 但 accesscard_black_detail ibd 144MB → 144MB 不变**。

### 2. DATA_FREE 严重虚高

| 表 | DATA_MB | IDX_MB | DATA_FREE (虚) | **ibd 实际 (FILE_SIZE)** | **真 free** | **真 PCT** |
|----|---------|--------|----------------|--------------------------|-------------|------------|
| accesscard_black_detail | 134.28 | 0 | 9MB (虚) | **144MB** | 9.72MB | **6.7%** |
| workflow_log | 0.05 | 0.02 | 9MB (虚) | **128KB** | 60KB | **50%** |
| archive_log | 2.52 | 0.02 | 4MB (虚) | **10MB** | 7.47MB | **74.7%** |

128KB ibd 报 9MB DATA_FREE (虚高 70 倍)。

## 根因 (8/25 16:50 调研)

### MySQL 8.0 INSTANT 优化 4 种 alter 全 no-op

| alter 子句 | MySQL 8.0.22 行为 | gh-ost 看到 | 实际效果 |
|------------|-------------------|-------------|----------|
| `ENGINE=InnoDB` (改自己) | 8.0.12+ INSTANT 跳过 | success | **无 ibd 收缩** |
| `ROW_FORMAT=DYNAMIC` (改自己) | 8.0.16+ INPLACE 跳过 | success | **无 ibd 收缩** |
| `DEFAULT CHARACTER SET=utf8mb4` (改自己) | 8.0.22 INPLACE/INSTANT 跳过 | success | **无 ibd 收缩** |
| `ENGINE=InnoDB, ALGORITHM=COPY` | 8.0.22 走 COPY 触发物理重写 | success | **ibd 收缩** ✓ (但 gh-ost cut-over 仍走 INSTANT) |
| 显式 `ALTER TABLE ... ALGORITHM=COPY` | 走 COPY 物理重写 | N/A | **ibd 收缩** ✓ (锁表, 大表不可接受) |
| `OPTIMIZE TABLE` (默认) | 8.0.22 ALGORITHM=DEFAULT (INSTANT no-op) | N/A | **无 ibd 收缩** |

### gh-ost 1.1.x 切表机制 (8/25 调研)

gh-ost 走 **binlog 异步重写 + cut-over 切表** 架构:
1. 创建影子表 `<orig>_ghost`
2. 订阅原表 binlog, 把变更 apply 到影子表
3. 后台 worker 把原表数据按 chunk 拷到影子表
4. **cut-over 阶段**: LOCK 原表, RENAME 影子表 → 原表名
5. **关键问题**: cut-over 阶段也会触发 MySQL 原生 DDL (改 metadata), 8.0 走 INSTANT 跳过

8.0.22 实测: gh-ost status=success, 但 cut-over 因为 alter 子句全 no-op, **没有真物理重写**。
5.7.44 不会: 5.7 改 ENGINE 改自己走 **COPY 触发整表物理重写**, gh-ost 完整工作。

## 用户拍板 (8/25 17:30 方案 A)

> 用户原话 (11 字): "生产环境没有 mysql 5.7 的版本, 110 虽然是 mysql 5.7 但仅供 archery 使用. 所以方案 A 即可"

**方案 A 含义**:
1. **接受架构性限制**, 不在 gh-ost 层面修 INSTANT 跳过
2. **134 dev 演练验收改标准**:
   - ✅ task `status=success`
   - ✅ gh-ost log 显示 "migrating `<table>`", "Copy: N/M", "All-OK" → "Cut-over" → "completed"
   - ❌ ~~不依赖 ibd 收缩验证 (8.0 预期 no-op)~~
3. **110 prod 5.7.44 gh-ost rebuild 真 work**:
   - 5.7 改 ENGINE 改自己走 **COPY** 触发整表物理重写
   - 推 110 后, DBA 跑 rebuild 看到 ibd **真收缩** (5.7 行为)
4. **9 月 5.7→8.0 升级后需要架构性修法** (不在 8/27 推 110 范围):
   - 方案 a: gh-ost cut-over 强制 `ALGORITHM=COPY` (改 gh-ost, 跨工具, 需立项)
   - 方案 b: 不用 gh-ost, 直接 `ALTER TABLE ... ENGINE=InnoDB, ALGORITHM=COPY` (锁表, 大表不可接受)
   - 方案 c: 5.7 继续用, 8.0 走 gh-ost + DBA 手动验证 (现状)
   - 推 110 后, 跟 DBA 单独约 9 月升级时间表

## 推 110 / 演练 影响

| 阶段 | MySQL 版本 | gh-ost rebuild 行为 | 验收标准 |
|------|-----------|---------------------|----------|
| 8/27 推 110 后 | 110 prod 5.7.44 | **真物理重写**, ibd 收缩 | task success + ibd 缩小 |
| 8/26 134 dev 演练 | 134 dev 8.0.22 | **INSTANT no-op**, ibd 不收缩 | task success + log cut-over |
| 9 月 5.7→8.0 升级 (计划) | 110 prod 8.0.22 | **INSTANT no-op** (待解决) | 待立项, 走 ALGORITHM=COPY |

## 为什么不动 gh-ost 代码

- gh-ost 1.1.x 走 binlog 异步重写 + cut-over 切表, 不依赖 MySQL 原生 DDL
- 但 cut-over 阶段会改原表 metadata, 8.0 走 INSTANT 跳过导致 gh-ost 看不到要重写的子句而空转
- 改 gh-ost 让 cut-over 强制 `ALGORITHM=COPY` 涉及 gh-ost 内部 binlog + 影子表切换逻辑, **跨工具范围**
- 110 prod 5.7 不受影响, **8/27 推 110 业务可用**

## 8.0.22 DATA_FREE 虚高问题 (8/25 16:55 顺手修, 已 commit `14e3007`)

8.0.22 INFORMATION_SCHEMA.TABLES.DATA_FREE 字段返回 **tablespace 预分配**, 严重虚高。
**真碎片率必须用 `INNODB_TABLESPACES.FILE_SIZE` 算** (ibd 实际文件大小)。

| 老算法 (DATA_FREE 虚高) | 新算法 (FILE_SIZE 真实) |
|------------------------|------------------------|
| 128KB ibd 报 9MB DATA_FREE (虚高 70 倍) | FILE_SIZE = 128KB (真实) |
| `pct = DATA_FREE / (DATA_FREE + DATA + INDEX)` | `pct = (FILE_SIZE - DATA - INDEX) / FILE_SIZE` |
| workflow_log 99.3% (误报) | workflow_log 50.0% (真) |
| archive_log 4.5% (漏报 16 倍) | archive_log 74.7% (真) |

**修法**: `rebuild_list` 端点 SQL 改 `LEFT JOIN INNODB_TABLESPACES` 拿 `FILE_SIZE`。
**5.7 / 8.0 都用 FILE_SIZE 算法**, 不依赖 MySQL 版本。

## 推 110 后 DBA 必看 (110 prod 5.7 真 work 验证)

推 110 后, 在 110 prod 跑一个真 rebuild (任一碎片表), 验证 ibd 真收缩:

```bash
# 1. 选 accesscard_black_detail 或 archive_log (8/25 演练验证真碎片率高)
# 2. /gh_ost/rebuild/select/ 勾表, 触发 rebuild
# 3. 看 task progress: 5.7 cut-over 阶段会真重写表, gh-ost log 报 "Copying rows" 真拷贝
# 4. 完事后查 INFORMATION_SCHEMA.INNODB_TABLESPACES.FILE_SIZE 对比
#    期望: FILE_SIZE 显著下降 (5.7 真物理重写)
#    异常: FILE_SIZE 不变 → 110 prod 5.7 features.py patch 漏了, 看 5 步必做步骤 9
```

## 8/25 17:00 拍板记录 (回顾)

- **8/25 16:40**: 用户反馈 "accesscard_black_detail 执行碎片回收后, 刷新页面碎片率没有变化"
- **8/25 16:50**: 调研发现 4 种 alter 全 no-op + DATA_FREE 虚高
- **8/25 16:55**: 用户拍板方案 A: 撤回方案 C 改字符集, 改碎片率算法 (commit `14e3007`)
- **8/25 17:00**: 新算法演练 16/16 PASS (新 FILE_SIZE 算法)
- **8/25 17:30**: 用户 11 字拍板方案 A 接受 8.0 INSTANT 架构性限制
- **8/27 21:00**: 推 110 prod (5.7.44), gh-ost rebuild 真 work, DBA 验证 ibd 收缩

## 教训 (跨项目可复用)

1. **MySQL 8.0 INSTANT 优化坑** (跨项目):
   - 8.0.12+ 改 ENGINE 改自己走 INSTANT 跳过
   - 8.0.16+ 改 ROW_FORMAT 改自己走 INPLACE 跳过
   - 8.0.22 改 CHARSET 改自己走 INPLACE/INSTANT 跳过
   - 8.0.22 OPTIMIZE TABLE 默认 ALGORITHM=DEFAULT (INSTANT no-op)
   - 真物理重写需显式 `ALGORITHM=COPY` (但 gh-ost cut-over 仍走 INSTANT)
2. **MySQL 8.0 INFORMATION_SCHEMA.TABLES.DATA_FREE 严重虚高** (跨项目):
   - 返回 tablespace 预分配, 不是真可清理碎片
   - 128KB ibd 报 9MB (虚高 70 倍)
   - **真碎片率必须用 `INNODB_TABLESPACES.FILE_SIZE` 算**
3. **5.7 vs 8.0 演练差异** (跨项目):
   - 5.7 改 ENGINE 改自己走 COPY 触发整表物理重写
   - 8.0 改 ENGINE 改自己走 INSTANT 跳过
   - **二次开发涉及 ALTER 重写, 必查目标 MySQL 版本**
4. **gh-ost 1.1.x 切表机制** (跨项目):
   - binlog 异步重写 + cut-over 切表
   - cut-over 阶段也会触发 MySQL 原生 DDL (改 metadata)
   - 8.0 走 INSTANT 跳过 → gh-ost status=success 但 ibd 不收缩
5. **架构性限制的处理原则** (跨项目):
   - 如果是 1-2 行代码能修的, 立刻修
   - 如果涉及跨工具 / 跨版本, 评估 业务影响 / 时间成本 / 替代方案
   - 业务 RD 实际使用 110 prod (5.7) 不受影响 → 接受架构性限制, 9 月再立项

## 关联

- 推 110 主手册 §1.4: `docs/runbooks/2026-08-27_push-v030-execution-manual.md`
- FILE_SIZE 算法修法: `docs/changelogs/2026-08-25_v0405-fragmentation-algorithm-fix.md`
- 选表页面: `docs/changelogs/2026-08-25_v0405-rebuild-select-page.md`
- perm 守卫统一: `docs/changelogs/2026-08-25_v0405-rebuild-perm-guard.md`
- 演练脚本: `scripts/_archive/_drill_frag_algorithm.py` (新算法 16/16 PASS)
- DBA 工具: `scripts/_archive/_analyze_real_fragmentation.py` (INNODB_TABLESPACES 算)
- 5 步必做: `scripts/deploy/5step_prerequisites_110prod.sh` 步骤 9 (5.7 features.py patch) + 步骤 13 (验证 8.0/5.7 兼容性)
- 8/13 拍板 3 决策: `docs/changelogs/2026-08-13_v0405-rebuilt-fields.md`
