# v0.4.5 碎片率算法修复 — 用 INNODB_TABLESPACES.FILE_SIZE — 8/25 17:00

## 症状

8/25 16:40 用户反馈"同一张表执行多次碎片回收，列表中还是会展示"。

8/25 16:50 排查发现 134 dev workflow_log 反复 rebuild 8+ 次（task #70-72/87-89/94/95/96），
全部 status=success，但 DATA_FREE 一直 9MB，ibd 实际 128KB。

**2 个真相**：
1. **8.0.22 INFORMATION_SCHEMA.TABLES.DATA_FREE 严重虚高** — 返回 tablespace 预分配大小，不代表可清理碎片
2. **8.0.22 改 CHARSET/ENGINE/ROW_FORMAT 改自己都走 INSTANT 跳过** — gh-ost 看到 success 但没真重写

## 根因

### 真相 1：DATA_FREE 字段虚高
134 dev 实测：
| 表 | DATA_MB | IDX_MB | DATA_FREE (虚) | **ibd 实际** | **真 free** | **真 PCT** |
|---|---|---|---|---|---|---|
| workflow_log | 0.05 | 0.02 | 9MB (虚) | **128KB** | 60KB (元数据) | 50% |
| archive_log | 2.52 | 0.02 | 4MB (虚) | **10MB** | **7.47MB** | **74.7%** |
| workflow_audit | 0.02 | 0.02 | 5MB (虚) | **9MB** | **8.97MB** | **99.7%** |
| ext_ddl_ghost_task | 1.50 | 0.14 | 4MB (虚) | **9MB** | **7.36MB** | **81.8%** |

8.0.22 文档说明 DATA_FREE 字段是 "已分配但未使用"，但实际**严重虚高**（128KB ibd 表报 9MB DATA_FREE）。

### 真相 2：碎片率公式错
老公式：`pct = DATA_FREE / (DATA_FREE + DATA + INDEX)`
- DATA_FREE 虚高导致 pct 误导
- 例如 workflow_log 0.05MB data + 9MB DATA_FREE → 99.3% (误报)
- archive_log 2.52MB data + 4MB DATA_FREE → 4.5% (漏报，实际 74.7%)

**业务影响**：
- DBA 看 workflow_log 99.3% 误以为要 rebuild，结果跑了 8 次 ibd 都不变
- 真要 rebuild 的 archive_log 74.7% 反而因为老算法 4.5% 不显示在 top 列表

## 修法

8/25 16:55 用户拍板方案 A：撤回方案 C 改字符集（因为 8.0 改 CHARSET 也走 INSTANT 跳过），
改**碎片率算法**用 `INNODB_TABLESPACES.FILE_SIZE` 算真实碎片率。

### 1. 撤回方案 C 改 alter 子句（`_build_rebuild_alter_clause`）

- 删 `target_charset` / `target_collation` 字段
- 改回 8/13 拍板的"字符集不漂"alter 子句
- 8/25 16:55 撤回原因：8.0.22 改 CHARSET 也走 INSTANT no-op，**反而永久改字符集，得不偿失**

### 2. 改碎片率算法（`rebuild_list` 端点 SQL + Python）

**SQL 改**：
```sql
SELECT t.TABLE_SCHEMA, t.TABLE_NAME,
       t.DATA_FREE, t.DATA_LENGTH, t.INDEX_LENGTH,
       COALESCE(its.FILE_SIZE, t.DATA_LENGTH + t.INDEX_LENGTH) AS ibd_size
FROM INFORMATION_SCHEMA.TABLES t
LEFT JOIN INFORMATION_SCHEMA.INNODB_TABLESPACES its
  ON its.NAME = CONCAT(t.TABLE_SCHEMA, '/', t.TABLE_NAME)
WHERE t.ENGINE = 'InnoDB'
  AND t.TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
  AND t.TABLE_TYPE = 'BASE TABLE'
ORDER BY t.DATA_FREE DESC
LIMIT 200
```

**Python 改**：
```python
# 真实 free = ibd 实际 - data - index
real_free_bytes = max(0, ibd_size - data_len - idx_len)
pct = (real_free_bytes / ibd_size * 100) if ibd_size > 0 else 0.0
```

