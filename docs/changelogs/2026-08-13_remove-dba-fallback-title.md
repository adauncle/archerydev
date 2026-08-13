# 2026-08-13 字段变更检测标题去掉 "(DBA 兜底)" 字样

## 业务背景

8/13 用户反馈: SQL 提交页字段变更检测标题 **"字段变更检测 (DBA 兜底)"** 里的
"(DBA 兜底)" 字样容易引起开发误解 — 看到"有 DBA 在兜底"就觉得"随便提工单也行,
反正有 DBA 给我把关", 不用心写 SQL。

期望: 字段变更检测标题**只显示"字段变更检测"**, 不带"(DBA 兜底)"字样。
      让开发意识到字段 diff 是**自己提交前的自查工具**, 不是 DBA 的兜底。

## 修法

改 2 个文件, 各 1 行:

### `sql/templates/sqlsubmit.html` line 805

```diff
- '<strong style="font-size:15px;color:#14171e;">📋 字段变更检测 (DBA 兜底)</strong>' +
+ '<strong style="font-size:15px;color:#14171e;">📋 字段变更检测</strong>' +
```

### `sql/templates/detail.html` line 604

```diff
- <h4 class="modal-title"><i class="fa fa-columns"></i> 字段变更检测 (DBA 兜底)</h4>
+ <h4 class="modal-title"><i class="fa fa-columns"></i> 字段变更检测</h4>
```

**不动的位置**:
- 详情页大表 alert "强烈建议启用 gh-ost 无锁 DDL——RD 漏勾时，DBA 可在下方兜底启用"
  这是大表 DDL 防呆 alert 里的"兜底"语境 (DBA 兜底启用 gh-ost), 跟字段 diff 标题语境不同, 保留
- Excel v3 / 进度面板 / 任务列表 等其他位置的"DBA 兜底"描述 (产品定位文档, 跟 UI 标题无关)

## 验证

- [x] 134 dev 2 文件 sync 完毕 (`grep` 确认两边都没"(DBA 兜底)")
- [x] gunicorn reload 完毕
- [ ] **用户浏览器手动验收** (SQL 提交页 + 详情页字段 diff 弹窗)

## 同源 entry

- 8/12 commit `1f32976` (v0.3.x 字段 diff 检测) — 初版, 标题写"(DBA 兜底)"
- 8/13 commit `fba0564` (字段 diff 补全 SQL 一键复制)
- 8/13 commit `36eb885` (字段 diff UI 调大字号)
- 8/13 commit `374d990` (SQL 提交页大表 DDL 防呆)
- **本次 commit** 去掉标题"(DBA 兜底)"字样
