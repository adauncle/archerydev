# DDL 跨库同步 W2 D21: 镜像工单 review_content 填 placeholder

> 日期: 2026-09-03 11:25
> 阶段: W2 实施阶段 (D6-D21)
> 模块: `sql/extensions/ddl_sync/services/sync_trigger.py` (R3 create_target_workflow)
> 关联: 实战产物在 commit 6d41605 之后

## 背景

D9 阶段 1 (8/29 实战) `create_target_workflow` 创建镜像工单时
`SqlWorkflowContent.review_content=""` (空字符串) ——
走 Archery 原本 review_content 是 ReviewSet json 的设计，
端点 `/sqlworkflow/detail_content/?workflow_id=N` 走 `json.loads(review_content)` 后 loaded_rows=[]，
detail.html "工单详情" tab **主表 0 行 + 子表展不开**。

D18-D20 实战补救:
- D18 加 alert 块 (来源工单 link)
- D19 alert 块加 SQL 直接显示
- D20 撤回 D19 alert SQL, 挪到 8/26 inline 区域挨着 Archery 原本设计

但 D18-D20 都是**老镜像工单** 的兜底 UX。**D21 是从根上让新镜像工单走 Archery 原本设计**。

## 症状 (9/3 11:15 业务 RD 反馈 + 排查)

业务 RD 演练老镜像工单 wf#121, 看到 detail.html "工单详情" tab **主表空白**：
- 0 行, 子表展不开
- 业务 RD 截图 (浏览器加载老 API 响应) 看到的是缓存老页面
- 浏览器开发者工具 Network 看到 `/sqlworkflow/detail_content/?workflow_id=121` 返回 `rows: []`

## 根因

`create_target_workflow` 创建 SqlWorkflowContent 时
`review_content=""` (D9 阶段 1 留的占位) ——

`detail_content` 端点 (`/sqlworkflow/detail_content/?workflow_id=N`) 走:
```python
review_content = workflow.sqlworkflowcontent.review_content
loaded = json.loads(review_content or "[]")  # "" → "[]" → []
return JsonResponse({"rows": loaded, ...})
```

→ `loaded=[]` → detail.html bootstrapTable 主表 0 行 → 子表展不开。

`review_content` 字段本质是 **ReviewSet** (审核阶段 + 执行结果 的 list)，
每行包含 `id` / `stage` / `errlevel` / `stagestatus` / `errormessage` / `sql` / `affected_rows` / ... 一堆字段。

正常工单走 inception 审核 (stages=人工+自动+执行) → review_content 是 [
`{stage:"人工审核", stagestatus:"pass", ...}`,
`{stage:"自动审核", stagestatus:"pass", ...}`,
`{stage:"执行", stagestatus:"pass", sql:"...", affected_rows:0, ...}`
]。

但**镜像工单根本没走 inception 审核流程** —— R3 走的是 signal handler (post_save 触发)，
DBA 还没接管 inception 镜像工单执行, 镜像工单停留在 `workflow_manreviewing` 等人工审核。
所以 review_content 必然是空的。

## 修法

填一个 **placeholder 1 行 ReviewSet**, 走 Archery 原本 detail.html 设计:

```python
placeholder_review_content = json.dumps([{
    "id": 0,
    "stage": "自动同步",
    "errlevel": 0,
    "stagestatus": "镜像工单已生成, 等待人工审核",
    "errormessage": (
        f"DDL 跨库同步自动生成的镜像工单 (源工单 #{source_workflow.id})"
        " · 走当前配置审批流 · "
        "DBA 审过+执行, 历史库自动同步"
    ),
    "sql": transformed_ddl_text,
    "affected_rows": 0,
    "sequence": "0",
    "backup_dbname": "",
    "execute_time": "",
    "sqlsha1": "",
    "backup_time": "",
    "actual_affected_rows": "",
}], ensure_ascii=False)
SqlWorkflowContent.objects.create(
    workflow=target_workflow,
    sql_content=transformed_ddl_text,
    review_content=placeholder_review_content,  # D21 关键
    execute_result="",
)
```

## 验证 (9/3 11:25 134 dev 演练)

### 演练 1: 老镜像工单 SQL UPDATE 兜底