**返回字段变化**：
- `data_free_mb`: 之前是 DATA_FREE 虚高值, 改**真实 free (ibd - data - idx)**
- `size_mb`: data + idx (保持)
- **`ibd_size_mb`: 新增, ibd 实际文件大小**
- `data_free_pct`: 改**真实 pct (real_free / ibd_size)**

## 验证 (134 dev)

演练脚本 `scripts/_archive/_drill_frag_algorithm.py` 调 `/gh_ost/rebuild/list/?instance_id=1`：

| 表 | IBD_MB | DATA_MB | FREE_MB (真) | **PCT (真)** | 对比老算法 |
|---|---|---|---|---|---|
| archery_prod.workflow_log | 0.12 | 0.06 | 0.06 | **50.0%** | 老 99.3% (误报) |
| archery_prod.django_q_task | 136.00 | 123.09 | 12.91 | **9.5%** | 老 4.6% (漏报) |
| archery_prod.workflow_audit | 9.00 | 0.03 | 8.97 | **99.7%** | 老 99.4% (一致) |
| archery_dev.accesscard_black_detail | 144.00 | 134.28 | 9.72 | **6.7%** | 老 3.6% (漏报) |
| archery_prod.archive_log | 10.00 | 2.53 | 7.47 | **74.7%** | 老 4.5% (漏报 16 倍) |
| archery_prod.audit_log | 18.00 | 10.73 | 7.27 | **40.4%** | 老 27.1% (漏报) |
| archery_prod.ext_ddl_ghost_task | 9.00 | 1.64 | 7.36 | **81.8%** | 老 70.9% (漏报) |
| archery_prod.query_log | 68.00 | 60.56 | 7.44 | **10.9%** | 老 6.2% (漏报) |

**关键变化**：
- workflow_log 99.3% → 50% (老夸大 2 倍, 但仍有 50% 真实碎片)
- archive_log 4.5% → 74.7% (老漏报 16 倍, 之前没显示在 top 列表)
- ext_ddl_ghost_task 70.9% → 81.8% (老漏报 11%)

## 推 110

- 134 dev push + kill master (37260 → 20456) + /login/ 200 OK
- 8/27 推 110 范围已包含
- 110 prod 推完后, DBA 看新算法结果, **archive_log / ext_ddl_ghost_task 这些真高碎片表才会被勾到**

## 教训 (跨项目可复用)

1. **8.0.22 INFORMATION_SCHEMA.TABLES.DATA_FREE 严重虚高** — 不能用作"碎片率"指标
2. **碎片率应该用 `INNODB_TABLESPACES.FILE_SIZE`** — 这是 ibd 实际文件大小
3. **真 free = ibd 实际 - data - idx**, pct = free / ibd_size
4. **MySQL 8.0 INSTANT 优化坑** — 改 CHARSET/ENGINE/ROW_FORMAT 改自己都走 INSTANT 跳过, gh-ost 看到 success 但没重写
5. **8.0 真要触发物理重写**:
   - 改 CHARSET 跨字符集 (utf8 ↔ utf8mb4) — 但 8.0.22 也走 INPLACE
   - 加列（变长）/ 加删二级索引 — 但不能"rebuild"
   - 实际方案: **OPTIMIZE TABLE** 强制 ALGORITHM=COPY (但 8.0.22 也走 INSTANT)
   - **真正的方案**: gh-ost 走 binlog 异步重写 (它自己重写表, 不依赖 MySQL 原生 DDL)
6. **碎片率算法要走 ibd 实际**, 不要走 INFORMATION_SCHEMA 的"虚高"字段
7. **演练脚本 `_analyze_real_fragmentation.py` 的 SQL 可以归档为 DBA 工具**, 让 DBA 自己看真实碎片

## 关联

- 8/13 拍板 3 决策: `docs/changelogs/2026-08-13_v0405-rebuilt-fields.md`
- 8/25 选表页面: `docs/changelogs/2026-08-25_v0405-rebuild-select-page.md`
- 推 110 准备: `docs/runbooks/2026-08-27_push-v030-execution-manual.md`
- 演练脚本: `scripts/_archive/_drill_frag_algorithm.py` + `_analyze_real_fragmentation.py`
- 数据真相脚本 (DBA 工具): `scripts/_archive/_analyze_real_fragmentation.py` (134 dev 走 INNODB_TABLESPACES 算)
