# 2026-08-25 134 dev 演练后 2 个新 bug 修复

> **触发时间**: 2026-08-25 11:30 (演练完成后 30 分钟内)
> **触发人**: 阿达叔叔 (业务 RD 浏览器验证 /sqlworkflow/ + 测"启动 gh-ost")
> **修复时间**: 2026-08-25 11:37
> **影响**: 134 dev 业务 RD 之前一直在用残废页面 + gh-ost 启动不了 (演练漏检查)

---

## Bug 1: 134 dev `static/dist/` 目录完全缺失

### 症状
- `/sqlworkflow/` 页面 JS 404 (`/static/dist/js/formatter.js` + `utils.js`)
- `/login/` 页面 CSS 404 (浏览器报 "Refused to apply style from /login/")
- 业务 RD 之前在 134 dev 用 `/sqlworkflow/` 应该一直是列表渲染不出来的状态, 但没人反馈

### 根因
- 134 dev `static/dist/` 目录**从来就不存在** (git clone 时 .gitignore 排除 `static/dist`, 没人 build 过前端)
- 5 端点验证 (`verify_5endpoints_110prod.sh`) 只测 HTTP 200 状态, 没看 HTML 里 CSS/JS 引用是否 404
- 演练时这个 bug **被漏掉** (curl /login/ 返 200 但 HTML 框架 OK, CSS 引用 404 没被发现)

### 修法
- 从 110 prod scp 12 个 dist 文件到 134 dev:
  - `/opt/archery/prod/static/dist/css/login.css` (+ .gz)
  - `/opt/archery/prod/static/dist/js/formatter.js` (+ .gz)
  - `/opt/archery/prod/static/dist/js/marked.min.js` (+ .gz)
  - `/opt/archery/prod/static/dist/js/utils.js` (+ .gz)
  - `/opt/archery/prod/common/static/dist/css/login.css`
  - `/opt/archery/prod/common/static/dist/js/formatter.js`
  - `/opt/archery/prod/common/static/dist/js/marked.min.js`
  - `/opt/archery/prod/common/static/dist/js/utils.js`
- chown archery:archery + chmod 755

### 8/25 教训 (跨项目可复用, 重要)
1. **演练 5 端点验证漏了前端 static 资源** — 只测 HTTP 200, 没看 HTML 里 CSS/JS 引用
2. **git clone + .gitignore 排除 `static/dist` 是个坑** — 业务环境必须 build 前端
3. **演练前必看 HTML 内容** (不只是 HTTP 状态)
4. **新增 `check_frontend_static.sh`** 脚本, 验证 dist 目录完整性 + curl 200 + MIME type (commit 9c7d4ee)

### 演练脚本
`scripts/deploy/check_frontend_static.sh`:
- 检查 12 个关键文件存在
- 验证 4 个 URL HTTP 200 (不跳登录)
- 验证 MIME type (防 HTML 当 CSS/JS 错)
- 134 dev 演练: 12/12 文件 + 4/4 URL PASS
- 模拟 dist 缺失: 4/12 FAIL (正确检测 + 修法提示)

---

## Bug 2: 134 dev `/opt/archery/bin/` 目录不存在 (gh-ost symlink 失效)

### 症状
- 业务 RD 在 `/detail/94/` 页面点"启动 gh-ost" 按钮
- 报错: `启动 gh-ost 失败: [Errno 2] No such file or directory: '/usr/local/bin/gh-ost'`
- HTTP 500 (Internal Server Error)
- 预检报告全 PASS (binlog_format=ROW / disk_space / replication_privileges) — 但启动 subprocess 时找不到二进制

### 根因
- `/usr/local/bin/gh-ost` 是 symlink → 指向 `/opt/archery/bin/gh-ost`
- 但 `/opt/archery/bin/` 目录**从来就不存在** (134 dev 上)
- 8/24 推 110 摸底时装的 gh-ost 是 110 prod, **134 dev 实际从来没装过**
- 8/24 演练 summary 写"gh-ost 1.1.10 已装 (8/24 完成)" 是 110 prod 装的, 134 dev 漏装
- 5 步必做脚本 步骤 8 检查 `/opt/archery/bin/gh-ost` 应该 ERR, 但演练时被其他输出盖住了, 没看到

