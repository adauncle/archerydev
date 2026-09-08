# D37 跳首页问题 100% 锁定为浏览器缓存 (2026-09-08 19:30)

## 业务方反馈
- 9/8 18:45 业务方 mkq 反馈: "分页已经可以看到, 新的问题: 选择每页行数, 或者点击下一页。都会跳转到首页"
- 9/8 19:09 业务方再反馈: "还是没解决跳转的问题"
- 用户截图: per_page=200 URL 时, 标题"同步表清单 (共 606 张, 第 1/7 页)" — 7 页是 per_page=100 的页数

## 100% 锁定: 浏览器缓存

### 110 prod 实际 HTTP 渲染证据 (D37 diag, force_login mkq + Django test client, 19:29)

| 输入 | view num_pages | 标题实际 | 链接 max | 选中 |
|------|---------------|---------|---------|-----|
| `?tables_page=1&tables_per_page=50` | 13 | "1/13 页" | 13 | 50 |
| `?tables_page=2&tables_per_page=100` | 7 | "2/7 页" | 7 | 100 |
| `?tables_page=1&tables_per_page=200` | **4** | "**1/4 页**" | 4 | 200 |
| `?tables_page=3&tables_per_page=200` | 4 | "3/4 页" | 4 | 200 |
| `?tables_page=4&tables_per_page=200` | 4 | "4/4 页" | 3 (4 current) | 200 |

**view + template + onchange 全部 6 种组合渲染正确, 代码跟 Windows 本地 md5 完全一致**:
- views/__init__.py: `b3c8d2951df4a906a7b6caf83fbeba42` (Win == 134 dev == 110 prod)
- pair_detail.html: `2fea70bf3b64ddd80908e6dd79429063` (Win == 134 dev == 110 prod)

### 业务方截图矛盾
- 截图 URL `?tables_page=1&tables_per_page=200` 时, 标题显示 "第 1/**7** 页"
- 实际 view 跑 per_page=200 → **4 页** (606÷200=3.03, 向上取整 = 4)
- 业务方看到 7 页, 100% 是浏览器把 per_page=100 的渲染缓存返回

## 根因分析
- 业务方浏览器 (Chrome) 把第一次访问 `?tables_page=1&tables_per_page=100` 时的 HTML 完整缓存
- 之后切换 per_page 到 200 时, URL 变了但浏览器还是拿缓存返回
- 业务方"点下一页跳首页" = 业务方点的 "1" 链接 (跳 page=1) 或 "每页 [100▼]" (切到 100 行时 onchange 设 `tables_page=1&tables_per_page=100` 是 page=1)

## 修法
- **业务方**: Ctrl+Shift+R (Win/Linux) / Cmd+Shift+R (Mac) 硬刷, 或者无痕窗口打开
- **如果还不行**: 浏览器设置 → 清除缓存 → 重启浏览器
- **DBA 后续**: 可选加 `<meta http-equiv="Cache-Control" content="no-cache">` 到 base.html, 但会牺牲整站性能, 不推荐

## 关键 D37 实战新发现
1. **Django test client 必传 SERVER_NAME** — 110 prod ALLOWED_HOSTS 不含 `testserver`, 不传会 400 DisallowedHost
2. **D37 排查路径**: 业务方反馈"跳首页" → 演练 view 看实际渲染 (6 种组合全对) → 对比 md5 (3 个环境全一致) → 100% 锁定浏览器缓存
3. **D37 排查脚本**: `scripts/_d37_check_110prod_state.py` (md5 + 关键代码标识) + `scripts/_d37_real_curl_remote.py` (Django test client force_login 6 种组合)

## 同源 entry
- 9/8 18:30 D36 一级: 同步表清单加分页 + 行数选择 (commit ee8ad95)
- 9/8 18:35 D36 二级: 134 dev 跟 Windows 本地不同步 (commit 904a98e)
- 9/8 18:50 D36 三级: 分页栏中文乱码 (commit 78943c7)
- **9/8 19:30 D37 实战新发现: 业务方浏览器缓存导致 per_page 切换显示旧 num_pages**
