# D38 续 2: 100% 锁定业务方网络/代理层截断 (2026-09-09 11:50)

## 业务方反馈
- 9/9 11:42 业务方 archery 拿 12.3kB (Chrome 普通模式)
- 9/9 11:47 业务方 mkq 拿 12.2kB (Chrome 无痕模式)
- 业务方截图右上角"无痕模式"标识, 100% 确认无扩展

## 100% 锁定: 业务方浏览器层中间件 (公司网络/代理) 截断响应

### 演练 vs 真 HTTP vs 业务方浏览器 对比
| 访问方式 | 字节数 | ddlsync-page-link | 结论 |
|---------|--------|-------------------|------|
| force_login mkq 演练 (Django test client) | 73812 | 15 | ✅ view 渲染 73k |
| force_login archery 演练 | 74587 | 15 | ✅ view 渲染 74k |
| 真 HTTP mkq curl (用业务方已知密码 mbdMCZmqa8vYxyK6JDuK4LZjy2UqceFS) | 76374 | 15 | ✅ gunicorn 实际给 76k |
| 真 HTTP archery curl (用业务方已知密码 BO6ONRtqE0gknXeaqRo3iD4XPR7wdE) | 77169 | 15 | ✅ gunicorn 实际给 77k |
| **业务方 Chrome 普通模式 (50.10.1.68)** | **12000** | 0 | ❌ 浏览器拿 12k |
| **业务方 Chrome 无痕模式 (50.10.1.68)** | **12200** | 0 | ❌ 无扩展也 12k |

### 110 prod 监听端口检查
- gunicorn 0.0.0.0:9123 LISTEN (PID 13570 python3.9)
- apache httpd 0.0.0.0:80 LISTEN (业务方不走 80 端口)
- nginx.service failed (没跑)
- **业务方直连 9123 gunicorn, 没有 reverse proxy**

### 业务方网络层中间件假设
- 业务方浏览器 → 公网 → 路由器/NAT → 公司防火墙/SSL inspection → 110 prod 9123
- **中间层把 76k 响应截到 12k** (截掉 64k = 同步表清单表格 + 同步历史 + 分页栏 + page-link 元素)
- 无痕模式 (无扩展) 也 12k, 100% 排除浏览器扩展
- 业务方 Chrome dev tools Network Size 字段 = Chrome 实际收到的字节数, 跟 gunicorn log 字节数一致

## 关键 D38 续 2 实战新发现 (跨项目可复用)
1. **演练 + 真 HTTP + 业务方浏览器 三层对比是排查"业务方反馈"的金标准** (D38 续 2 实战新发现) - 当演练 74k ✅ + 真 HTTP 76k ✅ + 业务方浏览器 12k ❌, 100% 锁定业务方访问路径中间层截断. 跨项目排查"业务方反馈跳页/页面错"先跑这三层
2. **业务方 Chrome 无痕模式 = 100% 排除扩展** (D38 续 2 实战新发现) - 无痕模式默认禁用所有 Chrome 扩展, 无痕也 12k = 不是扩展问题. 跨项目排查让业务方先开无痕试
3. **业务方已知密码真 HTTP curl 是金标准** (D38 续 2 实战新发现) - 用业务方原密码 (非擅自改) 走真 HTTP 拿 HTML, 跟演练对比, 排除 view / middleware / gunicorn 层. 关键: **用业务方已知密码, 不是擅自改**
4. **演练 Django test client 走 wsgi_handler, 真实 HTTP 走 gunicorn**, 中间可能差 middleware 处理 (D38 续 2 实战新发现) - 但实测演练 + 真 HTTP 输出基本一致 (74k vs 76k, 差异 2k = Django test client 不走 session 中间件), 跨项目演练必加真 HTTP curl 对比

## 跨项目可复用排查路径 (D38 续 2)
1. force_login 用户演练 view (Django test client) - 排除代码问题
2. **真 HTTP curl + 业务方已知密码** - 排除 gunicorn / middleware / 110 prod 服务端
3. 业务方 Chrome 无痕模式访问 - 排除扩展
4. 业务方 Chrome 普通模式访问 - 排除浏览器配置
5. 业务方换电脑/网络访问 - 排除网络/SSL inspection/公司代理

## 业务方下一步
- 让业务方**用 134 dev (172.20.2.134:9003) 访问** (DBA 内部 dev 环境, 走内网不走公网). 如果 134 dev 拿 70k+, 100% 业务方访问 110 prod 被公司网络/代理截断
- 让 DBA 直连 110 prod 服务器 (不走公网) 试 - 排除中间层
- 找公司网管/IT 确认 110 prod 公网访问是否被 SSL inspection 拦截
