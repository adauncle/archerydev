# D36 实战新发现 #6: 134 dev 跟 Windows 本地 git 仓库不同步, 推 110 prod 前必同步 (9/8 18:30 业务方反馈驱动)

> **日期**: 2026-09-08 18:30
> **触发**: D36 同步表清单分页 commit `ee8ad95` 落地后, 业务方硬刷页面还是显示"前 200 张" 提示, 没看到分页
> **根因 (100% 锁定)**: D36 改的 view + template 只在 Windows 本地 git 仓库 (commit `ee8ad95`), 134 dev `/opt/archery/prod/` 实际没改! 推 110 prod 时从 134 dev 拉, 110 prod 也是 D35 推的旧代码, 没分页逻辑.

## 根因深度分析

### 134 dev 跟 Windows 本地的关系
- **Windows 本地**: `G:\MiniMax工作空间\archery_dev\` (git 仓库, 跑演练, 实战 commit 都进这)
- **134 dev 实际部署**: `/opt/archery/prod/` (D34 dry-run 演练时改, D35 push 演练时改, D9 演练时改)
- **D32 演练**: 用 `if False:` 替换 4 大步守卫, 演练 1 干净状态 + 演练 2 还原, 134 dev 跟 Windows 本地一致
- **D34 演练**: 9 步 dry-run, 134 dev 改的 base.html / settings.py / urls.py 演练后**没真回滚** (因为演练是直接改文件), 134 dev 跟 Windows 本地 commit 出现脱节
- **D36 改的代码**: 只在 Windows 本地 (commit `ee8ad95`), 演练时跑的是 Django shell Paginator 绕过 view, 演练 PASS 但 view 改的代码没真到 134 dev

### D36 演练踩坑链路
| 步 | 演练 | 实际状态 |
|---|---|---|
| 18:00 commit ee8ad95 (改 views + template) | Windows 本地改 | 134 dev / 110 prod 没改 |
| 18:13 134 dev Paginator 演练 (`_d36_drill_v6.py`) | Paginator 跑通 (绕开 view) | view 改的代码 134 dev 没动, view 实际跑原版 |
| 18:24 scp 134 dev → 110 prod (`_d36_push_pair_pagination.py`) | 推 2 文件 | 134 dev 推的是 D35 旧版, 110 prod 也是 D35 旧版 |
| 18:30 commit ee8ad95 落地 (认为已推 110 prod) | 演练以为 PASS | 实际上 134 dev / 110 prod 都还是 D35 旧版 |
| 18:30 业务方硬刷页面 | 看到"前 200 张" | 110 prod 实际是 D35 旧版 [:200], 没分页 |
| **18:34 二级踩坑排查** | ssh 110 prod 查 views/__init__.py | **tables_per_page 引用 0** (D36 改的代码没推过来!) |

### 排查 100% 锁定
- 134 dev `/opt/archery/prod/sql/extensions/ddl_sync/views/__init__.py` md5 = `4702b478...` (D35 推的旧版, 没 tables_per_page)
- 134 dev `/opt/archery/prod/sql/extensions/ddl_sync/templates/ddl_sync/pair_detail.html` md5 = `385c098a...` (D35 推的旧版, 没 tables_per_page)
- `grep -c tables_per_page 134 dev views/__init__.py = 0` (确认 D36 改的代码没到 134 dev)
- Windows 本地 `commit ee8ad95` 改的 views md5 = `b3c8d295...` (D36 改的, 跟 134 dev 不一致)

## 修法 (9/8 18:35 实战完成)

### 链路
1. **scp Windows → 134 dev** (2 文件: views/__init__.py + pair_detail.html)
2. **134 dev 拉新 gunicorn** (5 进程, /login/ 200)
3. **134 dev 演练 view** (确认 tables_per_page 引用 9 + 6)
4. **scp 134 dev → 110 prod** (2 文件, md5 一致 `b3c8d295...` + `fba0e395...`)
5. **110 prod 拉新 gunicorn** (6 进程, /login/ 200)
6. **110 prod 演练 view** (Paginator 13/7/4 页, view HttpResponse 200)

### 9/8 18:35 110 prod 状态 (PASS)
- views/__init__.py md5 = `b3c8d295...` (D36 改的, 跟 Windows 本地一致)
- pair_detail.html md5 = `fba0e395...` (D36 改的)
- tables_per_page 引用 9 (views) + 6 (template) ✅
- gunicorn 6 进程, 9123 LISTEN, /login/ 200 ✅
- pair #1 hly_accesscard 606 张表演练 Paginator 13/7/4 PASS ✅
- 业务方硬刷 (Ctrl+Shift+R) 应该能看到分页 + 行数选择 ✅

## 教训 (D36 实战新发现, 跨项目可复用)

1. **134 dev 跟 Windows 本地是分开部署目录**, D34 dry-run 演练时 base.html 改的没真回滚, 134 dev 跟 Windows 本地 commit 链路脱节
2. **演练不能只 Paginator 跑通**, 必须用 ssh 端 view 跑通 + 看 HTTP 响应 HTML 真的有分页栏 + 表格只有当前页的 rows
3. **推 110 prod 前必演练 "Windows 本地 → 134 dev → 110 prod" 完整链路** (这次踩坑链路), 每一步用 md5 校验, 不能只看 Paginator 跑通
4. **演练 pair_detail view 时必带 perm user + RequestFactory 拿 req.user** (Django `@permission_required` 装饰器需要 req.user, 不传会 AttributeError)
5. **修 D35 push 脚本时, D35 push runbook 流程要补 "演练必用 ssh 端 view 跑通 + 业务方账号硬刷验证" 步骤**, 不能只看路由 (reverse) + 模板渲染检查 (Django shell Paginator 跑通)

## 实战脚本

- `scripts/_archive/_d36_push_v2.py` (D36 二级踩坑修复: scp Windows → 134 dev → 110 prod, 9 步完整演练)
- `scripts/_archive/_d36_check_110prod_state.py` (查 110 prod 实际状态, 发现 md5 DIFF + tables_per_page 引用 0)
- `scripts/_archive/_d36_push_pair_pagination.py` (第一版推, scp 错路径 - 演练踩坑)
- `scripts/_archive/_d36_drill_v6.py` (Paginator 边界演练 PASS, 但 view 没改, 误判)
- `scripts/_archive/_d36_curl_test.py` (110 prod view 跑通 200, 演练最终验证)

## 实战 changelog (D36 系列)

- `docs/changelogs/2026-09-08_ddl-sync-w2-d36-pair-tables-pagination.md` (D36 改 view + template, 18:30 commit `ee8ad95`)
- `docs/changelogs/2026-09-08_ddl-sync-w2-d36-second-level-pitfall.md` (本次, D36 实战新发现 #6, 二级踩坑 134 dev 跟 Windows 本地不同步)
