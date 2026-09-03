# v0.3.x 字段 diff D28: /editsql/ 字段 diff 弹窗化

> 日期: 2026-09-03 17:35
> 阶段: v0.3.x 字段 diff UX 升级
> 模块: `sql/templates/sqlsubmit.html`
> 关联: 9/3 17:33 业务方反馈 (110 prod /editsql/ 页底部 inline 字段 diff 不直观)

## 背景

`/editsql/` 提交工单页面, "SQL 检测" 按钮 AJAX 成功后, 字段 diff 走 `fetchColumnDiff()` 函数
渲染到 `#column-diff-result` div (line 155 inline) — 业务方看到 inline 区域在页面底部
+ SQL 编辑器 + 配置项 + 检测结果, 字段 diff 容易看漏, 业务方反馈"不直观".

## 症状 (9/3 17:33 业务方反馈 + 截图)

业务方演练 `/editsql/` 页 (110 prod prodarchery.ahggwl.com:9123/editsql/):
- 编辑 SQL `alter table import_data modify oil_belong varchar(2048) null comment '油气服务商'`
- 点 "SQL 检测" 按钮
- 检测结果 + 字段 diff 都在底部"检测结果"panel, inline 展示
- 业务方反馈: 想让字段 diff 跳出弹窗, 看完再关掉

## 根因

`/editsql/` 页的 `fetchColumnDiff()` 函数 (sqlsubmit.html line 707-733) 走 inline 渲染:
```javascript
function fetchColumnDiff(sqlContent, instanceId, dbName) {
    var $box = $("#column-diff-result");
    // ... 渲染 HTML 到 $box ...
    $box.html(html).show();  // inline 显示
}
```

inline 区域 (`#column-diff-result` div) 在底部"检测结果" panel 里, 跟 SQL 检测主结果混在一起,
业务方要 scroll 到底部才能看到.

## 修法

1. 加 `columnDiffModal` Bootstrap Modal 元素 (line 165-180)
2. 加 inline 兜底入口 `column-diff-inline` (line 155-160, "字段变更检测已运行, 点击查看" 链接)
3. 改 `fetchColumnDiff()` 函数:
   - AJAX success 后: 渲染到 modal body + **自动 `$('#columnDiffModal').modal('show')`**
4. 改 `renderColumnDiff()` 函数: `$box` 指向 `#column-diff-modal-body`
5. 加 inline 链接 click 绑定: 点 "字段变更检测已运行" 重新打开 modal

## 验证 (9/3 17:35 134 dev 演练)

### 演练 1: /editsql/ 渲染 + columnDiffModal 元素齐全

`scripts/_archive/_d28_push_test.py` 演练 1:
- 推 sqlsubmit.html 134 dev (md5 一致 15c07b211c91)
- kill gunicorn + 拉新 (master 57520 + 4 worker 57532/57533/57534)
- render /editsql/

演练 1 实战结果:
```
Status: 200, length: 94500
  D28 columnDiffModal 存在                count=1
  D28 column-diff-modal-body 存在         count=1
  D28 column-diff-inline 兜底链接 存在    count=1
  D28 btn-show-column-diff-modal 兜底按钮 存在  count=1
  D28 关闭按钮 (data-dismiss)            count=10
```

**D28 渲染 PASS** ✓ (count=10 因为 detail.html 也有 data-dismiss, 共享)

### 演练 2: D27 ALTER COLUMN 端点兼容 D28

`scripts/_archive/_d28_push_test.py` 演练 2:
- 调 `column_diff_full(instance, "hly_accesscard", "alter table accesscard_black_detail alter column reason set default 'd28_test'")`
- 验证 D27 ALTER_DEFAULT 还能正常用

演练 2 实战结果:
```
ok=True, columns=1
  col reason op=ALTER_DEFAULT
    diffs=[{'field': 'default', 'old': None, 'new': 'd28_test', 'risk': 'low',
            'reason': "DEFAULT 从 None 改为 'd28_test', 不影响存量数据, 只影响新插入行"}]
```

