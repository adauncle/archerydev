# D36 同步表清单分页 + 行数选择 (9/8 18:03 业务方实战反馈驱动)

> **日期**: 2026-09-08 18:03
> **触发**: 业务方 (mkq) 反馈 `/ddl_sync/pair/1/` 同步表清单 tab 显示"仅显示前 200 张, 完整列表请用一键配刷新后查看", 库对 #1 (hly_accesscard) 有 606 张表, 200+ 部分看不到
> **根因**: 134 dev / 110 prod 之前 `pair_detail` view 写死 `tables = pair.tables.all()[:200]`, 同步历史 tab 已经有分页 (D33), 但同步表清单 tab 没分页

## 实战踩坑 (D36 实战新发现)

D33 同步历史 tab 加分页 + Excel 导出, 同步表清单 tab 当时没动. 业务方 9/8 17:14 实战反馈 + 9/8 18:03 二次反馈"看不全表" (606 张).

## 修法 (9/8 18:20 实战完成)

### 1. View 改 (134 dev → 110 prod 一致)

`sql/extensions/ddl_sync/views/__init__.py:96-99` 从写死 200 改成 Paginator:
```python
# 同步表清单 tab - 同步表清单加分页 + 行数选择
TABLES_PER_PAGE_CHOICES = [50, 100, 200]
tables_per_page_param = request.GET.get("tables_per_page", 50)
try:
    tables_per_page = int(tables_per_page_param)
    if tables_per_page not in TABLES_PER_PAGE_CHOICES:
        tables_per_page = 50
except (ValueError, TypeError):
    tables_per_page = 50
tables_qs = pair.tables.all().order_by("sync_type", "table_name")
table_count = tables_qs.count()
tables_paginator = Paginator(tables_qs, tables_per_page)
tables_page_num = request.GET.get("tables_page", 1)
try:
    tables_page_obj = tables_paginator.get_page(tables_page_num)
except Exception:
    tables_page_obj = tables_paginator.get_page(1)
tables = tables_page_obj.object_list
```

context 加: `tables_paginator`, `tables_page_obj`, `tables_per_page`, `tables_per_page_choices`.

### 2. Template 改 (134 dev → 110 prod 一致)

`sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html:168-209`:

- **h5** 改: `同步表清单 (前 {{ tables|length }} 张)` → `同步表清单 (共 {{ table_count }} 张{% if paginator.num_pages > 1 %}, 第 {{ page_obj.number }}/{{ paginator.num_pages }} 页{% endif %})`
- **工具栏** 加行数选择下拉 (在搜索 + 类型筛选同一行, `margin-left: auto` 推到右侧):
  ```html
  <span style="margin-left: auto; ...">
    <span>每页</span>
    <select id="tables-per-page" onchange="window.location.href='?tables_page=1&tables_per_page='+this.value+'#tab-tables'">
      {% for n in tables_per_page_choices %}
      <option value="{{ n }}" {% if n == tables_per_page %}selected{% endif %}>{{ n }}</option>
      {% endfor %}
    </select>
    <span>行</span>
  </span>
  ```
- **table 下方** 加分页栏 (跟 D33 同步历史 tab 一致, 用 `ddlsync-page-link` + `ddlsync-page-current` CSS class):
  ```html
  {% if tables_paginator.num_pages > 1 %}
  <div class="ddlsync-pagination">
    {% if tables_page_obj.has_previous %}<a href="?tables_page=...&tables_per_page=...#tab-tables">‹ 上一页</a>{% endif %}
    {% for p in tables_paginator.page_range %}<a class="ddlsync-page-link">...</a>{% endfor %}
    {% if tables_page_obj.has_next %}<a href="?tables_page=...&tables_per_page=...#tab-tables">下一页 ›</a>{% endif %}
  </div>
  {% endif %}
  ```
- **删** line 204-206 `仅显示前 200 张, 完整列表请用「🎯 一键配」刷新后查看` 提示 (因为现在能看到全部 606 张)

## 134 dev 演练 (9/8 18:13 PASS)

造 60 张临时表 + pair #1 原 11 张 = 71 张, 演练 6 种 per_page/page 组合 + 3 种边界 (per_page=300/abc/50.5):

| per_page | total_pages | page2 count | 备注 |
|---|---|---|---|
| 50 | 2 | 21 (71-50) | ✅ |
| 100 | 1 | 自动回 page 1 | ✅ |
| 200 | 1 | 自动回 page 1 | ✅ |
| 300 (不在 choices) | 回退 50 | 21 | ✅ |
| "abc" (非 int) | 回退 50 | 21 | ✅ |
| 50.5 (float) | int() 转 50 | 21 | ✅ |

## 110 prod 演练 (9/8 18:30 PASS)

110 prod pair #1 hly_accesscard 606 张表:

| per_page | total_pages | page1 count | page13 count | 备注 |
|---|---|---|---|---|
| 50 | 13 | 50 | 6 (606-50×12) | ✅ |
| 100 | 7 | 100 | 6 | ✅ |
| 200 | 4 | 200 | 6 | ✅ |

View 跑通: `pair_detail(req, pair_id=1)` 返回 HttpResponse status_code=200 ✅.

## 9/8 18:30 110 prod 状态

- 推 2 文件 (views/__init__.py + pair_detail.html) ✅
- md5 校验 PASS (dev=prod) ✅
- 拉新 gunicorn 6 进程, 9123 LISTEN, /login/ 200 ✅
- pair #1 hly_accesscard 606 张表, Paginator 演练 PASS ✅
- 业务方 mkq has_perm view_ddlsyncpair: True ✅
- 业务方刷新 (Ctrl+Shift+R 硬刷) 即可看到分页 + 行数选择

## 实战脚本

- `scripts/_archive/_d36_drill_pair_detail_pagination.py` (134 dev 演练 v1)
- `scripts/_archive/_d36_drill_v2.py` `v3.py` `v4.py` (134 dev 演练 v2-v4, 改 mkq 业务方 + 修 f-string 错误)
- `scripts/_archive/_d36_drill_v5.py` `v6.py` (134 dev 演练 v5-v6, Paginator 边界 + 60 张临时表)
- `scripts/_archive/_d36_push_pair_pagination.py` (推 110 prod + 演练)
- `scripts/_archive/_d36_verify_prod_v2.py` `v3.py` (110 prod 验证)
- `scripts/_archive/_d36_curl_test.py` (110 prod view 跑通验证)

## 业务方话术 (DBA 发)

> 同步表清单 tab 升级: 每页默认 50 行 (可切换 50/100/200), 共 606 张表能完整查看, 不用一键配刷新了. 业务方刷新 /ddl_sync/pair/1/ 页面 (硬刷 Ctrl+Shift+R) 即可.
