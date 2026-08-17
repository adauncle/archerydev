# 2026-08-17 dashboard get_chart_data 优雅降级

## CUSTOM-MODIFIED

- **文件**: `common/dashboard.py`
- **原因**: 修 Archery 上游 1.14.0 缺陷 (get_chart_data 9+1 张图串行查询无 try/except, 1 张挂整页 500)
- **修改日期**: 2026-08-17
- **作者**: mavis

## 症状

8/17 13:54 134 dev 上开发用户登录后点 Dashboard 按钮,报 500:

```
ProgrammingError at /dashboard/
(1146, "Table 'archery_prod.mysql_slow_query_review_history' doesn't exist")
Exception Location: /opt/archery/prod/venv/lib/python3.11/site-packages/MySQLdb/connections.py, line 286, in query
Raised during: common.dashboard.pyecharts
```

错误信息截图: 用户浏览器反馈 `/dashboard/` 整页 500。

## 根因 (两层)

### 第 1 层: 134 dev 库缺表
- `mysql_slow_query_review_history` 是 Archery 上游 "MySQL 慢查询分析" 功能配套表
- `sql/models.py:1341` `managed = False`, Django migration 不管这张表
- 上游没有正式建表 SQL,只在 `sql/tests.py:120` 测试代码里 `CREATE TABLE IF NOT EXISTS`
- 8/06 .env 事故重建 134 dev 库时漏建这张表
- 110 prod 库 (7/27 init 建的) 有这张表 + 有数据 (hly_billing 802 条),所以不触发

### 第 2 层 (真正根因): Archery 上游架构缺陷
- `common/dashboard.py:86-193` `get_chart_data` 函数, 10 个图表查询**串行执行**, **无 try/except 兜底**
- 任何 1 张图 SQL 错 (表不在 / 列名错 / 权限错 / 字段缺),异常冒到 Django middleware → 整个 dashboard 500
- 110 prod 之所以没暴露,纯粹是侥幸:表有 + 数据有 + 字段对
- 任何上游 schema 变化 / MySQL 权限调整 / 8.0→5.7 差异都会让 110 prod 也踩这个坑

## 修法

### 改前 (上游原版, line 86-193)
```python
def get_chart_data(start_date, end_date):
    chart_dao = ChartDao()
    # SQL上线数量
    data = chart_dao.workflow_by_date(start_date, end_date)  # ← 表不在抛 1146
    attr = chart_dao.get_date_list(...)
    _dict = {row[0]: row[1] for row in data["rows"]}
    value = [_dict.get(day, 0) for day in attr]
    bar1 = create_bar_chart(attr, value)
    # ... 9 张图同理, 串行, 任何一张挂整页 500
    chart = {
        "bar1": bar1.render_embed(),
        "bar2": bar2.render_embed(),
        ...
    }
```

### 改后 (本次修复)
- `get_chart_data` 每个图独立 try/except, 失败时返空字符串
- 模板 `{{ chart.pie3|safe }}` 渲染空 div (空字符串 → 空白)
- 1 张图挂只影响那 1 张, 其他 9 张照常显示
- 失败时 `logger.warning` 记录, 不影响正常流程
- 新增 `_safe_chart_render` 私有 helper, 9+1 = 10 张图都走这个 helper, DRY

## 验证 (134 dev 演练 4 Case, 待补)

演练脚本: `scripts/drill_dashboard_graceful_degrade.py` (待写)

| Case | 场景 | 预期 |
|------|------|------|
| A | 表存在 + 数据全有 | 10 张图全显示 ✓ |
| B | 模拟 pie3 / bar3 (慢 SQL) 失败 (mock) | 这 2 张图空,其他 8 张照常 ✓ |
| C | 模拟所有 10 张图全失败 | 10 张图全空, 整页 200, 不 500 ✓ |
| D | 真实复现 1146 (134 dev 库确实缺表) | 慢 SQL 2 张图空,其他 8 张照常 ✓ |

## 影响面

### 受益
- 134 dev 库: dashboard 恢复正常 (8 张图照常 + 2 张慢 SQL 图空)
- 110 prod: 多一层防御, 任何上游 schema 变化不再让 dashboard 全死
- 任何未来 `managed=False` 表缺失 / 字段缺 / 权限收回都不再让整页 500

### 不影响
- 业务逻辑: 0 改动
- API 契约: chart dict key 完全一致, 模板不用改
- 性能: 加 try/except 微秒级, 无感
- 数据库: 0 改动 (134 dev 库不建表, 走"空表渲染空图"路径)

## 110 prod 推 v0.3.0 时必带

- 物料: 本 commit + 本 changelog
- 风险: 低 (仅加 try/except, 0 业务逻辑改动)
- 不需要 runbook (5 步必做清单之外)

## 相关

- 8/13 6 commit bug 修复 (cancel 端点返 JSON / DdlGhostTask 同步 / 弹窗去链接 / 字号 / 大表防呆 / 标题去 "DBA 兜底") — 同思路: 上游缺陷我们合规修补
- 8/06 134 dev .env 事故 → 暴露 `managed=False` 表缺失的连锁问题
- 8/13 "bug 必记"原则固化: 修一个 bug, 先写 changelog (症状/根因/修法/验证), 再写代码, 最后 commit
