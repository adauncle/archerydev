# 2026-08-25 134 dev 业务 RD 实战 9 个 bug 修复 (推 110 前追加)

> **触发时间**: 2026-08-25 11:30-13:00 (8 阶段演练后业务 RD 浏览器实战)
> **修复人**: mavis (远程) + 业务 RD (阿达叔叔, 浏览器验证)
> **关联**: `docs/changelogs/2026-08-25_134dev-rehearsal-pre-110.md` (8 阶段演练, 11:00-11:25)
> **意义**: 演练漏了前端 + 业务流程实战, 业务 RD 真用才发现 5 个新 bug

---

## 0. TL;DR

8 阶段演练 (commit `9c7d4ee`) 之后, 业务 RD 浏览器真用 134 dev, 实战发现 **5 个新 bug**, 总计 9 个 bug 修复 + 3 次 gh-ost 任务全过, 134 dev 准备就绪推 110.

---

## 1. 5 个新 bug (业务 RD 实战发现)

### Bug 1: 134 dev `static/dist/` 目录完全缺失 (11:30)

- **症状**: `/sqlworkflow/` 页面 JS 404 (`/static/dist/js/formatter.js` + `utils.js`), 列表渲染不出来; `/login/` 页面 CSS 404, 浏览器报 "Refused to apply style from /login/"
- **根因**: 134 dev `static/dist/` 目录从来就不存在 (git clone 时 .gitignore 排除 `static/dist`, 没人 build 过前端)
- **修法**: 从 110 prod scp 12 个 dist 文件 (4 css/js + 4 .gz + 4 common), chown archery:archery
- **commit**: `151dc64`

### Bug 2: 134 dev `/opt/archery/bin/gh-ost` symlink 失效 (11:37)

- **症状**: 业务 RD 启动 gh-ost 报 `No such file or directory: '/usr/local/bin/gh-ost'`
- **根因**: `/usr/local/bin/gh-ost` 是 symlink → 指向 `/opt/archery/bin/gh-ost`, 但 `/opt/archery/bin/` 目录从来就不存在 (8/24 摸底 summary 写"8/24 装好"是 110 prod, 134 dev 漏装)
- **修法**: `cp /opt/gh-ost/gh-ost /opt/archery/bin/gh-ost` + `chown archery:archery` + `ln -s /opt/archery/bin/gh-ost /usr/local/bin/gh-ost`
- **commit**: `151dc64`

### Bug 3: gh-ost 1146 noise 写到 task.error_message (12:30)

- **症状**: gh-ost 成功完成后, `error_message` 字段写 `Error 1146 (42S02): Table 'X' doesn't exist`, 业务 RD 看着别扭
- **根因**: gh-ost 1.1.10 cut-over 成功后 cleanup 阶段 (drop _x_ghc changelog 表) 报 1146, parser 写到 error_message
- **修法**: parser.py 加 `_RE_CLEANUP_NOISE_1146` 正则过滤, 1 行 + 1 正则
- **commit**: `ac7e929`
- **drill 验证**: 4 Case 全 PASS (1146 过滤 / FATAL 保留 / 混合 / 其他错误)

### Bug 4: 进度面板终态不 reload, UI/状态不同步 (12:50)

- **症状**: task #71 后端 `status='success'`, 但前端显示"排队中 + 100% Done migrating"矛盾
- **根因**: 8/13 拍板进度面板 polling 3s + 终态停 poll, 模板渲染 (server-side) 不重渲染, JS 只更新 DOM 局部
- **修法**: progress.html JS 终态分支加 `setTimeout(() => location.reload(), 1000)`
- **commit**: `f76282e`

### Bug 5: 演练 checklist 漏前端 + 业务流程 (跨项目可复用教训)

- **症状**: 8 阶段演练只测了 HTTP 200 状态 + drill 脚本测 Archery 二次开发代码, 没真启动 gh-ost 进程, 没真用浏览器访问业务页面
- **根因**: drill 脚本测不到 gh-ost 自身边缘 case (1146 noise), curl 200 看不到 HTML 里的 CSS/JS 404
- **修法**: 新增 `scripts/deploy/check_frontend_static.sh` 验证 dist 完整性, 8/26 演练清单加"业务 RD 浏览器实操"段
- **commit**: `151dc64` (check_frontend_static.sh) + 多个 changelog

---

## 2. 3 次 gh-ost 实战任务全过 (11:38 / 12:42 / 12:58)

| Task | 工单 | 触发时间 | 耗时 | 状态 | 1146 noise | UI 一致 |
|------|------|----------|------|------|-----------|---------|
| #70 | #94 | 11:38 | 18s | out-over 成功 | ❌ 旧代码 (Err 1146) | n/a |
| #71 | #96 | 12:42 | 18s | out-over 成功 | ✅ parser 修法生效 | ❌ 排队中+100% (旧前端) |
| **#72** | **#97** | **12:58** | **18s** | **out-over 成功** | **✅ 修法生效** | **✅ reload 修法生效** |

