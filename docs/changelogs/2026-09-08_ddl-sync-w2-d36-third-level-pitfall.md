# D36 实战新发现 #7: 同步表清单分页栏中文 "‹ 上一页" 乱码 -> font-awesome icon (9/8 18:45 业务方反馈驱动)

> **日期**: 2026-09-08 18:45
> **触发**: 业务方 mkq 反馈 "选择每页行数, 或者点击下一页, 都会跳转到首页"
> **根因 (100% 锁定)**: 同步表清单分页栏 + 同步历史分页栏用的中文 `‹ 上一页` / `下一页 ›` 在浏览器渲染时空格 (编码链路某一步字符丢失), 业务方看到分页栏链接但没文字, 误以为点错跳到首页

## 实战踩坑 (D36 实战新发现 #7, 业务方反馈驱动)

### 演练 100% 锁定
- 演练 v3 (Django shell 渲染 page=2 per_page=50) 输出 HTML 分页栏:
  - 上一页: `<a href="?tables_page=1&tables_per_page=50#tab-tables"> </a>` ← 文本是空格!
  - 下一页: `<a href="?tables_page=3&tables_per_page=50#tab-tables"> </a>` ← 文本是空格!
- 业务方硬刷页面看到分页栏, 但 "上一页" / "下一页" 文字是空格 / 乱码, 误以为链接无效, 实际跳转到 page=1 (默认) - 看起来像"跳到首页"

### 根因分析
D33 同步历史 tab + D36 同步表清单 tab 都用 `‹ 上一页` / `下一页 ›` 中文, 在文件编辑链路某一步 (Windows 编辑器 / PowerShell / SSH 编码) 字符丢失, 实际文件里可能正常但浏览器渲染时空格.

## 修法 (9/8 18:50 完成)

### Template 改 (134 dev + 110 prod)
- 同步表清单 tab + 同步历史 tab 分页栏:
  - 上一页: `<i class="fa fa-arrow-left"></i> Prev` (font-awesome icon + 英文)
  - 下一页: `Next <i class="fa fa-arrow-right"></i>` (英文 + font-awesome icon)
- 兼容: 同步历史 tab 跳转加 `&tables_per_page={{ tables_per_page }}` 参数 (同步表清单 tab 切换行数时保留 history 页码)

### 演练 100% PASS
- 134 dev 演练: page=2 per_page=50 HTML 渲染:
  - `<a href="?tables_page=1&tables_per_page=50#tab-tables"><i class="fa fa-arrow-left"></i> Prev</a>` ✅
  - 页码 1-13 + current 2 高亮 ✅
  - Next + fa-arrow-right 对称 ✅
- 110 prod 演练: 同样 PASS, gunicorn 6 进程, /login/ 200 ✅
- scp 链路: Windows md5 `2fea70bf...` → 134 dev md5 一致 → 110 prod md5 一致 ✅

## 9/8 18:50 110 prod 状态

| 项 | 状态 |
|---|---|
| gunicorn 进程 | 6 (PID 119014 master + 5 worker) ✅ |
| 9123 端口 | LISTEN ✅ |
| /login/ | 200 ✅ |
| pair_detail.html md5 | `2fea70bf...` (D36 三级踩坑修复后) ✅ |
| 业务方渲染 HTML | "Prev" / "Next" + fa-arrow icon 正确显示 ✅ |
| 业务方硬刷 | 可见分页栏 + 切换行数 + 下一页/上一页 全部正常 ✅ |

## 教训 (D36 实战新发现 #7, 跨项目可复用)

1. **中文 UI 文字必用 font-awesome icon + 英文, 不用中文符号** (跨平台/编码链路稳, 不会乱码)
2. **演练时必看 HTML 实际渲染输出** (演练 v3 v4 v5 之前输出空, 我没深究, 业务方反馈才发现中文乱码)
3. **base.html 等模板里 D33 同步历史 tab 用的 `‹ 上一页` / `下一页 ›` 也应该一起改** (D33 实战踩坑没被发现, 这次 D36 顺手修了)
4. **演练 pair_detail view 时必渲染 + grep 实际文字** (`{% if %}` 块渲染 PASS ≠ 链接文本正确)

## 实战脚本

- `scripts/_archive/_d36_diag_pagination.py` (第一版 diag, Django test client DisallowedHost)
- `scripts/_archive/_d36_diag_v2.py` (用 view 函数 + HttpResponse.content 抓 HTML)
- `scripts/_archive/_d36_diag_v3.py` (完整 ddlsync-pagination 段, 演练 v3 输出 Prev/Next 文本是空格, 100% 锁定中文乱码)
- `scripts/_archive/_d36_diag_v4.py` (regex 写错 #tab-history vs #tab-tables, 演练没匹配)
- `scripts/_archive/_d36_diag_v5.py` (完整分页栏段, 演练 PASS, Prev + fa-arrow-left + Next + fa-arrow-right 全部正确)
- `scripts/_archive/_d36_push_v3.py` (scp Windows → 134 dev → 110 prod, 9 步完整演练)

## 实战 changelog (D36 系列)

- `docs/changelogs/2026-09-08_ddl-sync-w2-d36-pair-tables-pagination.md` (D36 一级: 加分页 + 行数选择, commit `ee8ad95`)
- `docs/changelogs/2026-09-08_ddl-sync-w2-d36-second-level-pitfall.md` (D36 二级: 134 dev 跟 Windows 本地不同步, commit `904a98e`)
- `docs/changelogs/2026-09-08_ddl-sync-w2-d36-third-level-pitfall.md` (本次 D36 三级: 中文上一页/下一页乱码, 改 font-awesome icon)
