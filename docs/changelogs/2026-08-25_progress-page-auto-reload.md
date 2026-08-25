# 2026-08-25 进度面板终态自动 reload (task #71 实战发现)

> **触发时间**: 2026-08-25 12:42 (业务 RD 第二个 gh-ost 任务完成)
> **修复时间**: 2026-08-25 12:50
> **影响**: gh-ost 任务完成时, 进度面板自动刷新整个页面, 业务 RD 不再需要手动 F5

---

## 症状

业务 RD 在 `/detail/96/` 页面点"启动 gh-ost" → task #71 18 秒内 100% 复制完 + Done migrating → **数据库 task.status='success'**（已确认）。

但**前端页面**显示：
- 标题：**排队中** (queued)
- 进度：100% / 成功 / Done migrating
- 复制：241558/241558
- 预计剩余：1h

**矛盾**：后端是 success，前端是 queued。

---

## 根因

进度面板 `progress.html` JS 逻辑：

```javascript
async function poll() {
  const d = await fetch(`/gh_ost/status/${wfId}/`).then(r => r.json());
  render(d);
  if (["running", "cut_over", "queued"].includes(d.status)) {
    setTimeout(poll, 3000);  // 中间态继续 poll
  }
  // 终态 (success/failed/cancelled) 停 poll, 但页面不更新
}
```

**问题**：
- 8/13 拍板进度面板 polling 3s + 终态停 poll
- 终态时**不调** `location.reload()`, 所以**模板渲染不变**（一直是初始加载的 task.status）
- 业务 RD 看不到最终 status 切换

**实际数据流**：
1. 业务 RD 打开 `/detail/96/` → server 渲染模板时 task.status=queued (页面打开时) → 页面显示"排队中"
2. gh-ost 跑 18 秒, poller 切 status=success
3. JS poll 3s 一次, 拿到 status=success, 调 `render(d)` 更新 **JS 控制的 DOM** (进度条 100%, 按钮 disabled, "Done migrating")
4. 但**模板的"成功"标题** (line 114-115) 是 server 渲染的, JS 不重渲染
5. 所以"排队中"标题 + "100% Done migrating" 进度 同时出现

---

## 修法

`sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/progress.html` line 239-251：

```javascript
if (["running", "cut_over", "queued"].includes(d.status)) {
  setTimeout(poll, 3000);
} else {
  {# CUSTOM-MODIFIED: 终态自动 reload 整个页面 @ 2026-08-25 @ mavis #}
  {# 关联: docs/changelogs/2026-08-25_progress-page-auto-reload.md #}
  setTimeout(() => location.reload(), 1000);  // 终态 1s 后刷新整个页面
}
```

**业务**：终态时调 `location.reload()` 整页刷新，server 重新渲染模板（用最新 task.status），UI 一致。

---

## 8/25 实战验证 (task #71)

| 时间 | 状态 | 进度 | 备注 |
|------|------|------|------|
| 12:43:03 | queued | 0% | 业务 RD 点"启动 gh-ost" |
| 12:43:21 | success | 100% | 18 秒完成, poller 切 status (err='' 1146 过滤生效) |
| 12:44 | success | 100% | 业务 RD 截图 (但页面 JS 渲染停留在 "排队中") |
| 12:50 | success | 100% | 改 location.reload(), 部署到 134 dev |

---

## 8/24 教训 + 8/25 教训

1. **8/13 拍板 polling 3s 终态停 poll** — 但停 poll 不 reload, UI 不更新
2. **8/25 实战**：状态机切换跟 UI 渲染不同步, 需要 reload 触发
3. **8/25 教训 (跨项目可复用)**:
   - 进度类 UI 终态必须 reload 整页, 不能只更新 JS DOM
   - 模板渲染 (server-side) 跟 JS 渲染 (client-side) 要协调
   - 实战演练才能发现这种 UI/状态不同步 bug

---

## 8/27 推 110 影响

- 8/27 推 110 推代码后, 业务 RD 启动 gh-ost 完成后, 页面**自动 reload 1 次**, 业务 RD 看到"成功"标题
- 不需要手动 F5
- 防止"排队中 + 100% 矛盾"再现

---

## 关联 commit

- 本次 commit: `progress.html` 终态 reload 改动
- 8/13 进度面板 polling 3s 拍板: `docs/changelogs/2026-08-10_gh-ost-v030b-state-sync.md`
- 8/13 大表 DDL 防呆: `docs/changelogs/2026-08-13_gh-ost-sqlsubmit-big-table.md`