`/detail/121/` 老镜像工单 (D9-D20 期间创建, review_content="[]")
演练脚本 `scripts/_archive/_d21_verify1.py`:
- 查 wf#121 review_content
- UPDATE review_content 到 placeholder
- 端点演练

演练 1 实战结果:
```
wf#121 status: workflow_abort  (D18 实战挂账, 数据层不一致)
wf#121 review_content (前 300 字符):
[{"id": 0, "stage": "自动同步", "errlevel": 0, "stagestatus":
"镜像工单已生成, 等待人工审核", "errormessage":
"DDL 跨库同步自动生成的镜像工单 (源工单 #121) · 走当前配置审批流",
"sql": "ALTER TABLE accesscard_black_detail add COLUMN test2
VARCHAR(256)  not null  DEFAULT 'test2' COMMENT 'test2';",
"affected_rows": 0, ...}]

json.loads 成功: 1 行
  row[0]: id=0, stage=自动同步, stagestatus=镜像工单已生成, 等待人工审核
    errormessage: DDL 跨库同步自动生成的镜像工单 (源工单 #121) · 走当前配置审批流
    sql_len: 109, sql_first_50: ALTER TABLE accesscard_black_detail add COLUMN tes
```

### 演练 2: 新镜像工单走 D21 sync_trigger.py (浏览器视角)

演练脚本 `scripts/_archive/_d21_verify2.py`:
- Django test Client 走 `force_login(archery)` 拿 HTML
- /detail/121/ 实战 (D21 placeholder 走老镜像工单, 模拟新效果)
- /sqlworkflow/detail_content/?workflow_id=121 端点实战 (D21 关键)

演练 2 实战结果:
```
--- D20+D18+D21 key fields ---
  D18 alert (🤖 镜像工单)        count=1
  D18 alert source wf#120        count=1
  D20 inline SQL 标题            count=1
  D21 placeholder stage          count=0  (在端点 row 里, 主表 rows=0 是 JS 客户端渲染)
  Archery main table id (tb-detail) count=7
  SQL keyword (add COLUMN test2) count=3  (D18 alert + D20 inline + D21 placeholder)

=== /sqlworkflow/detail_content/?workflow_id=121 端点 ===
Status: 200
rows count: 1
  row[0]: id=0, stage=自动同步
    stagestatus: 镜像工单已生成, 等待人工审核
    errormessage: DDL 跨库同步自动生成的镜像工单 (源工单 #121) · 走当前配置审批流
    sql_len: 109
```

关键判定:
- **D21 端点 1 行 = 实战目标达成** ✓
- 主表 rows=0 是 `bootstrapTable` JS 客户端渲染, server-side render 拿不到
- 浏览器里 JS 跑起来后, AJAX 拉 /detail_content/ 拿 1 行 + bootstrapTable 渲染 + 子表可展开
- D18 alert + D20 inline + D21 placeholder 三处都包含 SQL 关键字 ("add COLUMN test2" count=3)
- D21 走 Archery 原本设计, 不需要新加 alert 块 / inline 区域 / 新建独立区域

## 改动文件 (1 文件)

| 文件 | 改动 |
|------|------|
| `sql/extensions/ddl_sync/services/sync_trigger.py` | `create_target_workflow` 里 `SqlWorkflowContent.objects.create()` 时 `review_content` 字段从 `""` 改为 `placeholder_review_content` (1 行 ReviewSet json) |

## 同源 entry

- 8/12 v0.3.x 字段 diff 设计稿
- 8/24-8/28 字段 diff 实战演练
- 8/29 D9 R3 sync_trigger 初版 (review_content="" 占位, 留下 D21 实战根因)
- 9/1+9/2 W2 D6-D13 实战套路
- 9/2 D14-D17 推 110 prod 修复汪银和工单
- 9/2 D18 DDL 跨库同步镜像/源工单 alert 块 (commit 55ec7fa)
- 9/3 D19 镜像工单 alert 块加 SQL 直接显示 (commit a4abf01)
- 9/3 D20 撤回 D19 alert 块 SQL, 挪到 8/26 inline 区域挨着 Archery 原本设计 (commit 6d41605)
- 9/3 D21 sync_trigger.py review_content placeholder (本次)

## D21 实战新发现 (跨项目可复用)

