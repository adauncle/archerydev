# 2026-10-09 DBA-bug-16: instanceaccount onSearch ReferenceError 修复

## 背景

10/9 13:46 阿达叔叔 (110 prod 截图) 反馈: 进入
http://prodarchery.ahggwl.com:9123/instanceaccount/ (实例账号管理),
在搜索框输入字符后, Chrome DevTools Console 报:

```
Uncaught ReferenceError: queryParams is not defined
    at Object.onSearch (instanceaccount/:2073:21)
    at r.value (bootstrap-table.min.js:10.11106)
    at r.value (bootstrap-table.min.js:10.67121)
    at bootstrap-table.min.js:10.84740
```

业务影响: 每次在搜索框输入字符, 浏览器抛 ReferenceError, 搜索功能
虽然仍能工作 (因为 bootstrap-table 内部会重 fetch), 但控制台
全是红字, 掩盖其他真实 JS 错误 (DBA 日常排查问题时被噪声干扰)。
DBA 同事管理实例账号时频繁触发。

## 根因

`sql/templates/instanceaccount.html` line 1312-1315 (merge upstream
v1.14.0 至今未改):

```js
onSearch: function (e) {
    //传搜索参数给服务器
    queryParams(e)        // ← ReferenceError
}
```

`queryParams` 不是全局函数!它是 bootstrap-table 初始化时的
**配置项属性** (line 1289 传入的 function), 当作 `table.options.queryParams`
访问, 不是 `window.queryParams` / 全局变量。

JavaScript 引擎在 `onSearch` 函数体内找 `queryParams`:
1. local scope — 无
2. enclosing scope (初始化匿名函数) — 无
3. global scope — 无
→ `ReferenceError: queryParams is not defined`

业务搜 "monitor" 时触发 → bootstrap-table 触发 onSearch 钩子
(用户输入字符) → 钩子体 `queryParams(e)` 抛 ReferenceError。
**bootstrap-table 内部仍然会按 queryParams 重新 fetch**, 所以
搜索结果还能用, 但 console 全是红字。

## 方案

最小修法 (1 个 function 改空体):

```js
// 改前 (line 1312-1315):
onSearch: function (e) {
    //传搜索参数给服务器
    queryParams(e)
}

// 改后 (line 1312-1320):
onSearch: function (e) {
    // CUSTOM-MODIFIED: 10/9 删 onSearch 里对 queryParams(e) 的调用 @ 2026-10-09 @ mavis
    // 关联: docs/changelogs/2026-10-09_dba-bug-16-instanceaccount-onsearch-referenceerror.md
    // 业务: 10/9 阿达叔叔在 110 prod /instanceaccount/ 报 ReferenceError: queryParams is not defined
    //       触发: 用户在搜索框输入字符, bootstrap-table 触发 onSearch 钩子
    // 根因: 上游 1.14.0 误把 queryParams(e) 当函数调, 但 queryParams 只是 bootstrap-table 的配置项属性 (function), 不是全局函数
    // 修法: 删 queryParams(e) 调用, 因为 bootstrap-table 内部在 onSearch 时已自动用 queryParams 重新 fetch
    //       onSearch 钩子本意是 "用户搜索时触发额外动作", 删空等于回到 1.14.0 改这个钩子之前的状态
}
```

**为什么这么改**:
- bootstrap-table 设计上, `onSearch` 钩子本意是"用户输入搜索字时
  触发额外动作", **不是用来触发 queryParams 的** (queryParams 在
  每次 fetch 时自动用)
- 上游写错, 本意可能是想"用户搜索时也发请求", 但 bootstrap-table
  内部已经处理 — 多余的 `queryParams(e)` 调用既报错又无效
- 改完 onSearch 是空 function, 搜索功能照常工作, 只是不再报
  ReferenceError, console 清爽

**影响范围**: 仅 `sql/templates/instanceaccount.html` 1 个文件, 1 个
空 function; 不影响其他页 (其他页 onSearch 钩子用法都正确)

**风险**: 极低 — onSearch 是"用户搜索时"的可选钩子, 删空它等于
回到 1.14.0 改这个钩子之前的状态

## 演练 / 部署流程

(本 bug 是 JS 钩子问题, server-side drill (Django test client)
不会执行 JS, 所以没有 server-side 演练. 改用真实浏览器验证)

### 134 dev (172.20.2.134, port 9003)

- push `sql/templates/instanceaccount.html` (md5 `60df0e125a3849885a6b25c7c29691c6`,
  103404 bytes, 走 scp + md5 验证)
- 旧版备份: `/opt/archery/prod/sql/templates/instanceaccount.html.bak_20261009_1400_bug16`
- gunicorn reload (pkill + setsid daemon 重启, master pid 53168)
- 阿达叔叔在 http://172.20.2.134:9003/instanceaccount/ 搜索框输字符
  → Console 无红字 `queryParams is not defined` ✅
- 表格按搜索过滤正常 (搜 "monitor" 返回 4 条 monitor 账号)

### 110 prod (172.20.2.110, port 9123)

- push `sql/templates/instanceaccount.html` (md5 匹配, 103404 bytes)
- 旧版备份: `/dbdata/archery_v114_c9236a0/sql/templates/instanceaccount.html.bak_20261009_1420_bug16`
- `systemctl restart archery-v114-gunicorn` (master pid 42833, 4 workers)
- 阿达叔叔在 http://prodarchery.ahggwl.com:9123/instanceaccount/ 验证
  → Console 无红字 ✅

## 关键文件修改

```
sql/templates/instanceaccount.html  | 1 line removed (实际 queryParams(e) 调用)
                                    | 7 lines added (CUSTOM-MODIFIED 注释)
                                    | (注: 注释里出现 queryParams(e) 是字面字符串, 不影响 JS 执行)
```

## commit

- `fix(instanceaccount)`: DBA-bug-16 onSearch ReferenceError 修复
  - sql/templates/instanceaccount.html (删 1 个调用 + 加 7 行注释)
