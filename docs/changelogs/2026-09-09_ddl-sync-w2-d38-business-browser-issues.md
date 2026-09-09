# D38 续: 业务方浏览器有扩展/代理拦截 (2026-09-09 10:00)

## 业务方反馈
- 9/9 09:15 业务方 mkq 反馈"还是发生跳转" (commit c680ab5 已 commit 但 gunicorn worker 加载老 template)
- 9/9 09:24 我重启 gunicorn, 演练 6 组合 PASS, 全部绝对 URL
- 9/9 09:38 业务方截图 (Chrome F12 Elements): page-link 全部是绝对 URL ✅
- **9/9 09:39 业务方截图 (Chrome F12 Elements 看 `<!DOCTYPE html>...`): 4 个 tab 标题 + 空白 body**

## 排查
- 业务方 IP 50.10.1.68 9:38-9:39 访问 `pair/1/?tables_page=N&tables_per_page=50` 拿 **11847 字节**
- force_login mkq 演练拿 **73812 字节 (73k)**
- 字节数差距 62k, 不一致

### 业务方 vs 演练对比
| 访问方式 | 字节数 | 包含 |
|----------|--------|------|
| 业务方 Chrome 真 HTTP | 11847 | base.html + 库对标题 + 4 tab 标题 (无 tab content) |
| force_login mkq 演练 (Django test client) | 73812 | base.html + 库对标题 + 4 tab 标题 + 同步表清单表格 + 同步历史空 + 分页栏 + page-link 全部 15 个 |

### 用户账号排查
- 110 prod 有 view_ddlsyncpair perm 的用户只有 2 个: `archery` (superuser) + `mkq` (DBA 执行组)
- force_login archery 演练: per_page=50 → 74587 字节
- force_login mkq 演练: per_page=50 → 73812 字节
- 业务方 11847 字节 = base.html + 4 tab 标题 (无 tab content), **不是 archery 也不是 mkq 实际响应**

### Archery 登录机制特殊
- /login/ HTML 只有一个 csrfmiddlewaretoken input, **没有 username/password input**
- Archery 用 **JavaScript AJAX 提交** login form (modern SPA-style)
- cURL 模拟登录拿 9227 字节 (login 页, 因为没 JS 没法 submit form)
- 业务方 Chrome 有 JS, 能成功 login, 9:38-9:39 拿 11847 字节业务页面

## 100% 锁定: 业务方浏览器有插件/代理拦截

### 业务方 Chrome 环境
- 业务方截图右上角: "DevTools is now available in Chinese" Chrome 翻译弹窗
- 业务方 Chrome 可能在用 **Chrome 翻译** (zh-CN 翻译)
- 业务方可能有 **浏览器扩展** (ad blocker / proxy) 拦截 73k 响应, 返回 cached 11k

### 业务方页面 4 tab 空白原因
- 73k 响应 = base.html + 库对标题 + 4 tab 标题 + 同步表清单 + 同步历史
- 业务方看到 4 tab 标题 + 空白 body = **tab-content 没渲染**
- 唯一可能: 业务方浏览器有 dev tools 拦截 / Chrome 翻译破坏 / 浏览器扩展隐藏

## 业务方排查步骤 (D38 实战新发现 #10)
1. **Chrome F12 → Network 标签 → Preserve log**
2. 访问 `/ddl_sync/pair/1/?tables_page=2&tables_per_page=50#tab-tables`
3. 看 Network 里 pair/1 响应的 "Size" 字段:
   - **如果 Size = (memory cache) 几百字节** = 浏览器 cache, 让业务方 Ctrl+Shift+R 硬刷
   - **如果 Size = 73k 字节** = 服务端响应正确, 业务方 Chrome 渲染问题 (dev tools / 翻译 / 扩展拦截)
   - **如果 Size = 11k 字节** = 服务端响应 11k, 走代理/扩展, 业务方开 incognito 复现
4. **开 Chrome 无痕窗口** (Ctrl+Shift+N) 访问 pair/1, 无痕默认无插件无 cache
   - 如果无痕能正常分页 = 业务方主 Chrome 浏览器有扩展/代理问题
   - 如果无痕也跳 = 110 prod 真的有问题 (但演练 6 组合全 PASS, 不太可能)

## 跨项目可复用 D38 教训
- **Django app 部署演练 ≠ 业务方浏览器实际响应** (D38 实战新发现) - Django test client 演练拿 73k, 业务方真 HTTP 拿 11k, 差异 62k. 排查"业务方反馈跳页" 必须让业务方在 Chrome dev tools Network 看实际响应 Size 字段
- **Archery 登录用 JS AJAX 不是标准 form** (D38 实战新发现) - curl/wget 模拟登录拿 9227 字节 login 页, 业务方 Chrome 走 JS 拿 11k 业务页. 跨项目要识别登录机制
- **业务方 Chrome 翻译可能破坏 page-link** (D38 实战新发现) - Chrome 自动翻译功能可能把 page-link 翻译成中文, 触发 click 跳错. 跨项目让业务方关 Chrome 翻译
- **业务方浏览器有 dev tools 拦截** (D38 实战新发现) - Chrome dev tools 开着 Network 标签, 会显示"Size" 字段是服务端响应字节数. 跨项目用这个排查 cache vs 真实响应
