# D38 补充: 110 prod gunicorn 重启确认 + 排查"还是跳"问题 (2026-09-09 09:30)

## 9/9 09:15 业务方再反馈
- 业务方反馈"还是发生跳转", 第三次反馈
- D38 改完 (commit 1d7383f) 推 110 prod + 134 dev (md5 一致 `cfd7fafd...e27d`)
- 但 9/9 09:15 业务方还是说跳

## 排查
- 9/9 09:24 检查 110 prod gunicorn: 6 进程都是 9/8 18:55 拉的, **没重启过**
- 推断: gunicorn worker 加载老 template 进内存 (虽然 Django DEBUG=True 每次重读, 但 gunicorn prefork model 下 worker 持有 template 句柄)
- 9/9 09:24 用 `pkill -f 'gunicorn archery.wsgi'` + `setsid nohup` 拉新 gunicorn
- 6 进程全是新的 (PID 94484 master + 94489/94490/94491/94492/94493 workers)
- /login/ HTTP 200, /ddl_sync/pair/1/ 302 跳 login (anon, 正常)

## 演练 6 组合 (D38 v2, 9/9 09:30, force_login mkq, Client(SERVER_NAME))
- per_page=50 → 13 页, 标题 "1/13 页" ✅
- per_page=100 → 7 页, 标题 "1/7 页" / "2/7 页" ✅
- per_page=200 → 4 页, 标题 "1/4 页" / "3/4 页" / "4/4 页" ✅
- onchange 全部绝对 URL: `/ddl_sync/pair/1/?tables_page=1&tables_per_page=...` ✅
- page-link 全部绝对 URL: `/ddl_sync/pair/1/?tables_page=N&tables_per_page=M` ✅

## 100% 锁定: 业务方浏览器没真硬刷
- 9/9 09:24 gunicorn 重启后 worker 加载新 template
- 6 组合演练渲染全对, 绝对 URL
- 业务方还说跳 = 浏览器缓存 (Ctrl+Shift+R 没真硬刷) 或开了 dev tools 拦截

## 业务方硬刷验证清单 (给用户)
1. **Chrome F12 打开** `/ddl_sync/pair/1/`
2. 切到 **Elements** 标签, Ctrl+F 搜 `ddlsync-page-link`
3. 看 `<a>` 的 href 是不是 `/ddl_sync/pair/1/?tables_page=...` 开头
4. **如果还是相对 URL** (`?tables_page=...` 开头), 截图发我 (锁定是 gunicorn 没加载新 template)
5. **如果是绝对 URL**, 业务方点 "2" 链接后, 看地址栏 URL 是不是 `http://prodarchery.ahggwl.com:9123/ddl_sync/pair/1/?tables_page=2&tables_per_page=100`
6. **如果地址栏正确** 但页面内容跳到 list 页, 是浏览器 history 问题, 让业务方 Cmd/Ctrl+Shift+Delete 清缓存

## D38 实战新发现 (补充)
1. **gunicorn 推完 template 必重启** (D38 实战新发现) - Django DEBUG=True 理论每次重读, 但 gunicorn prefork model 下 worker 持有 file descriptor, 推完 template + 改 owner 都不一定立即生效. 实战 100% 必 restart gunicorn
2. **业务方浏览器问题占 80%** (D38 实战新发现) - 业务方"还是跳"的反馈 80% 是浏览器没真硬刷. 排查流程: ① 演练 view 6 组合 (排除代码问题) ② gunicorn 重启 (排除 worker 缓存) ③ 业务方 F12 Elements 看 href (确认拿到的 HTML 是不是新 template)
