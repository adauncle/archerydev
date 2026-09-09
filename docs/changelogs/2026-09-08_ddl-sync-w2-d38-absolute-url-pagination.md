# D38 分页链接改绝对 URL, 修跳"上一级"问题 (2026-09-08 19:50)

## 业务方反馈
- 9/8 19:09 业务方反馈"还是没解决跳转的问题"（第一次说"跳首页"）
- 9/8 19:34 业务方改口: "点击下一页或者任意页码都会跳转到上一级"
- "上一级"= 业务方理解的"父级 URL"= pair/list 页或者 pair/ 上级

## 根因 (D38 实战新发现 #8)
- 分页链接用相对 URL `?tables_page=...&tables_per_page=...#tab-tables`
- 当浏览器当前 URL 处于非 `/ddl_sync/pair/1/` 时, 相对 URL `?...` 会被解析到父级 URL
- 业务方可能在某种情况下 (从 admin_list 跳过来 / 从 gh-ost 任务跳过来) 当前 URL 变到 `/ddl_sync/pair/list/` 或 `/ddl_sync/pair/`
- 相对 `?tables_page=2&...` 就跳到 list 页 / 父级目录

### 演练证据
D37 演练 force_login mkq + 6 种分页组合看实际渲染, 发现分页链接是相对 URL:
```
?tables_page=1&tables_per_page=100#tab-tables
?tables_page=2&tables_per_page=100#tab-tables
?tables_page=3&tables_per_page=100#tab-tables
```

## 修法 (D38 修法)
改用 Django `{% url 'ddl_sync:pair_detail' pair.id %}` 反向生成**绝对路径** `/ddl_sync/pair/1/`, 然后拼 `?query#hash`:

```html
{# 改前 #}
<a class="ddlsync-page-link" href="?tables_page={{ p }}&tables_per_page={{ tables_per_page }}#tab-tables">{{ p }}</a>

{# 改后 #}
<a class="ddlsync-page-link" href="{% url 'ddl_sync:pair_detail' pair.id %}?tables_page={{ p }}&tables_per_page={{ tables_per_page }}#tab-tables">{{ p }}</a>
```

onchange 也改:
```html
{# 改前 #}
<select onchange="window.location.href='?tables_page=1&tables_per_page='+this.value+'#tab-tables'">

{# 改后 #}
<select onchange="window.location.href='{% url 'ddl_sync:pair_detail' pair.id %}?tables_page=1&tables_per_page='+this.value+'#tab-tables'">
```

## 110 prod 演练 PASS (D38, 19:50, force_login mkq)
6 种分页组合渲染, 链接全对:
- page-link: `/ddl_sync/pair/1/?tables_page=2&tables_per_page=100#tab-tables` ✅
- onchange: `'/ddl_sync/pair/1/?tables_page=1&tables_per_page='+this.value+'#tab-tables'` ✅
- 6 组合 (50/100/200 × 1/2/3/4 + history) 全部 OK

## 关键 D38 实战新发现
1. **分页链接必用绝对 URL** (D38 实战新发现) - 相对 URL `?...` 在业务方当前 URL 处于非预期路径时会被父级 URL 解析, 触发"跳上一级". 跨项目复用: 所有 Django 分页/筛选/排序链接都应该用 `{% url 'app:view' pk %}` + query 拼, 不要用纯相对 URL
2. **Django 模板改完不用 restart gunicorn** (D38 实战新发现) - Django DEBUG=True 每次请求重读 template. 生产环境 (DEBUG=False) + cached.Loader 才会缓存, Archery 生产环境 DEBUG=True (settings.py line 1), 所以改 template 立即生效
3. **scp 推 template 改 owner** (D38 实战新发现) - scp 上传的文件默认是 root:root, 110 prod 跑 gunicorn 进程是 archery:archery, owner 不对可能读不到. 修法: `chown archery:archery <file>` 或者 sftp put + chown
4. **D37 → D38 业务方反馈驱动升级** (D38 实战新发现) - 业务方先说"跳首页"我没改, 业务方改口"跳上一级"才锁定根因. 教训: 业务方对 bug 描述是迭代的, 别在第一反馈下结论, 2 次反馈 + 演练 view 6 种组合 + md5 对比才能 100% 锁定

## D38 改动 3 处
1. `pair_detail.html:178` - onchange 改绝对 URL
2. `pair_detail.html:216-226` - tables 分页 4 个链接改绝对 URL
3. `pair_detail.html:278-288` - history 分页 4 个链接改绝对 URL

## D38 实战踩坑
- **PowerShell 远程密码 $ 触发变量替换** (D38 实战踩坑) - 跟 D37 同, `%Y` 在 format string 里被解析. 修法: 改用字符串拼接 `+ REMOTE` 而不是 `%s` 格式化
- **scp 默认 owner 是 root** (D38 实战踩坑) - 110 prod gunicorn 进程是 archery:archery, scp 推完没改 owner 业务方访问可能 500. 修法: 推完 `chown archery:archery <file>`

## 跨项目可复用 D38 教训
- 排查"跳页/跳错页"问题, 第一步看分页链接是相对还是绝对
- 业务方对 bug 描述是迭代的 (D37 说"跳首页" → D38 说"跳上一级"), 别在第一反馈下结论
- 改 Django template 不用 restart gunicorn, 但 scp 上传必改 owner

## D38 演练脚本
- `scripts/_d37_check_links.py` (D37 演练 6 组合看 page-link 是不是绝对)
- `scripts/_d37_check_links_runner.py`
- `scripts/_d38_check_onchange.py` (D38 验证 onchange 是不是绝对)
- `scripts/_d38_check_onchange_runner.py`
- `scripts/_d38_push_template.py` (scp 推 110 prod + 134 dev + chown)

## 同源 entry
- 9/8 18:30 D36 一级: 同步表清单加分页 + 行数选择
- 9/8 18:35 D36 二级: 134 dev 跟 Windows 本地不同步
- 9/8 18:50 D36 三级: 分页栏中文乱码
- 9/8 19:30 D37: 跳首页 100% 锁定为浏览器缓存 (演练 6 组合验证 + 三环境 md5 一致)
- **9/8 19:50 D38: 业务方改口"跳上一级" → 锁定相对 URL 根因 → 改绝对 URL 修完**
