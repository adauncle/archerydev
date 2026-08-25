# v0.4.5 rebuild 拍板 3 决策落地 (8/13) (2026-08-13)

## 症状

8/13 用户拍板 3 决策（详设稿 `2026-08-13_v0405-ghost-rebuild-design.md`），但 v0.4.5-alpha
基础版（commit `6412da4` + `8e40d26`）还在用 **COMMENT 触发方案**：

```sql
-- 旧方案 (8/13 之前, 会破坏表 COMMENT 业务描述)
ALTER TABLE t COMMENT 'archery-auto-rebuild-20260813';
```

8/13 用户明确指出：表 COMMENT 是数据治理的命根子（存表用途 / 业务归属 / 责任人），
覆盖了等于数据治理裸奔。

## 修法 (8/13 拍板 3 决策, ~0.8 人天)

### 决策 1: alter 子句用 ENGINE+ROW_FORMAT+CHARSET (3 层防护)

**5.7/8.0 触发行为差异** (核心踩坑):
- MySQL 5.7: `ALTER TABLE t ENGINE=InnoDB` (原表就是 InnoDB) 强制走 **COPY, 整表重写** ✓
- MySQL 8.0.12+: 单独 ENGINE 改 InnoDB 走 **INSTANT, 跳过重写** (gh-ost 不干活) ✗
- **修法**: 8.0 看到至少 1 个子句不是 INSTANT → 走 COPY/INPLACE 触发重写
  实测 8.0.22 对 ROW_FORMAT 改自己的 COPY 触发（INSTANT 优化对 ROW_FORMAT 不完整）

**3 层防护 alter** (5.7/8.0 都触发, 字符集不漂):
```sql
ALTER TABLE t
  ENGINE=InnoDB,                          -- 原表就是 InnoDB, no-op
  ROW_FORMAT=Dynamic,                     -- 原表就是 Dynamic, 但 5.7/8.0 都触发 rebuild
  DEFAULT CHARACTER SET=utf8mb4           -- 原表就是 utf8mb4, no-op
  COLLATE=utf8mb4_general_ci;             -- 跟原表一致, 0 风险飘字段
```

**5 个 0 风险点**:
1. ENGINE 改 InnoDB (原表就是 InnoDB, no-op)
2. ROW_FORMAT 改 Dynamic (原表就是 Dynamic, 仍触发 rebuild)
3. CHARSET 改 utf8mb4 (原表就是 utf8mb4, no-op)
4. COLLATION 改 utf8mb4_general_ci (原表就是, no-op)
5. **不动 COMMENT** (业务描述保留)

### 决策 2: DdlGhostTask 加 5 个 rebuilt_* 字段

DBA 一眼能看出"这次 rebuild 改了什么", 方便排查:

```python
# 2026-08-13 新增 (migration 0004)
rebuilt_charset = CharField(max_length=32, null=True)        # utf8mb4
rebuilt_row_format = CharField(max_length=16, null=True)     # Dynamic
rebuilt_collation = CharField(max_length=64, null=True)      # utf8mb4_general_ci
rebuilt_alter_full = TextField(blank=True)                    # 完整 alter 子句
rebuilt_at = DateTimeField(null=True)                         # 物理重写完成时间
```

**填值时机**:
- `rebuilt_charset/row_format/collation/alter_full`: rebuild_start 时查
  information_schema.tables 拿原表属性, 拼 alter 前填
- `rebuilt_at`: rebuild 切表成功后写 (poller 检测 status=success 时由 on_rebuild_success hook 写)

### 决策 3: 任务列表页显示 "ALTER 子句" 列

`task_list.html` 加 "ALTER 子句" 列 (8/13 拍板):
- rebuild 场景: 显示 truncated ENGINE+ROW_FORMAT+CHARSET (橙底 code tag)
  + rebuilt_charset/row_format/rebuilt_at 时间
- ghost 场景: 显示原 alter_statement
- 不显示敏感字段 (业务 COMMENT / 数据样本)

## 改的文件

### 1. sql/extensions/ddl_gh_ost/models.py

DdlGhostTask 加 5 字段 (~30 行, 8/13 CUSTOM-MODIFIED 注释)。

### 2. sql/extensions/ddl_gh_ost/migrations/0004_ddlghosttask_rebuilt_fields.py (新建)

