# 碎片回收 选表页加 3 筛选器 (库/表名/碎片率) — 8/25

## 症状 / 背景

8/25 11:00 选表页面 (方案 B) 上线后, DBA 反馈:
"top 200 一股脑全显示, 找特定库/特定表很费劲"

134 dev 上 instance=1 有 142 张表, 跨 4 个库 (archery_dev / archery_prod / archery_staging / test_archery),
DBA 找 `archery_prod` 库下 30%+ 碎片率且表名带 `log` 的表, 要手动滚屏 N 次。

## 需求 (8/25 14:55 用户提)

3 个筛选器:
1. **库筛选** — 下拉, 选特定库
2. **表名筛选** — 文本框, 模糊匹配
3. **碎片率范围** — min/max 数字框, 0~100%

## 实现

**前端筛选** (200 张表已全拉到前端, 实时过滤):
- 后端 0 改动 (`rebuild_list` 端点不变)
- 仅改模板 `rebuild_select.html` (~2KB 新增)

### 筛选行 UI

```
筛选:  [库: 全部 (4) ▼]  [表名: 模糊匹配]  [碎片率: 0 ~ 100 %]  [重置]
```

- 库下拉: 拉表后从 `state.tables` 动态提取 unique db, 字母序, 显示 "全部 (N)"
- 表名: substring 匹配 (不区分大小写)
- 碎片率: min/max input number, 兜底 min>max 互换
- 重置: 一键清 3 个筛选器

### JS 核心

```js
function applyFilter() {
  readFilter();
  state.filtered = state.tables.filter(t => {
    if (f.db && t.db !== f.db) return false;
    if (f.table && !t.table.toLowerCase().includes(f.table)) return false;
    if (t.data_free_pct < f.pctMin) return false;
    if (t.data_free_pct > f.pctMax) return false;
    return true;
  });
  renderTables();  // 用 filtered 渲染
}
```

监听 3 个 input (db 走 `change` 事件, table/pct 走 `input` 实时):
```js
['filter-db', 'filter-table', 'filter-pct-min', 'filter-pct-max'].forEach(id => {
  document.getElementById(id).addEventListener(
    id === 'filter-db' ? 'change' : 'input',
    applyFilter
  );
});
```

### 联动修改

- **`btn-select-all`**: 改按 `state.filtered` 全选 (跟用户看到的列表一致, 不会选筛掉的表)
- **`tables-info`**: 顶部加 "显示 X / 共 Y 张" + "(已应用筛选)" 提示
- **空结果态**: 筛完 0 张时显示 "无匹配表 — 调整筛选条件或点重置" (橘色提示)

## 演练

134 dev Django test client 验证 6 个筛选组合:

| Case | 筛选条件 | 结果 |
|------|---------|------|
| 1 | `db=archery_prod` | 53 张 |
| 2 | `table 含 workflow` | 20 张 |
| 3 | `pct 50~100` | 5 张 |
| 4 | `db=archery_prod + table 含 log + pct 30~100` | **2 张** (workflow_log 99.3% + archive_log 61.2%) |
| 5 | 重置 = 全部 | 142 张 |
| 6 | `db=archery_prod + pct 99~100` (高碎片率) | 2 张 |

Case 4 验证真实 DBA 场景: "找 archery_prod 库下需要 rebuild 的 log 表", 2 张都对。

模板元素 + JS 函数 11/11 PASS (filter-db / filter-table / filter-pct-min / filter-pct-max / filter-reset / filters-row / placeholder / applyFilter / populateDbFilter / state.filtered / 重置).

## 推 110

- 134 dev push + kill master (46092 → 4080) + `/login/` 200 OK
- 8/27 推 110 范围已包含

## 教训 (跨项目可复用)

1. **top N 一股脑显示一定要加筛选**, 哪怕 50 行也要给库/表名/阈值 3 筛
2. **筛选放前端不放后端** (N≤200 时): 实时反馈, 0 网络请求, UX 更好
3. **"全选"按钮要按当前 filtered 选**, 不会误选筛掉的表 (隐藏 bug 高发)
4. **空结果给提示**, 不要让用户面对一片空白 (Element UI 风格: 橘色 + 图标 + 行动建议)
5. **min/max 输入框要兜底互换**, 用户可能输反 (常见 UX 痛点)