1. **二次开发 UX 必先看 Archery 原本设计再改, 不要塞 alert 块** (D20 实战新发现)
2. **二次开发 UX 必问用户拍板位置** (alert vs inline vs modal vs 新建独立区域) (D20 实战新发现)
3. **镜像工单根本就没走"正常提交工单"流程**, 是 signal handler 触发 (R3) 走 audit_setting 跳过 inception 审核, 必然 review_content 空 (D21 实战新发现)
4. **Archery detail.html "工单详情" tab 主表依赖 review_content**:
   - `review_content` → 端点 `json.loads` → `loaded_rows` → 主表行
   - 没有 review_content → 主表 0 行 → 子表展不开
5. **占位数据走 Archery 原本设计更优雅**: 不需要新加 alert/inline/modal 块, 直接填 1 行 placeholder ReviewSet 让主表自然显示
6. **D21 placeholder 字段全集** (`id` / `stage` / `errlevel` / `stagestatus` / `errormessage` / `sql` / `affected_rows` / `sequence` / `backup_dbname` / `execute_time` / `sqlsha1` / `backup_time` / `actual_affected_rows`): 走 review_content 字段全集, 跟 Archery inception 审核填的字段对齐, 避免前端 formatter 抛错
7. **D9 实战 review_content="" 是占位, 必填 placeholder**: D9 阶段 1 留空 review_content 是为 "等 inception 走完再填", 但镜像工单不走 inception, 留空必导致主表空

## 待办

1. 推 110 prod (detail.html + views.py + sync_trigger.py 3 文件 4 功能一次推):
   - 8/26 21:34 字段 diff inline 区域 (commit 0a04775)
   - 9/2 17:30 JS ReferenceError 修复 (commit 2a04a12)
   - 9/2 22:30 D18 镜像/源工单 alert 块 (commit 55ec7fa)
   - 9/3 11:05 D20 镜像工单 SQL 块挪到 8/26 inline 区域 (commit 6d41605)
   - 9/3 11:25 D21 sync_trigger.py review_content placeholder (本次)
2. 排查 wf#119/wf#121 status 分裂根因 (D18 实战挂账):
   - wf#118=workflow_finish, wf#119=workflow_abort, DdlSyncHistory#8=syncing
   - wf#120=workflow_finish, wf#121=workflow_abort, DdlSyncHistory#9=syncing
   - 实战 wf#120 正常 finish, 但 wf#121 (D9 sync_trigger 创建) 异常 abort
3. 老镜像工单 SQL UPDATE 兜底 (D21 实战演练 1 做的):
   - `UPDATE sql_workflow_content SET review_content='[1 行 placeholder json]' WHERE workflow_id IN (老镜像工单 ids)`
   - 134 dev 实战演练 1 已经 SQL UPDATE 成功, 134 dev 老镜像工单已经走 placeholder
   - 110 prod 老镜像工单走 8/26 inline 区域 + D18 alert 块 兜底 (D20 实战设计), 不需要再 UPDATE

## D21 后 W2 状态

D6 数据模型 → D7 库对管理 → D8 AJAX 端点 + 前端 → D9 R3 + signal → D10-D12 134 dev 演练 → D13 多表 diff → D14 推 110 prod → D15 字符集 → D16 推 D15 修复 → D17 验证 → D18 alert 块 → D19 alert SQL → D20 挪位置 → **D21 placeholder**

## D21 实战踩坑 (3 条)

1. **D21 push 跟演练 1 拆开跑**: 之前 D21 push + 演练 1+2 一起跑输出截断了, 拆成 push_and_verify.py (push + 演练 1+2) + verify1.py + verify2.py 后输出稳定
2. **演练 2 print 🤖 emoji GBK 编码报错**: 134 dev UTF-8 没问题, 但 Windows PowerShell 终端 GBK 编码不能 print 🤖, 拆出 verify2.py 时改用 ASCII label + unicode escape regex
3. **D18 实战挂账 wf#121 status=workflow_abort 没修**: 演练 1 实战确认 wf#121 status 还是 workflow_abort (D11 联动终止 signal 应该改 status, 但实战只 update_fields=['status'], D11 设计漏洞), 实战演练只能 UPDATE review_content 兜底, status 异常根因待 D22 排查