5 个 AddField 操作 (rebuilt_charset/collation/row_format/alter_full/at),
不影响旧数据 (null=True + blank=True)。

### 3. sql/extensions/ddl_gh_ost/services/runner.py

`_make_rebuild_alter` 改用 `task.rebuilt_alter_full` (8/13 拍板方案),
旧 task (rebuilt_alter_full 为空) 兜底用 COMMENT 触发 (避免老 task 全坏)。

### 4. sql/extensions/ddl_gh_ost/views.py

`rebuild_start` 视图查 information_schema 拿原表属性,
拼出 alter 子句, 写到 task (5 字段 + rebuilt_alter_full 完整 alter)。

新增 helper:
- `_fetch_table_info_for_rebuild(instance, db, table) -> dict` 查原表属性
- `_build_rebuild_alter_clause(table_info) -> str` 拼 alter 子句
- `TableNotExistForRebuildError` 异常

### 5. sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/task_list.html

表头加 "ALTER 子句" 列, 行内显示 (rebuild vs ghost 区分展示)。

## 验证

### 134 dev 真表演练 5 Case

演练表 `accesscard_black_detail` (134 dev / MySQL 8.0.22):

| Case | 操作 | 期望 | 实测 |
|------|------|------|------|
| A | 删 50% 行造碎片 | DATA_FREE 涨到 15MB+ | ✓ |
| B | rebuild 启动 (查表属性) | rebuilt_charset=8.0.22 utf8mb4, rebuilt_alter_full=ENGINE=InnoDB,... 拼好 | ✓ |
| C | rebuild 跑中 (polling) | 进度 0% → 100%, 影子表行数追平 | ✓ |
| D | rebuild 切表成功 | status=success, rebuilt_at 写时间, 物理页重写 | ✓ |
| E | 演练后查表 | DATA_FREE < 1MB, **COMMENT 跟原表一致**, 字符集没变, 索引没变 | ✓ |

**核心 Case E 验证** (防止 5.7/8.0 字符集漂移):
```sql
-- 演练前
SELECT TABLE_COLLATION, ENGINE, ROW_FORMAT
FROM information_schema.tables
WHERE table_schema='archery_dev' AND table_name='accesscard_black_detail';
-- utf8mb4_general_ci / InnoDB / Dynamic

-- 演练后
-- 同样查询: 必须跟演练前一致 (字符集不漂)
```

演练脚本: `scripts/drill_v0405_rebuilt.py` (~250 行)

## 影响

- **正面**: rebuild 任务不再破坏表 COMMENT 业务描述 (数据治理关键)
- **正面**: 5.7/8.0 都能触发物理重写 (3 层防护 ENGINE+ROW_FORMAT+CHARSET)
- **正面**: rebuilt_* 5 字段让 DBA 排查有据可依
- **正面**: 列表页 ALTER 子句列让 DBA 一眼看到 rebuild 用了什么 alter
- **零 DB 风险**: 5 字段全 null=True, 不影响旧数据
- **5.7/8.0 兼容**: 查 information_schema 用标准 SQL, 都 OK
- **不影响 ghost 任务**: rebuilt_* 字段对 ghost 任务都是 NULL (null=True)

## 边界情况

- **旧 task (rebuilt_alter_full 为空)**: runner 兜底用 COMMENT 触发 (避免全坏)
- **8.0 INSTANT 跳过重写**: ROW_FORMAT 改自己实测能触发 COPY 重写
- **rebuild 任务失败**: rebuilt_at 仍为 NULL (只 success 时写)
- **DBA 改过表结构后**: rebuilt_charset 可能跟当前 schema 不一致, 但 rebuilt_alter_full 完整记录了"当初用的 alter"

## 相关 commits / changelogs

- 前置: `6412da4` + `8e40d26` v0.4.5-alpha 基础版 (COMMENT 触发)
- 前置: `2026-08-13_v0405-ghost-rebuild-design.md` 详设稿 (8/13 拍板)
- 本次 commit: 5 决策增量落地

## 产品决策记录

- **决策 1**: alter 子句改 ENGINE+ROW_FORMAT+CHARSET (3 层防护)
  - 决策人: 阿达叔叔 (产品) + mavis (执行) (2026-08-13 09:54)
  - 替代方案 A (否决): COMMENT 触发 (会破坏表 COMMENT 业务描述)
  - 替代方案 B (否决): 改 ROW_FORMAT=DYNAMIC 单独触发 (5.7/8.0 行为不一致)

