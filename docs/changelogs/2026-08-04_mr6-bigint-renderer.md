# v0.2.1-rc · MR6 SimpleJSONRenderer bigint 精度保留

**Commit**: `09d3cc2`
**Date**: 2026-08-04
**Type**: fix · precision · P0
**影响范围**: SQLQueryExecuteView（DRF `/api/v1/sqlquery/execute/`）

---

## 问题

v1.14.0 把老的 `/query/` 接口迁到 DRF `/api/v1/sqlquery/execute/`，新的 `sql_api/renderers.py:SimpleJSONRenderer` 调 `simplejson.dumps` 时**漏了 `bigint_as_string=True` 参数**。

后果：
- 超过 2^53（9007199254740992）的 long int 序列化为 JSON 数字（无引号）
- 前端 `JSON.parse` 后变 IEEE 754 double
- 精度被舍入到最近的 2^53 倍数

复现 SQL：
```sql
select 1641282436039114767 as bigint_col, 4100 as small_col limit 1;
```

| 来源 | 值 | 误差 |
|---|---|---|
| DB 原值 | 1641282436039114767 | - |
| v1.14.0 Archery API 输出 | `1641282436039114767`（JSON 数字无引号） | 0（后端） |
| 前端 `JSON.parse` 后 | `1641282436039114800` | **差 33** |
| Navicat 直查 | 1641282436039114767 | 0（无 JS 中转） |

老接口 `sql/query.py:49` 一直显式传 `bigint_as_string=True`，所以 v1.10.0 时代不爆。

---

## 修复

`sql_api/renderers.py:56` 加一行：

```python
ret = json.dumps(
    self.sanitize(data),
    indent=indent,
    ensure_ascii=self.ensure_ascii,
    allow_nan=not self.strict,
    separators=separators,
    default=self.default,
    bigint_as_string=True,  # ## CUSTOM-MODIFIED: MR6 bigint precision @ 2026-08-03 @ mavis
)
```

修复后：
- 后端输出 `"1641282436039114767"`（**JSON 字符串带引号**）
- 前端 `JSON.parse` 保留完整精度
- 普通 int（id=4100 / status=0 等）仍为数字，前端无破坏

---

## 验证

**Stage 1 - simplejson 直接调用**（standalone）
- buggy: `simplejson.dumps({...1641282436039114767...})` → `1641282436039114767`（**无引号**）
- fixed: `simplejson.dumps({...1641282436039114767...}, bigint_as_string=True)` → `"1641282436039114767"`（**带引号**）

**Stage 2 - 模拟 SimpleJSONRenderer.render() 内部 6 行精确参数**
- 复刻 `ensure_ascii/allow_nan/separators/default` 全部 kwargs
- 行为 100% 等价 SimpleJSONRenderer.render()

**Stage 3 - 真实 SimpleJSONRenderer import**（依赖 psycopg2/bson/pymongo，134 dev 跑）

复现 + 验证脚本：`scripts/test_mr6_bigint.py`

---

## 影响面

- 仅 `SQLQueryExecuteView` 走 `SimpleJSONRenderer`（`api_sqlquery.py:82`）
- 其他 API 走 DRF 默认 `JSONRenderer`，不受影响
- 普通 int 仍为数字，无破坏
- 修复后大数字列变成字符串，前端 `bootstrapTable` 的 `formatter: return value` 直接显示，无精度问题

---

## 上游 PR 计划

**双线提交**：
1. 本地 dev 仓库：commit `09d3cc2` 已合入 main
2. 上游 hhyo/Archery：5 行 diff（renderers.py + 注释），附复现 SQL + 证据链
   - PR 标题建议：`fix: preserve bigint precision in SimpleJSONRenderer`
   - 影响所有 1.14.0 用户

---

## 110 PROD 同步

待 134 dev 跨环境 e2e 验证后，patch 到 `/dbdata/archery_v114/sql_api/renderers.py:56`（同样一行）。

---

## 关联

- MR 清单：`G:\MiniMax工作空间\archery_upgrade\MR-清单.md` § MR6
- 110 复盘：`docs/changelogs/2026-07-30_v0.1.0-110-actual-issues.md`
- 测试脚本：`scripts/test_mr6_bigint.py`
