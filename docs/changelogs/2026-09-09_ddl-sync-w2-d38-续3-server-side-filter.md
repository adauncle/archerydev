# D38 续 3: 同步表清单加 server-side 黑白名单筛选 + 搜索 (2026-09-09 12:40)

## 业务方反馈
- 9/9 12:22 业务方 mkq 反馈"再看看黑白名单筛选问题"
- 业务方截图: 选了"白名单"下拉, 表格 body 空白 (因为 hly_accesscard 是黑名单默认模式, 606 张表全黑名单, 没白名单)
- 老 client-side JS filter (pair_detail.js:78-95) 不持久化 / 分页不感知 / 不能分享链接

## 修法: server-side filter (D38 续 3 实战新发现)
- view 读 `request.GET.get('sync_type')` 和 `request.GET.get('search')`
- sync_type 合法值: 'whitelist' / 'blacklist' / '' (全部)
- search 走 `table_name__icontains`
- 分页按过滤后数量 (e.g. blacklist 167 张 → 4 页, 不是 13 页)
- 工具栏用 form GET 提交, onchange 自动 submit
- 分页链接 + 切每页都保留 sync_type + search query
- 删 client-side JS filter (改成空函数兼容 init() 调用)

## 改动 3 个文件
1. `sql/extensions/ddl_sync/views/__init__.py` (line 91-120 + 138-140) - 加 sync_type_filter + search_filter 逻辑
2. `sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` (line 170-186 + 214-228) - form GET + sync_type/search 保留
3. `sql/extensions/ddl_sync/static/ddl_sync/pair_detail.js` (line 77-79) - 删 client-side filter, 留空函数

## 演练 PASS (force_login mkq + archery, 18 组合, 12:40)
| 场景 | 结果 |
|------|------|
| 默认 | 606 张 / 13 页 ✅ |
| `?sync_type=whitelist` | 439 张 / 9 页 ✅ |
| `?sync_type=blacklist` | 167 张 / 4 页 ✅ |
| `?sync_type=` 空 | 606 张 ✅ |
| `?sync_type=invalid` | 606 张 (invalid fallback) ✅ |
| `?sync_type=blacklist&tables_page=2&tables_per_page=50` | 50 行 (page 2/4) ✅ |
| `?sync_type=blacklist&tables_page=13&tables_per_page=50` | 17 行 (page 4/4 末页) ✅ |
| `?search=billing` | 64 张 / 2 页 ✅ |
| `?search=accesscard&sync_type=blacklist` | 85 张 / 2 页 ✅ |
| `?search=NOTEXIST12345XYZ` | 0 张 (无 page-link, 正确空状态) ✅ |
| `?search=&sync_type=blacklist` | 167 张 ✅ |
| `?sync_type=blacklist&tables_per_page=200` | 167 张 (1 页, tr=167) ✅ |
| `?sync_type=blacklist&search=access&tables_per_page=100` | 黑名单 + 搜 access = 85 张 ✅ |
| `?sync_type=blacklist&search=billing&tables_page=1&tables_per_page=50` | 复合 filter ✅ |
| onchange 全部 `this.form.submit()` | server-side ✅ |
| page-link 全部含 `sync_type`/`search` | 切页保留 filter ✅ |

## 真 HTTP 演练 PASS (业务方已知密码 mkq123, 12:42)
- `?sync_type=whitelist&tables_per_page=50` → 76340 字节, 50 行 tr, 11 个 page-link
- `?sync_type=blacklist&tables_per_page=50` → 75829 字节, 50 行 tr, 6 个 page-link
- `?search=billing&sync_type=blacklist` → 64220 字节, 27 行 tr, 2 个 page-link
- `?search=accesscard&sync_type=blacklist&tables_page=2&tables_per_page=50` → 69012 字节, 35 行 tr, 4 个 page-link

## 110 prod 部署
- 3 文件 scp 推 110 prod (md5: view `1c9f08af...f083` + tpl `92790673...13ca` + js `5eb0e447...a97a`)
- 3 文件 scp 推 134 dev (md5 一致)
- 110 prod gunicorn pkill + setsid nohup 重启 (PID 30918 master + 30924/30930/5 workers, 9/9 12:37)
- 134 dev gunicorn 不重启 (DEBUG=True Django 每次请求重读 template + view 通过 reload 触发)

## D38 续 3 实战新发现 (跨项目可复用)
1. **client-side filter 不持久化, 用 server-side filter** (D38 续 3 实战新发现) - JS row.style.display='none' 客户端 filter 不能分享链接 / 刷新丢 / 分页不感知. 跨项目做筛选/搜索功能必须 server-side (URL query + view 过滤)
2. **Django form GET 提交 + onchange 自动 submit** (D38 续 3 实战新发现) - 工具栏 select/ input 用 `<form method="get" action="{% url %}">` 包, onchange="this.form.submit()". URL 持久化, 浏览器后退/分享链接都正常
3. **Paginator 按过滤后数量分页** (D38 续 3 实战新发现) - view 过滤后 Paginator 自动按过滤后数量算 num_pages. e.g. 606 张 filter 后 167 张 → 4 页. 跨项目要测试边界 (过滤后 0 张 / 1 张 / 超大数)
4. **演练必须先推代码再演练** (D38 续 3 实战新发现) - 我之前在 Windows 本地改完 view, 演练 18 组合都显示 606 张, 因为 110 prod view 文件没改. 推完代码 + 重启 gunicorn + 再演练才能看到真效果

## D38 续 3 实战踩坑
- **PowerShell `$` 变量替换** (D38 续 3 实战踩坑) - Python format string `%s` 跟 bash `$(date)` 冲突, 用字符串拼接 + `+ REMOTE` 代替
- **Django test client force_login 走 110 prod wsgi_handler** (D38 续 3 实战踩坑) - force_login 在 110 prod venv 跑, 读 110 prod view 文件. Windows 本地改完演练看到 606 张 (因为 110 prod 还是老 view)

## 业务方下一步
- 业务方 mkq/archery 访问 `?sync_type=whitelist&tables_per_page=50` 应该看到 439 张 / 9 页
- 业务方访问 `?search=billing&sync_type=blacklist` 应该看到 27 张 (黑名单 billing*)
- 业务方访问 `?search=NOTEXIST12345XYZ` 应该看到 0 张 (无 page-link)
- 业务方访问分页链接, URL 保留 sync_type + search
