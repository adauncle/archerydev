# 碎片回收 碎片率/库筛选不生效 — 8/25 修 (v3)

## 症状

8/25 15:20 用户截图反馈: 选 instance + 库=archery_dev + 碎片率 10~20%，
表格里仍然显示 `archery_prod.workflow_log` (99.3%) 等不匹配的行。
顶部明明显示 "显示 0 / 共 142 张"，但表格渲染了 10+ 行。

## 根因

`renderTables` 函数里写反的 JS 表达式 + 优先级 bug：

```js
// 错的 (v1, v2)
var list = state.filtered.length || state.tables.length === 0 ? state.filtered : state.tables;
```

JS 优先级解析成 `state.filtered.length || (state.tables.length === 0)`：
- `state.filtered.length` = 0 (筛选没匹配, filtered 是空数组)
- `0 || (142 === 0)` = `0 || false` = `false`
- `false ? state.filtered : state.tables` → 走 **`state.tables`** ❌

**实际效果**：`applyFilter` 算出来的 `state.filtered` 是 [] (没匹配),
但 `renderTables` 拿到了 `state.tables` (全部 142 张), 表格里渲染了全表。

**用户看到**:
- 顶部"显示 X" 用的是 `state.filtered.length` = 0 (对)
- 表格行用的是 `state.tables` (错, 全表)
- "已应用筛选" 提示用 state.filter 非空判断 (对)
→ 用户看到 "显示 0" + 表格里 10 行 + 提示已应用, 严重 UX 撕裂

## 修法 (v3)

```js
// 对的
var list = state.filtered;
// 边界由下方 if 处理
if (state.tables.length === 0) {
  // 拉表前
} else if (list.length === 0) {
  // 拉表后筛完 0 张
}
```

直接用 `state.filtered`, 让边界条件显式 if 判断, 不再用一行三目 + 优先级坑。

## 验证

- 134 dev 推送 + kill master (41890 → 12469) + /login/ 200 OK
- Django test client 验证模板 366 行 `var list = state.filtered;` 已生效
- 顶部"显示 X" 跟表格渲染行数现在保持一致

## 教训 (跨项目可复用)

1. **JS 三目 + 运算符优先级 + 数字 falsy 是经典三重坑**:
   ```js
   a || b ? c : d    // 实际是 (a || b) ? c : d
   a.length || b === 0 ? c : d  // 实际是 (a.length || (b === 0)) ? c : d
   ```
   0 / "" / null / undefined 都是 falsy, 当 `a.length === 0` 时 `a.length` 是 falsy,
   会走 `||` 右侧 — 几乎一定不是预期行为
2. **复杂条件别用一行三目**, 拆成 `if/else` 块, 边界显式处理
3. **顶层状态变量 (state.filtered) 直接用**, 别在 render 函数里"智能判断该用 filtered 还是 tables"
4. **多状态显示撕裂要警觉**: 顶部"显示 0" 跟表格"渲染 10 行"不一致, 是典型的"两个数据源不同步"信号

## 关联

- 8/25 15:13 筛选行挪位 fix: `docs/changelogs/2026-08-25_v0405-rebuild-filters.md`
- 8/25 15:20 优先级 bug fix: 本 changelog
- 演练脚本: `scripts/_archive/_drill_filter_v2.py` (5/5 PASS 挪位)
- 8/27 推 110 范围已包含本 fix