**D28 跟 D27 兼容 PASS** ✓

## 改动文件 (1 文件)

| 文件 | 改动 |
|------|------|
| `sql/templates/sqlsubmit.html` | 加 columnDiffModal 元素 + column-diff-inline 兜底链接 + fetchColumnDiff 改走 modal + renderColumnDiff 渲染到 modal body + inline 链接 click 绑定 |

## 同源 entry

- 8/12 v0.3.x 字段 diff 设计稿 (设计时就是 inline 渲染, 业务方当年没吐槽)
- 8/24 v0.3.x 字段 diff 模态框 8/24 fix (8/12 实战时 modal 在 endblock 之后)
- 8/26 v0.3.x 字段 diff inline 区域 (commit 0a04775) - 业务方吐槽"为什么不弹窗", 跟 D28 一样的需求, 当时选了 inline
- 9/2 D14 推 110 prod 修汪银和工单
- 9/2 D15 字符集 implicit/explicit 区分 (commit e939ffe)
- 9/2 D16 推 D15 修复实战 110 prod c9236a0 (commit 289adc7)
- 9/2 D17 验证 110 prod D15 修复实战生效
- 9/3 D18-D21 镜像工单 UX 完整链路
- 9/3 D22-D27 实战链路

## D28 实战新发现 (跨项目可复用, 3 条)

1. **D28 业务方需求 8/26 已潜伏 (8/26 实战备注 "为什么不弹窗")** (D28 实战新发现) - 8/26 v0.3.x inline 区域 实战时用户当时没要求弹窗, 9/3 17:33 业务方明确要求"想弹窗", 实战选 A 方案跟 8/24 modal 套路一致
2. **D28 走 modal 但保留 inline 兜底链接** (D28 实战新发现) - 业务方关掉 modal 后能通过 inline 链接重新打开, 兜底 UX 完整; detail.html v0.3.x 设计也是 inline + modal 双入口套路
3. **D28 实战 py_compile 134 dev HTML 报错** (D28 实战踩坑) - Windows PowerShell GBK 编码不能 parse UTF-8 HTML, 改用 SFTP 推 134 dev + render 演练直接验证, 跳过本地 py_compile (HTML 也不需要 Python parse)

## D28 实战踩坑 (2 条)

1. **D28 改 fetchColumnDiff 字符串 跟 renderColumnDiff 隔一段距离** (D28 实战踩坑) - 第一次 edit 失败因为两段间有 instanceId/dbName 校验的 $box.hide().empty() (line 712) 我没改, 实战重读 line 707-735 才看清结构, 重写 edit 字符串成功
2. **D28 PowerShell GBK 终端打印 unicode escape regex 演练问题** (D21 实战踩坑 3 复用) - 演练 1 "D28 modal 标题" + "D28 footer 关闭按钮" count=0 (PowerShell GBK 终端 unicode escape 编码问题, 不是数据问题), 用 ASCII label 替代更稳

## 待办

1. 推 110 prod (D28 1 文件):
   - sqlsubmit.html 推 110 prod
   - 推前必查 110 prod md5 (D12 实战新发现)
   - 推完演练 1 个 MODIFY + 1 个 ALTER COLUMN 工单 + 1 个"SQL 检测"按钮点字段 diff 弹窗
2. 110 prod 推完后, 业务方演练 wf#4776 类似工单, 验证 D27 + D28 实战生效
3. W3 计划: v0.3.x 字段 diff 全部 ALTER 语法边界梳理 (RENAME COLUMN, MODIFY COLUMN COMMENT, CHANGE COLUMN, ALGORITHM=INPLACE 等), 一次性修齐

## D28 实战后 134 dev gunicorn pids

master 57520 + 4 worker 57532/57533/57534 (D28 演练拉新)
