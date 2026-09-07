# D35 修复: 去掉推到 110 prod 的功能里的版本号文案 (9/7 业务方反馈)

> **日期**: 2026-09-07 12:48
> **触发**: 业务方截图 110 prod gh-ost 任务管理页, 类型列显示 "v0.3.0 改造" / "v0.4.5 改造"
> **决策**: 推到 110 prod 的功能不能出现版本号 (业务方视角不关心内部改造版本)
> **影响范围**: 134 dev + 110 prod 同步修

---

## 一、问题

业务方截图 110 prod `/gh_ost/admin_list/` 页面 (9/7 12:39 截), 任务类型列:
- #14 gh-ost DDL **(v0.3.0 改造，SQL 工单触发)**
- #13 gh-ost DDL **(v0.3.0 改造，SQL 工单触发)**
- #12 碎片回收 **(v0.4.5 改造，DBA 手动连续触发)**

业务方反馈: "推到 110 prod 的功能都不能出现版本号" — 业务方只关心功能本身, 不关心是 v0.3.0 还是 v0.4.5 改造的. 改成"中性"文案.

## 二、改法

### 5 处文案调整

#### 1. `sql/extensions/ddl_gh_ost/models.py:32-33` TASK_TYPE_CHOICES
```python
# 修前
TASK_TYPE_CHOICES = (
    ("ghost", "gh-ost DDL（v0.3.0 改造，SQL 工单触发）"),
    ("rebuild", "碎片回收（v0.4.5 改造，DBA 手动选表触发）"),
)
# 修后
TASK_TYPE_CHOICES = (
    ("ghost", "gh-ost DDL（SQL 工单触发）"),
    ("rebuild", "碎片回收（DBA 手动选表触发）"),
)
```

#### 2. `sql/extensions/ddl_gh_ost/migrations/0002_*.py:41-42`
同步 migration choices, 跟 models.py 保持一致 (Django migrate 不会 complain choices 不一致, 但运行时会显示)

#### 3. `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/progress_rebuild.html:94`
```html
<!-- 修前 -->
<h1>碎片回收进度 <span class="badge" style="background:#67C23A;vertical-align:middle;">v0.4.5</span></h1>
<!-- 修后 -->
<h1>碎片回收进度</h1>
```

#### 4. `sql/templates/detail.html:31` 镜像工单 alert
```html
<!-- 修前 -->
<span class="label label-default">v0.5.0 自动生成</span>
<!-- 修后 -->
<span class="label label-default">自动生成</span>
```

#### 5. `sql/templates/detail.html:74` 源工单 alert
```html
<!-- 修前 -->
<span class="label label-default">v0.5.0 联动中</span>
<!-- 修后 -->
<span class="label label-default">联动中</span>
```

## 三、不动 (注释/文档/历史)

- `common/templates/base.html` / `sql/templates/sqlsubmit.html` 注释里的版本号
  (Django/Jinja 注释 `{# #}` `<!-- -->` 不渲染到页面)
- `archery/settings.py` `## CUSTOM-MODIFIED: v0.3.0-alpha ...` 注释
  (代码内部历史, 不上 UI)
- `docs/changelogs/2026-*_v*.md` 文件名版本号
  (历史 changelog 不动, 重命名会破坏 AGENTS.md 引用)
- `docs/runbooks/*.md` 内部 runbook
  (运维文档, 跟业务方 UI 无关)
- `docs/reports/*.html` 项目进度报告
  (历史静态文档, 不会上 110 prod)

## 四、134 dev 演练 PASS (9/7 12:50)

演练脚本: `scripts/_archive/_d35_134dev_no_version_verify.py`

```
=== 4 文件 md5 一致性验证 ===
  models.py: PASS
  0002_*.py: PASS
  progress_rebuild.html: PASS
  detail.html: PASS

=== DdlGhostTask.TASK_TYPE_CHOICES ===
  ghost -> gh-ost DDL（SQL 工单触发）  [PASS]
  rebuild -> 碎片回收（DBA 手动选表触发）  [PASS]

=== admin_list 页面验证 ===
  GET /gh_ost/admin_list/ status: 200
  admin_list 页面含 v0.3.0? False  ✅
  admin_list 页面含 v0.4.5? False  ✅
  GET /login/ 200 业务不中断
```

## 五、commit 影响

| commit | 改动 |
|------|------|
| 本次 commit (待) | fix(ddl_gh_ost, sql): 去掉用户能看到的版本号文案 |
| 涉及文件 | models.py, migrations/0002, progress_rebuild.html, detail.html |

## 六、110 prod 推送影响

D35 push 9 步 runbook Step 6 跨 app 6 文件清单更新:
- `sql/extensions/ddl_gh_ost/models.py` (**新增 D35 nover**)
- `sql/extensions/ddl_gh_ost/migrations/0002_*.py` (**新增 D35 nover**)
- `sql/extensions/ddl_gh_ost/templates/ddl_gh_ost/progress_rebuild.html` (**新增 D35 nover**)
- `sql/templates/detail.html` (D18/D20/D25 v2 + **D35 nover**)
- `sql/templates/sqlsubmit.html` (D28/D29 弹窗化)
- `sql/extensions/ddl_gh_ost/services/column_diff.py` (D27 + **D35 backticks 修复**)
- `sql/extensions/ddl_sync/views/__init__.py` (D22/D23/D25/D33)
- `sql/extensions/ddl_sync/urls.py` (D33 history_export)
- `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` (D33 同步历史 tab)

Step 6 跨 app 文件从 6 个增加到 9 个 (ddl_gh_ost 新增 3 个). D35 push 实战时 9 步走完即一并生效.

## 七、相关 changelog

- `docs/changelogs/2026-09-07_ddl-sync-w2-d35-backticks-parse-bug.md` (D35 修 backticks 解析)
- `docs/changelogs/2026-09-03_ddl-sync-w2-d31-prod-deploy-precheck.md` (D31 8 步原始)
- `docs/changelogs/2026-09-04_ddl-sync-w2-d34-prod-push-drill.md` (D34 9 步演练)
