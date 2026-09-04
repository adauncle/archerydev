# DDL 跨库同步 W2 D33: 同步历史加分页 + Excel 导出

> 日期: 2026-09-04 11:30 - 14:10
> 阶段: W2 实施阶段 D33 (W2 收尾 + 134 dev 优化)
> 模块: pair_detail.html 同步历史 tab + pair_history_export view
> 关联: 9/3 D32 实战 commit 096c715 之后业务方实战反馈

## 背景

业务方实战使用 pair_detail.html 同步历史 tab 时反馈:

1. **分页** — 同步历史后期变更工单多了 (16+ 条), 单页显示 50 条太臃肿, 不利于用户筛选
2. **导出 Excel** — 业务方需要做月度变更汇报, 希望导出全量历史到 Excel 离线分析

## 业务需求 (D33 拍板)

D33 实战优化:
1. **分页** — 每页 20 条, URL 加 `?history_page=N` 参数, 总条数 > 20 才显示分页栏
2. **导出 Excel** — 新增 view, 输出 .xlsx (兼容 Excel 2007+), 包含全量历史
3. **导出按钮位置** — tab 内右上角 (h5 同一行), 跳到 `/ddl_sync/pair/<id>/history_export/`
4. **文件名规范** — `ddl_sync_history_pair<pair_id>_<timestamp>.xlsx` (ASCII safe, 防 GBK 编码)

## 修改清单 (D33 拍板 3 文件 + 1 新 view)

### 1. `sql/extensions/ddl_sync/views/__init__.py` 改 2 处

- **pair_detail view** 加分页:
  ```python
  HISTORY_PER_PAGE = 20
  history_qs = pair.history.select_related(...).order_by("-created_at")
  history_count = history_qs.count()
  history_paginator = Paginator(history_qs, HISTORY_PER_PAGE)
  history_page_num = request.GET.get("history_page", 1)
  history_page_obj = history_paginator.get_page(history_page_num)
  history = history_page_obj.object_list
  ```
- **新增 pair_history_export view**:
  ```python
  @permission_required("ddl_sync.view_ddlsynctable", raise_exception=True)
  @require_http_methods(["GET"])
  def pair_history_export(request, pair_id):
      """导出库对同步历史为 Excel (.xlsx)"""
      from openpyxl import Workbook
      from openpyxl.styles import Font, Alignment
      from django.utils import timezone
      ...
  ```
  - 用项目已依赖的 `openpyxl==3.1.5` (requirements.txt line 68)
  - 8 列: ID / 表名 / 业务库工单 / 历史库镜像工单 / 状态 / 创建时间 / 完成时间 / 错误信息
  - 表头加粗, 列宽 8/28/14/18/16/20/20/50
  - 错误信息截 1000 字避免撑爆

### 2. `sql/extensions/ddl_sync/urls.py` 加 1 路由

```python
# D33 同步历史 Excel 导出
path("pair/<int:pair_id>/history_export/", views.pair_history_export, name="pair_history_export"),
```

### 3. `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` 改 同步历史 tab

- **h5** 改 "同步历史 (共 X 条, 第 N/M 页)" — 含分页信息
- **导出按钮** 加 h5 右侧 — `📥 导出 Excel` 跳到 `pair_history_export` URL
- **分页栏** table 下方 — 上页/数字/下页, 每页链接带 `#tab-history` 锚点 (切回历史 tab)
- **新 CSS** — `.ddlsync-btn-export` (绿色) + `.ddlsync-page-link` (蓝色) + `.ddlsync-page-current` (蓝色实心)

## 实战新发现 (跨项目可复用, 3 条)

1. **Django 模板 `{% url %}` 渲染后不再包含 namespace 字面量** (D33 实战新发现) — 验证 "has export button" 时检查 namespace 字面量 `'pair_history_export'` 会误报 False, 应该检查渲染后的实际 URL 字符串 `/ddl_sync/pair/1/history_export/` 或用 `reverse()` 拿 URL 再 `in html`. 实战教训: 验证 Django 模板渲染时, 字符串匹配要匹配渲染后产物, 不匹配原始模板源码
2. **openpyxl 写 .xlsx 中文表头在 PowerShell GBK 终端显示乱码** (D33 实战踩坑) - 验证 .xlsx 解析时 `print([c.value for c in ws[1]])` 输出 `'ID', '', '', '', ...` 表头都是空, 实际是中文 (表名/业务库工单/...) 被 iconv -t ascii//IGNORE 丢了. 实战教训: 验证 .xlsx 用 `ws.cell(1, col).value` 拿具体列的值, 不要 print 整行
3. **DdlSyncHistory.source_workflow 是 NOT NULL FK** (D33 实战踩坑) - 创建测试 history 报 `Column 'source_workflow_id' cannot be null`. 实战教训: 测试用 history 必带 `source_workflow=<existing>`, 不能为空, source_workflow 是 PROTECT FK

## 实战踩坑 (2 条)

1. **D33 Step 6 sudo venv/bin/python: command not found** (D33 实战踩坑) - sudo -u 之后 pwd 改了, 要 cd /opt/archery/prod 才能找到 venv/bin/python. 教训: 远程 sudo 跑命令必 cd 到正确目录, 用绝对路径更稳
2. **D33 验证分页要造 > 20 条 history 才能看到分页栏** (D33 实战踩坑) - 134 dev pair#1 实际只有 16 条 history, 第一次验证 "has history_page= link" 报 False 是因为 num_pages == 1, 分页栏没渲染. 教训: 验证分页功能必造 > 每页条数条数据, 或传 `?history_page=2` URL 参数 (但 num_pages=1 时 page 2 还是 page 1)

## 验证结果 (D33 实战 PASS)

D33 实战验证 5 步:
1. **Step 1**: 当前 history count = 16 (小于 20, 分页栏隐藏 — 符合预期)
2. **Step 2**: 临时造 5 条 → count = 21 (测试用, 测试后清理)
3. **Step 3**: 验证分页 (21 条 → 2 页):
   - ✓ has history_page link: True
   - ✓ has history_page=2 link: True
   - ✓ has page current class: True
   - ✓ has 1/2 text: True (h5 显示 "第 1/2 页")
4. **Step 4**: 测 page 2 渲染 → status 200, len 58740 bytes
5. **Step 5**: 导出 view 测 → status 200, content-type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
6. **Step 6**: openpyxl 解析 → rows: 22 (1 表头 + 21 数据), 包含新造的 _d33_test_pagination_ 数据
7. **Step 7**: 清理 → deleted (5, ...), count 回到 16

实战 commit: D33 改 3 文件 + 1 新 view, 4 处变更:
- views/__init__.py: pair_detail 加分页 + 新增 pair_history_export view
- urls.py: 加 1 path
- pair_detail.html: 同步历史 tab 改 h5 + 加导出按钮 + 加分页栏 + 加 CSS

## 实战新发现 (跨项目可复用, 1 条)

- **D33 业务方实战反馈驱动优化, 实战 3 个改动: 1 view + 1 url + 1 template + 1 css** (D33 实战新发现) - 业务方长期使用才会发现 "臃肿" + "需要导出" 这类需求, 设计时无法预知. 实战教训: 业务方实战反馈是优化的最佳输入, 比设计时拍板更准

## D33 实战后 W2 状态

D6 → D7 → ... → D29 → D31 → D32 → **D33 同步历史加分页 + Excel 导出** (实战验证 PASS, 134 dev 已用) → D33+ 准备推 110 prod