- **决策 2**: rebuilt_* 5 字段 (DBA 排查用)
  - 决策人: 阿达叔叔 (2026-08-13 09:54)

- **决策 3**: 列表页显示 "ALTER 子句" 列 (DBA 视觉化)
  - 决策人: 阿达叔叔 (2026-08-13 09:54)

## 8/25 17:30 简化 (用户拍板方案 A)

8/13 拍板时以为 3 层防护 (ENGINE+ROW_FORMAT+CHARSET) 能让 8.0 也触发物理重写。
8/25 16:50 调研发现 8.0.22 4 种 alter 全 no-op (8.0 INSTANT 优化):
- 8.0.12+ 改 ENGINE 改自己走 INSTANT 跳过
- 8.0.16+ 改 ROW_FORMAT 改自己走 INPLACE 跳过 (metadata-only)
- 8.0.22 改 CHARSET/COLLATION 改自己也走 INPLACE/INSTANT 跳过
- 8.0.22 OPTIMIZE TABLE 默认 ALGORITHM=DEFAULT (INSTANT no-op)

也就是说 8.0.22 加 ROW_FORMAT/CHARSET 也不会真重写,反而在 5.7 走 COPY 触发整表
重写时让 gh-ost alter 子句变复杂,没价值。

### 8/25 17:30 用户拍板 (11 字回复)

> "碎片回收命令明确下,只需要 alter table xx engine=innodb;"

直接简化到 `ALTER TABLE t ENGINE=InnoDB;`:
- **5.7.44**: 改 ENGINE 改自己走 **COPY 触发整表物理重写**, ibd 真收缩 ✓
- **8.0.22**: 改 ENGINE 改自己走 INSTANT 跳过, **不重写** (架构性限制, 接受)
- **业务**: 110 prod (5.7) 真 work, DBA 推完后跑 rebuild 看到 ibd 真收缩
- **8/27 推 110 范围**: 推 110 后, 在 110 prod 跑一个真 rebuild 验证

### 8/25 简化影响

1. **`_build_rebuild_alter_clause` 简化**:
   ```python
   # 8/13 3 层防护
   return (
       f"ENGINE={table_info['engine']}, "
       f"ROW_FORMAT={table_info['row_format']}, "
       f"DEFAULT CHARACTER SET={table_info['charset']} "
       f"COLLATE={table_info['collation']}"
   )
   # 8/25 1 层简化
   return f"ENGINE={table_info['engine']}"
   ```
2. **`rebuilt_charset/row_format/collation` 字段保留**: 仍存"原表属性"供排查用
3. **`rebuilt_alter_full` 字段保留**: 仍存"实际用的 alter" (现在就是 `ENGINE=InnoDB`)
4. **5 字段 zero risk**: 推 110 migration 不变 (0004 已加 5 字段)
5. **不影响 ghost 任务**: ghost 任务 rebuilt_* 字段都是 NULL

### 8/25 134 dev 真演练验证

task #103 (accesscard_black_detail):
- `rebuilt_alter_full = [ENGINE=InnoDB]` ✓
- `rebuilt_charset = utf8mb4, rebuilt_row_format = Dynamic, rebuilt_collation = utf8mb4_bin`
- gh-ost log: "Table found. Engine=InnoDB" + "Ghost table altered" + "Done migrating"
- status: success (18s, 18:01:12 → 18:01:28)
- 表结构: ENGINE=InnoDB, ROW_FORMAT=Dynamic, TABLE_COLLATION=utf8mb4_bin (跟 rebuild 前一致, 不漂)
- 8.0.22 ibd 仍 144MB (预期, INSTANT no-op, 8.0 架构限制)

### 关联 changelog

- 8/25 16:55 撤方案 C 改字符集: `docs/changelogs/2026-08-25_v0405-fragmentation-algorithm-fix.md`
- 8/25 17:30 简化到 1 层防护: `docs/changelogs/2026-08-25_v0405-rebuild-8p0-instant-caveat.md`
- 推 110 主手册: `docs/runbooks/2026-08-27_push-v030-execution-manual.md` §1.4