**实战数据**:
- gh-ost 1.1.10 24 万行数据迁移 18 秒稳定
- 业务 RD 浏览器实操流程跑通
- 8/25 11:30 之前所有 8 阶段演练 + 11:30-13:00 实战修复闭环

---

## 3. 8/25 全天修了 9 个 bug (汇总)

| # | Bug | 修复时间 | Commit | 修复方法 |
|---|-----|----------|--------|----------|
| 1 | 5 步必做脚本步骤顺序错乱 (13 错放 7 后) | 11:15 | `9c7d4ee` | Python 重排 |
| 2 | sed 在 CRLF 状态不工作 | 11:15 | `9c7d4ee` | dos2unix 转换 |
| 3 | 134 dev 没 /root/.my.cnf | 11:20 | `9c7d4ee` | MY_CNF env var |
| 4 | drill_ghost_task 假设 task 是 queued | 11:10 | `9c7d4ee` | 幂等改 |
| 5 | 134 dev `static/dist/` 缺失 (12 文件) | 11:30 | `151dc64` | scp 自 110 prod |
| 6 | 134 dev `/opt/archery/bin/gh-ost` symlink 失效 | 11:37 | `151dc64` | cp + ln |
| 7 | gh-ost 1146 noise 写到 error_message | 12:33 | `ac7e929` | parser.py 1 行过滤 |
| 8 | 进度面板终态不 reload, UI/状态不同步 | 12:50 | `f76282e` | progress.html location.reload() |
| 9 | 演练 checklist 漏前端 + 业务流程 | 12:00 | `151dc64` | check_frontend_static.sh + 8/26 清单 |

---

## 4. 8/25 8/13 拍板设计 vs 实战冲突 (跨项目可复用教训)