### 修法
- 134 dev 上 `/opt/gh-ost/gh-ost` 真实文件已存在 (18MB, 1.1.10, root:root)
- 但 gunicorn 进程用 archery user 跑, 需要 archery 拥有
- 修法: 走 8/19 套路
  ```bash
  mkdir -p /opt/archery/bin
  cp /opt/gh-ost/gh-ost /opt/archery/bin/gh-ost
  chown archery:archery /opt/archery/bin/gh-ost
  chmod 755 /opt/archery/bin/gh-ost
  # 重新做 symlink (8/19 教训: 装到 /opt/archery/bin/, symlink /usr/local/bin/)
  rm -f /usr/local/bin/gh-ost
  ln -s /opt/archery/bin/gh-ost /usr/local/bin/gh-ost
  ```
- 验证: `sudo -u archery /usr/local/bin/gh-ost --version` → 1.1.10 OK
- 跟 110 prod 状态一致

### 8/25 教训 (跨项目可复用, 重要)
1. **演练 5 端点验证漏了 gh-ost 实际启动** — 只测了 3 个端点 (/login/ + /dbaprinciples/ + /admin/), 没测 /gh_ost/start/
2. **134 dev 之前根本没装过 gh-ost** — 8/24 摸底 summary 写"gh-ost 装好"是 110 prod, 134 dev 漏装
3. **演练时没真演练 gh-ost 启动** — 演练必真跑业务流程, 不能只测 HTTP 状态
4. **演练清单漏了"业务流程演练" 段** — 应该加一个 "业务 RD 浏览器实操" 段, 演练所有核心按钮

### 后续演练清单补全
8/26 134 dev 演练清单 (已在 8/25 提前演练) 应该加:
- `/sqlworkflow/` 页面 JS 加载验证 (用浏览器开发工具看 Network 标签)
- `/detail/<id>/` 页面 "启动 gh-ost" 按钮实操演练
- 浏览器开发工具 Console 看 4xx/5xx 错误

---

## 修了 4 个 bug (8/25 上午演练 + 11:30 后这 2 个)

1. ✅ 5 步必做脚本步骤顺序错乱 (步骤 13 错放在 7 后) → 重排到末尾
2. ✅ sed 在 CRLF 状态不工作 → dos2unix 转换 (8/25 教训)
3. ✅ 134 dev 没 /root/.my.cnf → 加 MY_CNF env var
4. ✅ drill_ghost_task_wf_abort_sync Case 1 假设 task 是 queued → 改幂等
5. ✅ 134 dev static/dist 目录缺失 → 从 110 prod scp 12 文件
6. ✅ 134 dev /opt/archery/bin/gh-ost symlink 失效 → cp + ln

**演练清单补全 (8/25 后)**:
- 加 `check_frontend_static.sh` 验证前端 static
- 演练时真跑业务 RD 按钮 (启动 gh-ost / 取消 / 字段 diff)
- 浏览器开发工具 Console + Network 标签 0 错

---

## 8/27 推 110 影响评估

### 110 prod 当前状态
- ✅ static/dist 完整 (8/05 升级时 docker 时代带的)
- ✅ /opt/archery/bin/gh-ost 存在 + symlink 正确
- ✅ 推 110 推的是代码改动, 不动 static 和 binary, 所以 110 prod 不受这 2 个 bug 影响

### 8/27 推 110 必做
- 推 110 推代码后, 跑 `check_frontend_static.sh` 验证 110 prod dist 完整 (idempotent)
- 跑 5 步必做 步骤 8 验证 gh-ost binary OK
- 浏览器真演练 "启动 gh-ost" 按钮 (DBA 自己实操, 不只是 curl)

### 推 110 checklist 加 2 项
- [ ] 推代码后跑 `check_frontend_static.sh` (110 prod, 期望 12/12 + 4/4 PASS)
- [ ] 推代码后 DBA 浏览器真演练 "启动 gh-ost" 按钮 (期望 启动成功 或 报业务错, 不是 "No such file")

---

## 关联 commit / changelog

- **commit `9c7d4ee`**: 8/25 134 dev 完整演练报告 + 5 步必做脚本 + 备份脚本 4 bug 修复
- **commit (待 push)**: `check_frontend_static.sh` (前端 dist 验证脚本)
- **本次 changelog**: 134 dev 演练后 2 个新 bug 修复
