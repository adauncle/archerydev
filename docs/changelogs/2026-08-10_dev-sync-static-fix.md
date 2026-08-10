# 134 dev 部署同步漏 `common/static/` 修复

**日期**: 2026-08-10
**作者**: mavis
**类型**: chore（部署修复，非代码改动）
**影响范围**: 172.20.2.134 DEV（`/opt/archery/prod/`）

## 背景

DBA 用浏览器点 `http://172.20.2.134:9003/admin/login/` 验证登录页时，页面**完全裸 HTML** —— 所有 CSS/JS 404，控制台一片红。截图见 message index 1（17:04）。

## 症状

```
Cross-Origin-Opener-Policy header has been ignored, because the URL's origin was untrustworthy
login/:1 Refused to apply style from 'http://172.20.2.134:9003/login/' because its MIME type ('text/html') is not a supported stylesheet MIME type
login/:1 Refused to execute script from 'http://172.20.2.134:9003/login/' because its MIME type ('text/html') is not executable
login/:123 Uncaught ReferenceError: $ is not defined
```

## 排查过程

### 1. 看 gunicorn / nginx

```
archery-prod-gunicorn.service:  active, pid 14426 (4 workers @ 0.0.0.0:9003)
nginx.service:                  disabled
```

**没有 nginx 反代**。`STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"` + `WhiteNoiseMiddleware` 在 SessionMiddleware 之前 —— 期望 gunicorn 自身通过 whitenoise serve static。

### 2. 看 static 目录

```
$ ls /opt/archery/prod/static/
admin
rest_framework
$ ls /opt/archery/prod/common/static/
ls: cannot access ... : No such file or directory
```

**`common/static/` 整个目录在 134 dev 上不存在**！collectstatic 只收齐 admin + rest_framework（来自 venv site-packages），archery 自定义那 22 子目录 / 118 文件全空。

### 3. 对比 upstream

```
$ ls /opt/archery_upstream/common/static/
ace  bootstrap  bootstrap-editable  bootstrap-fileinput  bootstrap-select
bootstrap-switch  bootstrap-table  daterangepicker  datetimepicker  dbdiagnostic
dist  echarts  font-awesome  img  jquery  metisMenu  notice  sb-admin-2
sql-formatter  watermark
$ find /opt/archery_upstream/common/static -type f | wc -l
118
```

**结论**：134 dev sync 脚本历史漏了 `common/static/` 整个目录（22 子目录 / 118 文件全没过来）。

### 4. 为什么之前没发现

- 7/27 起 gunicorn 一直在跑（pid 35516 长期存活）
- 所有 v0.3.0 + v0.4.5-alpha 演练都走 **Django RequestFactory + force_login** 绕过浏览器（pytest test infrastructure limitation 已知）
- 没人真去浏览器点过登录页

## 修复步骤

```bash
cd /opt/archery/prod
# 1. 从 upstream 复制
cp -r /opt/archery_upstream/common/static /opt/archery/prod/common/
# 2. 权限
chown -R archery:archery /opt/archery/prod/common/static
chown -R archery:archery /opt/archery/prod/static
# 3. 重新 collectstatic
source venv/bin/activate
python manage.py collectstatic --noinput
# → 118 new files copied, 154 unmodified
# 4. 重启 gunicorn
systemctl restart archery-prod-gunicorn
```

## 修复后验证

| 资源 | HTTP | 大小 | MIME |
|------|------|------|------|
| `/static/dist/css/login.css` | 200 | 524 B | text/css |
| `/static/bootstrap/css/bootstrap.min.css` | 200 | 121457 B | text/css |
| `/static/jquery/jquery.min.js` | 200 | 86927 B | text/javascript |
| `/static/admin/css/base.css` | 200 | 22120 B | text/css |
| `/login/` 整页 | 200 | 9227 B | text/html |

DBA 浏览器**强刷**（Ctrl+Shift+R）后登录页正常渲染。

## 教训 & 后续

### 1. sync 脚本必须显式包含 `common/static/`

之前用 tarball 同步（os.walk + relpath + tarfile 打包），可能加了 `__pycache__/*.pyc` / `.env` / `media/` 排除，但 `static/` 不该被排除。

**动作**：检查 `scripts/pack_v045.py` / 后续打包脚本，确认 `common/static/` 在打包范围内。

### 2. dev 部署应该有"基础环境冒烟测试"

当前 7/27 起 gunicorn "active" 状态其实掩盖了 static 全空的事 —— `systemctl is-active` 只看主进程，循环重启时只看主进程会一直 active。

**建议**（v0.x.x 收尾阶段补）：
- 加一个 `scripts/smoke_dev.sh`，每次 sync 完跑：
  ```bash
  curl -fsS http://127.0.0.1:9003/login/ -o /dev/null
  curl -fsS http://127.0.0.1:9003/static/bootstrap/css/bootstrap.min.css -o /dev/null
  curl -fsS http://127.0.0.1:9003/admin/login/ -o /dev/null
  ```
  任何 404 立即 fail。

### 3. 110 PROD 影响评估（已验证，✅ 没问题）

| 检查项 | 110 prod 状态 |
|--------|---------------|
| 部署目录 | `/dbdata/archery_v114_c9236a0/` |
| `common/static/` | ✅ **22 子目录齐全**（ace / admin / bootstrap / dist / jquery / ...） |
| `static/` 根目录 | ✅ 22 子目录（collectstatic 跑过） |
| 反代 | ✅ httpd (Apache) @ 0.0.0.0:80 |
| gunicorn | pid 102228 (4 workers @ 0.0.0.0:9123) |
| 浏览器渲染 | ✅ web_fetch `/login/` 拿到完整 HTML（CSRF / form / JS） |

**结论**：110 prod **没有同样问题**。差异点：
- 110 prod 当时走"完整 git clone"路径（v0.2.0 + 6 MR patch → `c9236a0`），`common/static/` 跟着代码一起过来了
- 110 prod 有 Apache httpd 在 80 端口（serve static + 可能的反代）
- 110 prod 7/27 起一直用浏览器能正常访问，**反过来印证**：如果 110 也缺 static，7/27 上线后就会被发现，不会藏到今天

**推 v0.3.0 到 110 时注意事项**（新增）：
- 新 tarball 打包脚本必须**显式包含 `common/static/`**（教训 #1）
- 推完后跑冒烟测试（教训 #2），确认 4 个 URL 200 才能切流量

### 4. 残留 console 噪音（无害）

修复后浏览器仍可能输出：
- `Cross-Origin-Opener-Policy header has been ignored` — 因为 `http://172.20.2.134` 不是 trustworthy origin（要 https 或 localhost），COOP 被浏览器忽略，**不影响登录**
- `sql-formatter 重复文件` 3 个 warning — 上游 archery 已知问题（`settings.py` 注释里写过：`# 上游用的是 ForgivingManifestStaticFilesStorage，但里面 sql-formatter 等文件有重复`），manifest 模式会忽略次出现的，**不影响功能**

## 相关 commit

无 commit（134 dev 是部署目录，**非 git 仓库**；本次修复仅在 134 dev 落地 + 文档记录）。