| 8/13 拍板 | 8/25 实战发现 | 修法 |
|-----------|------------|------|
| 进度面板 polling 3s (不要 SSE/WebSocket) | ✅ 终态停 poll, 但 UI 模板不重渲染 | 加 `location.reload()` 终态触发 |
| 进度面板 终态停 poll | ❌ UI 跟状态不同步 (task #71) | 同上 |
| drill 脚本测 Archery 二次开发代码 | ❌ 测不到第三方工具 (gh-ost 1146) | 加 drill_parser_1146_filter.py 单元测试 |
| gh-ost 端点 perm 守卫 (JsonResponse, 不 raise) | ✅ 实战 PASS | n/a |
| 大表 DDL 防呆 3 按钮 | ✅ 实战 PASS | n/a |
| 状态机: pending → precheck_failed → queued → running → cut_over → done | ✅ 切到 success, 但前端 UI 没显示 | 加 reload |

---

## 5. 8/25 新增交付物

| 名称 | 路径 | 用途 |
|------|------|------|
| `check_frontend_static.sh` | `scripts/deploy/check_frontend_static.sh` | 验证前端 dist 目录完整性 + curl 200 + MIME type |
| `drill_parser_1146_filter.py` | `scripts/drill_parser_1146_filter.py` | 4 Case 单元测试 1146 noise 过滤 |
| `2026-08-25_134dev-rehearsal-pre-110.md` | `docs/changelogs/` | 8 阶段演练报告 (11:00-11:25) |
| `2026-08-25_134dev-frontend-static-and-ghost-bin.md` | `docs/changelogs/` | Bug 1+2 修复记录 |
| `2026-08-25_gh-ost-cleanup-1146-noise.md` | `docs/changelogs/` | Bug 3 修复记录 |
| `2026-08-25_progress-page-auto-reload.md` | `docs/changelogs/` | Bug 4 修复记录 |
| **本 changelog** | `docs/changelogs/` | 9 bug 汇总 + 3 gh-ost 实战 |

---

## 6. 8/27 推 110 checklist (更新版)

### 推前 (8/27 20:45)
- [ ] 4 脚本全部 scp 到 110 prod /tmp/ (5 步必做 / 3 份备份 / 5 端点验证 / 一键回滚 / **check_frontend_static**)
- [ ] **5 脚本 8/25 134 dev 演练全过** (新增 check_frontend_static)
- [ ] **kill master 真演练 8/25 演练过** (systemd 5-7s 自动拉, 业务不可用 6.8s)
- [ ] **业务 RD 浏览器真演练 gh-ost 3 次全过** (task #70/#71/#72 18 秒稳定)
- [ ] **1146 noise 过滤实战验证** (task #71/#72 error_message 为空)
- [ ] **终态 reload 实战验证** (task #72 显示"成功"标题)
- [ ] 8/24 教训固化: kill 不是 HUP, 提新工单验证 detail 页
- [ ] 业务群通知模板准备好
- [ ] DBA 值守确认 8/27 21:00-22:00 在场

### 推中 (8/27 21:00-21:30)
- [ ] 20:50 跑 3 份备份
- [ ] 21:00 跑 5 步必做 13 步
- [ ] 21:05 推代码 (rsync)
- [ ] 21:08 跑 migration (4 个 ddl_gh_ost)
- [ ] 21:10 kill master 102228 + **手动 nohup 拉起新 master** (110 prod 没 systemd)
- [ ] 21:15 跑 5 端点验证 + **跑 check_frontend_static.sh** (期望 12/12 PASS)
- [ ] 21:20 **业务 RD 浏览器真演练 gh-ost** (期望 task 成功 + error_message 空 + UI 终态显示"成功")
- [ ] 21:30 群发业务群"推 110 完成"

### 推后 (8/27 22:00-8/28 09:00)
- [ ] 8/28 09:00 1 日观察报告
- [ ] 8/28 业务 RD 反馈收集

---

## 7. 134 dev 当前状态 (8/25 13:00)

- **gunicorn master pid**: 20652 (systemd 拉起, 12:33)
- **业务 RD 真演练 3 次 gh-ost**: 全过, 18 秒稳定
- **前端 dist**: 完整 (从 110 prod scp 12 文件)
- **gh-ost 二进制**: 1.1.10 装好 (跟 110 prod 一致)
- **5 端点验证**: 全 PASS
- **check_frontend_static**: 12/12 + 4/4 URL + 1/1 MIME PASS
- **演练 checklist**: 9/9 全过

**134 dev 业务 RD 可以正常用, 8/27 推 110 准备齐全** ✅

---

## 8. 8/25 教训 (跨项目可复用, 高优先级)

1. **演练漏前端 + 业务流程 → 实战才发现 5 个 bug** — 8 阶段演练只测 HTTP 状态, 业务 RD 真用才发现 static 缺失 + gh-ost 路径 + 1146 + 终态 UI 不同步
2. **drill 脚本测不到第三方工具边缘 case** — gh-ost 1146 cleanup noise 只能真跑 gh-ost 才发现
3. **进度类 UI 终态必须 reload 整页** — JS 终态停 poll 后, 模板渲染不变, UI 跟状态不同步
4. **演练必查浏览器开发工具** — Console + Network 标签看 4xx/5xx 错误, 不只 HTTP 状态
5. **真跑业务流程 > drill 脚本** — 5 端点验证 + drill 脚本 ≠ 业务 RD 真用
6. **静态资源 404 不影响 HTTP 状态** — curl 200 但 HTML 里 CSS/JS 引用 404, 业务 RD 看着别扭
7. **状态机切 status 后端要保证** — 8/13 状态机切到 success, 但前端没反映, 是 UI bug 不是状态机 bug
8. **演练 checklist 漏前端** — 8/26 清单要加 check_frontend_static + 业务 RD 浏览器实操段

---

## 9. 8/27 推 110 范围 (用户 8/25 11:00 拍板)

| 类别 | 数量 | 8/25 实战验证 |
|------|------|--------------|
| gh-ost v0.3.0-beta | 1 大功能 | ✅ 3 次任务实战通过 |
| gh-ost v0.4.5 (碎片回收 + 智能回滚) | 1 大功能 | ✅ 演练通过 |
| gh-ost 任务管理列表页 + 权限组细分 | 1 大功能 | ✅ 演练通过 |
| 8/24 6 bug fix | 6 commit | ✅ 演练通过 |
| 8/17 dashboard 优雅降级 | 1 commit | ✅ 演练通过 |
| 钉钉 OA framework (低风险) | 1 大功能 | n/a (NOT enabled) |
| `/dbaprinciples/` 修复 (8/24) | 1 commit | ✅ 演练通过 |
| W1 + W2 摸头 5 步必做扩展 | 13 步 | ✅ 演练通过 |
| **8/25 8 阶段演练 + 9 bug 修复** | 9 commit | ✅ 134 dev 实战通过 |
| **总计** | **40+ commit, 30+ changelog** | |

---

## 10. 关联文档

- **8/25 8 阶段演练报告**: `docs/changelogs/2026-08-25_134dev-rehearsal-pre-110.md`
- **推 110 执行手册**: `docs/runbooks/2026-08-27_push-v030-execution-manual.md`
- **8/26 演练清单**: `docs/runbooks/2026-08-26_134dev-rehearsal-checklist.md`
- **3 Bug 修复 changelog**:
  - `docs/changelogs/2026-08-25_134dev-frontend-static-and-ghost-bin.md`
  - `docs/changelogs/2026-08-25_gh-ost-cleanup-1146-noise.md`
  - `docs/changelogs/2026-08-25_progress-page-auto-reload.md`
- **9 Bug commits**: `9c7d4ee` + `151dc64` + `ac7e929` + `f76282e` (其他从原演练报告查)
